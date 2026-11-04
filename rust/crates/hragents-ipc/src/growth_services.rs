//! Growth, offboarding, and document-request application services.
//!
//! Kept in a separate module so the core employee/hiring/payroll service file
//! stays navigable. The methods use the same session, audit, and store rules.

use super::{AppError, AppResult, AppService};
use hragents_core::documents::DocumentRequest;
use hragents_core::error::DomainError;
use hragents_core::growth::{Goal, ReviewAnswer, ReviewAssignment, ReviewCycle, ReviewForm};
use hragents_core::ids::{
    DocumentId, DocumentRequestId, EmployeeId, GoalId, PayrollRunId, ReviewAssignmentId,
    ReviewCycleId,
};
use hragents_core::offboarding::{OffboardingPlan, OffboardingStep};
use hragents_core::time::{BusinessDate, UtcInstant};
use std::collections::BTreeMap;

impl AppService {
    // ------------------------------------------------------------------
    // Growth
    // ------------------------------------------------------------------

    pub fn create_review_cycle(
        &mut self,
        name: &str,
        starts_on: BusinessDate,
        ends_on: BusinessDate,
    ) -> AppResult<ReviewCycle> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let cycle = ReviewCycle::new(name, starts_on, ends_on, now)?;
        self.store_mut().save_review_cycle(&cycle)?;
        self.append_audit_pub(
            "growth.cycle_created",
            "review_cycle",
            &cycle.id.to_string(),
            serde_json::json!({"name": cycle.name, "starts_on": starts_on.to_string()}),
            now,
        )?;
        Ok(cycle)
    }

    pub fn list_review_cycles(&self) -> AppResult<Vec<ReviewCycle>> {
        self.require_session_pub()?;
        Ok(self.store().list_review_cycles()?)
    }

    pub fn set_review_cycle_status(
        &mut self,
        cycle_id: ReviewCycleId,
        activate: bool,
    ) -> AppResult<ReviewCycle> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut cycle = self
            .store()
            .list_review_cycles()?
            .into_iter()
            .find(|cycle| cycle.id == cycle_id)
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "review_cycle",
                    id: cycle_id.to_string(),
                })
            })?;
        if activate {
            cycle.activate()?;
        } else {
            cycle.close()?;
        }
        self.store_mut().save_review_cycle(&cycle)?;
        self.append_audit_pub(
            if activate {
                "growth.cycle_activated"
            } else {
                "growth.cycle_closed"
            },
            "review_cycle",
            &cycle.id.to_string(),
            serde_json::json!({"name": cycle.name}),
            now,
        )?;
        Ok(cycle)
    }

    pub fn create_review_assignment(
        &mut self,
        cycle_id: ReviewCycleId,
        employee_id: EmployeeId,
        reviewer_name: &str,
        form: Option<ReviewForm>,
    ) -> AppResult<ReviewAssignment> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let employee = self.store().employee(employee_id)?;
        let assignment = ReviewAssignment::new(
            cycle_id,
            employee.id,
            reviewer_name,
            form.unwrap_or_else(ReviewForm::standard),
            now,
        )?;
        self.store_mut().save_review_assignment(&assignment)?;
        self.append_audit_pub(
            "growth.assignment_created",
            "review_assignment",
            &assignment.id.to_string(),
            serde_json::json!({"employee": employee.full_name, "reviewer": reviewer_name}),
            now,
        )?;
        Ok(assignment)
    }

    fn review_assignment(&self, id: ReviewAssignmentId) -> AppResult<ReviewAssignment> {
        self.store()
            .list_review_assignments(None)?
            .into_iter()
            .find(|assignment| assignment.id == id)
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "review_assignment",
                    id: id.to_string(),
                })
            })
    }

    pub fn send_review_assignment(
        &mut self,
        id: ReviewAssignmentId,
    ) -> AppResult<ReviewAssignment> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut assignment = self.review_assignment(id)?;
        assignment.send(now)?;
        self.store_mut().save_review_assignment(&assignment)?;
        self.append_audit_pub(
            "growth.assignment_sent",
            "review_assignment",
            &assignment.id.to_string(),
            serde_json::json!({"reviewer": assignment.reviewer_name}),
            now,
        )?;
        Ok(assignment)
    }

    pub fn submit_review_response(
        &mut self,
        id: ReviewAssignmentId,
        answers: BTreeMap<String, ReviewAnswer>,
    ) -> AppResult<ReviewAssignment> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut assignment = self.review_assignment(id)?;
        assignment.submit(answers, now)?;
        self.store_mut().save_review_assignment(&assignment)?;
        self.append_audit_pub(
            "growth.response_imported",
            "review_assignment",
            &assignment.id.to_string(),
            serde_json::json!({
                "reviewer": assignment.reviewer_name,
                "answers": assignment.response.as_ref().map(|answers| answers.len()),
            }),
            now,
        )?;
        Ok(assignment)
    }

    pub fn summarize_review(&mut self, id: ReviewAssignmentId) -> AppResult<ReviewAssignment> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut assignment = self.review_assignment(id)?;
        assignment.summarize()?;
        self.store_mut().save_review_assignment(&assignment)?;
        self.append_audit_pub(
            "growth.review_summarized",
            "review_assignment",
            &assignment.id.to_string(),
            serde_json::json!({"reviewer": assignment.reviewer_name}),
            now,
        )?;
        Ok(assignment)
    }

    pub fn list_review_assignments(
        &self,
        cycle_id: Option<ReviewCycleId>,
    ) -> AppResult<Vec<ReviewAssignment>> {
        self.require_session_pub()?;
        Ok(self.store().list_review_assignments(cycle_id)?)
    }

    pub fn create_goal(&mut self, employee_id: EmployeeId, title: &str) -> AppResult<Goal> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut goal = Goal::new(employee_id, title, now)?;
        goal.activate()?;
        self.store_mut().save_goal(&goal)?;
        self.append_audit_pub(
            "goal.created",
            "goal",
            &goal.id.to_string(),
            serde_json::json!({"title": goal.title}),
            now,
        )?;
        Ok(goal)
    }

    pub fn update_goal_progress(&mut self, goal_id: GoalId, progress_bp: i64) -> AppResult<Goal> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut goal = self
            .store()
            .list_goals(None)?
            .into_iter()
            .find(|goal| goal.id == goal_id)
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "goal",
                    id: goal_id.to_string(),
                })
            })?;
        goal.set_progress(progress_bp)?;
        self.store_mut().save_goal(&goal)?;
        self.append_audit_pub(
            "goal.progress_updated",
            "goal",
            &goal.id.to_string(),
            serde_json::json!({"progress_bp": progress_bp, "status": format!("{:?}", goal.status)}),
            now,
        )?;
        Ok(goal)
    }

    pub fn list_goals(&self, employee_id: Option<EmployeeId>) -> AppResult<Vec<Goal>> {
        self.require_session_pub()?;
        Ok(self.store().list_goals(employee_id)?)
    }

    // ------------------------------------------------------------------
    // Offboarding
    // ------------------------------------------------------------------

    fn default_offboarding_steps() -> Vec<OffboardingStep> {
        vec![
            OffboardingStep::new("handover", "Hand over projects and documents", "Manager"),
            OffboardingStep::new("assets", "Return laptop, badges, and equipment", "IT"),
            OffboardingStep::new("access", "Revoke accounts and access", "IT"),
            OffboardingStep::new("exit", "Run the exit interview", "HR"),
            OffboardingStep::new("final_pay", "Prepare the final payroll run", "HR"),
        ]
    }

    pub fn start_offboarding(
        &mut self,
        employee_id: EmployeeId,
        last_day: BusinessDate,
    ) -> AppResult<OffboardingPlan> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let employee = self.store().employee(employee_id)?;
        let plan = OffboardingPlan::start(
            employee.id,
            last_day,
            Self::default_offboarding_steps(),
            now,
        )?;
        self.store_mut().save_offboarding_plan(&plan)?;
        self.append_audit_pub(
            "offboarding.started",
            "offboarding_plan",
            &plan.id.to_string(),
            serde_json::json!({"employee": employee.full_name, "last_day": last_day.to_string()}),
            now,
        )?;
        Ok(plan)
    }

    pub fn offboarding_for(&self, employee_id: EmployeeId) -> AppResult<Option<OffboardingPlan>> {
        self.require_session_pub()?;
        Ok(self.store().offboarding_plan_for(employee_id)?)
    }

    pub fn complete_offboarding_step(
        &mut self,
        employee_id: EmployeeId,
        step_key: &str,
    ) -> AppResult<OffboardingPlan> {
        let now = UtcInstant::now();
        let actor_name = self.require_active_pub()?.operator_name.clone();
        let mut plan = self
            .store()
            .offboarding_plan_for(employee_id)?
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "offboarding_plan",
                    id: employee_id.to_string(),
                })
            })?;
        plan.complete_step(step_key, actor_name, now)?;
        self.store_mut().save_offboarding_plan(&plan)?;
        self.append_audit_pub(
            "offboarding.step_completed",
            "offboarding_plan",
            &plan.id.to_string(),
            serde_json::json!({"employee_id": employee_id.to_string(), "step": step_key}),
            now,
        )?;
        Ok(plan)
    }

    pub fn record_offboarding_final_pay(
        &mut self,
        employee_id: EmployeeId,
        run_id: PayrollRunId,
    ) -> AppResult<OffboardingPlan> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut plan = self
            .store()
            .offboarding_plan_for(employee_id)?
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "offboarding_plan",
                    id: employee_id.to_string(),
                })
            })?;
        plan.record_final_pay(run_id);
        self.store_mut().save_offboarding_plan(&plan)?;
        self.append_audit_pub(
            "offboarding.final_pay_recorded",
            "offboarding_plan",
            &plan.id.to_string(),
            serde_json::json!({"payroll_run_id": run_id.to_string()}),
            now,
        )?;
        Ok(plan)
    }

    /// Named-human gate: finishing offboarding requires a fresh re-auth, every
    /// required step done or skipped, and a recorded final payroll run.
    pub fn finish_offboarding(&mut self, employee_id: EmployeeId) -> AppResult<OffboardingPlan> {
        let now = UtcInstant::now();
        self.require_reauth_pub()?;
        let mut plan = self
            .store()
            .offboarding_plan_for(employee_id)?
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "offboarding_plan",
                    id: employee_id.to_string(),
                })
            })?;
        plan.finish(now)?;
        self.store_mut().save_offboarding_plan(&plan)?;
        self.append_audit_pub(
            "offboarding.completed",
            "offboarding_plan",
            &plan.id.to_string(),
            serde_json::json!({"employee_id": employee_id.to_string(), "reauth": true}),
            now,
        )?;
        Ok(plan)
    }

    // ------------------------------------------------------------------
    // Document requests
    // ------------------------------------------------------------------

    pub fn create_document_request(
        &mut self,
        employee_id: EmployeeId,
        document_type: &str,
        due_on: Option<BusinessDate>,
    ) -> AppResult<DocumentRequest> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let employee = self.store().employee(employee_id)?;
        let request = DocumentRequest::new(employee.id, document_type, due_on, now)?;
        self.store_mut().save_document_request(&request)?;
        self.append_audit_pub(
            "document_request.created",
            "document_request",
            &request.id.to_string(),
            serde_json::json!({"employee": employee.full_name, "type": request.document_type}),
            now,
        )?;
        Ok(request)
    }

    pub fn list_document_requests(
        &self,
        employee_id: Option<EmployeeId>,
    ) -> AppResult<Vec<DocumentRequest>> {
        self.require_session_pub()?;
        Ok(self.store().list_document_requests(employee_id)?)
    }

    fn document_request(&self, id: DocumentRequestId) -> AppResult<DocumentRequest> {
        self.store()
            .list_document_requests(None)?
            .into_iter()
            .find(|request| request.id == id)
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "document_request",
                    id: id.to_string(),
                })
            })
    }

    pub fn attach_document_request(
        &mut self,
        id: DocumentRequestId,
        document_id: DocumentId,
    ) -> AppResult<DocumentRequest> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        self.store().document(document_id)?;
        let mut request = self.document_request(id)?;
        request.attach(document_id)?;
        self.store_mut().save_document_request(&request)?;
        self.append_audit_pub(
            "document_request.attached",
            "document_request",
            &request.id.to_string(),
            serde_json::json!({"document_id": document_id.to_string()}),
            now,
        )?;
        Ok(request)
    }

    pub fn verify_document_request(&mut self, id: DocumentRequestId) -> AppResult<DocumentRequest> {
        let now = UtcInstant::now();
        let actor_name = self.require_active_pub()?.operator_name.clone();
        let mut request = self.document_request(id)?;
        request.verify(actor_name)?;
        self.store_mut().save_document_request(&request)?;
        self.append_audit_pub(
            "document_request.verified",
            "document_request",
            &request.id.to_string(),
            serde_json::json!({}),
            now,
        )?;
        Ok(request)
    }

    pub fn reject_document_request(
        &mut self,
        id: DocumentRequestId,
        reason: &str,
    ) -> AppResult<DocumentRequest> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut request = self.document_request(id)?;
        request.reject(reason)?;
        self.store_mut().save_document_request(&request)?;
        self.append_audit_pub(
            "document_request.rejected",
            "document_request",
            &request.id.to_string(),
            serde_json::json!({"reason": reason}),
            now,
        )?;
        Ok(request)
    }
}
