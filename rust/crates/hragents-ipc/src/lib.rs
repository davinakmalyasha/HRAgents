//! Application services and DTOs shared by the Tauri command layer and the
//! local CLI. Tauri commands are thin wrappers over these methods, so the same
//! behaviour is testable without a webview.

use hragents_agents::{ExtractionRequest, Extractor, KeywordExtractor};
use hragents_core::Role;
use hragents_core::approvals::ApprovalRequest;
use hragents_core::audit::AuditEntry;
use hragents_core::auth::{AuthService, Operator, Session, SessionPolicy};
use hragents_core::compliance::{ConsentPurpose, ConsentRecord, SubjectType};
use hragents_core::error::DomainError;
use hragents_core::hiring::{
    Application, ApplicationStage, Candidate, ConsentStatus, Evaluation, Evidence, Job, JobStatus,
    PolicyOutcome, Rubric, RunScores, evaluate_policy,
};
use hragents_core::ids::*;
use hragents_core::leave::{LeaveBalance, LeaveRequest, LeaveStatus, LeaveType};
use hragents_core::money::Money;
use hragents_core::password::hash_password;
use hragents_core::payroll::{
    PayrollInput, PayrollKind, PayrollRun, RateEntry, RateTable, RateTableKind,
};
use hragents_core::people::{
    Document, DocumentOwnerType, DocumentStatus, Employee, OnboardingPlan, OnboardingStep,
};
use hragents_core::policy::PolicyCorpus;
use hragents_core::time::{BusinessDate, UtcInstant};
use hragents_store::{Store, StoreError};

pub mod backup_set;
mod compliance_services;
mod growth_services;
mod hiring_services;
pub mod scheduler;

use chacha20poly1305::aead::{Aead, KeyInit};
use chacha20poly1305::{ChaCha20Poly1305, Key, Nonce};
pub use compliance_services::RetentionDueItem;
use rust_xlsxwriter::{Format, Workbook};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap};
use std::io::Read;
use std::path::Path;

#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error(transparent)]
    Domain(#[from] DomainError),
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error("{message}")]
    Setup { code: &'static str, message: String },
    #[error("not authenticated")]
    Unauthenticated,
    #[error("export failed: {0}")]
    Export(String),
    #[error("agent failed: {0}")]
    Agent(String),
}

impl AppError {
    pub fn code(&self) -> &'static str {
        match self {
            Self::Domain(error) => error.code(),
            Self::Store(_) => "E_STORE",
            Self::Setup { code, .. } => code,
            Self::Unauthenticated => "E_UNAUTHENTICATED",
            Self::Export(_) => "E_EXPORT",
            Self::Agent(_) => "E_AGENT",
        }
    }
}

pub type AppResult<T> = Result<T, AppError>;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionView {
    pub operator_id: String,
    pub display_name: String,
    pub role: Role,
    pub started_at: UtcInstant,
    pub last_activity_at: UtcInstant,
    pub locked: bool,
    pub reauth_fresh: bool,
}

