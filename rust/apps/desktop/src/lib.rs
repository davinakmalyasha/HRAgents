//! Tauri 2.12 command surface. Every command delegates to `hragents-ipc`; no
//! business rule lives here. The state is a single `AppService`, which owns the
//! only SQLite connection and the unlocked operator session.

use hragents_core::approvals::ApprovalRequest;
use hragents_core::hiring::{Application, Evidence, Rubric, RunScores};
use hragents_core::ids::{
    ApplicationId, DocumentId, EmployeeId, JobId, LeaveRequestId, LeaveTypeId, PayrollRunId,
};
use hragents_core::leave::{LeaveBalance, LeaveType};
use hragents_core::payroll::{PayrollInput, PayrollKind, PayrollRun};
use hragents_core::people::{Document, DocumentOwnerType, Employee, OnboardingPlan};
use hragents_core::time::BusinessDate;
use hragents_ipc::{
    AppError, AppService, CreateEmployeeInput, EvaluationView, ImportCandidateInput, LeaveView,
    PayrollView, RecordLeaveInput, SearchHit, SessionView, SetupInput, TodayView,
};
use serde::Serialize;
use std::str::FromStr;
use std::sync::{Arc, Mutex};
use tauri::{Manager, State};

mod growth_commands;
use growth_commands::*;
mod compliance_commands;
use compliance_commands::*;
mod hiring_commands;
use hiring_commands::*;

pub(crate) struct AppState {
    service: Arc<Mutex<AppService>>,
}

/// Shared handle that lets the background scheduler drive the same
/// single-connection AppService the commands use. Jobs run under the
/// unlocked operator session when one exists; when the app is locked they
/// fail fast and log, never blocking the loop.
struct SharedBackend(Arc<Mutex<AppService>>);

impl hragents_ipc::scheduler::JobBackend for SharedBackend {
    fn run_retention_sweep(&mut self) -> Result<usize, String> {
        self.0
            .lock()
            .map_err(|_| "state is poisoned".to_owned())?
            .retention_sweep(hragents_core::time::BusinessDate::today())
            .map(|due| due.len())
            .map_err(|error| error.to_string())
    }

    fn run_offer_sweep(&mut self) -> Result<usize, String> {
        self.0
            .lock()
            .map_err(|_| "state is poisoned".to_owned())?
            .sweep_expired_offers(hragents_core::time::BusinessDate::today())
            .map_err(|error| error.to_string())
    }

    fn run_backup(&mut self) -> Result<u64, String> {
        Err("backup directory is not configured".to_owned())
    }

    fn run_backup_to(&mut self, dest: &std::path::Path) -> Result<u64, String> {
        self.0
            .lock()
            .map_err(|_| "state is poisoned".to_owned())?
            .backup(dest)
            .map_err(|error| error.to_string())
    }

    fn run_reminders(&mut self) -> Result<usize, String> {
        self.0
            .lock()
            .map_err(|_| "state is poisoned".to_owned())?
            .reminders()
            .map(|items| items.len())
            .map_err(|error| error.to_string())
    }

    fn run_outbox(&mut self) -> Result<usize, String> {
        self.0
            .lock()
            .map_err(|_| "state is poisoned".to_owned())?
            .outbox_pending()
            .map(|items| items.len())
            .map_err(|error| error.to_string())
    }

    fn run_inbox_poll(&mut self) -> Result<usize, String> {
        self.0
            .lock()
            .map_err(|_| "state is poisoned".to_owned())?
            .poll_replies()
            .map_err(|error| error.to_string())
    }

    fn verify_audit(&self) -> Result<usize, String> {
        self.0
            .lock()
            .map_err(|_| "state is poisoned".to_owned())?
            .audit_verify()
            .map(|verification| verification.entries)
            .map_err(|error| error.to_string())
    }
}

struct SchedulerState {
    _shutdown: tokio::sync::watch::Sender<bool>,
}

