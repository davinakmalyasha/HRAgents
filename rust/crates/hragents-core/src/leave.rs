use crate::error::{DomainError, DomainResult};
use crate::ids::{EmployeeId, LeaveRequestId, LeaveTypeId, OperatorId};
use crate::time::{BusinessDate, UtcInstant};
use serde::{Deserialize, Serialize};

/// Leave is counted in half-days (`x2`) so no float ever enters a balance.
pub const HALF_DAY: i32 = 1;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct LeaveType {
    pub id: LeaveTypeId,
    pub name: String,
    pub annual_quota_x2: i32,
    pub carry_over_max_x2: i32,
    pub requires_attachment: bool,
    pub active: bool,
}

impl LeaveType {
    pub fn annual(name: impl Into<String>, days: i32) -> Self {
        Self {
            id: LeaveTypeId::new(),
            name: name.into(),
            annual_quota_x2: days * 2,
            carry_over_max_x2: 0,
            requires_attachment: false,
            active: true,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct LeaveBalance {
    pub employee_id: EmployeeId,
    pub leave_type_id: LeaveTypeId,
    pub year: i32,
    pub entitled_x2: i32,
    pub adjustment_x2: i32,
    pub used_x2: i32,
    pub pending_x2: i32,
}

impl LeaveBalance {
    pub fn new(
        employee_id: EmployeeId,
        leave_type_id: LeaveTypeId,
        year: i32,
        entitled_x2: i32,
    ) -> Self {
        Self {
            employee_id,
            leave_type_id,
            year,
            entitled_x2,
            adjustment_x2: 0,
            used_x2: 0,
            pending_x2: 0,
        }
    }

    pub fn available_x2(&self) -> i32 {
        self.entitled_x2 + self.adjustment_x2 - self.used_x2 - self.pending_x2
    }

    pub fn available_days(&self) -> f64 {
        f64::from(self.available_x2()) / 2.0
    }

    pub fn adjust(&mut self, delta_x2: i32, reason: &str) -> DomainResult<()> {
        if reason.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_ADJUST_REASON",
                "a balance adjustment needs a reason",
            ));
        }
        if self.available_x2() + delta_x2 < 0 {
            return Err(DomainError::conflict(
                "E_BALANCE_NEGATIVE",
                "this adjustment would make the available balance negative",
            ));
        }
        self.adjustment_x2 += delta_x2;
        Ok(())
    }

    fn reserve(&mut self, days_x2: i32) -> DomainResult<()> {
        if days_x2 <= 0 {
            return Err(DomainError::validation(
                "E_LEAVE_DAYS",
                "leave must be at least half a day",
            ));
        }
        if self.available_x2() < days_x2 {
            return Err(DomainError::conflict(
                "E_INSUFFICIENT_BALANCE",
                format!(
                    "only {} day(s) available, {} requested",
                    self.available_days(),
                    f64::from(days_x2) / 2.0
                ),
            ));
        }
        self.pending_x2 += days_x2;
        Ok(())
    }