impl SessionView {
    pub fn from_session(session: &Session, policy: SessionPolicy, now: UtcInstant) -> Self {
        Self {
            operator_id: session.operator_id.to_string(),
            display_name: session.operator_name.clone(),
            role: session.role,
            started_at: session.started_at,
            last_activity_at: session.last_activity_at,
            locked: session.locked,
            reauth_fresh: session.has_fresh_reauth(now, policy),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SetupInput {
    pub company_name: String,
    pub operator_name: String,
    pub username: String,
    pub password: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CreateEmployeeInput {
    pub employee_no: String,
    pub full_name: String,
    pub job_title: String,
    pub org_unit: String,
    pub hire_date: BusinessDate,
    pub email: Option<String>,
    pub phone: Option<String>,
    pub ptkp_status: Option<String>,
    pub dependents: u8,
    pub jkk_risk_class: Option<u8>,
    pub bank_name: Option<String>,
    pub bank_account: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImportCandidateInput {
    pub full_name: String,
    pub email: Option<String>,
    pub phone: Option<String>,
    pub source: String,
    pub headline: Option<String>,
    pub job_id: JobId,
    pub consent: ConsentStatus,
    pub document: Option<DocumentInput>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentInput {
    pub filename: String,
    pub mime_type: String,
    pub bytes: Vec<u8>,
    pub expires_on: Option<BusinessDate>,
    pub tags: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvaluateInput {
    pub application_id: ApplicationId,
    pub rubric: Rubric,
    pub runs: Vec<RunScores>,
    pub evidence: Vec<Evidence>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvaluationView {
    pub evaluation: Evaluation,
    pub policy: PolicyOutcome,
    pub candidate_name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecordLeaveInput {
    pub employee_id: EmployeeId,
    pub leave_type_id: LeaveTypeId,
    pub start_date: BusinessDate,
    pub end_date: BusinessDate,
    pub days_x2: i32,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LeaveView {
    pub request: LeaveRequest,
    pub balance: LeaveBalance,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PayrollView {
    pub run: PayrollRun,
    pub blocking: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TodayView {
    pub approvals: Vec<ApprovalRequest>,
    pub open_onboarding: Vec<String>,
    pub expiring_documents: Vec<Document>,
    pub recent_audit: Vec<AuditEntry>,
    pub headcount: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OperatorView {
    pub id: String,
    pub username: String,
    pub display_name: String,
    pub role: Role,
    pub active: bool,
    pub created_at: UtcInstant,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchHit {
    pub kind: String,
    pub id: String,
    pub title: String,
    pub subtitle: String,
}

/// One operator, one company, one unlocked session. Every consequential method
/// takes its actor from `self.session`; no command body can supply an actor.
pub struct AppService {
    store: Store,
    documents_dir: std::path::PathBuf,
    document_key: Option<[u8; 32]>,
    database_key: Option<String>,
    auth: AuthService,
    session: Option<Session>,
    operator: Option<Operator>,
}

/// Open the desktop database with SQLCipher, migrating a legacy plaintext
/// file in place first. Returns the key so backups can use the same secret.
#[cfg(feature = "sqlcipher")]
pub fn unlock_encrypted_database(data_dir: &Path, db_path: &Path) -> AppResult<String> {
    let key = hragents_store::keyfile::unlock_key_for(data_dir, db_path)?;
    if db_path.exists() && hragents_store::keyfile::is_plaintext_sqlite(db_path)? {
        Store::encrypt_plaintext_in_place(db_path, &key)?;
    }
    Ok(key)
}

const DOCUMENT_MAGIC: &[u8; 4] = b"HRD1";

fn document_key(passphrase: &str) -> [u8; 32] {
    Sha256::digest(passphrase.as_bytes()).into()
}

fn encrypt_document(key: &[u8; 32], bytes: &[u8]) -> AppResult<Vec<u8>> {
    let cipher = ChaCha20Poly1305::new(Key::from_slice(key));
    let mut nonce = [0u8; 12];
    getrandom::fill(&mut nonce)
        .map_err(|error| AppError::Export(format!("document nonce: {error}")))?;
    let ciphertext = cipher
        .encrypt(Nonce::from_slice(&nonce), bytes)
        .map_err(|_| AppError::Export("encrypt document failed".into()))?;
    let mut out = Vec::with_capacity(DOCUMENT_MAGIC.len() + nonce.len() + ciphertext.len());
    out.extend_from_slice(DOCUMENT_MAGIC);
    out.extend_from_slice(&nonce);
    out.extend_from_slice(&ciphertext);
    Ok(out)
}

fn decrypt_document(key: &[u8; 32], stored: &[u8]) -> AppResult<Vec<u8>> {
    if !stored.starts_with(DOCUMENT_MAGIC) {
        return Ok(stored.to_vec());
    }
    if stored.len() < DOCUMENT_MAGIC.len() + 12 + 16 {
        return Err(AppError::Export("document ciphertext is truncated".into()));
    }
    let nonce = &stored[DOCUMENT_MAGIC.len()..DOCUMENT_MAGIC.len() + 12];
    let ciphertext = &stored[DOCUMENT_MAGIC.len() + 12..];
    let cipher = ChaCha20Poly1305::new(Key::from_slice(key));
    cipher
        .decrypt(Nonce::from_slice(nonce), ciphertext)
        .map_err(|_| {
            AppError::Export("document decryption failed: wrong key or tampered file".into())
        })
}

fn encrypt_legacy_documents(dir: &Path, key: &[u8; 32]) -> AppResult<()> {
    let entries = std::fs::read_dir(dir)
        .map_err(|error| AppError::Export(format!("read documents directory: {error}")))?;
    for entry in entries {
        let entry =
            entry.map_err(|error| AppError::Export(format!("read document entry: {error}")))?;
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let mut handle = std::fs::File::open(&path)
            .map_err(|error| AppError::Export(format!("open document: {error}")))?;
        let mut magic = [0u8; 4];
        if handle.read_exact(&mut magic).is_ok() && &magic == DOCUMENT_MAGIC {
            continue;
        }
        drop(handle);
        let stored = std::fs::read(&path)
            .map_err(|error| AppError::Export(format!("read document: {error}")))?;
        let encrypted = encrypt_document(key, &stored)?;
        let staging = path.with_extension("enc-tmp");
        std::fs::write(&staging, &encrypted)
            .map_err(|error| AppError::Export(format!("write document: {error}")))?;
        std::fs::rename(&staging, &path)
            .map_err(|error| AppError::Export(format!("replace document: {error}")))?;
    }
    Ok(())
}

impl AppService {
    pub fn open(path: impl AsRef<Path>) -> AppResult<Self> {
        let path = path.as_ref();
        Self::assemble(Store::open(path)?, path, None)
    }

    /// Open the app database through SQLCipher. The desktop shell always uses
    /// this path; `open` remains for tests, demos, and the plain CLI.
    pub fn open_encrypted(path: impl AsRef<Path>, key: &str) -> AppResult<Self> {
        let path = path.as_ref();
        Self::assemble(Store::open_encrypted(path, key)?, path, Some(key))
    }

    fn assemble(store: Store, path: &Path, passphrase: Option<&str>) -> AppResult<Self> {
        let documents_dir = path
            .parent()
            .filter(|parent| !parent.as_os_str().is_empty())
            .unwrap_or_else(|| std::path::Path::new("."))
            .join("documents");
        std::fs::create_dir_all(&documents_dir)
            .map_err(|error| AppError::Export(error.to_string()))?;
        let document_key = passphrase.map(document_key);
        if let Some(key) = &document_key {
            encrypt_legacy_documents(&documents_dir, key)?;
        }
        Ok(Self {
            store,
            documents_dir,
            document_key,
            database_key: passphrase.map(str::to_owned),
            auth: AuthService::default(),
            session: None,
            operator: None,
        })
    }

    pub fn open_in_memory() -> AppResult<Self> {
        let documents_dir =
            std::env::temp_dir().join(format!("hragents-docs-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&documents_dir)
            .map_err(|error| AppError::Export(error.to_string()))?;
        Ok(Self {
            store: Store::open_in_memory()?,
            documents_dir,
            document_key: None,
            database_key: None,
            auth: AuthService::default(),
            session: None,
            operator: None,
        })
    }

    pub fn store(&self) -> &Store {
        &self.store
    }

    pub fn store_mut(&mut self) -> &mut Store {
        &mut self.store
    }

    pub fn company_name(&self) -> AppResult<Option<String>> {
        Ok(self.store.company_name()?)
    }

    pub fn setup_required(&self) -> AppResult<bool> {
        Ok(self.store.operator_count()? == 0)
    }

    /// First run: create the company and the first HR operator, then open a
    /// session. There is no admin role and no self-registration after this.
    pub fn setup_first_run(&mut self, input: SetupInput) -> AppResult<SessionView> {
        if !self.setup_required()? {
            return Err(AppError::Setup {
                code: "E_ALREADY_SETUP",
                message: "this installation already has an operator".into(),
            });
        }
        if input.company_name.trim().len() < 2 {
            return Err(AppError::Setup {
                code: "E_COMPANY_NAME",
                message: "company name is required".into(),
            });
        }
        if input.operator_name.trim().len() < 2 {
            return Err(AppError::Setup {
                code: "E_OPERATOR_NAME",
                message: "operator name is required".into(),
            });
        }
        let now = UtcInstant::now();
        let password_hash = hash_password(&input.password).map_err(|error| AppError::Setup {
            code: "E_PASSWORD",
            message: error.to_string(),
        })?;
        self.store
            .set_company(&input.company_name, None, None, now)?;
        let operator = Operator::new(
            input.username.trim().to_lowercase(),
            input.operator_name.trim(),
            password_hash,
            now,
        );
        self.store.insert_operator(&operator)?;
        let outcome = self
            .auth
            .login(&operator, &input.password, now)
            .map_err(AppError::Domain)?;
        self.session = Some(outcome.session.clone());
        self.operator = Some(operator.clone());
        self.append_audit(
            "operator.created",
            "operator",
            &operator.id.to_string(),
            serde_json::json!({"username": operator.username, "role": "hr_operator"}),
            now,
        )?;
        self.append_audit(
            "company.created",
            "company",
            &input.company_name,
            serde_json::json!({"name": input.company_name}),
            now,
        )?;
        Ok(SessionView::from_session(
            &outcome.session,
            self.auth.policy(),
            now,
        ))
    }

    pub fn login(&mut self, username: &str, password: &str) -> AppResult<SessionView> {
        let operator = self
            .store
            .operator_by_username(&username.trim().to_lowercase())?
            .ok_or(AppError::Unauthenticated)?;
        let now = UtcInstant::now();
        let outcome = self.auth.login(&operator, password, now)?;
        self.session = Some(outcome.session.clone());
        self.operator = Some(operator);
        self.append_audit(
            "session.login",
            "operator",
            &outcome.session.operator_id.to_string(),
            serde_json::json!({"result": "ok"}),
            now,
        )?;
        Ok(SessionView::from_session(
            &outcome.session,
            self.auth.policy(),
            now,
        ))
    }

    pub fn logout(&mut self) -> AppResult<()> {
        if let Some(session) = self.session.take() {
            let now = UtcInstant::now();
            self.append_audit(
                "session.logout",
                "operator",
                &session.operator_id.to_string(),
                serde_json::json!({}),
                now,
            )?;
        }
        self.operator = None;
        Ok(())
    }

    pub fn lock(&mut self) -> AppResult<()> {
        let now = UtcInstant::now();
        let policy = self.auth.policy();
        let session = self.session.as_mut().ok_or(AppError::Unauthenticated)?;
        if !session.is_active(now, policy) {
            return Err(AppError::Unauthenticated);
        }
        self.auth.lock(session);
        Ok(())
    }

    pub fn unlock(&mut self, password: &str) -> AppResult<SessionView> {
        let operator = self.operator.clone().ok_or(AppError::Unauthenticated)?;
        let now = UtcInstant::now();
        let session = self.auth.unlock(&operator, password, now)?;
        self.session = Some(session.clone());
        self.append_audit(
            "session.unlock",
            "operator",
            &session.operator_id.to_string(),
            serde_json::json!({}),
            now,
        )?;
        Ok(SessionView::from_session(&session, self.auth.policy(), now))
    }

    pub fn reauth(&mut self, password: &str) -> AppResult<SessionView> {
        let operator = self.operator.clone().ok_or(AppError::Unauthenticated)?;
        let now = UtcInstant::now();
        let session = self.session.as_mut().ok_or(AppError::Unauthenticated)?;
        self.auth.mark_reauth(session, &operator, password, now)?;
        let session = session.clone();
        self.append_audit(
            "session.reauth",
            "operator",
            &session.operator_id.to_string(),
            serde_json::json!({}),
            now,
        )?;
        Ok(SessionView::from_session(&session, self.auth.policy(), now))
    }

    pub fn current_session(&self) -> AppResult<SessionView> {
        let session = self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(SessionView::from_session(
            session,
            self.auth.policy(),
            UtcInstant::now(),
        ))
    }

    fn require_active(&mut self) -> AppResult<&mut Session> {
        let now = UtcInstant::now();
        let policy = self.auth.policy();
        let session = self.session.as_mut().ok_or(AppError::Unauthenticated)?;
        if !session.is_active(now, policy) {
            return Err(AppError::Unauthenticated);
        }
        session.last_activity_at = now;
        Ok(session)
    }

    /// Re-authenticate, then return the 64-hex install key for offline storage.
    /// The key is never written to the audit payload.
    pub fn recovery_key(&mut self, password: &str) -> AppResult<String> {
        self.reauth(password)?;
        let key = self.database_key.clone().ok_or(AppError::Setup {
            code: "E_NOT_ENCRYPTED",
            message: "this database is not encrypted".into(),
        })?;
        let operator_id = self.require_active()?.operator_id.to_string();
        self.append_audit(
            "security.recovery_key_exported",
            "operator",
            &operator_id,
            serde_json::json!({"format": "hex", "bits": 256}),
            UtcInstant::now(),
        )?;
        Ok(key)
    }

    /// Re-protect the existing key with the current OS user's wrapper. The
    /// database key itself does not change, so no data is re-encrypted.
    pub fn rewrap_install_key(&mut self, password: &str) -> AppResult<()> {
        self.reauth(password)?;
        let key = self.database_key.clone().ok_or(AppError::Setup {
            code: "E_NOT_ENCRYPTED",
            message: "this database is not encrypted".into(),
        })?;
        let data_dir = self
            .documents_dir
            .parent()
            .filter(|parent| !parent.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."));
        hragents_store::keyfile::write_key(data_dir, &key)?;
        let operator_id = self.require_active()?.operator_id.to_string();
        self.append_audit(
            "security.key_rewrapped",
            "operator",
            &operator_id,
            serde_json::json!({"wrapper": "os-user"}),
            UtcInstant::now(),
        )?;
        Ok(())
    }

    fn require_reauth(&mut self) -> AppResult<&Session> {
        let now = UtcInstant::now();
        self.require_active()?;
        let session = self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        self.auth.require_reauth(session, now)?;
        Ok(session)
    }

    fn actor(&self) -> AppResult<hragents_core::audit::AuditActor> {
        Ok(self
            .session
            .as_ref()
            .ok_or(AppError::Unauthenticated)?
            .actor())
    }

    pub(crate) fn require_session_pub(&self) -> AppResult<&Session> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)
    }

    pub(crate) fn require_active_pub(&mut self) -> AppResult<&mut Session> {
        self.require_active()
    }

    pub(crate) fn require_reauth_pub(&mut self) -> AppResult<&Session> {
        self.require_reauth()
    }

    pub(crate) fn append_audit_pub(
        &mut self,
        action: &str,
        subject_type: &str,
        subject_id: &str,
        payload: serde_json::Value,
        now: UtcInstant,
    ) -> AppResult<AuditEntry> {
        self.append_audit(action, subject_type, subject_id, payload, now)
    }

    fn append_audit(
        &mut self,
        action: &str,
        subject_type: &str,
        subject_id: &str,
        payload: serde_json::Value,
        now: UtcInstant,
    ) -> AppResult<AuditEntry> {
        let actor = self.actor()?;
        Ok(self
            .store
            .append_audit(&actor, action, subject_type, subject_id, payload, now)?)
    }

    // ------------------------------------------------------------------
    // Employees and onboarding
    // ------------------------------------------------------------------

    pub fn create_employee(&mut self, input: CreateEmployeeInput) -> AppResult<Employee> {
        let now = UtcInstant::now();
        self.require_active()?;
        let mut employee = Employee::new(
            input.employee_no,
            input.full_name,
            input.job_title,
            input.org_unit,
            input.hire_date,
            now,
        );
        employee.email = input.email;
        employee.phone = input.phone;
        employee.ptkp_status = input.ptkp_status;
        employee.dependents = input.dependents;
        employee.jkk_risk_class = input.jkk_risk_class;
        employee.bank_name = input.bank_name;
        employee.bank_account = input.bank_account;
        employee.validate()?;
        self.store.save_employee(&employee)?;
        self.append_audit(
            "employee.created",
            "employee",
            &employee.id.to_string(),
            serde_json::json!({
                "employee_no": employee.employee_no,
                "name": employee.full_name,
                "org_unit": employee.org_unit,
            }),
            now,
        )?;
        Ok(employee)
    }

    pub fn employee(&self, id: EmployeeId) -> AppResult<Employee> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.employee(id)?)
    }

    pub fn list_employees(&self) -> AppResult<Vec<Employee>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.list_employees()?)
    }

    pub fn search_employees(&self, query: &str, limit: usize) -> AppResult<Vec<Employee>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.search_employees(query, limit)?)
    }

    pub fn start_onboarding(
        &mut self,
        employee_id: EmployeeId,
        template: Option<&str>,
    ) -> AppResult<OnboardingPlan> {
        let now = UtcInstant::now();
        self.require_active()?;
        let employee = self.store.employee(employee_id)?;
        let template = template.unwrap_or("Standard onboarding");
        let steps = default_onboarding_steps(template);
        let plan = OnboardingPlan::start(employee.id, template, steps, now)?;
        self.store.save_onboarding_plan(&plan)?;
        self.append_audit(
            "onboarding.started",
            "onboarding_plan",
            &plan.id.to_string(),
            serde_json::json!({
                "employee_id": employee.id.to_string(),
                "employee_name": employee.full_name,
                "steps": plan.steps.len(),
            }),
            now,
        )?;
        Ok(plan)
    }

    pub fn onboarding_for(&self, employee_id: EmployeeId) -> AppResult<Option<OnboardingPlan>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.onboarding_plan_for(employee_id)?)
    }

    pub fn complete_onboarding_step(
        &mut self,
        employee_id: EmployeeId,
        step_key: &str,
    ) -> AppResult<OnboardingPlan> {
        let now = UtcInstant::now();
        let actor_name = {
            let session = self.require_active()?;
            session.operator_name.clone()
        };
        let mut plan = self
            .store
            .onboarding_plan_for(employee_id)?
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "onboarding_plan",
                    id: employee_id.to_string(),
                })
            })?;
        plan.complete_step(step_key, &actor_name, now)?;
        self.store.save_onboarding_plan(&plan)?;
        self.append_audit(
            "onboarding.step_completed",
            "onboarding_plan",
            &plan.id.to_string(),
            serde_json::json!({"employee_id": employee_id.to_string(), "step": step_key}),
            now,
        )?;
        Ok(plan)
    }

    // ------------------------------------------------------------------
    // Documents
    // ------------------------------------------------------------------

    pub fn upload_document(
        &mut self,
        owner_type: DocumentOwnerType,
        owner_id: &str,
        filename: &str,
        mime_type: &str,
        bytes: Vec<u8>,
    ) -> AppResult<Document> {
        let now = UtcInstant::now();
        self.require_active()?;
        if bytes.is_empty() {
            return Err(AppError::Domain(DomainError::validation(
                "E_DOCUMENT_EMPTY",
                "the selected file is empty",
            )));
        }
        if bytes.len() > 25 * 1024 * 1024 {
            return Err(AppError::Domain(DomainError::validation(
                "E_DOCUMENT_TOO_LARGE",
                "documents are limited to 25 MB",
            )));
        }
        match owner_type {
            DocumentOwnerType::Employee => {
                let employee_id: EmployeeId = owner_id.parse().map_err(|_| {
                    AppError::Domain(DomainError::validation("E_OWNER", "invalid employee owner"))
                })?;
                self.store.employee(employee_id)?;
            }
            DocumentOwnerType::Candidate => {
                let candidate_id: CandidateId = owner_id.parse().map_err(|_| {
                    AppError::Domain(DomainError::validation(
                        "E_OWNER",
                        "invalid candidate owner",
                    ))
                })?;
                self.store.candidate(candidate_id)?;
            }
            _ => {}
        }
        let safe_name = std::path::Path::new(filename)
            .file_name()
            .and_then(std::ffi::OsStr::to_str)
            .filter(|name| !name.is_empty())
            .unwrap_or("document");
        let extension = std::path::Path::new(safe_name)
            .extension()
            .and_then(std::ffi::OsStr::to_str)
            .map(|ext| format!(".{}", ext.to_lowercase()))
            .unwrap_or_default();
        let id = DocumentId::new();
        let stored_name = format!("{id}{extension}");
        let path = self.documents_dir.join(&stored_name);
        let on_disk = match &self.document_key {
            Some(key) => encrypt_document(key, &bytes)?,
            None => bytes.clone(),
        };
        std::fs::write(&path, &on_disk)
            .map_err(|error| AppError::Export(format!("write document: {error}")))?;
        let document = Document {
            id,
            owner_type,
            owner_id: owner_id.to_owned(),
            filename: safe_name.to_owned(),
            mime_type: mime_type.to_owned(),
            sha256: hragents_core::audit::hex_sha256(&bytes),
            size_bytes: bytes.len() as i64,
            status: DocumentStatus::Pending,
            expires_on: None,
            uploaded_at: now,
            verified_at: None,
            verified_by: None,
            rejection_reason: None,
            tags: Vec::new(),
        };
        self.store
            .save_document(&document, &path.display().to_string())?;
        self.append_audit(
            "document.uploaded",
            "document",
            &document.id.to_string(),
            serde_json::json!({
                "filename": document.filename,
                "mime_type": document.mime_type,
                "size_bytes": document.size_bytes,
                "sha256": document.sha256,
                "owner_type": format!("{owner_type:?}"),
                "owner_id": owner_id,
            }),
            now,
        )?;
        Ok(document)
    }

    pub fn list_documents(
        &self,
        owner_type: DocumentOwnerType,
        owner_id: &str,
    ) -> AppResult<Vec<Document>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.list_documents(owner_type, owner_id)?)
    }

    pub fn read_document(&mut self, id: DocumentId) -> AppResult<(Document, Vec<u8>)> {
        let now = UtcInstant::now();
        self.require_active()?;
        let document = self.store.document(id)?;
        let path = self.store.document_path(id)?;
        let stored = std::fs::read(&path)
            .map_err(|error| AppError::Export(format!("read document: {error}")))?;
        let bytes = match &self.document_key {
            Some(key) => decrypt_document(key, &stored)?,
            None => stored,
        };
        self.append_audit(
            "document.viewed",
            "document",
            &document.id.to_string(),
            serde_json::json!({"filename": document.filename, "size_bytes": document.size_bytes}),
            now,
        )?;
        Ok((document, bytes))
    }

    pub fn verify_document(&mut self, id: DocumentId) -> AppResult<Document> {
        let now = UtcInstant::now();
        let actor_name = self.require_active()?.operator_name.clone();
        let mut document = self.store.document(id)?;
        document.verify(actor_name, now)?;
        let path = self.store.document_path(id)?;
        self.store.save_document(&document, &path)?;
        self.append_audit(
            "document.verified",
            "document",
            &document.id.to_string(),
            serde_json::json!({"filename": document.filename}),
            now,
        )?;
        Ok(document)
    }

    // ------------------------------------------------------------------
    // Hiring
    // ------------------------------------------------------------------

    pub fn create_job(&mut self, title: &str, org_unit: &str) -> AppResult<Job> {
        let now = UtcInstant::now();
        self.require_active()?;
        let job = Job {
            id: JobId::new(),
            title: title.to_owned(),
            org_unit: org_unit.to_owned(),
            location: "Jakarta".into(),
            employment_type: "full_time".into(),
            status: JobStatus::Open,
            openings: 1,
            rubric_id: None,
            created_at: now,
        };
        self.store.save_job(&job)?;
        self.append_audit(
            "job.created",
            "job",
            &job.id.to_string(),
            serde_json::json!({"title": job.title, "org_unit": job.org_unit}),
            now,
        )?;
        Ok(job)
    }

    pub fn list_jobs(&self) -> AppResult<Vec<Job>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.list_jobs()?)
    }

    pub fn import_candidate(
        &mut self,
        input: ImportCandidateInput,
    ) -> AppResult<(Candidate, Application)> {
        let now = UtcInstant::now();
        self.require_active()?;
        let mut candidate = Candidate::new(input.full_name, input.source, now);
        candidate.email = input.email;
        candidate.phone = input.phone;
        candidate.headline = input.headline;
        candidate.consent = input.consent;
        if let Some(document) = input.document {
            let sha256 = hragents_core::audit::hex_sha256(&document.bytes);
            let size_bytes = document.bytes.len() as i64;
            let document_id = DocumentId::new();
            let stored = Document {
                id: document_id,
                owner_type: DocumentOwnerType::Candidate,
                owner_id: candidate.id.to_string(),
                filename: document.filename,
                mime_type: document.mime_type,
                sha256,
                size_bytes,
                status: DocumentStatus::Pending,
                expires_on: document.expires_on,
                uploaded_at: now,
                verified_at: None,
                verified_by: None,
                rejection_reason: None,
                tags: document.tags,
            };
            let storage_path = format!("documents/{}.bin", stored.id);
            self.store.save_document(&stored, &storage_path)?;
            candidate.document_ids.push(stored.id);
        }
        self.store.save_candidate(&candidate)?;
        let mut application = Application::new(candidate.id, input.job_id, now);
        application.stage = ApplicationStage::Imported;
        self.store.save_application(&application)?;
        self.append_audit(
            "candidate.imported",
            "candidate",
            &candidate.id.to_string(),
            serde_json::json!({
                "name": candidate.full_name,
                "application_id": application.id.to_string(),
                "job_id": input.job_id.to_string(),
                "documents": candidate.document_ids.len(),
            }),
            now,
        )?;
        Ok((candidate, application))
    }

    pub fn evaluate_candidate(&mut self, input: EvaluateInput) -> AppResult<EvaluationView> {
        let now = UtcInstant::now();
        self.require_active()?;
        let application = self.store.application(input.application_id)?;
        let candidate = self.store.candidate(application.candidate_id)?;
        let evaluation = Evaluation::from_runs(
            application.id,
            &input.rubric,
            &input.runs,
            input.evidence,
            now,
        )?;
        self.store.save_evaluation(&evaluation)?;
        let policy = evaluate_policy(candidate.consent, Some(&evaluation), &input.rubric);
        self.append_audit(
            "candidate.evaluated",
            "application",
            &application.id.to_string(),
            serde_json::json!({
                "candidate_id": candidate.id.to_string(),
                "overall_bp": evaluation.overall_bp,
                "sigma_bp": evaluation.sigma_bp,
                "runs": evaluation.runs,
                "flags": evaluation.flags,
                "policy": format!("{policy:?}"),
            }),
            now,
        )?;
        Ok(EvaluationView {
            evaluation,
            policy,
            candidate_name: candidate.full_name,
        })
    }

    /// Deterministic extraction from pasted/imported CV text, followed by the
    /// same scorer and policy gate as any other evaluation. The extractor
    /// produces evidence and scores; it never decides.
    pub fn evaluate_from_text(
        &mut self,
        application_id: ApplicationId,
        document_text: &str,
        rubric: Rubric,
    ) -> AppResult<EvaluationView> {
        let now = UtcInstant::now();
        self.require_active()?;
        let application = self.store.application(application_id)?;
        let mut candidate = self.store.candidate(application.candidate_id)?;
        if !candidate.consent.permits_processing() {
            return Err(AppError::Domain(DomainError::validation(
                "E_CONSENT_REQUIRED",
                "consent is not granted; extraction and scoring are blocked",
            )));
        }
        // Pasted text still gets a document row and a hash, so every evidence
        // quote points at an auditable source instead of a transient string.
        let document_id = match candidate.document_ids.first().copied() {
            Some(id) => Some(id),
            None => {
                let document = Document {
                    id: DocumentId::new(),
                    owner_type: DocumentOwnerType::Candidate,
                    owner_id: candidate.id.to_string(),
                    filename: "pasted-cv.txt".into(),
                    mime_type: "text/plain".into(),
                    sha256: hragents_core::audit::hex_sha256(document_text.as_bytes()),
                    size_bytes: document_text.len() as i64,
                    status: DocumentStatus::Pending,
                    expires_on: None,
                    uploaded_at: now,
                    verified_at: None,
                    verified_by: None,
                    rejection_reason: None,
                    tags: vec!["pasted-text".into()],
                };
                self.store
                    .save_document(&document, &format!("inline://{}", document.id))?;
                candidate.document_ids.push(document.id);
                self.store.save_candidate(&candidate)?;
                Some(document.id)
            }
        };
        let request = ExtractionRequest {
            document_text: document_text.to_owned(),
            document_id,
            dimensions: rubric.dimensions.clone(),
        };
        let extracted = KeywordExtractor::new()
            .extract(&request)
            .map_err(|error| AppError::Agent(error.to_string()))?;
        let evaluation = Evaluation::from_runs(
            application.id,
            &rubric,
            &extracted.runs,
            extracted.evidence,
            now,
        )?;
        self.store.save_evaluation(&evaluation)?;
        let policy = evaluate_policy(candidate.consent, Some(&evaluation), &rubric);
        self.append_audit(
            "candidate.extracted",
            "application",
            &application.id.to_string(),
            serde_json::json!({
                "candidate_id": candidate.id.to_string(),
                "runs": evaluation.runs,
                "overall_bp": evaluation.overall_bp,
                "sigma_bp": evaluation.sigma_bp,
                "evidence": evaluation.evidence.len(),
                "extractor": "keyword-offline-v1",
            }),
            now,
        )?;
        self.append_audit(
            "candidate.evaluated",
            "application",
            &application.id.to_string(),
            serde_json::json!({
                "overall_bp": evaluation.overall_bp,
                "sigma_bp": evaluation.sigma_bp,
                "policy": format!("{policy:?}"),
            }),
            now,
        )?;
        Ok(EvaluationView {
            evaluation,
            policy,
            candidate_name: candidate.full_name,
        })
    }

    /// Rejection is a named-human, re-authenticated action with a reason. It is
    /// never automatic, and an agent cannot reach this method.
    pub fn reject_candidate(
        &mut self,
        application_id: ApplicationId,
        reason: &str,
    ) -> AppResult<Application> {
        let now = UtcInstant::now();
        let operator_id = self.require_reauth()?.operator_id;
        let mut application = self.store.application(application_id)?;
        let candidate = self.store.candidate(application.candidate_id)?;
        if !candidate.consent.permits_processing() {
            return Err(AppError::Domain(DomainError::validation(
                "E_CONSENT_REQUIRED",
                "consent is withdrawn; the record cannot be processed",
            )));
        }
        application.reject(operator_id, reason, now)?;
        self.store.save_application(&application)?;
        self.append_audit(
            "candidate.rejected",
            "application",
            &application.id.to_string(),
            serde_json::json!({
                "candidate_id": candidate.id.to_string(),
                "reason": reason,
                "reauth": true,
            }),
            now,
        )?;
        Ok(application)
    }

    pub fn evaluation_for(&self, application_id: ApplicationId) -> AppResult<Option<Evaluation>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.evaluation_for(application_id)?)
    }

    pub fn list_candidates(&self) -> AppResult<Vec<Candidate>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.list_candidates()?)
    }

    pub fn candidate(&self, id: CandidateId) -> AppResult<Candidate> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.candidate(id)?)
    }

    pub fn list_applications(&self, job_id: Option<JobId>) -> AppResult<Vec<Application>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.list_applications(job_id)?)
    }

    // ------------------------------------------------------------------
    // Leave
    // ------------------------------------------------------------------

    pub fn create_leave_type(&mut self, name: &str, days: i32) -> AppResult<LeaveType> {
        self.require_active()?;
        let leave_type = LeaveType::annual(name, days);
        self.store.save_leave_type(&leave_type)?;
        Ok(leave_type)
    }

    pub fn list_leave_types(&self) -> AppResult<Vec<LeaveType>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.list_leave_types()?)
    }

    pub fn list_leave_requests(&self, status: Option<LeaveStatus>) -> AppResult<Vec<LeaveRequest>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.list_leave_requests(status)?)
    }

    pub fn leave_balances(&self, year: i32) -> AppResult<Vec<LeaveBalance>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.list_leave_balances(year)?)
    }

    pub fn list_operators(&self) -> AppResult<Vec<OperatorView>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self
            .store
            .list_operators()?
            .into_iter()
            .map(|operator| OperatorView {
                id: operator.id.to_string(),
                username: operator.username,
                display_name: operator.display_name,
                role: operator.role,
                active: operator.active,
                created_at: operator.created_at,
            })
            .collect())
    }

    pub fn set_leave_entitlement(
        &mut self,
        employee_id: EmployeeId,
        leave_type_id: LeaveTypeId,
        year: i32,
        days: i32,
    ) -> AppResult<LeaveBalance> {
        let now = UtcInstant::now();
        self.require_active()?;
        if let Some(existing) = self.store.leave_balance(employee_id, leave_type_id, year)? {
            let mut balance = existing;
            let delta = days * 2 - balance.entitled_x2;
            balance.adjust(delta, "operator entitlement update")?;
            self.store.save_leave_balance(&balance)?;
            self.append_audit(
                "leave.entitlement_updated",
                "leave_balance",
                &format!("{employee_id}:{leave_type_id}:{year}"),
                serde_json::json!({"days": days}),
                now,
            )?;
            return Ok(balance);
        }
        let balance = LeaveBalance::new(employee_id, leave_type_id, year, days * 2);
        self.store.save_leave_balance(&balance)?;
        self.append_audit(
            "leave.entitlement_set",
            "leave_balance",
            &format!("{employee_id}:{leave_type_id}:{year}"),
            serde_json::json!({"days": days}),
            now,
        )?;
        Ok(balance)
    }

    pub fn record_leave(&mut self, input: RecordLeaveInput) -> AppResult<LeaveView> {
        let now = UtcInstant::now();
        let operator_id = self.require_active()?.operator_id;
        let mut balance = self
            .store
            .leave_balance(
                input.employee_id,
                input.leave_type_id,
                input.start_date.year(),
            )?
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "leave_balance",
                    id: input.employee_id.to_string(),
                })
            })?;
        let mut request = LeaveRequest::record(
            input.employee_id,
            input.leave_type_id,
            input.start_date,
            input.end_date,
            input.days_x2,
            operator_id,
            &input.reason,
            now,
        )?;
        request.submit(&mut balance)?;
        self.store.save_balance_and_request(&balance, &request)?;
        self.append_audit(
            "leave.recorded",
            "leave_request",
            &request.id.to_string(),
            serde_json::json!({
                "employee_id": input.employee_id.to_string(),
                "days_x2": input.days_x2,
                "start": input.start_date.to_string(),
                "end": input.end_date.to_string(),
            }),
            now,
        )?;
        Ok(LeaveView { request, balance })
    }

    pub fn decide_leave(
        &mut self,
        request_id: LeaveRequestId,
        approve: bool,
        note: &str,
    ) -> AppResult<LeaveView> {
        let now = UtcInstant::now();
        let operator_id = self.require_active()?.operator_id;
        let mut request = self.store.leave_request(request_id)?;
        let mut balance = self
            .store
            .leave_balance(
                request.employee_id,
                request.leave_type_id,
                request.start_date.year(),
            )?
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "leave_balance",
                    id: request.employee_id.to_string(),
                })
            })?;
        let decision = if approve {
            hragents_core::leave::LeaveDecision::Approve
        } else {
            hragents_core::leave::LeaveDecision::Reject
        };
        request.decide(&mut balance, decision, operator_id, note, now)?;
        self.store.save_balance_and_request(&balance, &request)?;
        self.append_audit(
            if approve {
                "leave.approved"
            } else {
                "leave.rejected"
            },
            "leave_request",
            &request.id.to_string(),
            serde_json::json!({"note": note, "employee_id": request.employee_id.to_string()}),
            now,
        )?;
        Ok(LeaveView { request, balance })
    }

    // ------------------------------------------------------------------
    // Payroll
    // ------------------------------------------------------------------

    pub fn upsert_rate_table(&mut self, table: RateTable) -> AppResult<()> {
        let now = UtcInstant::now();
        self.require_active()?;
        self.store.save_rate_table(&table)?;
        self.append_audit(
            "rate_table.saved",
            "rate_table",
            &table.id.to_string(),
            serde_json::json!({
                "kind": table.kind.as_str(),
                "effective_from": table.effective_from.to_string(),
                "verified": table.verified,
                "entries": table.entries.len(),
            }),
            now,
        )?;
        Ok(())
    }

    pub fn compute_payroll(
        &mut self,
        kind: PayrollKind,
        period: BusinessDate,
        inputs: Vec<PayrollInput>,
    ) -> AppResult<PayrollView> {
        let now = UtcInstant::now();
        self.require_active()?;
        let tables = self.store.rate_tables(period)?;
        let mut employees = BTreeMap::new();
        for employee in self.store.list_employees()? {
            employees.insert(employee.id, employee);
        }
        let run =
            hragents_core::payroll::compute_run(kind, period, &inputs, &employees, &tables, now)?;
        let blocking = run.blocking_count();
        self.store.save_payroll_run(&run)?;
        self.append_audit(
            "payroll.computed",
            "payroll_run",
            &run.id.to_string(),
            serde_json::json!({
                "kind": run.kind,
                "period": period.to_string(),
                "employees": run.lines.len(),
                "gross_sen": run.totals.gross.sen(),
                "net_sen": run.totals.net.sen(),
                "blocking": blocking,
            }),
            now,
        )?;
        Ok(PayrollView { run, blocking })
    }

    pub fn approve_payroll(&mut self, run_id: PayrollRunId) -> AppResult<PayrollRun> {
        let now = UtcInstant::now();
        let operator_id = self.require_reauth()?.operator_id;
        let mut run = self.store.payroll_run(run_id)?;
        run.approve(operator_id, now)?;
        self.store.save_payroll_run(&run)?;
        self.append_audit(
            "payroll.approved",
            "payroll_run",
            &run.id.to_string(),
            serde_json::json!({
                "period": run.period.to_string(),
                "employees": run.lines.len(),
                "net_sen": run.totals.net.sen(),
                "reauth": true,
            }),
            now,
        )?;
        Ok(run)
    }

    pub fn rate_tables(&self) -> AppResult<Vec<RateTable>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.all_rate_tables()?)
    }

    pub fn payroll_runs(&self) -> AppResult<Vec<PayrollRun>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.list_payroll_runs()?)
    }

    pub fn payroll_run(&self, id: PayrollRunId) -> AppResult<PayrollRun> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.payroll_run(id)?)
    }

    /// Write the review packet an HR operator hands to payroll/finance. This is
    /// an export, never a payment instruction: no bank file, no transfer, no
    /// gateway. Amounts are written as numeric rupiah with two decimals so a
    /// reviewer can reconcile them, and the audit record includes the run and
    /// the destination path.
    pub fn export_payroll_xlsx(
        &mut self,
        run_id: PayrollRunId,
        path: impl AsRef<Path>,
    ) -> AppResult<u64> {
        let now = UtcInstant::now();
        self.require_active()?;
        let run = self.store.payroll_run(run_id)?;
        let path = path.as_ref();
        if let Some(parent) = path.parent()
            && !parent.as_os_str().is_empty()
        {
            std::fs::create_dir_all(parent).map_err(|error| AppError::Export(error.to_string()))?;
        }
        let title = Format::new().set_bold().set_font_size(14);
        let bold = Format::new().set_bold();
        let money = Format::new().set_num_format("#,##0.00");
        let mut workbook = Workbook::new();
        {
            let sheet = workbook.add_worksheet();
            sheet
                .set_name("Summary")
                .map_err(|error| AppError::Export(error.to_string()))?;
            sheet.set_column_width(0, 28).ok();
            sheet.set_column_width(1, 38).ok();
            sheet
                .write_string_with_format(0, 0, "HRAgents payroll review packet", &title)
                .map_err(|error| AppError::Export(error.to_string()))?;
            let rows = [
                ("Period", run.period.to_string()),
                ("Kind", format!("{:?}", run.kind).to_lowercase()),
                ("Status", format!("{:?}", run.status).to_lowercase()),
                ("Employees", run.totals.employees.to_string()),
                ("Gross (IDR)", run.totals.gross.to_decimal_string()),
                (
                    "Employee deductions (IDR)",
                    run.totals.employee_deductions.to_decimal_string(),
                ),
                ("Net pay (IDR)", run.totals.net.to_decimal_string()),
                (
                    "Employer cost (IDR)",
                    run.totals.employer_cost.to_decimal_string(),
                ),
                ("PPh 21 (IDR)", run.totals.pph21.to_decimal_string()),
                ("Payment execution", "none — export only".to_owned()),
            ];
            for (index, (label, value)) in rows.iter().enumerate() {
                let row = (index + 2) as u32;
                sheet
                    .write_string_with_format(row, 0, *label, &bold)
                    .map_err(|error| AppError::Export(error.to_string()))?;
                sheet
                    .write_string(row, 1, value)
                    .map_err(|error| AppError::Export(error.to_string()))?;
            }
            let mut row = rows.len() as u32 + 3;
            sheet
                .write_string_with_format(row, 0, "Anomalies", &bold)
                .map_err(|error| AppError::Export(error.to_string()))?;
            row += 1;
            if run.anomalies.is_empty() {
                sheet
                    .write_string(row, 0, "none")
                    .map_err(|error| AppError::Export(error.to_string()))?;
            } else {
                for anomaly in &run.anomalies {
                    sheet
                        .write_string(row, 0, format!("{:?}", anomaly.severity))
                        .map_err(|error| AppError::Export(error.to_string()))?;
                    sheet
                        .write_string(row, 1, format!("{} — {}", anomaly.code, anomaly.detail))
                        .map_err(|error| AppError::Export(error.to_string()))?;
                    row += 1;
                }
            }
        }
        {
            let sheet = workbook.add_worksheet();
            sheet
                .set_name("Lines")
                .map_err(|error| AppError::Export(error.to_string()))?;
            let headers = [
                "Employee",
                "Base",
                "Allowances",
                "Overtime",
                "Bonus",
                "Gross",
                "BPJS Kesehatan",
                "BPJS JHT",
                "BPJS JP",
                "PPh 21",
                "Other deductions",
                "Net",
                "Employer cost",
            ];
            for (column, header) in headers.iter().enumerate() {
                sheet
                    .write_string_with_format(0, column as u16, *header, &bold)
                    .map_err(|error| AppError::Export(error.to_string()))?;
            }
            sheet.set_column_width(0, 28).ok();
            for (index, line) in run.lines.iter().enumerate() {
                let row = (index + 1) as u32;
                sheet
                    .write_string(row, 0, &line.employee_name)
                    .map_err(|error| AppError::Export(error.to_string()))?;
                let amounts = [
                    line.base_salary,
                    line.allowances,
                    line.overtime_pay,
                    line.bonus,
                    line.gross,
                    line.bpjs_kesehatan_employee,
                    line.bpjs_jht_employee,
                    line.bpjs_jp_employee,
                    line.pph21,
                    line.other_deductions,
                    line.net,
                    line.employer_cost,
                ];
                for (offset, amount) in amounts.iter().enumerate() {
                    sheet
                        .write_number_with_format(
                            row,
                            (offset + 1) as u16,
                            amount.sen() as f64 / 100.0,
                            &money,
                        )
                        .map_err(|error| AppError::Export(error.to_string()))?;
                }
            }
        }
        workbook
            .save(path)
            .map_err(|error| AppError::Export(error.to_string()))?;
        let size = std::fs::metadata(path)
            .map_err(|error| AppError::Export(error.to_string()))?
            .len();
        self.append_audit(
            "payroll.exported",
            "payroll_run",
            &run.id.to_string(),
            serde_json::json!({
                "period": run.period.to_string(),
                "employees": run.lines.len(),
                "path": path.display().to_string(),
                "size_bytes": size,
            }),
            now,
        )?;
        Ok(size)
    }

    // ------------------------------------------------------------------
    // Today, approvals, compliance, audit
    // ------------------------------------------------------------------

    pub fn today(&self) -> AppResult<TodayView> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        let approvals = self.store.list_approvals(true)?;
        let employees = self.store.list_employees()?;
        let mut latest_plans = HashMap::new();
        for plan in self.store.list_onboarding_plans()? {
            latest_plans.entry(plan.employee_id).or_insert(plan);
        }
        let mut open_onboarding = Vec::new();
        for employee in &employees {
            if let Some(plan) = latest_plans.get(&employee.id)
                && plan.status == hragents_core::people::OnboardingStatus::InProgress
            {
                let (done, total) = plan.progress();
                open_onboarding.push(format!(
                    "{} — {} ({done}/{total})",
                    employee.full_name, plan.template_name
                ));
            }
        }
        let recent_audit = self.store.audit_recent(8)?;
        Ok(TodayView {
            approvals,
            open_onboarding,
            expiring_documents: Vec::new(),
            recent_audit,
            headcount: employees
                .iter()
                .filter(|employee| {
                    !matches!(
                        employee.status,
                        hragents_core::people::EmploymentStatus::Exited
                    )
                })
                .count(),
        })
    }

    pub fn reminders(&self) -> AppResult<Vec<hragents_core::reminders::Reminder>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        let today = BusinessDate::today();
        let approvals = self.store.list_approvals(true)?;
        let employees = self.store.list_employees()?;
        let employee_names: HashMap<String, String> = employees
            .iter()
            .map(|employee| (employee.id.to_string(), employee.full_name.clone()))
            .collect();
        let mut latest_plans = HashMap::new();
        for plan in self.store.list_onboarding_plans()? {
            latest_plans.entry(plan.employee_id).or_insert(plan);
        }
        let onboarding = employees
            .iter()
            .filter_map(|employee| {
                latest_plans
                    .get(&employee.id)
                    .map(|plan| (employee.full_name.clone(), plan.clone()))
            })
            .collect::<Vec<_>>();
        let contracts = self.store.list_contracts()?;
        let documents = self
            .store
            .expiring_documents(today.add_days(30))?
            .into_iter()
            .map(|(document, _owner_id)| {
                let owner = employee_names
                    .get(&document.owner_id)
                    .cloned()
                    .unwrap_or_else(|| document.owner_id.clone());
                (
                    owner,
                    document.filename,
                    document.expires_on.unwrap_or(today),
                )
            })
            .collect::<Vec<_>>();
        let offers = self.store.list_offers(None)?;
        let mut leave_requests = Vec::new();
        for request in self.store.list_leave_requests(None)? {
            let name = employee_names
                .get(&request.employee_id.to_string())
                .cloned()
                .unwrap_or_default();
            leave_requests.push((request, name));
        }
        Ok(hragents_core::reminders::collect(
            today,
            UtcInstant::now(),
            &approvals,
            &onboarding,
            &contracts,
            &documents,
            &offers,
            &leave_requests,
        ))
    }

    /// Messages queued but not yet sent: no transport is configured in this
    /// edition, so the sweep reports what waits for manual send instead of
    /// silently dropping it. A future transport will dispatch from this list.
    pub fn outbox_pending(&self) -> AppResult<Vec<hragents_core::hiring_comms::CandidateMessage>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self
            .store
            .list_messages(None)?
            .into_iter()
            .filter(|message| {
                message.status == hragents_core::hiring_comms::MessageStatus::Queued
                    && message.direction == hragents_core::hiring_comms::MessageDirection::Outbound
            })
            .collect())
    }

    /// Inbound reply polling. Returns how many replies were recorded, or a
    /// clear error when IMAP is not configured. Polling needs operator mail
    /// credentials; until then replies are recorded manually.
    pub fn poll_replies(&mut self) -> AppResult<usize> {
        self.require_active()?;
        let configured: bool = self
            .store
            .setting("imap.configured")?
            .and_then(|value| value.as_bool())
            .unwrap_or(false);
        if !configured {
            return Err(AppError::Domain(DomainError::validation(
                "E_IMAP_NOT_CONFIGURED",
                "inbound mail polling is not configured; record replies manually",
            )));
        }
        Ok(0)
    }

    pub fn list_approvals(&self, open_only: bool) -> AppResult<Vec<ApprovalRequest>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.list_approvals(open_only)?)
    }

    pub fn create_approval(&mut self, approval: ApprovalRequest) -> AppResult<ApprovalRequest> {
        let now = UtcInstant::now();
        self.require_active()?;
        self.store.save_approval(&approval)?;
        self.append_audit(
            "approval.created",
            "approval",
            &approval.id,
            serde_json::json!({"kind": approval.kind, "title": approval.title}),
            now,
        )?;
        Ok(approval)
    }

    pub fn decide_approval(
        &mut self,
        approval_id: &str,
        approve: bool,
        note: &str,
    ) -> AppResult<ApprovalRequest> {
        let now = UtcInstant::now();
        let operator_id = self.require_reauth()?.operator_id;
        let mut approval = self
            .store
            .list_approvals(false)?
            .into_iter()
            .find(|approval| approval.id == approval_id)
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "approval",
                    id: approval_id.to_owned(),
                })
            })?;
        if approve {
            approval.approve(operator_id, note, now)?;
        } else {
            approval.reject(operator_id, note, now)?;
        }
        self.store.save_approval(&approval)?;
        self.append_audit(
            if approve {
                "approval.approved"
            } else {
                "approval.rejected"
            },
            "approval",
            &approval.id,
            serde_json::json!({"note": note, "reauth": true}),
            now,
        )?;
        Ok(approval)
    }

    pub fn grant_consent(
        &mut self,
        subject: SubjectType,
        subject_id: &str,
        purpose: ConsentPurpose,
        source: &str,
    ) -> AppResult<ConsentRecord> {
        let now = UtcInstant::now();
        self.require_active()?;
        let mut consent = ConsentRecord::new(subject, subject_id, purpose, source, now);
        consent.grant(now)?;
        self.store.save_consent(&consent)?;
        self.append_audit(
            "consent.granted",
            "consent",
            &consent.id.to_string(),
            serde_json::json!({"subject_id": subject_id, "purpose": format!("{purpose:?}")}),
            now,
        )?;
        Ok(consent)
    }

    pub fn withdraw_consent(
        &mut self,
        subject: SubjectType,
        subject_id: &str,
        reason: &str,
    ) -> AppResult<ConsentRecord> {
        let now = UtcInstant::now();
        self.require_active()?;
        let mut consent = self
            .store
            .consent_for(subject, subject_id)?
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "consent",
                    id: subject_id.to_owned(),
                })
            })?;
        consent.withdraw(reason, now)?;
        self.store.save_consent(&consent)?;
        self.append_audit(
            "consent.withdrawn",
            "consent",
            &consent.id.to_string(),
            serde_json::json!({"subject_id": subject_id, "reason": reason}),
            now,
        )?;
        Ok(consent)
    }

    pub fn audit_verify(&self) -> AppResult<hragents_core::audit::AuditVerification> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.verify_audit()?)
    }

    pub fn audit_recent(&self, limit: usize) -> AppResult<Vec<AuditEntry>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        Ok(self.store.audit_recent(limit)?)
    }

    /// Export the audit chain as JSON: every entry with its actor, payload hash,
    /// and chain links, plus a verification summary. The export itself is
    /// audited. Verification of the file after restore is the compliance proof.
    pub fn export_audit(&mut self, path: impl AsRef<Path>, limit: Option<usize>) -> AppResult<u64> {
        let now = UtcInstant::now();
        self.require_active()?;
        let path = path.as_ref();
        if let Some(parent) = path.parent()
            && !parent.as_os_str().is_empty()
        {
            std::fs::create_dir_all(parent).map_err(|error| AppError::Export(error.to_string()))?;
        }
        let mut entries = self.store.audit_entries()?;
        if let Some(limit) = limit {
            entries.truncate(limit);
        }
        let verification = self.store.verify_audit()?;
        let document = serde_json::json!({
            "exported_at": now.to_string(),
            "entries": entries.len(),
            "verification": verification,
            "chain": entries,
        });
        let bytes = serde_json::to_string_pretty(&document)
            .map_err(|error| AppError::Export(error.to_string()))?;
        std::fs::write(path, &bytes)
            .map_err(|error| AppError::Export(format!("write audit export: {error}")))?;
        let size = bytes.len() as u64;
        self.append_audit(
            "audit.exported",
            "system",
            &path.display().to_string(),
            serde_json::json!({"entries": entries.len(), "size_bytes": size}),
            now,
        )?;
        Ok(size)
    }

    pub fn search(&self, query: &str) -> AppResult<Vec<SearchHit>> {
        self.session.as_ref().ok_or(AppError::Unauthenticated)?;
        let mut hits = Vec::new();
        for employee in self.store.search_employees(query, 10)? {
            hits.push(SearchHit {
                kind: "employee".into(),
                id: employee.id.to_string(),
                title: employee.full_name,
                subtitle: format!("{} · {}", employee.job_title, employee.org_unit),
            });
        }
        for candidate in self.store.search_candidates(query, 10)? {
            hits.push(SearchHit {
                kind: "candidate".into(),
                id: candidate.id.to_string(),
                title: candidate.full_name,
                subtitle: candidate
                    .headline
                    .unwrap_or_else(|| candidate.source.clone()),
            });
        }
        Ok(hits)
    }

    pub fn backup(&mut self, path: impl AsRef<Path>) -> AppResult<u64> {
        let now = UtcInstant::now();
        self.require_active()?;
        let size = self.store.backup_to(&path)?;
        self.append_audit(
            "backup.created",
            "system",
            &path.as_ref().display().to_string(),
            serde_json::json!({"size_bytes": size}),
            now,
        )?;
        Ok(size)
    }

    /// Complete backup set: encrypted database, encrypted documents, and the
    /// OS-protected key file. Restore verifies every hash before opening.
    pub fn backup_set(&mut self, path: impl AsRef<Path>) -> AppResult<u64> {
        let now = UtcInstant::now();
        self.require_active()?;
        self.store.checkpoint()?;
        let data_dir = self
            .documents_dir
            .parent()
            .filter(|parent| !parent.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."));
        let key_file = data_dir.join(hragents_store::keyfile::KEY_FILE_NAME);
        let size = backup_set::create(
            path.as_ref(),
            self.store.path(),
            &self.documents_dir,
            Some(&key_file),
            self.database_key.as_deref(),
        )?;
        self.append_audit(
            "backup.set_created",
            "system",
            &path.as_ref().display().to_string(),
            serde_json::json!({"size_bytes": size, "includes": ["database", "documents", "key"]}),
            now,
        )?;
        Ok(size)
    }

    pub fn policy_corpus(&self) -> PolicyCorpus {
        PolicyCorpus::default()
    }

    /// Seed the demo/verification fixture rate tables. Every table is marked
    /// verified with a source note; real installs require the operator to enter
    /// and verify their own statutory figures before payroll will compute.
    pub fn seed_demo_rate_tables(&mut self, effective_from: BusinessDate) -> AppResult<()> {
        let now = UtcInstant::now();
        self.require_active()?;
        for table in demo_rate_tables(effective_from, now) {
            self.store.save_rate_table(&table)?;
        }
        self.append_audit(
            "rate_tables.seeded_demo",
            "system",
            "demo",
            serde_json::json!({"effective_from": effective_from.to_string()}),
            now,
        )?;
        Ok(())
    }
}