#[derive(Debug, Serialize)]
pub(crate) struct CommandError {
    pub(crate) code: String,
    pub(crate) message: String,
}

impl From<AppError> for CommandError {
    fn from(error: AppError) -> Self {
        Self {
            code: error.code().to_owned(),
            message: error.to_string(),
        }
    }
}

pub(crate) type CmdResult<T> = Result<T, CommandError>;

pub(crate) fn with_service<T>(
    state: &State<'_, AppState>,
    action: impl FnOnce(&mut AppService) -> Result<T, AppError>,
) -> CmdResult<T> {
    let mut guard = state.service.lock().map_err(|_| CommandError {
        code: "E_STATE".into(),
        message: "state is poisoned".into(),
    })?;
    action(&mut guard).map_err(Into::into)
}

pub(crate) fn parse_id<T: FromStr>(raw: &str) -> CmdResult<T>
where
    T::Err: std::fmt::Display,
{
    raw.parse().map_err(|error: T::Err| CommandError {
        code: "E_ID".into(),
        message: error.to_string(),
    })
}

#[derive(Debug, Serialize)]
struct AppInfo {
    name: &'static str,
    version: &'static str,
    company: Option<String>,
    setup_required: bool,
    role: &'static str,
}

#[tauri::command]
fn app_info(state: State<'_, AppState>) -> CmdResult<AppInfo> {
    with_service(&state, |service| {
        Ok(AppInfo {
            name: "HRAgents",
            version: env!("CARGO_PKG_VERSION"),
            company: service.company_name()?,
            setup_required: service.setup_required()?,
            role: "hr_operator",
        })
    })
}

#[tauri::command]
fn setup_first_run(state: State<'_, AppState>, input: SetupInput) -> CmdResult<SessionView> {
    with_service(&state, |service| service.setup_first_run(input))
}

#[tauri::command]
fn login(state: State<'_, AppState>, username: String, password: String) -> CmdResult<SessionView> {
    with_service(&state, |service| service.login(&username, &password))
}

#[tauri::command]
fn logout(state: State<'_, AppState>) -> CmdResult<()> {
    with_service(&state, AppService::logout)
}

#[tauri::command]
fn lock(state: State<'_, AppState>) -> CmdResult<()> {
    with_service(&state, AppService::lock)
}

#[tauri::command]
fn unlock(state: State<'_, AppState>, password: String) -> CmdResult<SessionView> {
    with_service(&state, |service| service.unlock(&password))
}

#[tauri::command]
fn reauth(state: State<'_, AppState>, password: String) -> CmdResult<SessionView> {
    with_service(&state, |service| service.reauth(&password))
}

#[tauri::command]
fn recovery_key(state: State<'_, AppState>, password: String) -> CmdResult<String> {
    with_service(&state, |service| service.recovery_key(&password))
}

#[tauri::command]
fn rewrap_install_key(state: State<'_, AppState>, password: String) -> CmdResult<()> {
    with_service(&state, |service| {
        service.rewrap_install_key(&password)?;
        Ok(())
    })
}

#[tauri::command]
fn current_session(state: State<'_, AppState>) -> CmdResult<SessionView> {
    with_service(&state, |service| service.current_session())
}

#[tauri::command]
fn today(state: State<'_, AppState>) -> CmdResult<TodayView> {
    with_service(&state, |service| service.today())
}

#[tauri::command]
fn create_employee(state: State<'_, AppState>, input: CreateEmployeeInput) -> CmdResult<Employee> {
    with_service(&state, |service| service.create_employee(input))
}

#[tauri::command]
fn list_employees(state: State<'_, AppState>) -> CmdResult<Vec<Employee>> {
    with_service(&state, |service| service.list_employees())
}

#[tauri::command]
fn start_onboarding(
    state: State<'_, AppState>,
    employee_id: String,
    template: Option<String>,
) -> CmdResult<OnboardingPlan> {
    let employee_id: EmployeeId = parse_id(&employee_id)?;
    with_service(&state, |service| {
        service.start_onboarding(employee_id, template.as_deref())
    })
}

