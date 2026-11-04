use crate::approvals::{ApprovalRequest, ApprovalStatus};
use crate::hiring_comms::{Offer, OfferStatus};
use crate::leave::LeaveRequest;
use crate::people::{Contract, OnboardingPlan, OnboardingStatus};
use crate::time::{BusinessDate, UtcInstant};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ReminderSeverity {
    Urgent,
    Warning,
    Info,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Reminder {
    pub kind: String,
    pub title: String,
    pub detail: String,
    pub due_on: Option<BusinessDate>,
    pub severity: ReminderSeverity,
    pub subject_type: String,
    pub subject_id: String,
}

impl Reminder {
    fn new(
        kind: &str,
        title: impl Into<String>,
        detail: impl Into<String>,
        due_on: Option<BusinessDate>,
        severity: ReminderSeverity,
        subject_type: &str,
        subject_id: &str,
    ) -> Self {
        Self {
            kind: kind.into(),
            title: title.into(),
            detail: detail.into(),
            due_on,
            severity,
            subject_type: subject_type.into(),
            subject_id: subject_id.into(),
        }
    }
}

/// Deterministic reminder computation: pure function of records and the
/// business day. No network, no randomness, no LLM. The scheduler runs it;
/// the Today surface renders it.
#[allow(clippy::too_many_arguments)]
pub fn collect(
    today: BusinessDate,
    now: UtcInstant,
    approvals: &[ApprovalRequest],
    onboarding: &[(String, OnboardingPlan)],
    contracts: &[Contract],
    document_expiry: &[(String, String, BusinessDate)],
    offers: &[Offer],
    leave_requests: &[(LeaveRequest, String)],
) -> Vec<Reminder> {
    let _ = now;
    let mut reminders = Vec::new();

    for approval in approvals
        .iter()
        .filter(|item| item.status == ApprovalStatus::Open)
    {
        if approval.due_on.is_some_and(|due| due < today) {
            reminders.push(Reminder::new(
                "approval_overdue",
                format!("Overdue: {}", approval.title),
                format!(
                    "{} · was due {}",
                    approval.summary,
                    approval.due_on.unwrap()
                ),
                approval.due_on,
                ReminderSeverity::Urgent,
                "approval",
                &approval.id,
            ));
        }
    }

    for (employee_name, plan) in onboarding {
        if plan.status != OnboardingStatus::InProgress {
            continue;
        }
        let (done, total) = plan.progress();
        let age_days = today.days_between(plan.created_at.business_date()).abs();
        if total > 0 && done < total && age_days > 14 {
            reminders.push(Reminder::new(
                "onboarding_stalled",
                format!("{employee_name}'s onboarding is stalled"),
                format!("{done}/{total} steps done, started {age_days} days ago"),
                None,
                ReminderSeverity::Warning,
                "onboarding_plan",
                &plan.id.to_string(),
            ));
        }
    }

    for contract in contracts {
        if let Some(days) = contract.days_to_expiry(today)
            && (0..=30).contains(&days)
        {
            reminders.push(Reminder::new(
                "contract_expiring",
                "Contract expires soon".to_owned(),
                format!("employee {} ends in {days} day(s)", contract.employee_id),
                contract.end_date,
                if days <= 7 {
                    ReminderSeverity::Urgent
                } else {
                    ReminderSeverity::Warning
                },
                "contract",
                &contract.id.to_string(),
            ));
        }
    }

    for (owner_label, filename, expires_on) in document_expiry {
        let days = today.days_between(*expires_on);
        if (0..=30).contains(&days) {
            reminders.push(Reminder::new(
                "document_expiring",
                format!("{filename} expires soon"),
                format!("{owner_label} · expires {expires_on}"),
                Some(*expires_on),
                if days <= 7 {
                    ReminderSeverity::Urgent
                } else {
                    ReminderSeverity::Warning
                },
                "document",
                filename,
            ));
        }
    }

    for offer in offers
        .iter()
        .filter(|offer| offer.status == OfferStatus::Sent)
    {
        if offer.expires_on.is_some_and(|expires| expires < today) {
            reminders.push(Reminder::new(
                "offer_expired",
                "Sent offer passed its expiry".to_owned(),
                format!("run the expiry sweep for {}", offer.id),
                offer.expires_on,
                ReminderSeverity::Warning,
                "offer",
                &offer.id.to_string(),
            ));
        }
    }

    for (request, employee_name) in leave_requests {
        if request.status == crate::leave::LeaveStatus::Pending
            && today.days_between(request.created_at.business_date()).abs() > 3
        {
            reminders.push(Reminder::new(
                "leave_pending",
                format!("{employee_name}'s leave waits for a decision"),
                format!("{} · {}", request.reason, request.start_date),
                Some(request.start_date),
                ReminderSeverity::Info,
                "leave_request",
                &request.id.to_string(),
            ));
        }
    }

    reminders.sort_by(|a, b| {
        severity_rank(a.severity)
            .cmp(&severity_rank(b.severity))
            .then_with(|| a.due_on.cmp(&b.due_on))
            .then_with(|| a.title.cmp(&b.title))
    });
    reminders
}

const fn severity_rank(severity: ReminderSeverity) -> u8 {
    match severity {
        ReminderSeverity::Urgent => 0,
        ReminderSeverity::Warning => 1,
        ReminderSeverity::Info => 2,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ids::{EmployeeId, LeaveRequestId, LeaveTypeId, OperatorId};
    use crate::people::ContractKind;

    fn now() -> UtcInstant {
        UtcInstant::from_millis(1_760_000_000_000).unwrap()
    }

    fn today() -> BusinessDate {
        BusinessDate::parse("2026-11-02").unwrap()
    }

    #[test]
    fn overdue_approval_is_urgent_and_first() {
        let mut approval = ApprovalRequest::new(
            crate::approvals::ApprovalKind::Document,
            "Verify KTP",
            "stale",
            "document",
            "d1",
            now(),
        );
        approval.due_on = Some(BusinessDate::parse("2026-10-01").unwrap());
        let reminders = collect(
            today(),
            now(),
            std::slice::from_ref(&approval),
            &[],
            &[],
            &[],
            &[],
            &[],
        );
        assert_eq!(reminders.len(), 1);
        assert_eq!(reminders[0].severity, ReminderSeverity::Urgent);
        assert_eq!(reminders[0].kind, "approval_overdue");
    }

    #[test]
    fn stalled_onboarding_warns_after_two_weeks() {
        let employee = EmployeeId::new();
        let fresh = UtcInstant::from_rfc3339("2026-11-01T00:00:00Z").unwrap();
        let fresh_plan = OnboardingPlan::start(
            employee,
            "Standard",
            vec![crate::people::OnboardingStep::new("a", "A", "docs")],
            fresh,
        )
        .unwrap();
        let reminders = collect(
            today(),
            now(),
            &[],
            &[("Ayu".into(), fresh_plan)],
            &[],
            &[],
            &[],
            &[],
        );
        // Started yesterday: not stalled.
        assert!(reminders.is_empty());

        let old = UtcInstant::from_rfc3339("2026-09-01T00:00:00Z").unwrap();
        let old_plan = OnboardingPlan::start(
            employee,
            "Standard",
            vec![crate::people::OnboardingStep::new("a", "A", "docs")],
            old,
        )
        .unwrap();
        let reminders = collect(
            today(),
            now(),
            &[],
            &[("Ayu".into(), old_plan)],
            &[],
            &[],
            &[],
            &[],
        );
        assert_eq!(reminders.len(), 1);
        assert_eq!(reminders[0].kind, "onboarding_stalled");
    }

    #[test]
    fn contract_expiry_windows() {
        let contract = Contract {
            id: crate::ids::ContractId::new(),
            employee_id: EmployeeId::new(),
            kind: ContractKind::FixedTerm,
            start_date: BusinessDate::parse("2026-01-01").unwrap(),
            end_date: Some(BusinessDate::parse("2026-11-05").unwrap()),
            status: crate::people::ContractStatus::Active,
            document_id: None,
            created_at: now(),
        };
        let reminders = collect(
            today(),
            now(),
            &[],
            &[],
            std::slice::from_ref(&contract),
            &[],
            &[],
            &[],
        );
        assert_eq!(reminders.len(), 1);
        assert_eq!(reminders[0].severity, ReminderSeverity::Urgent);
    }

    #[test]
    fn document_expiry_and_offer_and_leave() {
        let request = LeaveRequest {
            id: LeaveRequestId::new(),
            employee_id: EmployeeId::new(),
            leave_type_id: LeaveTypeId::new(),
            start_date: BusinessDate::parse("2026-11-10").unwrap(),
            end_date: BusinessDate::parse("2026-11-10").unwrap(),
            days_x2: 2,
            half_day_start: false,
            half_day_end: false,
            reason: "trip".into(),
            status: crate::leave::LeaveStatus::Pending,
            recorded_by: OperatorId::new(),
            decided_by: None,
            decided_at: None,
            decision_note: None,
            attachment_document_id: None,
            created_at: UtcInstant::from_millis(1_760_000_000_000 - 5 * 86_400_000).unwrap(),
        };
        let reminders = collect(
            today(),
            now(),
            &[],
            &[],
            &[],
            &[(
                "Ayu".into(),
                "KTP.pdf".into(),
                BusinessDate::parse("2026-11-04").unwrap(),
            )],
            &[],
            &[(request, "Ayu".into())],
        );
        assert!(
            reminders
                .iter()
                .any(|item| item.kind == "document_expiring")
        );
        assert!(reminders.iter().any(|item| item.kind == "leave_pending"));
    }

    #[test]
    fn ordering_is_urgent_first_then_due_date() {
        let mk = |kind: &str, severity: ReminderSeverity| {
            Reminder::new(kind, kind, kind, None, severity, "x", "y")
        };
        let mut reminders = [
            mk("b", ReminderSeverity::Info),
            mk("a", ReminderSeverity::Urgent),
            mk("c", ReminderSeverity::Warning),
        ];
        reminders.sort_by(|a, b| {
            severity_rank(a.severity)
                .cmp(&severity_rank(b.severity))
                .then_with(|| a.title.cmp(&b.title))
        });

        assert_eq!(reminders[0].kind, "a");
        assert_eq!(reminders[2].kind, "b");
    }
}
