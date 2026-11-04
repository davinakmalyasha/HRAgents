use crate::error::{DomainError, DomainResult};
use crate::ids::{ConsentId, ErasureRequestId, OperatorId};
use crate::time::{BusinessDate, UtcInstant};
use chrono::Datelike;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum SubjectType {
    Candidate,
    Employee,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ConsentPurpose {
    Recruitment,
    Employment,
    Payroll,
    BackgroundCheck,
    Marketing,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ConsentState {
    Pending,
    Granted,
    Withdrawn,
    Expired,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct ConsentRecord {
    pub id: ConsentId,
    pub subject_type: SubjectType,
    pub subject_id: String,
    pub purpose: ConsentPurpose,
    pub state: ConsentState,
    pub source: String,
    pub granted_at: Option<UtcInstant>,
    pub withdrawn_at: Option<UtcInstant>,
    pub expires_on: Option<BusinessDate>,
    pub note: Option<String>,
}

impl ConsentRecord {
    pub fn new(
        subject_type: SubjectType,
        subject_id: impl Into<String>,
        purpose: ConsentPurpose,
        source: impl Into<String>,
        _now: UtcInstant,
    ) -> Self {
        Self {
            id: ConsentId::new(),
            subject_type,
            subject_id: subject_id.into(),
            purpose,
            state: ConsentState::Pending,
            source: source.into(),
            granted_at: None,
            withdrawn_at: None,
            expires_on: None,
            note: None,
        }
    }

    pub fn grant(&mut self, now: UtcInstant) -> DomainResult<()> {
        if self.state == ConsentState::Withdrawn {
            return Err(DomainError::conflict(
                "E_CONSENT_WITHDRAWN",
                "a withdrawn consent needs a new record; it cannot be silently re-granted",
            ));
        }
        self.state = ConsentState::Granted;
        self.granted_at = Some(now);
        Ok(())
    }

    pub fn withdraw(&mut self, reason: &str, now: UtcInstant) -> DomainResult<()> {
        if self.state != ConsentState::Granted {
            return Err(DomainError::conflict(
                "E_CONSENT_NOT_GRANTED",
                "only granted consent can be withdrawn",
            ));
        }
        if reason.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_WITHDRAW_REASON",
                "withdrawing consent needs a reason",
            ));
        }
        self.state = ConsentState::Withdrawn;
        self.withdrawn_at = Some(now);
        self.note = Some(reason.trim().to_owned());
        Ok(())
    }

    pub fn permits(&self, today: BusinessDate) -> bool {
        self.state == ConsentState::Granted && self.expires_on.is_none_or(|expiry| today <= expiry)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum RetentionAction {
    Purge,
    Anonymize,
    Archive,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct RetentionPolicy {
    pub id: String,
    pub record_type: String,
    pub retention_months: u32,
    pub action: RetentionAction,
    pub legal_basis: String,
    pub active: bool,
}

impl RetentionPolicy {
    pub fn due_on(&self, record_created: BusinessDate) -> BusinessDate {
        // Month-end-safe: clamp to the last day of the target month.
        let total = record_created.year() * 12
            + (record_created.month() as i32 - 1)
            + self.retention_months as i32;
        let year = total.div_euclid(12);
        let month = (total.rem_euclid(12) + 1) as u32;
        let last = last_day_of_month(year, month);
        let day = record_created.naive().day().min(last);
        BusinessDate::from_naive(
            chrono::NaiveDate::from_ymd_opt(year, month, day).expect("valid retention date"),
        )
    }
}

fn last_day_of_month(year: i32, month: u32) -> u32 {
    let (next_year, next_month) = if month == 12 {
        (year + 1, 1)
    } else {
        (year, month + 1)
    };
    let first = chrono::NaiveDate::from_ymd_opt(next_year, next_month, 1).expect("valid month");
    first.pred_opt().expect("valid date").day()
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct RetentionHold {
    pub id: String,
    pub subject_type: SubjectType,
    pub subject_id: String,
    pub reason: String,
    pub until: Option<BusinessDate>,
    pub created_by: OperatorId,
    pub created_at: UtcInstant,
}

impl RetentionHold {
    pub fn blocks(&self, today: BusinessDate) -> bool {
        self.until.is_none_or(|until| today <= until)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ErasureStatus {
    Pending,
    Approved,
    Rejected,
    Completed,
    Cancelled,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct ErasureRequest {
    pub id: ErasureRequestId,
    pub subject_type: SubjectType,
    pub subject_id: String,
    pub reason: String,
    pub status: ErasureStatus,
    pub requested_at: UtcInstant,
    pub decided_by: Option<OperatorId>,
    pub decided_at: Option<UtcInstant>,
    pub executed_at: Option<UtcInstant>,
    pub retained: Vec<String>,
}

impl ErasureRequest {
    pub fn new(
        subject_type: SubjectType,
        subject_id: impl Into<String>,
        reason: &str,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        if reason.trim().len() < 10 {
            return Err(DomainError::validation(
                "E_ERASURE_REASON",
                "an erasure request needs a reason of at least 10 characters",
            ));
        }
        Ok(Self {
            id: ErasureRequestId::new(),
            subject_type,
            subject_id: subject_id.into(),
            reason: reason.trim().to_owned(),
            status: ErasureStatus::Pending,
            requested_at: now,
            decided_by: None,
            decided_at: None,
            executed_at: None,
            retained: Vec::new(),
        })
    }

    pub fn approve(&mut self, operator_id: OperatorId, now: UtcInstant) -> DomainResult<()> {
        if self.status != ErasureStatus::Pending {
            return Err(DomainError::conflict(
                "E_ERASURE_CLOSED",
                "this erasure request has already been decided",
            ));
        }
        self.status = ErasureStatus::Approved;
        self.decided_by = Some(operator_id);
        self.decided_at = Some(now);
        Ok(())
    }

    pub fn reject(
        &mut self,
        operator_id: OperatorId,
        reason: &str,
        now: UtcInstant,
    ) -> DomainResult<()> {
        if self.status != ErasureStatus::Pending {
            return Err(DomainError::conflict(
                "E_ERASURE_CLOSED",
                "this erasure request has already been decided",
            ));
        }
        if reason.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_ERASURE_REJECT_REASON",
                "rejecting an erasure request needs a reason",
            ));
        }
        self.status = ErasureStatus::Rejected;
        self.decided_by = Some(operator_id);
        self.decided_at = Some(now);
        self.reason = reason.trim().to_owned();
        Ok(())
    }

    /// Execution is deliberately separate from approval: the approver and the
    /// executor are both named, and the command layer requires a fresh re-auth
    /// for each. Audit rows and legally retained records survive.
    pub fn execute(
        &mut self,
        operator_id: OperatorId,
        hold: Option<&RetentionHold>,
        today: BusinessDate,
        now: UtcInstant,
    ) -> DomainResult<ErasurePlan> {
        if self.status != ErasureStatus::Approved {
            return Err(DomainError::conflict(
                "E_ERASURE_NOT_APPROVED",
                "an erasure request must be approved before it can execute",
            ));
        }
        if hold.is_some_and(|hold| hold.blocks(today)) {
            return Err(DomainError::conflict(
                "E_RETENTION_HOLD",
                "a retention hold blocks erasure until it expires or is released",
            ));
        }
        self.status = ErasureStatus::Completed;
        self.executed_at = Some(now);
        self.decided_by = Some(operator_id);
        self.retained = vec![
            "audit_log (hash-chained evidence, never erased)".to_owned(),
            "payroll_runs (statutory payroll retention)".to_owned(),
            "aggregate_counts (no personal data)".to_owned(),
        ];
        Ok(ErasurePlan {
            subject_type: self.subject_type,
            subject_id: self.subject_id.clone(),
            purge: vec![
                "candidate_profile".to_owned(),
                "candidate_documents".to_owned(),
                "communications".to_owned(),
                "employee_contact_details".to_owned(),
            ],
            retained: self.retained.clone(),
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct ErasurePlan {
    pub subject_type: SubjectType,
    pub subject_id: String,
    pub purge: Vec<String>,
    pub retained: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum BreachSeverity {
    Low,
    Medium,
    High,
    Critical,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum BreachStatus {
    Open,
    Contained,
    Notified,
    Closed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct BreachIncident {
    pub id: String,
    pub title: String,
    pub description: String,
    pub severity: BreachSeverity,
    pub status: BreachStatus,
    pub discovered_at: UtcInstant,
    pub contained_at: Option<UtcInstant>,
    pub notified_at: Option<UtcInstant>,
    pub steps: Vec<String>,
    pub owner: OperatorId,
}

impl BreachIncident {
    pub fn contain(&mut self, now: UtcInstant, step: &str) -> DomainResult<()> {
        if self.status == BreachStatus::Closed {
            return Err(DomainError::conflict(
                "E_BREACH_CLOSED",
                "this incident is already closed",
            ));
        }
        if step.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_BREACH_STEP",
                "a containment step needs a description",
            ));
        }
        self.steps.push(step.trim().to_owned());
        self.status = BreachStatus::Contained;
        self.contained_at.get_or_insert(now);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn now() -> UtcInstant {
        UtcInstant::from_millis(1_760_000_000_000).unwrap()
    }

    fn today() -> BusinessDate {
        BusinessDate::parse("2026-11-01").unwrap()
    }

    #[test]
    fn withdrawal_blocks_processing() {
        let mut consent = ConsentRecord::new(
            SubjectType::Candidate,
            "c1",
            ConsentPurpose::Recruitment,
            "application form",
            now(),
        );
        consent.grant(now()).unwrap();
        assert!(consent.permits(today()));
        consent
            .withdraw("candidate asked us to stop", now())
            .unwrap();
        assert!(!consent.permits(today()));
        assert!(consent.grant(now()).is_err());
    }

    #[test]
    fn retention_due_date_handles_month_end() {
        let policy = RetentionPolicy {
            id: "candidate".into(),
            record_type: "candidate".into(),
            retention_months: 6,
            action: RetentionAction::Purge,
            legal_basis: "consent".into(),
            active: true,
        };
        assert_eq!(
            policy
                .due_on(BusinessDate::parse("2026-08-31").unwrap())
                .to_string(),
            "2027-02-28"
        );
    }

    #[test]
    fn erasure_requires_approval_and_respects_hold() {
        let mut request = ErasureRequest::new(
            SubjectType::Employee,
            "e1",
            "employee exercised their right to erasure",
            now(),
        )
        .unwrap();
        assert!(
            request
                .execute(OperatorId::new(), None, today(), now())
                .is_err()
        );
        request.approve(OperatorId::new(), now()).unwrap();
        let hold = RetentionHold {
            id: "h1".into(),
            subject_type: SubjectType::Employee,
            subject_id: "e1".into(),
            reason: "tax audit".into(),
            until: Some(BusinessDate::parse("2027-01-01").unwrap()),
            created_by: OperatorId::new(),
            created_at: now(),
        };
        assert!(matches!(
            request.execute(OperatorId::new(), Some(&hold), today(), now()),
            Err(DomainError::Conflict {
                code: "E_RETENTION_HOLD",
                ..
            })
        ));
        let plan = request
            .execute(OperatorId::new(), None, today(), now())
            .unwrap();
        assert!(plan.retained.iter().any(|item| item.contains("audit_log")));
    }
}