#[tauri::command]
fn onboarding_for(
    state: State<'_, AppState>,
    employee_id: String,
) -> CmdResult<Option<OnboardingPlan>> {
    let employee_id: EmployeeId = parse_id(&employee_id)?;
    with_service(&state, |service| service.onboarding_for(employee_id))
}

#[tauri::command]
fn complete_onboarding_step(
    state: State<'_, AppState>,
    employee_id: String,
    step_key: String,
) -> CmdResult<OnboardingPlan> {
    let employee_id: EmployeeId = parse_id(&employee_id)?;
    with_service(&state, |service| {
        service.complete_onboarding_step(employee_id, &step_key)
    })
}

#[tauri::command]
fn create_job(
    state: State<'_, AppState>,
    title: String,
    org_unit: String,
) -> CmdResult<hragents_core::hiring::Job> {
    with_service(&state, |service| service.create_job(&title, &org_unit))
}

#[tauri::command]
fn list_jobs(state: State<'_, AppState>) -> CmdResult<Vec<hragents_core::hiring::Job>> {
    with_service(&state, |service| service.list_jobs())
}

#[tauri::command]
fn import_candidate(
    state: State<'_, AppState>,
    input: ImportCandidateInput,
) -> CmdResult<(hragents_core::hiring::Candidate, Application)> {
    with_service(&state, |service| service.import_candidate(input))
}

#[tauri::command]
fn evaluate_candidate(
    state: State<'_, AppState>,
    input: hragents_ipc::EvaluateInput,
) -> CmdResult<EvaluationView> {
    with_service(&state, |service| service.evaluate_candidate(input))
}

#[tauri::command]
fn evaluate_from_text(
    state: State<'_, AppState>,
    application_id: String,
    document_text: String,
    rubric: Rubric,
) -> CmdResult<EvaluationView> {
    let application_id: ApplicationId = parse_id(&application_id)?;
    with_service(&state, |service| {
        service.evaluate_from_text(application_id, &document_text, rubric)
    })
}

#[tauri::command]
fn extract_and_evaluate(
    state: State<'_, AppState>,
    application_id: String,
    document_id: String,
    rubric: Rubric,
) -> CmdResult<EvaluationView> {
    let application_id: ApplicationId = parse_id(&application_id)?;
    let document_id: DocumentId = parse_id(&document_id)?;
    with_service(&state, |service| {
        service.extract_and_evaluate(application_id, document_id, rubric)
    })
}

#[tauri::command]
fn extract_with_provider(
    state: State<'_, AppState>,
    application_id: String,
    document_text: String,
    rubric: Rubric,
    provider: hragents_agents::provider::ProviderConfig,
) -> CmdResult<EvaluationView> {
    let application_id: ApplicationId = parse_id(&application_id)?;
    with_service(&state, |service| {
        service.extract_with_provider(application_id, &document_text, rubric, provider)
    })
}

#[tauri::command]
fn evaluation_for(
    state: State<'_, AppState>,
    application_id: String,
) -> CmdResult<Option<hragents_core::hiring::Evaluation>> {
    let application_id: ApplicationId = parse_id(&application_id)?;
    with_service(&state, |service| service.evaluation_for(application_id))
}

#[tauri::command]
fn reject_candidate(
    state: State<'_, AppState>,
    application_id: String,
    reason: String,
) -> CmdResult<Application> {
    let application_id: ApplicationId = parse_id(&application_id)?;
    with_service(&state, |service| {
        service.reject_candidate(application_id, &reason)
    })
}

#[tauri::command]
fn list_candidates(state: State<'_, AppState>) -> CmdResult<Vec<hragents_core::hiring::Candidate>> {
    with_service(&state, |service| service.list_candidates())
}

