use crate::error::{DomainError, DomainResult};
use crate::ids::OperatorId;
use crate::time::{BusinessDate, UtcInstant};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ApprovalKind {
    RejectionOverride,
    PayrollSignOff,
    OfferApproval,
    Erasure,
    Leave,
    Document,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ApprovalStatus {
    Open,
    Approved,
    Rejected,
    Expired,
    Cancelled,
}

#[derive(
    Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize, schemars::JsonSchema,
)]
#[serde(rename_all = "snake_case")]
pub enum Priority {
    Low,
    Normal,
    High,
    Urgent,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct ApprovalRequest {
    pub id: String,
    pub kind: ApprovalKind,
    pub title: String,
    pub summary: String,
    pub subject_type: String,
    pub subject_id: String,
    pub status: ApprovalStatus,
    pub priority: Priority,
    pub due_on: Option<BusinessDate>,
    pub requested_by: Option<OperatorId>,
    pub created_at: UtcInstant,
    pub decided_by: Option<OperatorId>,
    pub decided_at: Option<UtcInstant>,
    pub decision_note: Option<String>,
}

impl ApprovalRequest {
    pub fn new(
        kind: ApprovalKind,
        title: impl Into<String>,
        summary: impl Into<String>,
        subject_type: impl Into<String>,
        subject_id: impl Into<String>,
        created_at: UtcInstant,
    ) -> Self {
        Self {
            id: format!("AP-{}", &uuid::Uuid::new_v4().simple().to_string()[..8]),
            kind,
            title: title.into(),
            summary: summary.into(),
            subject_type: subject_type.into(),
            subject_id: subject_id.into(),
            status: ApprovalStatus::Open,
            priority: Priority::Normal,
            due_on: None,
            requested_by: None,
            created_at,
            decided_by: None,
            decided_at: None,
            decision_note: None,
        }
    }

    pub fn approve(
        &mut self,
        operator_id: OperatorId,
        note: &str,
        now: UtcInstant,
    ) -> DomainResult<()> {
        self.decide(ApprovalStatus::Approved, operator_id, note, now)
    }

    pub fn reject(
        &mut self,
        operator_id: OperatorId,
        note: &str,
        now: UtcInstant,
    ) -> DomainResult<()> {
        if note.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_APPROVAL_NOTE",
                "a rejection needs a reason",
            ));
        }
        self.decide(ApprovalStatus::Rejected, operator_id, note, now)
    }

    fn decide(
        &mut self,
        status: ApprovalStatus,
        operator_id: OperatorId,
        note: &str,
        now: UtcInstant,
    ) -> DomainResult<()> {
        if self.status != ApprovalStatus::Open {
            return Err(DomainError::conflict(
                "E_APPROVAL_CLOSED",
                "this request has already been decided",
            ));
        }
        self.status = status;
        self.decided_by = Some(operator_id);
        self.decided_at = Some(now);
        if !note.trim().is_empty() {
            self.decision_note = Some(note.trim().to_owned());
        }
        Ok(())
    }

    pub fn expire_if_due(&mut self, today: BusinessDate) -> bool {
        if self.status == ApprovalStatus::Open && self.due_on.is_some_and(|due| due < today) {
            self.status = ApprovalStatus::Expired;
            return true;
        }
        false
    }
}

/// The Today inbox ordering: urgent first, then due date, then age.
pub fn priority_order(requests: &[ApprovalRequest]) -> Vec<&ApprovalRequest> {
    let mut open: Vec<&ApprovalRequest> = requests
        .iter()
        .filter(|request| request.status == ApprovalStatus::Open)
        .collect();
    open.sort_by(|a, b| {
        b.priority
            .cmp(&a.priority)
            .then_with(|| match (a.due_on, b.due_on) {
                (Some(a), Some(b)) => a.cmp(&b),
                (Some(_), None) => std::cmp::Ordering::Less,
                (None, Some(_)) => std::cmp::Ordering::Greater,
                (None, None) => std::cmp::Ordering::Equal,
            })
            .then_with(|| a.created_at.cmp(&b.created_at))
    });
    open
}

#[cfg(test)]
mod tests {
    use super::*;

    fn now() -> UtcInstant {
        UtcInstant::from_millis(1_760_000_000_000).unwrap()
    }

    #[test]
    fn approval_is_named_and_one_shot() {
        let mut request = ApprovalRequest::new(
            ApprovalKind::RejectionOverride,
            "Reject above the merit floor",
            "Candidate scores 82; rejection needs sign-off",
            "application",
            "a1",
            now(),
        );
        request
            .approve(OperatorId::new(), "evidence reviewed", now())
            .unwrap();
        assert_eq!(request.status, ApprovalStatus::Approved);
        assert!(request.approve(OperatorId::new(), "", now()).is_err());
    }

    #[test]
    fn rejection_needs_a_reason() {
        let mut request = ApprovalRequest::new(
            ApprovalKind::OfferApproval,
            "Approve offer",
            "Offer for Ayu",
            "offer",
            "o1",
            now(),
        );
        assert!(request.reject(OperatorId::new(), "no", now()).is_err());
    }

    #[test]
    fn today_orders_urgent_and_due_first() {
        let mut low =
            ApprovalRequest::new(ApprovalKind::Document, "Low", "", "document", "d1", now());
        low.priority = Priority::Low;
        let mut urgent = ApprovalRequest::new(
            ApprovalKind::PayrollSignOff,
            "Urgent",
            "",
            "payroll",
            "p1",
            now(),
        );
        urgent.priority = Priority::Urgent;
        urgent.due_on = Some(BusinessDate::parse("2026-11-01").unwrap());
        let requests = [low, urgent];
        let order = priority_order(&requests);
        assert_eq!(order[0].title, "Urgent");
    }
}
