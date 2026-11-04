//! Tauri commands for compliance: retention, erasure, breach.

use super::{AppState, CmdResult, parse_id, with_service};
use hragents_core::compliance::{
    BreachIncident, BreachSeverity, ErasureRequest, RetentionHold, RetentionPolicy, SubjectType,
};
use hragents_core::ids::ErasureRequestId;
use hragents_core::time::BusinessDate;
use tauri::State;

use hragents_ipc::RetentionDueItem;

fn parse_subject_type(raw: &str) -> CmdResult<SubjectType> {
    match raw {
        "candidate" => Ok(SubjectType::Candidate),
        "employee" => Ok(SubjectType::Employee),
        other => Err(super::CommandError {
            code: "E_SUBJECT_TYPE".into(),
            message: format!("unknown subject type {other}"),
        }),
    }
}

#[tauri::command]
pub fn seed_retention_policies(state: State<'_, AppState>) -> CmdResult<Vec<RetentionPolicy>> {
    with_service(&state, |service| service.seed_retention_policies())
}

#[tauri::command]
pub fn list_retention_policies(state: State<'_, AppState>) -> CmdResult<Vec<RetentionPolicy>> {
    with_service(&state, |service| service.list_retention_policies())
}

#[tauri::command]
pub fn create_retention_hold(
    state: State<'_, AppState>,
    subject_type: String,
    subject_id: String,
    reason: String,
    until: Option<BusinessDate>,
) -> CmdResult<RetentionHold> {
    let subject_type = parse_subject_type(&subject_type)?;
    with_service(&state, |service| {
        service.create_retention_hold(subject_type, &subject_id, &reason, until)
    })
}

#[tauri::command]
pub fn release_retention_hold(state: State<'_, AppState>, hold_id: String) -> CmdResult<()> {
    with_service(&state, |service| service.release_retention_hold(&hold_id))
}

#[tauri::command]
pub fn list_retention_holds(state: State<'_, AppState>) -> CmdResult<Vec<RetentionHold>> {
    with_service(&state, |service| service.list_retention_holds())
}

#[tauri::command]
pub fn retention_sweep(
    state: State<'_, AppState>,
    today: BusinessDate,
) -> CmdResult<Vec<RetentionDueItem>> {
    with_service(&state, |service| service.retention_sweep(today))
}

#[tauri::command]
pub fn create_erasure_request(
    state: State<'_, AppState>,
    subject_type: String,
    subject_id: String,
    reason: String,
) -> CmdResult<ErasureRequest> {
    let subject_type = parse_subject_type(&subject_type)?;
    with_service(&state, |service| {
        service.create_erasure_request(subject_type, &subject_id, &reason)
    })
}

#[tauri::command]
pub fn approve_erasure(
    state: State<'_, AppState>,
    request_id: String,
) -> CmdResult<ErasureRequest> {
    let request_id: ErasureRequestId = parse_id(&request_id)?;
    with_service(&state, |service| service.approve_erasure(request_id))
}

#[tauri::command]
pub fn grant_consent(
    state: State<'_, AppState>,
    subject_type: String,
    subject_id: String,
    purpose: String,
    source: String,
) -> CmdResult<hragents_core::compliance::ConsentRecord> {
    use hragents_core::compliance::ConsentPurpose;
    let subject_type = parse_subject_type(&subject_type)?;
    let purpose = match purpose.as_str() {
        "recruitment" => ConsentPurpose::Recruitment,
        "employment" => ConsentPurpose::Employment,
        "payroll" => ConsentPurpose::Payroll,
        "background_check" => ConsentPurpose::BackgroundCheck,
        "marketing" => ConsentPurpose::Marketing,
        other => {
            return Err(super::CommandError {
                code: "E_PURPOSE".into(),
                message: format!("unknown consent purpose {other}"),
            });
        }
    };
    with_service(&state, |service| {
        service.grant_consent(subject_type, &subject_id, purpose, &source)
    })
}

#[tauri::command]
pub fn withdraw_consent(
    state: State<'_, AppState>,
    subject_type: String,
    subject_id: String,
    reason: String,
) -> CmdResult<hragents_core::compliance::ConsentRecord> {
    let subject_type = parse_subject_type(&subject_type)?;
    with_service(&state, |service| {
        service.withdraw_consent(subject_type, &subject_id, &reason)
    })
}

#[tauri::command]
pub fn consent_for(
    state: State<'_, AppState>,
    subject_type: String,
    subject_id: String,
) -> CmdResult<Option<hragents_core::compliance::ConsentRecord>> {
    let subject_type = parse_subject_type(&subject_type)?;
    with_service(&state, |service| {
        Ok(service.store().consent_for(subject_type, &subject_id)?)
    })
}

#[tauri::command]
pub fn reject_erasure(
    state: State<'_, AppState>,
    request_id: String,
    reason: String,
) -> CmdResult<ErasureRequest> {
    let request_id: ErasureRequestId = parse_id(&request_id)?;
    with_service(&state, |service| {
        service.reject_erasure(request_id, &reason)
    })
}

#[tauri::command]
pub fn execute_erasure(
    state: State<'_, AppState>,
    request_id: String,
) -> CmdResult<ErasureRequest> {
    let request_id: ErasureRequestId = parse_id(&request_id)?;
    with_service(&state, |service| service.execute_erasure(request_id))
}

#[tauri::command]
pub fn list_erasure_requests(state: State<'_, AppState>) -> CmdResult<Vec<ErasureRequest>> {
    with_service(&state, |service| service.list_erasure_requests())
}

#[tauri::command]
pub fn erasure_blockers(
    state: State<'_, AppState>,
    subject_id: String,
) -> CmdResult<Vec<RetentionHold>> {
    with_service(&state, |service| service.erasure_blockers(&subject_id))
}

#[tauri::command]
pub fn report_breach(
    state: State<'_, AppState>,
    title: String,
    description: String,
    severity: String,
) -> CmdResult<BreachIncident> {
    let severity = match severity.as_str() {
        "low" => BreachSeverity::Low,
        "medium" => BreachSeverity::Medium,
        "high" => BreachSeverity::High,
        "critical" => BreachSeverity::Critical,
        other => {
            return Err(super::CommandError {
                code: "E_SEVERITY".into(),
                message: format!("unknown severity {other}"),
            });
        }
    };
    with_service(&state, |service| {
        service.report_breach(&title, &description, severity)
    })
}

#[tauri::command]
pub fn contain_breach(
    state: State<'_, AppState>,
    breach_id: String,
    step: String,
) -> CmdResult<BreachIncident> {
    with_service(&state, |service| service.contain_breach(&breach_id, &step))
}

#[tauri::command]
pub fn mark_breach_notified(
    state: State<'_, AppState>,
    breach_id: String,
) -> CmdResult<BreachIncident> {
    with_service(&state, |service| service.mark_breach_notified(&breach_id))
}

#[tauri::command]
pub fn close_breach(state: State<'_, AppState>, breach_id: String) -> CmdResult<BreachIncident> {
    with_service(&state, |service| service.close_breach(&breach_id))
}

#[tauri::command]
pub fn list_breaches(state: State<'_, AppState>) -> CmdResult<Vec<BreachIncident>> {
    with_service(&state, |service| service.list_breaches())
}
