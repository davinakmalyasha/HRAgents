use crate::error::{DomainError, DomainResult};
use crate::ids::{EmployeeId, OffboardingPlanId, PayrollRunId};
use crate::time::{BusinessDate, UtcInstant};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum OffboardingStatus {
    Draft,
    InProgress,
    Completed,
    Cancelled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum OffboardingStepStatus {
    Pending,
    InProgress,
    Done,
    Skipped,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct OffboardingStep {
    pub key: String,
    pub title: String,
    pub owner: String,
    pub required: bool,
    pub status: OffboardingStepStatus,
    pub completed_at: Option<UtcInstant>,
    pub completed_by: Option<String>,
    pub notes: Option<String>,
}

impl OffboardingStep {
    pub fn new(key: impl Into<String>, title: impl Into<String>, owner: impl Into<String>) -> Self {
        Self {
            key: key.into(),
            title: title.into(),
            owner: owner.into(),
            required: true,
            status: OffboardingStepStatus::Pending,
            completed_at: None,
            completed_by: None,
            notes: None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct OffboardingPlan {
    pub id: OffboardingPlanId,
    pub employee_id: EmployeeId,
    pub last_day: BusinessDate,
    pub status: OffboardingStatus,
    pub steps: Vec<OffboardingStep>,
    pub final_pay_run_id: Option<PayrollRunId>,
    pub created_at: UtcInstant,
    pub completed_at: Option<UtcInstant>,
}

impl OffboardingPlan {
    pub fn start(
        employee_id: EmployeeId,
        last_day: BusinessDate,
        steps: Vec<OffboardingStep>,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        if steps.is_empty() {
            return Err(DomainError::validation(
                "E_OFFBOARDING_EMPTY",
                "an offboarding plan needs at least one step",
            ));
        }
        let mut keys = BTreeSet::new();
        for step in &steps {
            if !keys.insert(step.key.as_str()) {
                return Err(DomainError::validation(
                    "E_OFFBOARDING_DUPLICATE",
                    format!("duplicate offboarding step {}", step.key),
                ));
            }
        }
        Ok(Self {
            id: OffboardingPlanId::new(),
            employee_id,
            last_day,
            status: OffboardingStatus::InProgress,
            steps,
            final_pay_run_id: None,
            created_at: now,
            completed_at: None,
        })
    }

    pub fn complete_step(
        &mut self,
        key: &str,
        by: impl Into<String>,
        now: UtcInstant,
    ) -> DomainResult<()> {
        if self.status != OffboardingStatus::InProgress {
            return Err(DomainError::conflict(
                "E_OFFBOARDING_CLOSED",
                "this offboarding plan is no longer in progress",
            ));
        }
        let step = self
            .steps
            .iter_mut()
            .find(|step| step.key == key)
            .ok_or_else(|| DomainError::NotFound {
                entity: "offboarding_step",
                id: key.to_owned(),
            })?;
        if step.status == OffboardingStepStatus::Done {
            return Err(DomainError::conflict(
                "E_STEP_DONE",
                "this step is already complete",
            ));
        }
        step.status = OffboardingStepStatus::Done;
        step.completed_at = Some(now);
        step.completed_by = Some(by.into());
        Ok(())
    }

    pub fn skip_step(&mut self, key: &str, reason: &str) -> DomainResult<()> {
        if reason.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_SKIP_REASON",
                "skipping an offboarding step needs a reason",
            ));
        }
        let step = self
            .steps
            .iter_mut()
            .find(|step| step.key == key)
            .ok_or_else(|| DomainError::NotFound {
                entity: "offboarding_step",
                id: key.to_owned(),
            })?;
        step.status = OffboardingStepStatus::Skipped;
        step.notes = Some(reason.to_owned());
        Ok(())
    }

    pub fn record_final_pay(&mut self, run_id: PayrollRunId) {
        self.final_pay_run_id = Some(run_id);
    }

    /// Finishing is a named-human gate: every required step is done or skipped
    /// with a reason, and a final payroll run has been recorded. The command
    /// layer also requires a fresh re-auth before calling this.
    pub fn finish(&mut self, now: UtcInstant) -> DomainResult<()> {
        if self.status != OffboardingStatus::InProgress {
            return Err(DomainError::conflict(
                "E_OFFBOARDING_CLOSED",
                "this plan is no longer in progress",
            ));
        }
        let open: Vec<&str> = self
            .steps
            .iter()
            .filter(|step| {
                step.required
                    && !matches!(
                        step.status,
                        OffboardingStepStatus::Done | OffboardingStepStatus::Skipped
                    )
            })
            .map(|step| step.key.as_str())
            .collect();
        if !open.is_empty() {
            return Err(DomainError::conflict(
                "E_OFFBOARDING_OPEN_STEPS",
                format!("required steps remain open: {}", open.join(", ")),
            ));
        }
        if self.final_pay_run_id.is_none() {
            return Err(DomainError::conflict(
                "E_FINAL_PAY_REQUIRED",
                "record the final payroll run before completing offboarding",
            ));
        }
        self.status = OffboardingStatus::Completed;
        self.completed_at = Some(now);
        Ok(())
    }

    pub fn progress(&self) -> (usize, usize) {
        let done = self
            .steps
            .iter()
            .filter(|step| step.required)
            .filter(|step| {
                matches!(
                    step.status,
                    OffboardingStepStatus::Done | OffboardingStepStatus::Skipped
                )
            })
            .count();
        let total = self.steps.iter().filter(|step| step.required).count();
        (done, total)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn now() -> UtcInstant {
        UtcInstant::from_millis(1_760_000_000_000).unwrap()
    }

    fn plan() -> OffboardingPlan {
        OffboardingPlan::start(
            EmployeeId::new(),
            BusinessDate::parse("2026-12-31").unwrap(),
            vec![
                OffboardingStep::new("handover", "Hand over projects", "Manager"),
                OffboardingStep::new("assets", "Return laptop and badges", "IT"),
                OffboardingStep::new("exit", "Run exit interview", "HR"),
            ],
            now(),
        )
        .unwrap()
    }

    #[test]
    fn finish_requires_steps_and_final_pay() {
        let mut plan = plan();
        plan.complete_step("handover", "Rina", now()).unwrap();
        plan.complete_step("assets", "IT", now()).unwrap();
        plan.skip_step("exit", "employee declined").unwrap();
        assert!(plan.finish(now()).is_err());
        plan.record_final_pay(PayrollRunId::new());
        plan.finish(now()).unwrap();
        assert_eq!(plan.status, OffboardingStatus::Completed);
    }

    #[test]
    fn open_required_step_blocks_finish() {
        let mut plan = plan();
        plan.record_final_pay(PayrollRunId::new());
        assert!(matches!(
            plan.finish(now()),
            Err(DomainError::Conflict {
                code: "E_OFFBOARDING_OPEN_STEPS",
                ..
            })
        ));
    }

    #[test]
    fn skip_needs_a_reason() {
        let mut plan = plan();
        assert!(plan.skip_step("exit", "").is_err());
    }
}