#[tauri::command]
fn candidate(
    state: State<'_, AppState>,
    candidate_id: String,
) -> CmdResult<hragents_core::hiring::Candidate> {
    let candidate_id: hragents_core::ids::CandidateId = parse_id(&candidate_id)?;
    with_service(&state, |service| service.candidate(candidate_id))
}

#[tauri::command]
fn list_applications(
    state: State<'_, AppState>,
    job_id: Option<String>,
) -> CmdResult<Vec<Application>> {
    let job_id = job_id.as_deref().map(parse_id::<JobId>).transpose()?;
    with_service(&state, |service| service.list_applications(job_id))
}

#[tauri::command]
fn create_leave_type(state: State<'_, AppState>, name: String, days: i32) -> CmdResult<LeaveType> {
    with_service(&state, |service| service.create_leave_type(&name, days))
}

#[tauri::command]
fn list_leave_types(state: State<'_, AppState>) -> CmdResult<Vec<LeaveType>> {
    with_service(&state, |service| service.list_leave_types())
}

#[tauri::command]
fn list_leave_requests(
    state: State<'_, AppState>,
    status: Option<String>,
) -> CmdResult<Vec<hragents_core::leave::LeaveRequest>> {
    let status = match status.as_deref() {
        None => None,
        Some("pending") => Some(hragents_core::leave::LeaveStatus::Pending),
        Some("approved") => Some(hragents_core::leave::LeaveStatus::Approved),
        Some("rejected") => Some(hragents_core::leave::LeaveStatus::Rejected),
        Some("cancelled") => Some(hragents_core::leave::LeaveStatus::Cancelled),
        Some(other) => {
            return Err(CommandError {
                code: "E_LEAVE_STATUS".into(),
                message: format!("unknown leave status {other}"),
            });
        }
    };
    with_service(&state, |service| service.list_leave_requests(status))
}

#[tauri::command]
fn leave_balances(state: State<'_, AppState>, year: i32) -> CmdResult<Vec<LeaveBalance>> {
    with_service(&state, |service| service.leave_balances(year))
}

#[tauri::command]
fn list_operators(state: State<'_, AppState>) -> CmdResult<Vec<hragents_ipc::OperatorView>> {
    with_service(&state, |service| service.list_operators())
}

#[tauri::command]
fn rate_tables(state: State<'_, AppState>) -> CmdResult<Vec<hragents_core::payroll::RateTable>> {
    with_service(&state, |service| service.rate_tables())
}

#[tauri::command]
fn set_leave_entitlement(
    state: State<'_, AppState>,
    employee_id: String,
    leave_type_id: String,
    year: i32,
    days: i32,
) -> CmdResult<LeaveBalance> {
    let employee_id: EmployeeId = parse_id(&employee_id)?;
    let leave_type_id: LeaveTypeId = parse_id(&leave_type_id)?;
    with_service(&state, |service| {
        service.set_leave_entitlement(employee_id, leave_type_id, year, days)
    })
}

#[tauri::command]
fn record_leave(state: State<'_, AppState>, input: RecordLeaveInput) -> CmdResult<LeaveView> {
    with_service(&state, |service| service.record_leave(input))
}

#[tauri::command]
fn decide_leave(
    state: State<'_, AppState>,
    request_id: String,
    approve: bool,
    note: String,
) -> CmdResult<LeaveView> {
    let request_id: LeaveRequestId = parse_id(&request_id)?;
    with_service(&state, |service| {
        service.decide_leave(request_id, approve, &note)
    })
}

#[tauri::command]
fn seed_demo_rate_tables(state: State<'_, AppState>, effective_from: String) -> CmdResult<()> {
    let effective_from = BusinessDate::parse(&effective_from).map_err(|error| CommandError {
        code: "E_DATE".into(),
        message: error.to_string(),
    })?;
    with_service(&state, |service| {
        service.seed_demo_rate_tables(effective_from)
    })
}