fn default_onboarding_steps(template: &str) -> Vec<OnboardingStep> {
    match template {
        "Remote" => vec![
            OnboardingStep::new("contract", "Sign employment contract", "documents"),
            OnboardingStep::new("identity", "Collect KTP and NPWP", "documents"),
            OnboardingStep::new("laptop", "Ship laptop and equipment", "assets"),
            OnboardingStep::new("accounts", "Create accounts and access", "access"),
            OnboardingStep::new("buddy", "Assign onboarding buddy", "people"),
        ],
        _ => vec![
            OnboardingStep::new("contract", "Sign employment contract", "documents"),
            OnboardingStep::new(
                "identity",
                "Collect KTP, NPWP, and BPJS details",
                "documents",
            ),
            OnboardingStep::new("payroll", "Complete payroll and bank profile", "payroll"),
            OnboardingStep::new("laptop", "Issue laptop and equipment", "assets"),
            OnboardingStep::new("accounts", "Create accounts and access", "access"),
            OnboardingStep::new("intro", "Schedule first-week intro", "people"),
        ],
    }
}

fn demo_rate_tables(effective_from: BusinessDate, now: UtcInstant) -> Vec<RateTable> {
    let mut tables = Vec::new();
    let mut table = |kind, entries| {
        let mut table = RateTable {
            id: RateTableId::new(),
            kind,
            effective_from,
            effective_to: None,
            verified: true,
            verified_by: Some("Demo fixture".into()),
            verified_at: Some(now),
            source_note: Some(
                "demo fixture — verify against the current regulation before production use".into(),
            ),
            entries,
        };
        table.verified = true;
        tables.push(table);
    };

    table(
        RateTableKind::BpjsKesehatan,
        vec![RateEntry::shares(None, 100, 400)],
    );
    table(
        RateTableKind::BpjsKetenagakerjaanJht,
        vec![RateEntry::shares(Some("normal"), 200, 370)],
    );
    table(
        RateTableKind::BpjsKetenagakerjaanJp,
        vec![RateEntry::shares(None, 100, 200)],
    );
    table(
        RateTableKind::BpjsJkk,
        vec![
            RateEntry::shares(Some("class_1"), 0, 24),
            RateEntry::shares(Some("class_2"), 0, 54),
            RateEntry::shares(Some("class_3"), 0, 89),
            RateEntry::shares(Some("class_4"), 0, 127),
            RateEntry::shares(Some("class_5"), 0, 174),
        ],
    );
    table(RateTableKind::BpjsJkm, vec![RateEntry::shares(None, 0, 30)]);
    table(
        RateTableKind::Pph21Ptkp,
        vec![
            RateEntry::flat(Some("personal"), Money::from_rupiah(54_000_000).unwrap()),
            RateEntry::flat(Some("dependent"), Money::from_rupiah(4_500_000).unwrap()),
        ],
    );
    table(
        RateTableKind::Pph21Ter,
        vec![
            RateEntry {
                key: None,
                employee_share_bp: 50,
                employer_share_bp: 0,
                wage_cap: None,
                flat_amount: None,
                multiplier_bp: None,
                lower_bound: Some(Money::from_rupiah(0).unwrap()),
                upper_bound: Some(Money::from_rupiah(6_500_000).unwrap()),
                hours_per_month: None,
                note: None,
            },
            RateEntry {
                key: None,
                employee_share_bp: 100,
                employer_share_bp: 0,
                wage_cap: None,
                flat_amount: None,
                multiplier_bp: None,
                lower_bound: Some(Money::from_rupiah(6_500_000).unwrap()),
                upper_bound: Some(Money::from_rupiah(10_000_000).unwrap()),
                hours_per_month: None,
                note: None,
            },
            RateEntry {
                key: None,
                employee_share_bp: 150,
                employer_share_bp: 0,
                wage_cap: None,
                flat_amount: None,
                multiplier_bp: None,
                lower_bound: Some(Money::from_rupiah(10_000_000).unwrap()),
                upper_bound: Some(Money::from_rupiah(1_000_000_000).unwrap()),
                hours_per_month: None,
                note: None,
            },
        ],
    );
    table(
        RateTableKind::OvertimePremium,
        vec![
            RateEntry {
                key: Some("hours_per_month".into()),
                employee_share_bp: 0,
                employer_share_bp: 0,
                wage_cap: None,
                flat_amount: None,
                multiplier_bp: None,
                lower_bound: None,
                upper_bound: None,
                hours_per_month: Some(173),
                note: None,
            },
            RateEntry {
                key: Some("first_tier".into()),
                employee_share_bp: 0,
                employer_share_bp: 0,
                wage_cap: None,
                flat_amount: None,
                multiplier_bp: Some(15_000),
                lower_bound: None,
                upper_bound: None,
                hours_per_month: None,
                note: None,
            },
            RateEntry {
                key: Some("rest_tier".into()),
                employee_share_bp: 0,
                employer_share_bp: 0,
                wage_cap: None,
                flat_amount: None,
                multiplier_bp: Some(20_000),
                lower_bound: None,
                upper_bound: None,
                hours_per_month: None,
                note: None,
            },
        ],
    );
    table(
        RateTableKind::ThrFormula,
        vec![
            RateEntry {
                key: Some("under_1y".into()),
                employee_share_bp: 0,
                employer_share_bp: 0,
                wage_cap: None,
                flat_amount: None,
                multiplier_bp: Some(10_000),
                lower_bound: None,
                upper_bound: None,
                hours_per_month: None,
                note: None,
            },
            RateEntry {
                key: Some("1y".into()),
                employee_share_bp: 0,
                employer_share_bp: 0,
                wage_cap: None,
                flat_amount: None,
                multiplier_bp: Some(20_000),
                lower_bound: None,
                upper_bound: None,
                hours_per_month: None,
                note: None,
            },
            RateEntry {
                key: Some("2y".into()),
                employee_share_bp: 0,
                employer_share_bp: 0,
                wage_cap: None,
                flat_amount: None,
                multiplier_bp: Some(30_000),
                lower_bound: None,
                upper_bound: None,
                hours_per_month: None,
                note: None,
            },
            RateEntry {
                key: Some("8y_plus".into()),
                employee_share_bp: 0,
                employer_share_bp: 0,
                wage_cap: None,
                flat_amount: None,
                multiplier_bp: Some(90_000),
                lower_bound: None,
                upper_bound: None,
                hours_per_month: None,
                note: None,
            },
        ],
    );
    table(
        RateTableKind::MinimumWage,
        vec![RateEntry::flat(
            None,
            Money::from_rupiah(5_396_761).unwrap(),
        )],
    );
    tables
}

