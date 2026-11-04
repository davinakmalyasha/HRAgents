//! Tauri commands for growth, offboarding, and document requests.

use super::{AppState, CmdResult, parse_id, with_service};
use hragents_core::documents::DocumentRequest;
use hragents_core::growth::{Goal, ReviewAnswer, ReviewAssignment, ReviewCycle, ReviewForm};
use hragents_core::ids::{
    DocumentId, DocumentRequestId, EmployeeId, GoalId, PayrollRunId, ReviewAssignmentId,
    ReviewCycleId,
};
use hragents_core::offboarding::OffboardingPlan;
use hragents_core::time::BusinessDate;
use std::collections::BTreeMap;
use tauri::State;

#[tauri::command]
pub fn create_review_cycle(
    state: State<'_, AppState>,
    name: String,
    starts_on: BusinessDate,
    ends_on: BusinessDate,
) -> CmdResult<ReviewCycle> {
    with_service(&state, |service| {
        service.create_review_cycle(&name, starts_on, ends_on)
    })
}

#[tauri::command]
pub fn list_review_cycles(state: State<'_, AppState>) -> CmdResult<Vec<ReviewCycle>> {
    with_service(&state, |service| service.list_review_cycles())
}

#[tauri::command]
pub fn set_review_cycle_status(
    state: State<'_, AppState>,
    cycle_id: String,
    activate: bool,
) -> CmdResult<ReviewCycle> {
    let cycle_id: ReviewCycleId = parse_id(&cycle_id)?;
    with_service(&state, |service| {
        service.set_review_cycle_status(cycle_id, activate)
    })
}

#[tauri::command]
pub fn create_review_assignment(
    state: State<'_, AppState>,
    cycle_id: String,
    employee_id: String,
    reviewer_name: String,
    form: Option<ReviewForm>,
) -> CmdResult<ReviewAssignment> {
    let cycle_id: ReviewCycleId = parse_id(&cycle_id)?;
    let employee_id: EmployeeId = parse_id(&employee_id)?;
    with_service(&state, |service| {
        service.create_review_assignment(cycle_id, employee_id, &reviewer_name, form)
    })
}

#[tauri::command]
pub fn send_review_assignment(
    state: State<'_, AppState>,
    assignment_id: String,
) -> CmdResult<ReviewAssignment> {
    let assignment_id: ReviewAssignmentId = parse_id(&assignment_id)?;
    with_service(&state, |service| {
        service.send_review_assignment(assignment_id)
    })
}

#[tauri::command]
pub fn submit_review_response(
    state: State<'_, AppState>,
    assignment_id: String,
    answers: BTreeMap<String, ReviewAnswer>,
) -> CmdResult<ReviewAssignment> {
    let assignment_id: ReviewAssignmentId = parse_id(&assignment_id)?;
    with_service(&state, |service| {
        service.submit_review_response(assignment_id, answers)
    })
}

#[tauri::command]
pub fn summarize_review(
    state: State<'_, AppState>,
    assignment_id: String,
) -> CmdResult<ReviewAssignment> {
    let assignment_id: ReviewAssignmentId = parse_id(&assignment_id)?;
    with_service(&state, |service| service.summarize_review(assignment_id))
}

#[tauri::command]
pub fn list_review_assignments(
    state: State<'_, AppState>,
    cycle_id: Option<String>,
) -> CmdResult<Vec<ReviewAssignment>> {
    let cycle_id = cycle_id
        .as_deref()
        .map(parse_id::<ReviewCycleId>)
        .transpose()?;
    with_service(&state, |service| service.list_review_assignments(cycle_id))
}

#[tauri::command]
pub fn create_goal(
    state: State<'_, AppState>,
    employee_id: String,
    title: String,
) -> CmdResult<Goal> {
    let employee_id: EmployeeId = parse_id(&employee_id)?;
    with_service(&state, |service| service.create_goal(employee_id, &title))
}

#[tauri::command]
pub fn update_goal_progress(
    state: State<'_, AppState>,
    goal_id: String,
    progress_bp: i64,
) -> CmdResult<Goal> {
    let goal_id: GoalId = parse_id(&goal_id)?;
    with_service(&state, |service| {
        service.update_goal_progress(goal_id, progress_bp)
    })
}