#[tauri::command]
fn compute_payroll(
    state: State<'_, AppState>,
    kind: String,
    period: String,
    inputs: Vec<PayrollInput>,
) -> CmdResult<PayrollView> {
    let kind = match kind.as_str() {
        "monthly" => PayrollKind::Monthly,
        "thr" => PayrollKind::Thr,
        "final" => PayrollKind::Final,
        "adjustment" => PayrollKind::Adjustment,
        other => {
            return Err(CommandError {
                code: "E_PAYROLL_KIND".into(),
                message: format!("unknown payroll kind {other}"),
            });
        }
    };
    let period = BusinessDate::parse(&period).map_err(|error| CommandError {
        code: "E_DATE".into(),
        message: error.to_string(),
    })?;
    with_service(&state, |service| {
        service.compute_payroll(kind, period, inputs)
    })
}

#[tauri::command]
fn export_payroll(state: State<'_, AppState>, run_id: String, path: String) -> CmdResult<u64> {
    let run_id: PayrollRunId = parse_id(&run_id)?;
    with_service(&state, |service| service.export_payroll_xlsx(run_id, path))
}

#[tauri::command]
fn approve_payroll(state: State<'_, AppState>, run_id: String) -> CmdResult<PayrollRun> {
    let run_id: PayrollRunId = parse_id(&run_id)?;
    with_service(&state, |service| service.approve_payroll(run_id))
}

#[tauri::command]
fn payroll_runs(state: State<'_, AppState>) -> CmdResult<Vec<PayrollRun>> {
    with_service(&state, |service| service.payroll_runs())
}

#[tauri::command]
fn payroll_run(state: State<'_, AppState>, run_id: String) -> CmdResult<PayrollRun> {
    let run_id: PayrollRunId = parse_id(&run_id)?;
    with_service(&state, |service| service.payroll_run(run_id))
}

#[tauri::command]
fn reminders(state: State<'_, AppState>) -> CmdResult<Vec<hragents_core::reminders::Reminder>> {
    with_service(&state, |service| service.reminders())
}

#[tauri::command]
fn outbox_pending(
    state: State<'_, AppState>,
) -> CmdResult<Vec<hragents_core::hiring_comms::CandidateMessage>> {
    with_service(&state, |service| service.outbox_pending())
}

#[tauri::command]
fn poll_replies(state: State<'_, AppState>) -> CmdResult<usize> {
    with_service(&state, |service| service.poll_replies())
}

#[tauri::command]
fn list_approvals(state: State<'_, AppState>, open_only: bool) -> CmdResult<Vec<ApprovalRequest>> {
    with_service(&state, |service| service.list_approvals(open_only))
}

#[tauri::command]
fn audit_verify(state: State<'_, AppState>) -> CmdResult<hragents_core::audit::AuditVerification> {
    with_service(&state, |service| service.audit_verify())
}

#[tauri::command]
fn audit_recent(
    state: State<'_, AppState>,
    limit: usize,
) -> CmdResult<Vec<hragents_core::audit::AuditEntry>> {
    with_service(&state, |service| service.audit_recent(limit))
}

#[derive(Debug, Serialize)]
struct DocumentBytes {
    document: Document,
    base64: String,
    size_bytes: usize,
}

#[tauri::command]
fn upload_document(
    state: State<'_, AppState>,
    owner_type: String,
    owner_id: String,
    filename: String,
    mime_type: String,
    base64: String,
) -> CmdResult<Document> {
    use base64::Engine;
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(&base64)
        .map_err(|error| CommandError {
            code: "E_DOCUMENT_ENCODING".into(),
            message: format!("file content is not valid base64: {error}"),
        })?;
    let owner = match owner_type.as_str() {
        "employee" => DocumentOwnerType::Employee,
        "candidate" => DocumentOwnerType::Candidate,
        "company" => DocumentOwnerType::Company,
        "payroll_run" => DocumentOwnerType::PayrollRun,
        other => {
            return Err(CommandError {
                code: "E_OWNER_TYPE".into(),
                message: format!("unknown document owner type {other}"),
            });
        }
    };
    with_service(&state, |service| {
        service.upload_document(owner, &owner_id, &filename, &mime_type, bytes)
    })
}