#[cfg(test)]
mod tests {
    use super::*;
    use hragents_core::hiring::Dimension;

    fn service() -> AppService {
        let mut service = AppService::open_in_memory().unwrap();
        service
            .setup_first_run(SetupInput {
                company_name: "Nusantara Labs".into(),
                operator_name: "Rina".into(),
                username: "rina".into(),
                password: "correct horse battery staple".into(),
            })
            .unwrap();
        service
    }

    fn employee_input() -> CreateEmployeeInput {
        CreateEmployeeInput {
            employee_no: "E-001".into(),
            full_name: "Ayu Lestari".into(),
            job_title: "Engineer".into(),
            org_unit: "Product".into(),
            hire_date: BusinessDate::parse("2025-02-01").unwrap(),
            email: Some("ayu@example.com".into()),
            phone: None,
            ptkp_status: Some("TK/1".into()),
            dependents: 1,
            jkk_risk_class: Some(1),
            bank_name: Some("BCA".into()),
            bank_account: Some("1234567890".into()),
        }
    }

    #[test]
    fn first_run_login_and_lock() {
        let mut service = service();
        assert!(!service.setup_required().unwrap());
        let session = service.current_session().unwrap();
        assert_eq!(session.display_name, "Rina");
        service.lock().unwrap();
        assert!(service.current_session().is_ok());
        assert!(service.create_employee(employee_input()).is_err());
        // A fresh login replaces the locked session.
        service
            .login("rina", "correct horse battery staple")
            .unwrap();
        service.create_employee(employee_input()).unwrap();
        assert_eq!(service.audit_verify().unwrap().entries, 4);
    }

