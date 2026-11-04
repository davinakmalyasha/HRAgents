use crate::Role;
use crate::audit::AuditActor;
use crate::error::{DomainError, DomainResult};
use crate::ids::{OperatorId, SessionId};
use crate::password::{PasswordError, verify_password};
use crate::time::UtcInstant;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Operator {
    pub id: OperatorId,
    pub username: String,
    pub display_name: String,
    pub password_hash: String,
    pub role: Role,
    pub active: bool,
    pub created_at: UtcInstant,
}

impl Operator {
    pub fn new(
        username: impl Into<String>,
        display_name: impl Into<String>,
        password_hash: impl Into<String>,
        created_at: UtcInstant,
    ) -> Self {
        Self {
            id: OperatorId::new(),
            username: username.into(),
            display_name: display_name.into(),
            password_hash: password_hash.into(),
            role: Role::HrOperator,
            active: true,
            created_at,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionPolicy {
    /// Idle lock, in seconds. Default 10 minutes (07-ui-ux).
    pub idle_timeout_seconds: i64,
    /// Hard session cap, in seconds. Default 12 hours.
    pub absolute_timeout_seconds: i64,
    /// How long a re-auth remains fresh for payroll sign-off, erasure, and
    /// rejection overrides. Default 5 minutes.
    pub reauth_window_seconds: i64,
    /// Failed attempts before the first lockout.
    pub max_failed_attempts: u32,
}

impl Default for SessionPolicy {
    fn default() -> Self {
        Self {
            idle_timeout_seconds: 10 * 60,
            absolute_timeout_seconds: 12 * 60 * 60,
            reauth_window_seconds: 5 * 60,
            max_failed_attempts: 5,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Session {
    pub id: SessionId,
    pub operator_id: OperatorId,
    pub operator_name: String,
    pub role: Role,
    pub started_at: UtcInstant,
    pub last_activity_at: UtcInstant,
    pub last_reauth_at: Option<UtcInstant>,
    pub locked: bool,
}

impl Session {
    pub fn actor(&self) -> AuditActor {
        AuditActor::human(self.operator_id, self.operator_name.clone())
    }

    pub fn is_active(&self, now: UtcInstant, policy: SessionPolicy) -> bool {
        !self.locked
            && now.seconds_since(self.started_at) < policy.absolute_timeout_seconds
            && now.seconds_since(self.last_activity_at) < policy.idle_timeout_seconds
    }

    /// True when a consequential action may proceed without asking for the
    /// password again.
    pub fn has_fresh_reauth(&self, now: UtcInstant, policy: SessionPolicy) -> bool {
        self.last_reauth_at
            .is_some_and(|at| now.seconds_since(at) < policy.reauth_window_seconds)
    }
}

#[derive(Debug, Clone)]
pub struct LoginOutcome {
    pub session: Session,
    pub rehashed_password: Option<String>,
}

/// Local authentication. There are no server accounts, no email reset, no SSO,
/// and no roles to configure. The only principal is an HR operator.
#[derive(Debug, Clone)]
pub struct AuthService {
    policy: SessionPolicy,
    failed_attempts: u32,
    locked_until: Option<UtcInstant>,
}

impl Default for AuthService {
    fn default() -> Self {
        Self::new(SessionPolicy::default())
    }
}

impl AuthService {
    pub fn new(policy: SessionPolicy) -> Self {
        Self {
            policy,
            failed_attempts: 0,
            locked_until: None,
        }
    }

    pub fn policy(&self) -> SessionPolicy {
        self.policy
    }

    pub fn login(
        &mut self,
        operator: &Operator,
        password: &str,
        now: UtcInstant,
    ) -> DomainResult<LoginOutcome> {
        if !operator.active {
            return Err(DomainError::Forbidden);
        }
        if let Some(until) = self.locked_until {
            if now < until {
                return Err(DomainError::validation(
                    "E_LOGIN_LOCKED",
                    "too many failed attempts; wait before trying again",
                ));
            }
            self.locked_until = None;
        }
        let valid =
            verify_password(&operator.password_hash, password).map_err(|error| match error {
                PasswordError::InvalidHash => DomainError::Invariant(
                    "operator password hash is not a valid PHC string".into(),
                ),
                _ => DomainError::Unauthenticated,
            })?;
        if !valid {
            self.failed_attempts += 1;
            if self.failed_attempts >= self.policy.max_failed_attempts {
                let backoff = match self.failed_attempts {
                    5 => 30,
                    6..=7 => 300,
                    8..=9 => 900,
                    _ => 3600,
                };
                self.locked_until = Some(now.plus_seconds(backoff));
            }
            return Err(DomainError::Unauthenticated);
        }
        self.failed_attempts = 0;
        self.locked_until = None;
        let session = Session {
            id: SessionId::new(),
            operator_id: operator.id,
            operator_name: operator.display_name.clone(),
            role: operator.role,
            started_at: now,
            last_activity_at: now,
            last_reauth_at: Some(now),
            locked: false,
        };
        Ok(LoginOutcome {
            session,
            rehashed_password: None,
        })
    }

    /// Unlock requires the password again; biometrics are re-auth only, never a
    /// substitute for the database key.
    pub fn unlock(
        &mut self,
        operator: &Operator,
        password: &str,
        now: UtcInstant,
    ) -> DomainResult<Session> {
        let outcome = self.login(operator, password, now)?;
        Ok(outcome.session)
    }

    pub fn touch(&self, session: &mut Session, now: UtcInstant) -> DomainResult<()> {
        if !session.is_active(now, self.policy) {
            return Err(DomainError::Unauthenticated);
        }
        session.last_activity_at = now;
        Ok(())
    }

    pub fn lock(&self, session: &mut Session) {
        session.locked = true;
    }

    pub fn mark_reauth(
        &self,
        session: &mut Session,
        operator: &Operator,
        password: &str,
        now: UtcInstant,
    ) -> DomainResult<()> {
        if !session.is_active(now, self.policy) {
            return Err(DomainError::Unauthenticated);
        }
        let valid = verify_password(&operator.password_hash, password)
            .map_err(|_| DomainError::Unauthenticated)?;
        if !valid {
            return Err(DomainError::Unauthenticated);
        }
        session.last_reauth_at = Some(now);
        session.last_activity_at = now;
        Ok(())
    }

    /// The named-human gate. Consequential commands call this; read-only
    /// commands only need an active session. There is no actor in the request.
    pub fn require_reauth<'a>(
        &self,
        session: &'a Session,
        now: UtcInstant,
    ) -> DomainResult<&'a Session> {
        if !session.is_active(now, self.policy) {
            return Err(DomainError::Unauthenticated);
        }
        if !session.has_fresh_reauth(now, self.policy) {
            return Err(DomainError::ReauthRequired);
        }
        Ok(session)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::password::hash_password;

    fn operator() -> Operator {
        Operator::new(
            "rina",
            "Rina",
            hash_password("correct horse battery staple").unwrap(),
            UtcInstant::from_millis(1_760_000_000_000).unwrap(),
        )
    }

    fn now() -> UtcInstant {
        UtcInstant::from_millis(1_760_000_100_000).unwrap()
    }

    #[test]
    fn login_success_and_wrong_password() {
        let mut service = AuthService::default();
        let operator = operator();
        assert!(
            service
                .login(&operator, "correct horse battery staple", now())
                .is_ok()
        );
        assert!(matches!(
            service.login(&operator, "wrong password", now()),
            Err(DomainError::Unauthenticated)
        ));
    }

    #[test]
    fn idle_timeout_locks_the_session() {
        let mut service = AuthService::default();
        let operator = operator();
        let mut session = service
            .login(&operator, "correct horse battery staple", now())
            .unwrap()
            .session;
        let later = now().plus_seconds(601);
        assert!(matches!(
            service.touch(&mut session, later),
            Err(DomainError::Unauthenticated)
        ));
    }

    #[test]
    fn consequential_action_needs_fresh_reauth() {
        let mut service = AuthService::default();
        let operator = operator();
        let session = service
            .login(&operator, "correct horse battery staple", now())
            .unwrap()
            .session;
        let stale = now().plus_seconds(301);
        assert!(matches!(
            service.require_reauth(&session, stale),
            Err(DomainError::ReauthRequired)
        ));
        assert!(
            service
                .require_reauth(&session, now().plus_seconds(60))
                .is_ok()
        );
    }

    #[test]
    fn lockout_after_repeated_failures() {
        let mut service = AuthService::default();
        let operator = operator();
        for _ in 0..5 {
            let _ = service.login(&operator, "wrong password", now());
        }
        assert!(matches!(
            service.login(&operator, "correct horse battery staple", now()),
            Err(DomainError::Validation {
                code: "E_LOGIN_LOCKED",
                ..
            })
        ));
    }
}