#[tauri::command]
fn list_documents(
    state: State<'_, AppState>,
    owner_type: String,
    owner_id: String,
) -> CmdResult<Vec<Document>> {
    let owner = match owner_type.as_str() {
        "employee" => DocumentOwnerType::Employee,
        "candidate" => DocumentOwnerType::Candidate,
        "company" => DocumentOwnerType::Company,
        "payroll_run" => DocumentOwnerType::PayrollRun,
        other => {
            return Err(CommandError {
                code: "E_OWNER_TYPE".into(),
                message: format!("unknown document owner type {other}"),
            });
        }
    };
    with_service(&state, |service| service.list_documents(owner, &owner_id))
}

#[tauri::command]
fn read_document(state: State<'_, AppState>, document_id: String) -> CmdResult<DocumentBytes> {
    use base64::Engine;
    let document_id: DocumentId = parse_id(&document_id)?;
    with_service(&state, |service| {
        let (document, bytes) = service.read_document(document_id)?;
        Ok(DocumentBytes {
            document,
            base64: base64::engine::general_purpose::STANDARD.encode(&bytes),
            size_bytes: bytes.len(),
        })
    })
}

#[tauri::command]
fn verify_document(state: State<'_, AppState>, document_id: String) -> CmdResult<Document> {
    let document_id: DocumentId = parse_id(&document_id)?;
    with_service(&state, |service| service.verify_document(document_id))
}

#[tauri::command]
fn export_audit(state: State<'_, AppState>, path: String, limit: Option<usize>) -> CmdResult<u64> {
    with_service(&state, |service| service.export_audit(path, limit))
}

#[tauri::command]
fn search(state: State<'_, AppState>, query: String) -> CmdResult<Vec<SearchHit>> {
    with_service(&state, |service| service.search(&query))
}

#[tauri::command]
fn backup(state: State<'_, AppState>, path: String) -> CmdResult<u64> {
    with_service(&state, |service| service.backup(path))
}

#[tauri::command]
fn backup_set(state: State<'_, AppState>, path: String) -> CmdResult<u64> {
    with_service(&state, |service| service.backup_set(path))
}

#[tauri::command]
fn evaluate_input_schema() -> CmdResult<serde_json::Value> {
    Ok(serde_json::json!({
        "rubric": {"id": "string", "name": "string", "dimensions": [{"key":"string","label":"string","weight_bp":6000}], "merit_floor_bp": 6000, "sigma_limit_bp": 500},
        "runs": [{"dimension_scores": {"skills": 8500, "impact": 7500}}],
        "evidence": [{"dimension":"skills","quote":"...","source_document_id":"uuid","confidence_bp":9000,"page":1}]
    }))
}

// Keep these imports used when the command surface is expanded; they document
// the exact structured shapes the UI sends.
#[allow(dead_code)]
fn _types(_: JobId, _: Evidence, _: Rubric, _: RunScores) {}