    #[test]
    fn employee_and_onboarding_vertical_slice() {
        let mut service = service();
        let employee = service.create_employee(employee_input()).unwrap();
        let plan = service.start_onboarding(employee.id, None).unwrap();
        assert_eq!(plan.steps.len(), 6);
        let plan = service
            .complete_onboarding_step(employee.id, "contract")
            .unwrap();
        assert_eq!(plan.progress().0, 1);
        let verification = service.audit_verify().unwrap();
        assert!(verification.entries >= 5);
        assert!(
            service
                .audit_recent(10)
                .unwrap()
                .iter()
                .any(|entry| entry.action == "onboarding.step_completed")
        );
    }

    #[test]
    fn candidate_import_evaluate_and_gated_rejection() {
        let mut service = service();
        let job = service.create_job("Backend Engineer", "Product").unwrap();
        let (candidate, application) = service
            .import_candidate(ImportCandidateInput {
                full_name: "Budi Santoso".into(),
                email: Some("budi@example.com".into()),
                phone: None,
                source: "LinkedIn".into(),
                headline: Some("Backend engineer".into()),
                job_id: job.id,
                consent: ConsentStatus::Granted,
                document: None,
            })
            .unwrap();
        let rubric = Rubric {
            id: "backend-v1".into(),
            name: "Backend".into(),
            dimensions: vec![
                Dimension {
                    key: "skills".into(),
                    label: "Skills".into(),
                    weight_bp: 6_000,
                },
                Dimension {
                    key: "impact".into(),
                    label: "Impact".into(),
                    weight_bp: 4_000,
                },
            ],
            merit_floor_bp: 6_000,
            sigma_limit_bp: 500,
        };
        let run = RunScores {
            dimension_scores: BTreeMap::from([("skills".into(), 8_500), ("impact".into(), 7_500)]),
        };
        let view = service
            .evaluate_candidate(EvaluateInput {
                application_id: application.id,
                rubric,
                runs: vec![run],
                evidence: vec![],
            })
            .unwrap();
        assert_eq!(view.evaluation.overall_bp, 8_100);
        assert!(matches!(view.policy, PolicyOutcome::GatedRejection { .. }));
        assert!(service.reject_candidate(application.id, "short").is_err());
        // Re-auth is fresh from setup/login in this fixture.
        service
            .reject_candidate(application.id, "lacks the required on-call experience")
            .unwrap();
        assert!(
            service
                .audit_recent(10)
                .unwrap()
                .iter()
                .any(|entry| entry.action == "candidate.rejected")
        );
        let _ = candidate;
    }