    fn settle(&mut self, days_x2: i32, approved: bool) {
        self.pending_x2 -= days_x2;
        if approved {
            self.used_x2 += days_x2;
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum LeaveStatus {
    Pending,
    Approved,
    Rejected,
    Cancelled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum LeaveDecision {
    Approve,
    Reject,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct LeaveRequest {
    pub id: LeaveRequestId,
    pub employee_id: EmployeeId,
    pub leave_type_id: LeaveTypeId,
    pub start_date: BusinessDate,
    pub end_date: BusinessDate,
    pub days_x2: i32,
    pub half_day_start: bool,
    pub half_day_end: bool,
    pub reason: String,
    pub status: LeaveStatus,
    pub recorded_by: OperatorId,
    pub decided_by: Option<OperatorId>,
    pub decided_at: Option<UtcInstant>,
    pub decision_note: Option<String>,
    pub attachment_document_id: Option<String>,
    pub created_at: UtcInstant,
}

impl LeaveRequest {
    #[allow(clippy::too_many_arguments)]
    pub fn record(
        employee_id: EmployeeId,
        leave_type_id: LeaveTypeId,
        start_date: BusinessDate,
        end_date: BusinessDate,
        days_x2: i32,
        recorded_by: OperatorId,
        reason: &str,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        if end_date < start_date {
            return Err(DomainError::validation(
                "E_LEAVE_DATES",
                "end date cannot precede start date",
            ));
        }
        if reason.trim().len() < 3 {
            return Err(DomainError::validation(
                "E_LEAVE_REASON",
                "leave needs a reason",
            ));
        }
        let calendar_days_x2 =
            i32::try_from((start_date.days_between(end_date) + 1) * 2).unwrap_or(i32::MAX);
        if days_x2 <= 0 || days_x2 > calendar_days_x2 {
            return Err(DomainError::validation(
                "E_LEAVE_DAYS",
                format!("days must be between 0.5 and {calendar_days_x2} half-days"),
            ));
        }
        Ok(Self {
            id: LeaveRequestId::new(),
            employee_id,
            leave_type_id,
            start_date,
            end_date,
            days_x2,
            half_day_start: false,
            half_day_end: false,
            reason: reason.trim().to_owned(),
            status: LeaveStatus::Pending,
            recorded_by,
            decided_by: None,
            decided_at: None,
            decision_note: None,
            attachment_document_id: None,
            created_at: now,
        })
    }

    pub fn submit(&mut self, balance: &mut LeaveBalance) -> DomainResult<()> {
        if self.status != LeaveStatus::Pending {
            return Err(DomainError::conflict(
                "E_LEAVE_CLOSED",
                "this request is no longer pending",
            ));
        }
        if balance.leave_type_id != self.leave_type_id || balance.employee_id != self.employee_id {
            return Err(DomainError::invariant(
                "leave balance does not belong to this employee and type",
            ));
        }
        balance.reserve(self.days_x2)
    }

    pub fn decide(
        &mut self,
        balance: &mut LeaveBalance,
        decision: LeaveDecision,
        operator_id: OperatorId,
        note: &str,
        now: UtcInstant,
    ) -> DomainResult<()> {
        if self.status != LeaveStatus::Pending {
            return Err(DomainError::conflict(
                "E_LEAVE_CLOSED",
                "this request has already been decided",
            ));
        }
        if decision == LeaveDecision::Reject && note.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_LEAVE_DECISION_NOTE",
                "a rejection needs a note",
            ));
        }
        let approved = decision == LeaveDecision::Approve;
        balance.settle(self.days_x2, approved);
        self.status = if approved {
            LeaveStatus::Approved
        } else {
            LeaveStatus::Rejected
        };
        self.decided_by = Some(operator_id);
        self.decided_at = Some(now);
        self.decision_note = (!note.trim().is_empty()).then(|| note.trim().to_owned());
        Ok(())
    }

    /// Cancel an approved request and return the days to the balance. The reason
    /// is mandatory because a reversal without one is unauditable.
    pub fn cancel(
        &mut self,
        balance: &mut LeaveBalance,
        operator_id: OperatorId,
        reason: &str,
        now: UtcInstant,
    ) -> DomainResult<()> {
        if self.status != LeaveStatus::Approved {
            return Err(DomainError::conflict(
                "E_LEAVE_NOT_APPROVED",
                "only an approved request can be cancelled",
            ));
        }
        if reason.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_CANCEL_REASON",
                "a cancellation needs a reason",
            ));
        }
        if balance.used_x2 < self.days_x2 {
            return Err(DomainError::invariant(
                "approved leave exceeds the balance's used days",
            ));
        }
        balance.used_x2 -= self.days_x2;
        self.status = LeaveStatus::Cancelled;
        self.decided_by = Some(operator_id);
        self.decided_at = Some(now);
        self.decision_note = Some(reason.trim().to_owned());
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn now() -> UtcInstant {
        UtcInstant::from_millis(1_760_000_000_000).unwrap()
    }

    fn balance() -> LeaveBalance {
        LeaveBalance::new(EmployeeId::new(), LeaveTypeId::new(), 2026, 24)
    }

    fn request(balance: &LeaveBalance) -> LeaveRequest {
        LeaveRequest::record(
            balance.employee_id,
            balance.leave_type_id,
            BusinessDate::parse("2026-11-09").unwrap(),
            BusinessDate::parse("2026-11-10").unwrap(),
            4,
            OperatorId::new(),
            "family event",
            now(),
        )
        .unwrap()
    }

    #[test]
    fn approve_moves_pending_to_used() {
        let mut balance = balance();
        let mut request = request(&balance);
        request.submit(&mut balance).unwrap();
        assert_eq!(balance.pending_x2, 4);
        request
            .decide(
                &mut balance,
                LeaveDecision::Approve,
                OperatorId::new(),
                "",
                now(),
            )
            .unwrap();
        assert_eq!(balance.pending_x2, 0);
        assert_eq!(balance.used_x2, 4);
        assert_eq!(balance.available_x2(), 20);
    }

    #[test]
    fn cannot_reserve_more_than_available() {
        let mut balance = LeaveBalance::new(EmployeeId::new(), LeaveTypeId::new(), 2026, 2);
        let mut request = LeaveRequest::record(
            balance.employee_id,
            balance.leave_type_id,
            BusinessDate::parse("2026-11-09").unwrap(),
            BusinessDate::parse("2026-11-12").unwrap(),
            8,
            OperatorId::new(),
            "trip",
            now(),
        )
        .unwrap();
        assert!(request.submit(&mut balance).is_err());
    }

    #[test]
    fn rejection_releases_pending() {
        let mut balance = balance();
        let mut request = request(&balance);
        request.submit(&mut balance).unwrap();
        request
            .decide(
                &mut balance,
                LeaveDecision::Reject,
                OperatorId::new(),
                "team is on release that week",
                now(),
            )
            .unwrap();
        assert_eq!(balance.pending_x2, 0);
        assert_eq!(balance.used_x2, 0);
        assert_eq!(request.status, LeaveStatus::Rejected);
    }

    #[test]
    fn cancel_returns_days() {
        let mut balance = balance();
        let mut request = request(&balance);
        request.submit(&mut balance).unwrap();
        request
            .decide(
                &mut balance,
                LeaveDecision::Approve,
                OperatorId::new(),
                "",
                now(),
            )
            .unwrap();
        request
            .cancel(&mut balance, OperatorId::new(), "employee withdrew", now())
            .unwrap();
        assert_eq!(balance.available_x2(), 24);
    }
}