#[tauri::command]
pub fn list_goals(state: State<'_, AppState>, employee_id: Option<String>) -> CmdResult<Vec<Goal>> {
    let employee_id = employee_id
        .as_deref()
        .map(parse_id::<EmployeeId>)
        .transpose()?;
    with_service(&state, |service| service.list_goals(employee_id))
}

#[tauri::command]
pub fn start_offboarding(
    state: State<'_, AppState>,
    employee_id: String,
    last_day: BusinessDate,
) -> CmdResult<OffboardingPlan> {
    let employee_id: EmployeeId = parse_id(&employee_id)?;
    with_service(&state, |service| {
        service.start_offboarding(employee_id, last_day)
    })
}

#[tauri::command]
pub fn offboarding_for(
    state: State<'_, AppState>,
    employee_id: String,
) -> CmdResult<Option<OffboardingPlan>> {
    let employee_id: EmployeeId = parse_id(&employee_id)?;
    with_service(&state, |service| service.offboarding_for(employee_id))
}

#[tauri::command]
pub fn complete_offboarding_step(
    state: State<'_, AppState>,
    employee_id: String,
    step_key: String,
) -> CmdResult<OffboardingPlan> {
    let employee_id: EmployeeId = parse_id(&employee_id)?;
    with_service(&state, |service| {
        service.complete_offboarding_step(employee_id, &step_key)
    })
}

#[tauri::command]
pub fn record_offboarding_final_pay(
    state: State<'_, AppState>,
    employee_id: String,
    run_id: String,
) -> CmdResult<OffboardingPlan> {
    let employee_id: EmployeeId = parse_id(&employee_id)?;
    let run_id: PayrollRunId = parse_id(&run_id)?;
    with_service(&state, |service| {
        service.record_offboarding_final_pay(employee_id, run_id)
    })
}

#[tauri::command]
pub fn finish_offboarding(
    state: State<'_, AppState>,
    employee_id: String,
) -> CmdResult<OffboardingPlan> {
    let employee_id: EmployeeId = parse_id(&employee_id)?;
    with_service(&state, |service| service.finish_offboarding(employee_id))
}

#[tauri::command]
pub fn create_document_request(
    state: State<'_, AppState>,
    employee_id: String,
    document_type: String,
    due_on: Option<BusinessDate>,
) -> CmdResult<DocumentRequest> {
    let employee_id: EmployeeId = parse_id(&employee_id)?;
    with_service(&state, |service| {
        service.create_document_request(employee_id, &document_type, due_on)
    })
}

#[tauri::command]
pub fn list_document_requests(
    state: State<'_, AppState>,
    employee_id: Option<String>,
) -> CmdResult<Vec<DocumentRequest>> {
    let employee_id = employee_id
        .as_deref()
        .map(parse_id::<EmployeeId>)
        .transpose()?;
    with_service(&state, |service| {
        service.list_document_requests(employee_id)
    })
}

#[tauri::command]
pub fn attach_document_request(
    state: State<'_, AppState>,
    request_id: String,
    document_id: String,
) -> CmdResult<DocumentRequest> {
    let request_id: DocumentRequestId = parse_id(&request_id)?;
    let document_id: DocumentId = parse_id(&document_id)?;
    with_service(&state, |service| {
        service.attach_document_request(request_id, document_id)
    })
}

#[tauri::command]
pub fn verify_document_request(
    state: State<'_, AppState>,
    request_id: String,
) -> CmdResult<DocumentRequest> {
    let request_id: DocumentRequestId = parse_id(&request_id)?;
    with_service(&state, |service| {
        service.verify_document_request(request_id)
    })
}

#[tauri::command]
pub fn reject_document_request(
    state: State<'_, AppState>,
    request_id: String,
    reason: String,
) -> CmdResult<DocumentRequest> {
    let request_id: DocumentRequestId = parse_id(&request_id)?;
    with_service(&state, |service| {
        service.reject_document_request(request_id, &reason)
    })
}