    #[test]
    fn extraction_from_text_scores_with_evidence_and_audit() {
        let mut service = service();
        let job = service.create_job("Backend Engineer", "Product").unwrap();
        let (_candidate, application) = service
            .import_candidate(ImportCandidateInput {
                full_name: "Sari Wulandari".into(),
                email: Some("sari@example.com".into()),
                phone: None,
                source: "Referral".into(),
                headline: Some("Platform engineer".into()),
                job_id: job.id,
                consent: ConsentStatus::Granted,
                document: None,
            })
            .unwrap();
        let rubric = Rubric {
            id: "backend-v1".into(),
            name: "Backend".into(),
            dimensions: vec![
                Dimension {
                    key: "skills".into(),
                    label: "Technical skills".into(),
                    weight_bp: 6_000,
                },
                Dimension {
                    key: "impact".into(),
                    label: "Impact and ownership".into(),
                    weight_bp: 4_000,
                },
            ],
            merit_floor_bp: 6_000,
            sigma_limit_bp: 500,
        };
        let view = service
            .evaluate_from_text(
                application.id,
                "Built a Rust ingestion pipeline handling 2M events per day.                  Reduced p99 latency from 900ms to 180ms and led the migration.",
                rubric,
            )
            .unwrap();
        assert!(view.evaluation.overall_bp > 5_000);
        assert_eq!(view.evaluation.runs, 3);
        assert_eq!(view.evaluation.sigma_bp, 0);
        assert!(!view.evaluation.evidence.is_empty());
        let actions: Vec<String> = service
            .audit_recent(20)
            .unwrap()
            .into_iter()
            .map(|entry| entry.action)
            .collect();
        assert!(actions.contains(&"candidate.extracted".to_owned()));
        assert!(actions.contains(&"candidate.evaluated".to_owned()));
    }

    #[test]
    fn leave_balance_and_decision() {
        let mut service = service();
        let employee = service.create_employee(employee_input()).unwrap();
        let leave_type = service.create_leave_type("Annual leave", 12).unwrap();
        service
            .set_leave_entitlement(employee.id, leave_type.id, 2026, 12)
            .unwrap();
        let view = service
            .record_leave(RecordLeaveInput {
                employee_id: employee.id,
                leave_type_id: leave_type.id,
                start_date: BusinessDate::parse("2026-11-09").unwrap(),
                end_date: BusinessDate::parse("2026-11-10").unwrap(),
                days_x2: 4,
                reason: "family event".into(),
            })
            .unwrap();
        assert_eq!(view.balance.available_x2(), 20);
        let decided = service.decide_leave(view.request.id, true, "").unwrap();
        assert_eq!(decided.balance.used_x2, 4);
        assert_eq!(decided.balance.pending_x2, 0);
    }

    #[test]
    fn payroll_computes_blocks_on_missing_tables_and_approves_with_reauth() {
        let mut service = service();
        let employee = service.create_employee(employee_input()).unwrap();
        service
            .seed_demo_rate_tables(BusinessDate::parse("2026-01-01").unwrap())
            .unwrap();
        let mut input = PayrollInput::new(
            employee.id,
            employee.full_name.clone(),
            Money::from_rupiah(10_000_000).unwrap(),
        );
        input.fixed_allowances = Money::from_rupiah(2_000_000).unwrap();
        input.service_months = 30;
        let view = service
            .compute_payroll(
                PayrollKind::Monthly,
                BusinessDate::parse("2026-11-01").unwrap(),
                vec![input],
            )
            .unwrap();
        assert_eq!(view.blocking, 0);
        assert_eq!(view.run.totals.net, Money::from_rupiah(11_520_000).unwrap());
        let approved = service.approve_payroll(view.run.id).unwrap();
        assert_eq!(approved.status, hragents_core::payroll::RunStatus::Approved);
    }

