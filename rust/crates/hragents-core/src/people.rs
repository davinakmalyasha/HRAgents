use crate::error::{DomainError, DomainResult};
use crate::ids::{ContractId, DocumentId, EmployeeId, OnboardingPlanId};
use crate::time::{BusinessDate, UtcInstant};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum EmploymentStatus {
    Active,
    Probation,
    Notice,
    Exited,
}

impl EmploymentStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Probation => "probation",
            Self::Notice => "notice",
            Self::Exited => "exited",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ContractKind {
    Permanent,
    FixedTerm,
    Probation,
    Intern,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ContractStatus {
    Draft,
    Active,
    Expired,
    Terminated,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Contract {
    pub id: ContractId,
    pub employee_id: EmployeeId,
    pub kind: ContractKind,
    pub start_date: BusinessDate,
    pub end_date: Option<BusinessDate>,
    pub status: ContractStatus,
    pub document_id: Option<DocumentId>,
    pub created_at: UtcInstant,
}

impl Contract {
    pub fn activate(&mut self) -> DomainResult<()> {
        match self.status {
            ContractStatus::Draft => {
                self.status = ContractStatus::Active;
                Ok(())
            }
            other => Err(DomainError::Transition {
                from: format!("{other:?}").to_lowercase(),
                to: "active".into(),
            }),
        }
    }

    pub fn terminate(&mut self, on: BusinessDate) -> DomainResult<()> {
        if self.status != ContractStatus::Active {
            return Err(DomainError::Transition {
                from: format!("{:?}", self.status).to_lowercase(),
                to: "terminated".into(),
            });
        }
        if self.end_date.is_none_or(|end| on < end) {
            self.end_date = Some(on);
        }
        self.status = ContractStatus::Terminated;
        Ok(())
    }

    pub fn days_to_expiry(&self, today: BusinessDate) -> Option<i64> {
        self.end_date.map(|end| today.days_between(end))
    }
}

/// The payroll-relevant employee record. JKK class, dependents, PTKP status,
/// bank details, and BPJS membership live here because the Python product kept
/// them nowhere and payroll silently over- or under-withheld.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Employee {
    pub id: EmployeeId,
    pub employee_no: String,
    pub full_name: String,
    pub preferred_name: Option<String>,
    pub email: Option<String>,
    pub phone: Option<String>,
    pub job_title: String,
    pub org_unit: String,
    pub manager_id: Option<EmployeeId>,
    pub status: EmploymentStatus,
    pub hire_date: BusinessDate,
    pub end_date: Option<BusinessDate>,
    pub birth_date: Option<BusinessDate>,
    pub ptkp_status: Option<String>,
    pub dependents: u8,
    pub jkk_risk_class: Option<u8>,
    pub npwp: Option<String>,
    pub bank_name: Option<String>,
    pub bank_account: Option<String>,
    pub bpjs_kesehatan_no: Option<String>,
    pub bpjs_ketenagakerjaan_no: Option<String>,
    pub created_at: UtcInstant,
    pub updated_at: UtcInstant,
    pub version: i64,
}

impl Employee {
    pub fn new(
        employee_no: impl Into<String>,
        full_name: impl Into<String>,
        job_title: impl Into<String>,
        org_unit: impl Into<String>,
        hire_date: BusinessDate,
        created_at: UtcInstant,
    ) -> Self {
        Self {
            id: EmployeeId::new(),
            employee_no: employee_no.into(),
            full_name: full_name.into(),
            preferred_name: None,
            email: None,
            phone: None,
            job_title: job_title.into(),
            org_unit: org_unit.into(),
            manager_id: None,
            status: EmploymentStatus::Active,
            hire_date,
            end_date: None,
            birth_date: None,
            ptkp_status: None,
            dependents: 0,
            jkk_risk_class: None,
            npwp: None,
            bank_name: None,
            bank_account: None,
            bpjs_kesehatan_no: None,
            bpjs_ketenagakerjaan_no: None,
            created_at,
            updated_at: created_at,
            version: 1,
        }
    }

    pub fn display_name(&self) -> &str {
        self.preferred_name.as_deref().unwrap_or(&self.full_name)
    }

    pub fn validate(&self) -> DomainResult<()> {
        if self.full_name.trim().len() < 2 {
            return Err(DomainError::validation(
                "E_EMPLOYEE_NAME",
                "employee name is required",
            ));
        }
        if self.employee_no.trim().is_empty() {
            return Err(DomainError::validation(
                "E_EMPLOYEE_NO",
                "employee number is required",
            ));
        }
        if self.dependents > 10 {
            return Err(DomainError::validation(
                "E_DEPENDENTS",
                "dependents must be between 0 and 10",
            ));
        }
        if let Some(class) = self.jkk_risk_class
            && !(1..=5).contains(&class)
        {
            return Err(DomainError::validation(
                "E_JKK_CLASS",
                "BPJS JKK risk class must be 1 through 5",
            ));
        }
        if self.status == EmploymentStatus::Exited && self.end_date.is_none() {
            return Err(DomainError::validation(
                "E_EXIT_DATE",
                "an exited employee needs an end date",
            ));
        }
        Ok(())
    }

    pub fn exit(&mut self, on: BusinessDate, now: UtcInstant) -> DomainResult<()> {
        if self.status == EmploymentStatus::Exited {
            return Err(DomainError::conflict(
                "E_ALREADY_EXITED",
                "this employee has already exited",
            ));
        }
        if on < self.hire_date {
            return Err(DomainError::validation(
                "E_EXIT_BEFORE_HIRE",
                "exit date cannot precede the hire date",
            ));
        }
        self.status = EmploymentStatus::Exited;
        self.end_date = Some(on);
        self.updated_at = now;
        self.version += 1;
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum OnboardingStatus {
    Draft,
    InProgress,
    Completed,
    Cancelled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum StepStatus {
    Pending,
    InProgress,
    Done,
    Skipped,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct OnboardingStep {
    pub key: String,
    pub title: String,
    pub category: String,
    pub required: bool,
    pub status: StepStatus,
    pub due_date: Option<BusinessDate>,
    pub completed_at: Option<UtcInstant>,
    pub completed_by: Option<String>,
    pub document_request_id: Option<String>,
    pub notes: Option<String>,
}

impl OnboardingStep {
    pub fn new(
        key: impl Into<String>,
        title: impl Into<String>,
        category: impl Into<String>,
    ) -> Self {
        Self {
            key: key.into(),
            title: title.into(),
            category: category.into(),
            required: true,
            status: StepStatus::Pending,
            due_date: None,
            completed_at: None,
            completed_by: None,
            document_request_id: None,
            notes: None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct OnboardingPlan {
    pub id: OnboardingPlanId,
    pub employee_id: EmployeeId,
    pub template_name: String,
    pub status: OnboardingStatus,
    pub steps: Vec<OnboardingStep>,
    pub created_at: UtcInstant,
    pub completed_at: Option<UtcInstant>,
}

impl OnboardingPlan {
    pub fn start(
        employee_id: EmployeeId,
        template_name: impl Into<String>,
        steps: Vec<OnboardingStep>,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        if steps.is_empty() {
            return Err(DomainError::validation(
                "E_ONBOARDING_EMPTY",
                "an onboarding plan needs at least one step",
            ));
        }
        let mut seen = std::collections::BTreeSet::new();
        for step in &steps {
            if !seen.insert(step.key.clone()) {
                return Err(DomainError::validation(
                    "E_ONBOARDING_DUPLICATE_STEP",
                    format!("duplicate onboarding step key {}", step.key),
                ));
            }
        }
        Ok(Self {
            id: OnboardingPlanId::new(),
            employee_id,
            template_name: template_name.into(),
            status: OnboardingStatus::InProgress,
            steps,
            created_at: now,
            completed_at: None,
        })
    }

    pub fn complete_step(
        &mut self,
        key: &str,
        completed_by: impl Into<String>,
        now: UtcInstant,
    ) -> DomainResult<()> {
        if self.status != OnboardingStatus::InProgress {
            return Err(DomainError::conflict(
                "E_ONBOARDING_CLOSED",
                "this onboarding plan is no longer in progress",
            ));
        }
        let step = self
            .steps
            .iter_mut()
            .find(|step| step.key == key)
            .ok_or_else(|| DomainError::NotFound {
                entity: "onboarding_step",
                id: key.to_owned(),
            })?;
        if step.status == StepStatus::Done {
            return Err(DomainError::conflict(
                "E_STEP_DONE",
                "this onboarding step is already complete",
            ));
        }
        step.status = StepStatus::Done;
        step.completed_at = Some(now);
        step.completed_by = Some(completed_by.into());
        if self.required_steps_done() {
            self.status = OnboardingStatus::Completed;
            self.completed_at = Some(now);
        }
        Ok(())
    }

    pub fn skip_step(&mut self, key: &str, reason: &str, now: UtcInstant) -> DomainResult<()> {
        if reason.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_SKIP_REASON",
                "skipping a step needs a reason",
            ));
        }
        let step = self
            .steps
            .iter_mut()
            .find(|step| step.key == key)
            .ok_or_else(|| DomainError::NotFound {
                entity: "onboarding_step",
                id: key.to_owned(),
            })?;
        step.status = StepStatus::Skipped;
        step.notes = Some(reason.to_owned());
        if self.required_steps_done() {
            self.status = OnboardingStatus::Completed;
            self.completed_at = Some(now);
        }
        Ok(())
    }

    pub fn required_steps_done(&self) -> bool {
        self.steps
            .iter()
            .filter(|step| step.required)
            .all(|step| matches!(step.status, StepStatus::Done | StepStatus::Skipped))
    }

    pub fn progress(&self) -> (usize, usize) {
        let done = self
            .steps
            .iter()
            .filter(|step| step.required)
            .filter(|step| matches!(step.status, StepStatus::Done | StepStatus::Skipped))
            .count();
        let total = self.steps.iter().filter(|step| step.required).count();
        (done, total)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum DocumentStatus {
    Pending,
    Verified,
    Rejected,
    Expired,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum DocumentOwnerType {
    Employee,
    Candidate,
    Company,
    PayrollRun,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Document {
    pub id: DocumentId,
    pub owner_type: DocumentOwnerType,
    pub owner_id: String,
    pub filename: String,
    pub mime_type: String,
    pub sha256: String,
    pub size_bytes: i64,
    pub status: DocumentStatus,
    pub expires_on: Option<BusinessDate>,
    pub uploaded_at: UtcInstant,
    pub verified_at: Option<UtcInstant>,
    pub verified_by: Option<String>,
    pub rejection_reason: Option<String>,
    pub tags: Vec<String>,
}

impl Document {
    pub fn verify(&mut self, by: impl Into<String>, now: UtcInstant) -> DomainResult<()> {
        if self.status != DocumentStatus::Pending {
            return Err(DomainError::Transition {
                from: format!("{:?}", self.status).to_lowercase(),
                to: "verified".into(),
            });
        }
        self.status = DocumentStatus::Verified;
        self.verified_at = Some(now);
        self.verified_by = Some(by.into());
        Ok(())
    }

    pub fn reject(
        &mut self,
        reason: &str,
        by: impl Into<String>,
        now: UtcInstant,
    ) -> DomainResult<()> {
        if reason.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_REJECT_REASON",
                "rejecting a document needs a reason",
            ));
        }
        if self.status != DocumentStatus::Pending {
            return Err(DomainError::Transition {
                from: format!("{:?}", self.status).to_lowercase(),
                to: "rejected".into(),
            });
        }
        self.status = DocumentStatus::Rejected;
        self.verified_at = Some(now);
        self.verified_by = Some(by.into());
        self.rejection_reason = Some(reason.to_owned());
        Ok(())
    }

    pub fn is_expired(&self, today: BusinessDate) -> bool {
        self.expires_on.is_some_and(|date| date < today)
    }
}

/// Aggregates used by the People surface without loading every record.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Headcount {
    pub total: usize,
    pub active: usize,
    pub probation: usize,
    pub notice: usize,
    pub by_org_unit: BTreeMap<String, usize>,
}

impl Headcount {
    pub fn from_employees(employees: &[Employee]) -> Self {
        let mut headcount = Self::default();
        for employee in employees {
            if employee.status == EmploymentStatus::Exited {
                continue;
            }
            headcount.total += 1;
            match employee.status {
                EmploymentStatus::Active => headcount.active += 1,
                EmploymentStatus::Probation => headcount.probation += 1,
                EmploymentStatus::Notice => headcount.notice += 1,
                EmploymentStatus::Exited => {}
            }
            *headcount
                .by_org_unit
                .entry(employee.org_unit.clone())
                .or_insert(0) += 1;
        }
        headcount
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn now() -> UtcInstant {
        UtcInstant::from_millis(1_760_000_000_000).unwrap()
    }

    #[test]
    fn onboarding_completes_only_when_required_steps_done() {
        let mut plan = OnboardingPlan::start(
            EmployeeId::new(),
            "Standard",
            vec![
                OnboardingStep::new("contract", "Sign contract", "documents"),
                OnboardingStep::new("laptop", "Issue laptop", "assets"),
            ],
            now(),
        )
        .unwrap();
        plan.complete_step("contract", "Rina", now()).unwrap();
        assert_eq!(plan.status, OnboardingStatus::InProgress);
        assert_eq!(plan.progress(), (1, 2));
        plan.complete_step("laptop", "Rina", now()).unwrap();
        assert_eq!(plan.status, OnboardingStatus::Completed);
    }

    #[test]
    fn skip_requires_a_reason() {
        let mut plan = OnboardingPlan::start(
            EmployeeId::new(),
            "Standard",
            vec![OnboardingStep::new("laptop", "Issue laptop", "assets")],
            now(),
        )
        .unwrap();
        assert!(plan.skip_step("laptop", "", now()).is_err());
        plan.skip_step("laptop", "remote worker", now()).unwrap();
        assert_eq!(plan.status, OnboardingStatus::Completed);
    }

    #[test]
    fn exited_employee_needs_end_date() {
        let mut employee = Employee::new(
            "E-001",
            "Ayu Lestari",
            "Engineer",
            "Product",
            BusinessDate::parse("2024-01-15").unwrap(),
            now(),
        );
        assert!(employee.validate().is_ok());
        employee.status = EmploymentStatus::Exited;
        assert!(employee.validate().is_err());
    }

    #[test]
    fn document_verification_requires_pending_state() {
        let mut document = Document {
            id: DocumentId::new(),
            owner_type: DocumentOwnerType::Employee,
            owner_id: EmployeeId::new().to_string(),
            filename: "ktp.pdf".into(),
            mime_type: "application/pdf".into(),
            sha256: "a".repeat(64),
            size_bytes: 10,
            status: DocumentStatus::Pending,
            expires_on: None,
            uploaded_at: now(),
            verified_at: None,
            verified_by: None,
            rejection_reason: None,
            tags: vec![],
        };
        document.verify("Rina", now()).unwrap();
        assert!(document.verify("Rina", now()).is_err());
    }
}