pub fn run() {
    tauri::Builder::default()
        // One process owns the database and scheduler. A second launch focuses
        // the running window instead of opening a second connection.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .setup(|app| {
            let data_dir = app
                .path()
                .app_local_data_dir()
                .map_err(|error| Box::<dyn std::error::Error>::from(error.to_string()))?;
            std::fs::create_dir_all(&data_dir)?;
            let db_path = data_dir.join("hragents.db");
            // The shell always opens SQLCipher. A legacy plaintext file is
            // converted in place, and a missing key fails closed instead of
            // silently creating a new one.
            let key = hragents_ipc::unlock_encrypted_database(&data_dir, &db_path)
                .map_err(|error| Box::<dyn std::error::Error>::from(error.to_string()))?;
            let service = AppService::open_encrypted(&db_path, &key)
                .map_err(|error| Box::<dyn std::error::Error>::from(error.to_string()))?;
            let service = Arc::new(Mutex::new(service));
            app.manage(AppState {
                service: Arc::clone(&service),
            });
            // Background jobs: retention sweep, offer-expiry sweep, daily
            // backup, audit verification. Read-only until an operator unlocks;
            // writes land under the unlocked session and are audited.
            let (shutdown_tx, shutdown_rx) = hragents_ipc::scheduler::shutdown_trigger();
            let backend: Arc<tokio::sync::Mutex<dyn hragents_ipc::scheduler::JobBackend>> =
                Arc::new(tokio::sync::Mutex::new(SharedBackend(Arc::clone(&service))));
            let config = hragents_ipc::scheduler::SchedulerConfig {
                backup_dir: Some(data_dir.join("backups")),
                ..hragents_ipc::scheduler::SchedulerConfig::default()
            };
            tauri::async_runtime::spawn(async move {
                // The worker is detached; the shutdown sender retained in
                // state stops it. No await here: the setup hook must return.
                let _scheduler =
                    hragents_ipc::scheduler::Scheduler::spawn(backend, config, shutdown_rx);
            });
            app.manage(SchedulerState {
                _shutdown: shutdown_tx,
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            app_info,
            setup_first_run,
            login,
            logout,
            lock,
            unlock,
            reauth,
            recovery_key,
            rewrap_install_key,
            current_session,
            today,
            create_employee,
            list_employees,
            start_onboarding,
            onboarding_for,
            complete_onboarding_step,
            create_job,
            list_jobs,
            list_candidates,
            candidate,
            list_applications,
            import_candidate,
            evaluate_candidate,
            evaluate_from_text,
            extract_and_evaluate,
            extract_with_provider,
            evaluation_for,
            reject_candidate,
            create_leave_type,
            list_leave_types,
            list_leave_requests,
            create_review_cycle,
            list_review_cycles,
            set_review_cycle_status,
            create_review_assignment,
            send_review_assignment,
            submit_review_response,
            summarize_review,
            list_review_assignments,
            create_goal,
            update_goal_progress,
            list_goals,
            start_offboarding,
            offboarding_for,
            complete_offboarding_step,
            record_offboarding_final_pay,
            finish_offboarding,
            propose_schedule,
            confirm_schedule,
            decline_schedule,
            list_schedule_proposals,
            create_offer,
            approve_offer,
            send_offer,
            accept_offer,
            decline_offer,
            sweep_expired_offers,
            list_offers,
            draft_message,
            queue_message,
            mark_message_sent,
            cancel_message,
            record_inbound_reply,
            list_messages,
            generate_feedback,
            feedback_for,
            seed_retention_policies,
            list_retention_policies,
            create_retention_hold,
            release_retention_hold,
            list_retention_holds,
            retention_sweep,
            create_erasure_request,
            grant_consent,
            withdraw_consent,
            consent_for,
            approve_erasure,
            reject_erasure,
            execute_erasure,
            list_erasure_requests,
            erasure_blockers,
            report_breach,
            contain_breach,
            mark_breach_notified,
            close_breach,
            list_breaches,
            create_document_request,
            list_document_requests,
            attach_document_request,
            verify_document_request,
            reject_document_request,
            leave_balances,
            list_operators,
            rate_tables,
            set_leave_entitlement,
            record_leave,
            decide_leave,
            seed_demo_rate_tables,
            compute_payroll,
            approve_payroll,
            export_payroll,
            payroll_runs,
            payroll_run,
            list_approvals,
            reminders,
            outbox_pending,
            poll_replies,
            audit_verify,
            audit_recent,
            export_audit,
            upload_document,
            list_documents,
            read_document,
            verify_document,
            search,
            backup,
            backup_set,
            evaluate_input_schema
        ])
        .run(tauri::generate_context!())
        .expect("error while running HRAgents Desktop");
}