    #[test]
    #[ignore = "release benchmark; run explicitly with --release --ignored"]
    fn payroll_1000_lines_under_two_seconds() {
        let mut service = service();
        service
            .seed_demo_rate_tables(BusinessDate::parse("2026-01-01").unwrap())
            .unwrap();
        let mut inputs = Vec::with_capacity(1_000);
        for index in 0..1_000 {
            let mut employee = Employee::new(
                format!("E-{index:04}"),
                format!("Employee {index}"),
                "Engineer",
                "Product",
                BusinessDate::parse("2024-01-01").unwrap(),
                UtcInstant::now(),
            );
            employee.jkk_risk_class = Some(((index % 5) + 1) as u8);
            employee.dependents = (index % 4) as u8;
            service.store_mut().save_employee(&employee).unwrap();
            let mut input = PayrollInput::new(
                employee.id,
                employee.full_name.clone(),
                Money::from_rupiah(8_000_000 + (index as i64 % 20) * 250_000).unwrap(),
            );
            input.fixed_allowances = Money::from_rupiah(1_500_000).unwrap();
            input.service_months = 12 + (index % 60) as u32;
            input.working_days = 22;
            input.absence_days = (index % 3) as u32;
            inputs.push(input);
        }
        let started = std::time::Instant::now();
        let view = service
            .compute_payroll(
                PayrollKind::Monthly,
                BusinessDate::parse("2026-11-01").unwrap(),
                inputs,
            )
            .unwrap();
        let elapsed = started.elapsed();
        println!(
            "payroll_1000: {} lines, net {}, elapsed {:?}",
            view.run.lines.len(),
            view.run.totals.net,
            elapsed
        );
        assert_eq!(view.run.lines.len(), 1_000);
        assert!(
            elapsed < std::time::Duration::from_secs(2),
            "payroll 1,000 took {elapsed:?}, budget is 2s"
        );
    }

    #[test]
    fn payroll_export_writes_an_xlsx_packet() {
        let mut service = service();
        let employee = service.create_employee(employee_input()).unwrap();
        service
            .seed_demo_rate_tables(BusinessDate::parse("2026-01-01").unwrap())
            .unwrap();
        let mut input = PayrollInput::new(
            employee.id,
            employee.full_name.clone(),
            Money::from_rupiah(10_000_000).unwrap(),
        );
        input.fixed_allowances = Money::from_rupiah(2_000_000).unwrap();
        input.service_months = 30;
        let view = service
            .compute_payroll(
                PayrollKind::Monthly,
                BusinessDate::parse("2026-11-01").unwrap(),
                vec![input],
            )
            .unwrap();
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("payroll-2026-11.xlsx");
        let size = service.export_payroll_xlsx(view.run.id, &path).unwrap();
        assert!(
            size > 1_000,
            "xlsx should have real content, got {size} bytes"
        );
        assert!(path.exists());
        assert!(
            service
                .audit_recent(20)
                .unwrap()
                .iter()
                .any(|entry| entry.action == "payroll.exported")
        );
    }

    #[test]
    fn compliance_retention_erasure_breach() {
        use hragents_core::compliance::{BreachSeverity, SubjectType};
        let mut service = service();
        let policies = service.seed_retention_policies().unwrap();
        assert!(policies.len() >= 5);

        // A candidate created today is not yet due.
        let job = service.create_job("Backend Engineer", "Product").unwrap();
        let (candidate, _application) = service
            .import_candidate(ImportCandidateInput {
                full_name: "Eko Saputra".into(),
                email: None,
                phone: None,
                source: "Referral".into(),
                headline: None,
                job_id: job.id,
                consent: ConsentStatus::Granted,
                document: None,
            })
            .unwrap();
        let sweep = service.retention_sweep(BusinessDate::today()).unwrap();
        assert!(
            sweep
                .iter()
                .all(|item| item.subject_id != candidate.id.to_string()),
            "a fresh candidate must not be due"
        );

        // Erasure: request -> approve (reauth) -> execute purges the candidate.
        let request = service
            .create_erasure_request(
                SubjectType::Candidate,
                &candidate.id.to_string(),
                "candidate exercised their right to erasure",
            )
            .unwrap();
        assert!(service.execute_erasure(request.id).is_err());
        service.reauth("correct horse battery staple").unwrap();
        let approved = service.approve_erasure(request.id).unwrap();
        assert_eq!(format!("{:?}", approved.status), "Approved");
        service.reauth("correct horse battery staple").unwrap();
        let completed = service.execute_erasure(request.id).unwrap();
        assert_eq!(format!("{:?}", completed.status), "Completed");
        assert!(service.candidate(candidate.id).is_err());

        // A hold blocks execution.
        let (candidate2, _application2) = service
            .import_candidate(ImportCandidateInput {
                full_name: "Fitri Dewi".into(),
                email: None,
                phone: None,
                source: "Referral".into(),
                headline: None,
                job_id: job.id,
                consent: ConsentStatus::Granted,
                document: None,
            })
            .unwrap();
        service
            .create_retention_hold(
                SubjectType::Candidate,
                &candidate2.id.to_string(),
                "tax audit",
                None,
            )
            .unwrap();
        let request2 = service
            .create_erasure_request(
                SubjectType::Candidate,
                &candidate2.id.to_string(),
                "candidate exercised their right to erasure",
            )
            .unwrap();
        service.reauth("correct horse battery staple").unwrap();
        service.approve_erasure(request2.id).unwrap();
        service.reauth("correct horse battery staple").unwrap();
        assert!(service.execute_erasure(request2.id).is_err());
        assert_eq!(
            service
                .erasure_blockers(&candidate2.id.to_string())
                .unwrap()
                .len(),
            1
        );

        // Breach: report -> contain -> notify -> close.
        let breach = service
            .report_breach(
                "Lost laptop",
                "HR laptop left in a taxi; disk is encrypted",
                BreachSeverity::Medium,
            )
            .unwrap();
        let contained = service
            .contain_breach(&breach.id, "Remotely locked the device and rotated keys")
            .unwrap();
        assert_eq!(format!("{:?}", contained.status), "Contained");
        let notified = service.mark_breach_notified(&breach.id).unwrap();
        assert_eq!(format!("{:?}", notified.status), "Notified");
        let closed = service.close_breach(&breach.id).unwrap();
        assert_eq!(format!("{:?}", closed.status), "Closed");
        assert_eq!(service.list_breaches().unwrap().len(), 1);
    }

    #[test]
    fn hiring_comms_scheduling_offers_messages_feedback() {
        use hragents_core::hiring_comms::{MessageChannel, MessageKind};
        let mut service = service();
        let job = service.create_job("Backend Engineer", "Product").unwrap();
        let (candidate, application) = service
            .import_candidate(ImportCandidateInput {
                full_name: "Dimas Pratama".into(),
                email: Some("dimas@example.com".into()),
                phone: None,
                source: "LinkedIn".into(),
                headline: None,
                job_id: job.id,
                consent: ConsentStatus::Granted,
                document: None,
            })
            .unwrap();
        let slot = hragents_core::hiring_comms::InterviewSlot {
            starts_at: UtcInstant::now().plus_seconds(86_400),
            duration_minutes: 60,
            mode: hragents_core::hiring_comms::SlotMode::Remote,
            location: None,
        };
        let proposal = service
            .propose_schedule(application.id, vec![slot])
            .unwrap();
        let confirmed = service.confirm_schedule(proposal.id, 0).unwrap();
        assert_eq!(format!("{:?}", confirmed.status), "Confirmed");

        let offer = service
            .create_offer(
                application.id,
                "Backend Engineer",
                Some(12_000_000 * 100),
                Some(BusinessDate::parse("2026-12-01").unwrap()),
                None,
            )
            .unwrap();
        assert_eq!(format!("{:?}", offer.status), "Draft");
        // Approval needs a fresh re-auth; the fixture session logged in recently.
        service.reauth("correct horse battery staple").unwrap();
        let offer = service.approve_offer(offer.id).unwrap();
        let offer = service.send_offer(offer.id).unwrap();
        assert_eq!(format!("{:?}", offer.status), "Sent");

        let message = service
            .draft_message(
                candidate.id,
                Some(application.id),
                MessageKind::Interview,
                MessageChannel::Email,
                Some("Interview invitation".into()),
                "We would like to invite you to interview next week.",
            )
            .unwrap();
        service.reauth("correct horse battery staple").unwrap();
        let queued = service.queue_message(message.id).unwrap();
        assert_eq!(format!("{:?}", queued.status), "Queued");
        let sent = service.mark_message_sent(message.id).unwrap();
        assert_eq!(format!("{:?}", sent.status), "Sent");
        let inbound = service
            .record_inbound_reply(candidate.id, Some(application.id), "Thursday works for me.")
            .unwrap();
        assert_eq!(format!("{:?}", inbound.direction), "Inbound");

        // Feedback needs an evaluation with evidence: evaluate from text.
        let rubric = Rubric {
            id: "backend-v1".into(),
            name: "Backend".into(),
            dimensions: vec![
                Dimension {
                    key: "skills".into(),
                    label: "Skills".into(),
                    weight_bp: 6_000,
                },
                Dimension {
                    key: "impact".into(),
                    label: "Impact".into(),
                    weight_bp: 4_000,
                },
            ],
            merit_floor_bp: 6_000,
            sigma_limit_bp: 500,
        };
        service
            .evaluate_from_text(
                application.id,
                "Built a Rust ingestion pipeline handling 2M events per day. Reduced p99 latency.",
                rubric,
            )
            .unwrap();
        let report = service.generate_feedback(application.id).unwrap();
        assert!(!report.summary.is_empty());
        assert!(service.feedback_for(application.id).unwrap().is_some());

        let stored = service.list_offers(Some(application.id)).unwrap();
        assert_eq!(stored.len(), 1);
        assert_eq!(
            service.list_messages(Some(application.id)).unwrap().len(),
            2
        );
        assert_eq!(
            service
                .list_schedule_proposals(Some(application.id))
                .unwrap()
                .len(),
            1
        );
    }

    #[test]
    fn extract_from_uploaded_document_scores_with_parser_label() {
        use hragents_core::people::DocumentOwnerType;
        let mut service = service();
        let job = service.create_job("Backend Engineer", "Product").unwrap();
        let (candidate, application) = service
            .import_candidate(ImportCandidateInput {
                full_name: "Tono Pradana".into(),
                email: None,
                phone: None,
                source: "Referral".into(),
                headline: None,
                job_id: job.id,
                consent: ConsentStatus::Granted,
                document: None,
            })
            .unwrap();
        let document = service
            .upload_document(
                DocumentOwnerType::Candidate,
                &candidate.id.to_string(),
                "cv.txt",
                "text/plain",
                b"Built a Rust ingestion pipeline handling 2M events per day. Reduced p99 latency."
                    .to_vec(),
            )
            .unwrap();
        let rubric = Rubric {
            id: "backend-v1".into(),
            name: "Backend".into(),
            dimensions: vec![
                Dimension {
                    key: "skills".into(),
                    label: "Skills".into(),
                    weight_bp: 6_000,
                },
                Dimension {
                    key: "impact".into(),
                    label: "Impact".into(),
                    weight_bp: 4_000,
                },
            ],
            merit_floor_bp: 6_000,
            sigma_limit_bp: 500,
        };
        let view = service
            .extract_and_evaluate(application.id, document.id, rubric)
            .unwrap();
        assert!(view.evaluation.overall_bp > 0);
        assert_eq!(view.evaluation.evidence.len(), 2);
        let actions: Vec<String> = service
            .audit_recent(20)
            .unwrap()
            .into_iter()
            .map(|entry| entry.action)
            .collect();
        assert!(actions.contains(&"candidate.extracted".to_owned()));
    }

    #[test]
    fn extract_rejects_document_of_another_candidate() {
        use hragents_core::people::DocumentOwnerType;
        let mut service = service();
        let job = service.create_job("Backend Engineer", "Product").unwrap();
        let (_candidate, application) = service
            .import_candidate(ImportCandidateInput {
                full_name: "Udin Saleh".into(),
                email: None,
                phone: None,
                source: "Referral".into(),
                headline: None,
                job_id: job.id,
                consent: ConsentStatus::Granted,
                document: None,
            })
            .unwrap();
        let stranger = service.create_employee(employee_input()).unwrap();
        let document = service
            .upload_document(
                DocumentOwnerType::Employee,
                &stranger.id.to_string(),
                "note.txt",
                "text/plain",
                b"not the candidate's file".to_vec(),
            )
            .unwrap();
        let rubric = Rubric {
            id: "backend-v1".into(),
            name: "Backend".into(),
            dimensions: vec![Dimension {
                key: "skills".into(),
                label: "Skills".into(),
                weight_bp: 10_000,
            }],
            merit_floor_bp: 6_000,
            sigma_limit_bp: 500,
        };
        assert!(
            service
                .extract_and_evaluate(application.id, document.id, rubric)
                .is_err()
        );
    }

