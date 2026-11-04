//! Compliance services: retention sweep, erasure lifecycle, breach response.
//!
//! Same pattern as growth/hiring services: session/audit/store rules shared
//! with the core AppService.

use super::{AppError, AppResult, AppService};
use hragents_core::compliance::{
    BreachIncident, BreachSeverity, ErasureRequest, RetentionHold, RetentionPolicy, SubjectType,
};
use hragents_core::error::DomainError;
use hragents_core::ids::OperatorId;
use hragents_core::time::{BusinessDate, UtcInstant};

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct RetentionDueItem {
    pub record_type: String,
    pub subject_type: String,
    pub subject_id: String,
    pub subject_name: String,
    pub record_created: String,
    pub due_on: String,
    pub action: String,
    pub blocked_by_hold: bool,
}

impl AppService {
    // ------------------------------------------------------------------
    // Retention
    // ------------------------------------------------------------------

    pub fn seed_retention_policies(&mut self) -> AppResult<Vec<RetentionPolicy>> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let defaults = vec![
            ("candidate", 24, "purge", "consent + legitimate interest"),
            ("application", 24, "purge", "consent + legitimate interest"),
            (
                "communication",
                24,
                "purge",
                "consent + legitimate interest",
            ),
            (
                "employee_contact",
                84,
                "anonymize",
                "statutory payroll retention",
            ),
            ("payroll_run", 120, "archive", "statutory payroll retention"),
            (
                "audit_log",
                120,
                "archive",
                "tamper-evident evidence, never erased",
            ),
        ];
        let mut policies = Vec::new();
        for (record_type, months, action, basis) in defaults {
            let policy = RetentionPolicy {
                id: format!("retention-{record_type}"),
                record_type: record_type.into(),
                retention_months: months,
                action: match action {
                    "anonymize" => hragents_core::compliance::RetentionAction::Anonymize,
                    "archive" => hragents_core::compliance::RetentionAction::Archive,
                    _ => hragents_core::compliance::RetentionAction::Purge,
                },
                legal_basis: basis.into(),
                active: true,
            };
            self.store_mut().save_retention_policy(&policy)?;
            policies.push(policy);
        }
        self.append_audit_pub(
            "retention.policies_seeded",
            "system",
            "retention",
            serde_json::json!({"policies": policies.len()}),
            now,
        )?;
        Ok(policies)
    }

    pub fn list_retention_policies(&self) -> AppResult<Vec<RetentionPolicy>> {
        self.require_session_pub()?;
        Ok(self.store().list_retention_policies()?)
    }

    pub fn create_retention_hold(
        &mut self,
        subject_type: SubjectType,
        subject_id: &str,
        reason: &str,
        until: Option<BusinessDate>,
    ) -> AppResult<RetentionHold> {
        let now = UtcInstant::now();
        let operator = self.require_active_pub()?;
        let operator_id = operator.operator_id;
        if reason.trim().len() < 5 {
            return Err(AppError::Domain(DomainError::validation(
                "E_HOLD_REASON",
                "a retention hold needs a reason",
            )));
        }
        let hold = RetentionHold {
            id: format!("hold-{}", uuid::Uuid::new_v4()),
            subject_type,
            subject_id: subject_id.to_owned(),
            reason: reason.trim().to_owned(),
            until,
            created_by: operator_id,
            created_at: now,
        };
        self.store_mut().save_retention_hold(&hold)?;
        self.append_audit_pub(
            "retention.hold_created",
            "retention_hold",
            &hold.id,
            serde_json::json!({"subject_id": subject_id, "reason": hold.reason}),
            now,
        )?;
        Ok(hold)
    }

    pub fn release_retention_hold(&mut self, hold_id: &str) -> AppResult<()> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        self.store_mut().delete_retention_hold(hold_id)?;
        self.append_audit_pub(
            "retention.hold_released",
            "retention_hold",
            hold_id,
            serde_json::json!({}),
            now,
        )?;
        Ok(())
    }

    pub fn list_retention_holds(&self) -> AppResult<Vec<RetentionHold>> {
        self.require_session_pub()?;
        Ok(self.store().list_retention_holds()?)
    }

    /// Compute what is due under the active policies. Candidates whose records
    /// predate the policy window are listed for purge; employees are listed for
    /// anonymization review but never auto-purged (payroll is statutory).
    /// Holds block the item.
    pub fn retention_sweep(&self, today: BusinessDate) -> AppResult<Vec<RetentionDueItem>> {
        self.require_session_pub()?;
        let policies = self.store().list_retention_policies()?;
        let holds = self.store().list_retention_holds()?;
        let mut due = Vec::new();
        for policy in policies.iter().filter(|policy| policy.active) {
            match policy.record_type.as_str() {
                "candidate" | "application" | "communication" => {
                    for candidate in self.store().list_candidates()? {
                        let created = candidate.created_at.business_date();
                        let due_on = policy.due_on(created);
                        if due_on <= today {
                            let blocked = holds.iter().any(|hold| {
                                hold.subject_id == candidate.id.to_string() && hold.blocks(today)
                            });
                            due.push(RetentionDueItem {
                                record_type: policy.record_type.clone(),
                                subject_type: "candidate".into(),
                                subject_id: candidate.id.to_string(),
                                subject_name: candidate.full_name.clone(),
                                record_created: created.to_string(),
                                due_on: due_on.to_string(),
                                action: format!("{:?}", policy.action).to_lowercase(),
                                blocked_by_hold: blocked,
                            });
                        }
                    }
                }
                _ => {}
            }
        }
        due.sort_by(|a, b| a.due_on.cmp(&b.due_on));
        Ok(due)
    }

    // ------------------------------------------------------------------
    // Erasure
    // ------------------------------------------------------------------

    pub fn create_erasure_request(
        &mut self,
        subject_type: SubjectType,
        subject_id: &str,
        reason: &str,
    ) -> AppResult<ErasureRequest> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let request = ErasureRequest::new(subject_type, subject_id, reason, now)?;
        self.store_mut().save_erasure_request(&request)?;
        self.append_audit_pub(
            "erasure.requested",
            "erasure_request",
            &request.id.to_string(),
            serde_json::json!({"subject_id": subject_id, "reason": request.reason}),
            now,
        )?;
        Ok(request)
    }

    fn erasure_request(
        &self,
        id: hragents_core::ids::ErasureRequestId,
    ) -> AppResult<ErasureRequest> {
        self.store()
            .list_erasure_requests()?
            .into_iter()
            .find(|request| request.id == id)
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "erasure_request",
                    id: id.to_string(),
                })
            })
    }

    /// Approve an erasure. Named-human gate: fresh re-auth required.
    pub fn approve_erasure(
        &mut self,
        id: hragents_core::ids::ErasureRequestId,
    ) -> AppResult<ErasureRequest> {
        let now = UtcInstant::now();
        let operator_id = self.require_reauth_pub()?.operator_id;
        let mut request = self.erasure_request(id)?;
        request.approve(operator_id, now)?;
        self.store_mut().save_erasure_request(&request)?;
        self.append_audit_pub(
            "erasure.approved",
            "erasure_request",
            &request.id.to_string(),
            serde_json::json!({"reauth": true}),
            now,
        )?;
        Ok(request)
    }

    pub fn reject_erasure(
        &mut self,
        id: hragents_core::ids::ErasureRequestId,
        reason: &str,
    ) -> AppResult<ErasureRequest> {
        let now = UtcInstant::now();
        let operator_id = self.require_active_pub()?.operator_id;
        let mut request = self.erasure_request(id)?;
        request.reject(operator_id, reason, now)?;
        self.store_mut().save_erasure_request(&request)?;
        self.append_audit_pub(
            "erasure.rejected",
            "erasure_request",
            &request.id.to_string(),
            serde_json::json!({"reason": reason}),
            now,
        )?;
        Ok(request)
    }

    /// Execute an approved erasure. Named-human gate: fresh re-auth, holds
    /// block, audit rows and payroll records survive. Purges candidate PII or
    /// clears employee contact fields.
    pub fn execute_erasure(
        &mut self,
        id: hragents_core::ids::ErasureRequestId,
    ) -> AppResult<ErasureRequest> {
        let now = UtcInstant::now();
        self.require_reauth_pub()?;
        let mut request = self.erasure_request(id)?;
        let today = BusinessDate::today();
        let hold = self
            .store()
            .list_retention_holds()?
            .into_iter()
            .find(|hold| hold.subject_id == request.subject_id && hold.blocks(today));
        let plan = self
            .store_mut()
            .execute_erasure(&mut request, hold.as_ref())?;
        self.append_audit_pub(
            "erasure.executed",
            "erasure_request",
            &request.id.to_string(),
            serde_json::json!({
                "subject_id": request.subject_id,
                "purged": plan.purge,
                "retained": plan.retained,
                "reauth": true,
            }),
            now,
        )?;
        Ok(request)
    }

    pub fn list_erasure_requests(&self) -> AppResult<Vec<ErasureRequest>> {
        self.require_session_pub()?;
        Ok(self.store().list_erasure_requests()?)
    }

    // ------------------------------------------------------------------
    // Breach
    // ------------------------------------------------------------------

    pub fn report_breach(
        &mut self,
        title: &str,
        description: &str,
        severity: BreachSeverity,
    ) -> AppResult<BreachIncident> {
        let now = UtcInstant::now();
        let operator_id = self.require_active_pub()?.operator_id;
        if title.trim().len() < 5 {
            return Err(AppError::Domain(DomainError::validation(
                "E_BREACH_TITLE",
                "a breach report needs a title",
            )));
        }
        if description.trim().len() < 10 {
            return Err(AppError::Domain(DomainError::validation(
                "E_BREACH_DESCRIPTION",
                "a breach report needs a description of what happened",
            )));
        }
        let incident = BreachIncident {
            id: format!("breach-{}", &uuid::Uuid::new_v4().to_string()[..8]),
            title: title.trim().to_owned(),
            description: description.trim().to_owned(),
            severity,
            status: hragents_core::compliance::BreachStatus::Open,
            discovered_at: now,
            contained_at: None,
            notified_at: None,
            steps: Vec::new(),
            owner: operator_id,
        };
        self.store_mut().save_breach(&incident)?;
        self.append_audit_pub(
            "breach.reported",
            "breach",
            &incident.id,
            serde_json::json!({"title": incident.title, "severity": format!("{severity:?}")}),
            now,
        )?;
        Ok(incident)
    }

    fn breach(&self, id: &str) -> AppResult<BreachIncident> {
        self.store()
            .list_breaches()?
            .into_iter()
            .find(|incident| incident.id == id)
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "breach",
                    id: id.to_owned(),
                })
            })
    }

    pub fn contain_breach(&mut self, id: &str, step: &str) -> AppResult<BreachIncident> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut incident = self.breach(id)?;
        incident.contain(now, step)?;
        self.store_mut().save_breach(&incident)?;
        self.append_audit_pub(
            "breach.contained",
            "breach",
            &incident.id,
            serde_json::json!({"step": step}),
            now,
        )?;
        Ok(incident)
    }

    /// Mark the notifications sent (authority + affected people, outside the
    /// app). Notified is a status, not a transport: the app never sends it.
    pub fn mark_breach_notified(&mut self, id: &str) -> AppResult<BreachIncident> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut incident = self.breach(id)?;
        if !matches!(
            incident.status,
            hragents_core::compliance::BreachStatus::Contained
        ) {
            return Err(AppError::Domain(DomainError::conflict(
                "E_BREACH_STATE",
                "only a contained incident can move to notified",
            )));
        }
        incident.status = hragents_core::compliance::BreachStatus::Notified;
        incident.notified_at = Some(now);
        self.store_mut().save_breach(&incident)?;
        self.append_audit_pub(
            "breach.notified",
            "breach",
            &incident.id,
            serde_json::json!({}),
            now,
        )?;
        Ok(incident)
    }

    pub fn close_breach(&mut self, id: &str) -> AppResult<BreachIncident> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut incident = self.breach(id)?;
        if !matches!(
            incident.status,
            hragents_core::compliance::BreachStatus::Notified
                | hragents_core::compliance::BreachStatus::Contained
        ) {
            return Err(AppError::Domain(DomainError::conflict(
                "E_BREACH_STATE",
                "only a contained or notified incident can close",
            )));
        }
        incident.status = hragents_core::compliance::BreachStatus::Closed;
        self.store_mut().save_breach(&incident)?;
        self.append_audit_pub(
            "breach.closed",
            "breach",
            &incident.id,
            serde_json::json!({}),
            now,
        )?;
        Ok(incident)
    }

    pub fn list_breaches(&self) -> AppResult<Vec<BreachIncident>> {
        self.require_session_pub()?;
        Ok(self.store().list_breaches()?)
    }

    /// Convenience for tests and the UI: who can still be purged right now.
    pub fn erasure_blockers(&self, subject_id: &str) -> AppResult<Vec<RetentionHold>> {
        self.require_session_pub()?;
        let today = BusinessDate::today();
        Ok(self
            .store()
            .list_retention_holds()?
            .into_iter()
            .filter(|hold| hold.subject_id == subject_id && hold.blocks(today))
            .collect())
    }

    #[allow(dead_code)]
    fn _operator_marker(&self) -> Option<OperatorId> {
        None
    }
}