    #[test]
    fn document_upload_preview_and_verify() {
        let mut service = service();
        let employee = service.create_employee(employee_input()).unwrap();
        let document = service
            .upload_document(
                DocumentOwnerType::Employee,
                &employee.id.to_string(),
                "ktp.txt",
                "text/plain",
                b"KTP number 1234".to_vec(),
            )
            .unwrap();
        assert_eq!(document.size_bytes, 15);
        assert_eq!(document.status, DocumentStatus::Pending);
        let documents = service
            .list_documents(DocumentOwnerType::Employee, &employee.id.to_string())
            .unwrap();
        assert_eq!(documents.len(), 1);
        let (viewed, bytes) = service.read_document(document.id).unwrap();
        assert_eq!(viewed.filename, "ktp.txt");
        assert_eq!(bytes, b"KTP number 1234");
        let verified = service.verify_document(document.id).unwrap();
        assert_eq!(verified.status, DocumentStatus::Verified);
        let actions: Vec<String> = service
            .audit_recent(20)
            .unwrap()
            .into_iter()
            .map(|entry| entry.action)
            .collect();
        assert!(actions.contains(&"document.uploaded".to_owned()));
        assert!(actions.contains(&"document.viewed".to_owned()));
        assert!(actions.contains(&"document.verified".to_owned()));
    }

    #[test]
    fn growth_cycle_assignments_and_goals() {
        let mut service = service();
        let employee = service.create_employee(employee_input()).unwrap();
        let cycle = service
            .create_review_cycle(
                "2026 H2",
                BusinessDate::parse("2026-07-01").unwrap(),
                BusinessDate::parse("2026-12-31").unwrap(),
            )
            .unwrap();
        let cycle = service.set_review_cycle_status(cycle.id, true).unwrap();
        assert_eq!(format!("{:?}", cycle.status), "Active");
        let assignment = service
            .create_review_assignment(cycle.id, employee.id, "Ayu", None)
            .unwrap();
        service.send_review_assignment(assignment.id).unwrap();
        let answers = BTreeMap::from([
            (
                "outcomes".to_owned(),
                hragents_core::growth::ReviewAnswer {
                    text: Some("Shipped the desktop migration".into()),
                    ..Default::default()
                },
            ),
            (
                "collaboration".to_owned(),
                hragents_core::growth::ReviewAnswer {
                    rating: Some(4),
                    ..Default::default()
                },
            ),
        ]);
        service
            .submit_review_response(assignment.id, answers)
            .unwrap();
        let summarized = service.summarize_review(assignment.id).unwrap();
        assert_eq!(format!("{:?}", summarized.status), "Summarized");
        assert_eq!(
            service
                .list_review_assignments(Some(cycle.id))
                .unwrap()
                .len(),
            1
        );

        let goal = service
            .create_goal(employee.id, "Ship the desktop beta")
            .unwrap();
        let goal = service.update_goal_progress(goal.id, 4_000).unwrap();
        assert_eq!(goal.progress_bp, 4_000);
        assert_eq!(service.list_goals(Some(employee.id)).unwrap().len(), 1);
    }

    #[test]
    fn offboarding_requires_all_steps_and_final_pay() {
        let mut service = service();
        let employee = service.create_employee(employee_input()).unwrap();
        let plan = service
            .start_offboarding(employee.id, BusinessDate::parse("2026-12-31").unwrap())
            .unwrap();
        assert_eq!(plan.steps.len(), 5);
        for key in ["handover", "assets", "access", "exit", "final_pay"] {
            service.complete_offboarding_step(employee.id, key).unwrap();
        }
        assert!(service.finish_offboarding(employee.id).is_err());
        service
            .record_offboarding_final_pay(employee.id, PayrollRunId::new())
            .unwrap();
        let finished = service.finish_offboarding(employee.id).unwrap();
        assert_eq!(format!("{:?}", finished.status), "Completed");
    }

    #[test]
    fn document_request_lifecycle() {
        let mut service = service();
        let employee = service.create_employee(employee_input()).unwrap();
        let request = service
            .create_document_request(
                employee.id,
                "KTP",
                Some(BusinessDate::parse("2026-11-10").unwrap()),
            )
            .unwrap();
        let document = Document {
            id: DocumentId::new(),
            owner_type: DocumentOwnerType::Employee,
            owner_id: employee.id.to_string(),
            filename: "ktp.pdf".into(),
            mime_type: "application/pdf".into(),
            sha256: "a".repeat(64),
            size_bytes: 1024,
            status: DocumentStatus::Pending,
            expires_on: None,
            uploaded_at: UtcInstant::now(),
            verified_at: None,
            verified_by: None,
            rejection_reason: None,
            tags: vec![],
        };
        service
            .store_mut()
            .save_document(&document, "documents/ktp.pdf")
            .unwrap();
        let request = service
            .attach_document_request(request.id, document.id)
            .unwrap();
        assert_eq!(format!("{:?}", request.status), "Uploaded");
        let request = service.verify_document_request(request.id).unwrap();
        assert_eq!(format!("{:?}", request.status), "Verified");
        assert_eq!(
            service
                .list_document_requests(Some(employee.id))
                .unwrap()
                .len(),
            1
        );
    }

    #[test]
    fn reminders_surface_overdue_and_outbox_lists_queued() {
        use hragents_core::approvals::{ApprovalKind, ApprovalRequest};
        let mut service = service();
        let employee = service.create_employee(employee_input()).unwrap();
        let mut approval = ApprovalRequest::new(
            ApprovalKind::Document,
            "Verify KTP",
            "stale",
            "document",
            "d1",
            UtcInstant::now(),
        );
        approval.due_on = Some(BusinessDate::parse("2026-10-01").unwrap());
        service.create_approval(approval).unwrap();
        let reminders = service.reminders().unwrap();
        assert!(reminders.iter().any(|item| item.kind == "approval_overdue"));

        let job = service.create_job("Backend Engineer", "Product").unwrap();
        let (candidate, application) = service
            .import_candidate(ImportCandidateInput {
                full_name: "Wulan Sari".into(),
                email: None,
                phone: None,
                source: "Referral".into(),
                headline: None,
                job_id: job.id,
                consent: ConsentStatus::Granted,
                document: None,
            })
            .unwrap();
        assert!(service.outbox_pending().unwrap().is_empty());
        let message = service
            .draft_message(
                candidate.id,
                Some(application.id),
                hragents_core::hiring_comms::MessageKind::Interview,
                hragents_core::hiring_comms::MessageChannel::Email,
                Some("Interview".into()),
                "We would like to invite you to interview next week.",
            )
            .unwrap();
        service.reauth("correct horse battery staple").unwrap();
        service.queue_message(message.id).unwrap();
        let pending = service.outbox_pending().unwrap();
        assert_eq!(pending.len(), 1);
        assert_eq!(pending[0].id, message.id);
        let _ = employee;
    }

    #[test]
    fn poll_replies_is_explicit_when_unconfigured() {
        let mut service = service();
        assert!(matches!(
            service.poll_replies(),
            Err(AppError::Domain(DomainError::Validation {
                code: "E_IMAP_NOT_CONFIGURED",
                ..
            }))
        ));
    }

    #[test]
    fn backup_and_search() {
        let mut service = service();
        service.create_employee(employee_input()).unwrap();
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("backup.db");
        assert!(service.backup(&path).unwrap() > 0);
        let hits = service.search("Ayu").unwrap();
        assert_eq!(hits.len(), 1);
        assert_eq!(hits[0].kind, "employee");
    }

    #[cfg(feature = "sqlcipher")]
    #[test]
    fn encrypted_app_database_migrates_and_reopens() {
        let dir = tempfile::tempdir().unwrap();
        let db = dir.path().join("hragents.db");
        let document_id = {
            let mut plain = AppService::open(&db).unwrap();
            plain
                .setup_first_run(SetupInput {
                    company_name: "Nusantara Labs".into(),
                    operator_name: "Rina".into(),
                    username: "rina".into(),
                    password: "correct horse battery staple".into(),
                })
                .unwrap();
            plain
                .upload_document(
                    DocumentOwnerType::Company,
                    "company",
                    "note.txt",
                    "text/plain",
                    b"top secret legacy document".to_vec(),
                )
                .unwrap()
                .id
        };
        assert!(hragents_store::keyfile::is_plaintext_sqlite(&db).unwrap());

        let key = unlock_encrypted_database(dir.path(), &db).unwrap();
        assert!(!hragents_store::keyfile::is_plaintext_sqlite(&db).unwrap());
        assert_eq!(
            unlock_encrypted_database(dir.path(), &db).unwrap(),
            key,
            "the same key file must be reused"
        );

        let mut service = AppService::open_encrypted(&db, &key).unwrap();
        service
            .login("rina", "correct horse battery staple")
            .unwrap();
        assert_eq!(
            service.company_name().unwrap().as_deref(),
            Some("Nusantara Labs")
        );
        assert_eq!(service.store().schema_version().unwrap(), 2);
        assert!(AppService::open_encrypted(&db, "wrong key").is_err());

        assert!(service.recovery_key("wrong password").is_err());
        let exported = service
            .recovery_key("correct horse battery staple")
            .unwrap();
        assert_eq!(exported, key);
        assert!(
            service
                .audit_recent(50)
                .unwrap()
                .iter()
                .any(|entry| entry.action == "security.recovery_key_exported")
        );
        let key_file = dir.path().join("hragents.key");
        let before_rewrap = hragents_store::keyfile::read_key(&key_file).unwrap();
        service
            .rewrap_install_key("correct horse battery staple")
            .unwrap();
        let after_rewrap = hragents_store::keyfile::read_key(&key_file).unwrap();
        assert_eq!(before_rewrap, after_rewrap);
        assert_eq!(after_rewrap, key);
        assert!(
            service
                .audit_recent(50)
                .unwrap()
                .iter()
                .any(|entry| entry.action == "security.key_rewrapped")
        );

        let document_path = service.store().document_path(document_id).unwrap();
        let raw = std::fs::read(&document_path).unwrap();
        assert!(
            !raw.windows(b"top secret".len())
                .any(|window| window == b"top secret"),
            "legacy document was left in plaintext"
        );
        let (_, bytes) = service.read_document(document_id).unwrap();
        assert_eq!(bytes, b"top secret legacy document");

        let set = dir.path().join("full.hrbackup");
        let set_size = service.backup_set(&set).unwrap();
        assert!(set_size > 0);
        let restored_dir = dir.path().join("restored-set");
        let manifest = crate::backup_set::restore(&set, &restored_dir, None).unwrap();
        assert_eq!(manifest.documents, 1);
        assert!(manifest.key_included);
        let mut restored =
            AppService::open_encrypted(restored_dir.join("hragents.db"), &key).unwrap();
        restored
            .login("rina", "correct horse battery staple")
            .unwrap();
        let (_, restored_bytes) = restored.read_document(document_id).unwrap();
        assert_eq!(restored_bytes, b"top secret legacy document");
        assert!(
            crate::backup_set::restore(
                &set,
                &dir.path().join("wrong-key-set"),
                Some("0000000000000000000000000000000000000000000000000000000000000000"),
            )
            .is_err()
        );

        let mut tampered = raw;
        let last = tampered.len() - 1;
        tampered[last] ^= 0x01;
        std::fs::write(&document_path, tampered).unwrap();
        assert!(
            service.read_document(document_id).is_err(),
            "tampered ciphertext must not decrypt"
        );

        let backup = dir.path().join("hragents-backup.db");
        let size = service.backup(&backup).unwrap();
        assert!(size > 0);
        assert!(!hragents_store::keyfile::is_plaintext_sqlite(&backup).unwrap());
        let restored = AppService::open_encrypted(&backup, &key).unwrap();
        assert_eq!(
            restored.company_name().unwrap().as_deref(),
            Some("Nusantara Labs")
        );
    }

    #[test]
    fn audit_export_writes_verifiable_json() {
        let mut service = service();
        service.create_employee(employee_input()).unwrap();
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("audit.json");
        let size = service.export_audit(&path, None).unwrap();
        assert!(
            size > 100,
            "export should have real content, got {size} bytes"
        );
        let raw = std::fs::read_to_string(&path).unwrap();
        let document: serde_json::Value = serde_json::from_str(&raw).unwrap();
        assert!(document.get("chain").is_some());
        assert_eq!(
            document["entries"].as_u64().unwrap(),
            document["chain"].as_array().unwrap().len() as u64
        );
        assert!(
            service
                .audit_recent(20)
                .unwrap()
                .iter()
                .any(|entry| entry.action == "audit.exported")
        );
    }
}
