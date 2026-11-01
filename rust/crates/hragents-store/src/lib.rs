//! SQLite persistence for HRAgents Desktop.
//!
//! One connection owns the database file. Writes are serialized by the caller
//! (a `Mutex<Store>` in the Tauri app), which is the correct concurrency model
//! for a one-machine, one-company HR cockpit. Reads use the same connection;
//! WAL and prepared statements keep them fast without a pool.

use hragents_core::Role;
use hragents_core::approvals::{ApprovalRequest, ApprovalStatus, Priority};
use hragents_core::audit::{AuditActor, AuditChain, AuditEntry, AuditVerification};
use hragents_core::auth::Operator;
use hragents_core::compliance::{ConsentPurpose, ConsentRecord, ConsentState, SubjectType};
use hragents_core::error::DomainError;
use hragents_core::hiring::{
    Application, ApplicationStage, Candidate, ConsentStatus, Evaluation, Job, JobStatus,
};
use hragents_core::ids::*;
use hragents_core::leave::{LeaveBalance, LeaveRequest, LeaveStatus, LeaveType};
use hragents_core::money::Money;
use hragents_core::payroll::{
    PayrollKind, PayrollLine, PayrollRun, PayrollTotals, RateEntry, RateTable, RateTableKind,
    RateTableSet, RunStatus,
};
use hragents_core::people::{
    Contract, ContractKind, ContractStatus, Document, DocumentOwnerType, DocumentStatus, Employee,
    EmploymentStatus, OnboardingPlan, OnboardingStatus, OnboardingStep, StepStatus,
};
use hragents_core::time::{BusinessDate, UtcInstant};
use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
use std::path::{Path, PathBuf};
use std::time::Duration;

const SCHEMA: &str = include_str!("../migrations/0001_init.sql");
const SCHEMA_VERSION: i64 = 1;

#[derive(Debug, thiserror::Error)]
pub enum StoreError {
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Domain(#[from] DomainError),
    #[error("migration failed: {0}")]
    Migration(String),
    #[error("{entity} not found: {id}")]
    NotFound { entity: &'static str, id: String },
    #[error("corrupt row: {0}")]
    Corrupt(String),
    #[error("optimistic concurrency conflict on {entity} {id}")]
    Conflict { entity: &'static str, id: String },
    #[error("backup failed: {0}")]
    Backup(String),
}

impl From<hragents_core::money::MoneyError> for StoreError {
    fn from(value: hragents_core::money::MoneyError) -> Self {
        Self::Domain(DomainError::Money(value))
    }
}

pub type StoreResult<T> = Result<T, StoreError>;

#[derive(Debug)]
pub struct Store {
    conn: Connection,
    path: PathBuf,
}

impl Store {
    pub fn open(path: impl AsRef<Path>) -> StoreResult<Self> {
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|error| StoreError::Migration(format!("create {parent:?}: {error}")))?;
        }
        let conn = Connection::open(&path)?;
        let mut store = Self { conn, path };
        store.configure()?;
        store.migrate()?;
        Ok(store)
    }

    /// Open a SQLCipher-encrypted database. Only available with the
    /// `sqlcipher` feature; release builds must enable it. A plain build returns
    /// an error rather than pretending the file is encrypted.
    #[cfg(feature = "sqlcipher")]
    pub fn open_encrypted(path: impl AsRef<Path>, key: &str) -> StoreResult<Self> {
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|error| StoreError::Migration(format!("create {parent:?}: {error}")))?;
        }
        let conn = Connection::open(&path)?;
        conn.pragma_update(None, "key", key)?;
        let mut store = Self { conn, path };
        store.configure()?;
        store.migrate()?;
        Ok(store)
    }

    #[cfg(not(feature = "sqlcipher"))]
    pub fn open_encrypted(_path: impl AsRef<Path>, _key: &str) -> StoreResult<Self> {
        Err(StoreError::Backup(
            "this build does not include SQLCipher; rebuild with --features sqlcipher".into(),
        ))
    }

    pub fn open_in_memory() -> StoreResult<Self> {
        let conn = Connection::open_in_memory()?;
        let mut store = Self {
            conn,
            path: PathBuf::from(":memory:"),
        };
        store.configure()?;
        store.migrate()?;
        Ok(store)
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    fn configure(&mut self) -> StoreResult<()> {
        let _: String = self
            .conn
            .query_row("PRAGMA journal_mode = WAL", [], |row| row.get(0))?;
        self.conn.execute_batch(
            "PRAGMA foreign_keys = ON;
             PRAGMA synchronous = NORMAL;
             PRAGMA busy_timeout = 5000;
             PRAGMA temp_store = MEMORY;
             PRAGMA cache_size = -64000;
             PRAGMA mmap_size = 268435456;",
        )?;
        Ok(())
    }

    pub fn migrate(&mut self) -> StoreResult<()> {
        let version: i64 = self
            .conn
            .query_row("PRAGMA user_version", [], |row| row.get(0))?;
        if version > SCHEMA_VERSION {
            return Err(StoreError::Migration(format!(
                "database schema {version} is newer than this binary ({SCHEMA_VERSION})"
            )));
        }
        if version == 0 {
            let tx = self
                .conn
                .transaction_with_behavior(TransactionBehavior::Immediate)?;
            tx.execute_batch(SCHEMA)?;
            let now = UtcInstant::now().millis();
            tx.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?1, ?2)",
                params![SCHEMA_VERSION, now],
            )?;
            tx.pragma_update(None, "user_version", SCHEMA_VERSION)?;
            tx.commit()?;
        }
        Ok(())
    }

    pub fn schema_version(&self) -> StoreResult<i64> {
        Ok(self
            .conn
            .query_row("PRAGMA user_version", [], |row| row.get(0))?)
    }

    // ------------------------------------------------------------------
    // Company, operators, settings
    // ------------------------------------------------------------------

    pub fn set_company(
        &mut self,
        legal_name: &str,
        npwp: Option<&str>,
        address: Option<&str>,
        now: UtcInstant,
    ) -> StoreResult<String> {
        let id = CompanyId::new().to_string();
        self.conn.execute(
            "INSERT INTO company (id, legal_name, npwp, address, timezone, currency, created_at)
             VALUES (?1, ?2, ?3, ?4, 'Asia/Jakarta', 'IDR', ?5)
             ON CONFLICT(id) DO UPDATE SET legal_name=excluded.legal_name,
                npwp=excluded.npwp, address=excluded.address",
            params![id, legal_name, npwp, address, now.millis()],
        )?;
        Ok(id)
    }

    pub fn company_name(&self) -> StoreResult<Option<String>> {
        Ok(self
            .conn
            .query_row("SELECT legal_name FROM company LIMIT 1", [], |row| {
                row.get(0)
            })
            .optional()?)
    }

    pub fn insert_operator(&mut self, operator: &Operator) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO operator (id, username, display_name, password_hash, role, active, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![
                operator.id.to_string(),
                operator.username,
                operator.display_name,
                operator.password_hash,
                operator.role.as_str(),
                i64::from(operator.active),
                operator.created_at.millis()
            ],
        )?;
        Ok(())
    }

    pub fn operator_by_username(&self, username: &str) -> StoreResult<Option<Operator>> {
        let row = self
            .conn
            .query_row(
                "SELECT id, username, display_name, password_hash, role, active, created_at
                 FROM operator WHERE username = ?1",
                params![username],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, String>(4)?,
                        row.get::<_, i64>(5)?,
                        row.get::<_, i64>(6)?,
                    ))
                },
            )
            .optional()?;
        row.map(|row| {
            Ok(Operator {
                id: parse_id(&row.0, "operator")?,
                username: row.1,
                display_name: row.2,
                password_hash: row.3,
                role: Role::HrOperator,
                active: row.5 != 0,
                created_at: instant(row.6)?,
            })
        })
        .transpose()
    }

    pub fn list_operators(&self) -> StoreResult<Vec<Operator>> {
        let mut statement = self.conn.prepare(
            "SELECT id, username, display_name, password_hash, role, active, created_at
             FROM operator ORDER BY created_at",
        )?;
        let rows = statement.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, i64>(5)?,
                row.get::<_, i64>(6)?,
            ))
        })?;
        let mut operators = Vec::new();
        for row in rows {
            let row = row?;
            operators.push(Operator {
                id: parse_id(&row.0, "operator")?,
                username: row.1,
                display_name: row.2,
                password_hash: row.3,
                role: Role::HrOperator,
                active: row.4 != 0,
                created_at: instant(row.5)?,
            });
        }
        Ok(operators)
    }

    pub fn operator_count(&self) -> StoreResult<i64> {
        Ok(self
            .conn
            .query_row("SELECT COUNT(*) FROM operator", [], |row| row.get(0))?)
    }

    pub fn set_setting(
        &mut self,
        key: &str,
        value: &serde_json::Value,
        now: UtcInstant,
    ) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?1, ?2, ?3)
             ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            params![key, serde_json::to_string(value)?, now.millis()],
        )?;
        Ok(())
    }

    pub fn setting(&self, key: &str) -> StoreResult<Option<serde_json::Value>> {
        let raw: Option<String> = self
            .conn
            .query_row(
                "SELECT value FROM settings WHERE key = ?1",
                params![key],
                |row| row.get(0),
            )
            .optional()?;
        raw.map(|raw| serde_json::from_str(&raw).map_err(StoreError::from))
            .transpose()
    }

    // ------------------------------------------------------------------
    // Audit chain
    // ------------------------------------------------------------------

    pub fn append_audit(
        &mut self,
        actor: &AuditActor,
        action: &str,
        subject_type: &str,
        subject_id: &str,
        payload: serde_json::Value,
        created_at: UtcInstant,
    ) -> StoreResult<AuditEntry> {
        // Instants persist at millisecond precision. Normalise before hashing,
        // otherwise the in-memory hash covers microseconds the stored row cannot
        // reproduce and every verification after restart fails.
        let created_at = UtcInstant::from_millis(created_at.millis())
            .map_err(|error| StoreError::Corrupt(error.to_string()))?;
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let head: Option<(i64, String)> = tx
            .query_row(
                "SELECT seq, entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?;
        let seq = head.as_ref().map(|(seq, _)| seq + 1).unwrap_or(0);
        let prev_hash = head.map(|(_, hash)| hash);
        let entry_hash = AuditEntry::compute_hash(
            prev_hash.as_deref(),
            actor,
            action,
            subject_type,
            subject_id,
            &payload,
            created_at,
        )?;
        let entry = AuditEntry {
            seq,
            entry_id: AuditId::new(),
            created_at,
            actor: actor.clone(),
            action: action.to_owned(),
            subject_type: subject_type.to_owned(),
            subject_id: subject_id.to_owned(),
            payload: payload.clone(),
            prev_hash: prev_hash.clone(),
            entry_hash: entry_hash.clone(),
        };
        tx.execute(
            "INSERT INTO audit_log
             (seq, entry_id, created_at, actor_json, action, subject_type, subject_id,
              payload_json, prev_hash, entry_hash)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
            params![
                seq,
                entry.entry_id.to_string(),
                created_at.millis(),
                serde_json::to_string(actor)?,
                action,
                subject_type,
                subject_id,
                serde_json::to_string(&payload)?,
                prev_hash,
                entry_hash
            ],
        )?;
        tx.commit()?;
        Ok(entry)
    }

    pub fn audit_entries(&self) -> StoreResult<Vec<AuditEntry>> {
        let mut statement = self.conn.prepare(
            "SELECT seq, entry_id, created_at, actor_json, action, subject_type, subject_id,
                    payload_json, prev_hash, entry_hash
             FROM audit_log ORDER BY seq",
        )?;
        let rows = statement.query_map([], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, String>(6)?,
                row.get::<_, String>(7)?,
                row.get::<_, Option<String>>(8)?,
                row.get::<_, String>(9)?,
            ))
        })?;
        let mut entries = Vec::new();
        for row in rows {
            let row = row?;
            entries.push(AuditEntry {
                seq: row.0,
                entry_id: parse_id(&row.1, "audit_entry")?,
                created_at: instant(row.2)?,
                actor: serde_json::from_str(&row.3).map_err(json_err)?,
                action: row.4,
                subject_type: row.5,
                subject_id: row.6,
                payload: serde_json::from_str(&row.7).map_err(json_err)?,
                prev_hash: row.8,
                entry_hash: row.9,
            });
        }
        Ok(entries)
    }

    pub fn verify_audit(&self) -> StoreResult<AuditVerification> {
        let chain = AuditChain::from_entries(self.audit_entries()?)
            .map_err(|error| StoreError::Corrupt(error.to_string()))?;
        chain
            .verify()
            .map_err(|error| StoreError::Corrupt(error.to_string()))
    }

    pub fn audit_head(&self) -> StoreResult<Option<String>> {
        Ok(self
            .conn
            .query_row(
                "SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1",
                [],
                |row| row.get(0),
            )
            .optional()?)
    }

    // ------------------------------------------------------------------
    // Employees and contracts
    // ------------------------------------------------------------------

    pub fn save_employee(&mut self, employee: &Employee) -> StoreResult<()> {
        employee.validate()?;
        let changed = self.conn.execute(
            "INSERT INTO employees
             (id, employee_no, full_name, preferred_name, email, phone, job_title, org_unit,
              manager_id, status, hire_date, end_date, birth_date, ptkp_status, dependents,
              jkk_risk_class, npwp, bank_name, bank_account, bpjs_kesehatan_no,
              bpjs_ketenagakerjaan_no, created_at, updated_at, version)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,?20,?21,?22,?23,?24)
             ON CONFLICT(id) DO UPDATE SET
                employee_no=excluded.employee_no, full_name=excluded.full_name,
                preferred_name=excluded.preferred_name, email=excluded.email, phone=excluded.phone,
                job_title=excluded.job_title, org_unit=excluded.org_unit, manager_id=excluded.manager_id,
                status=excluded.status, hire_date=excluded.hire_date, end_date=excluded.end_date,
                birth_date=excluded.birth_date, ptkp_status=excluded.ptkp_status,
                dependents=excluded.dependents, jkk_risk_class=excluded.jkk_risk_class,
                npwp=excluded.npwp, bank_name=excluded.bank_name, bank_account=excluded.bank_account,
                bpjs_kesehatan_no=excluded.bpjs_kesehatan_no,
                bpjs_ketenagakerjaan_no=excluded.bpjs_ketenagakerjaan_no,
                updated_at=excluded.updated_at, version=excluded.version
             WHERE employees.version + 1 = excluded.version",
            params![
                employee.id.to_string(),
                employee.employee_no,
                employee.full_name,
                employee.preferred_name,
                employee.email,
                employee.phone,
                employee.job_title,
                employee.org_unit,
                employee.manager_id.map(|id| id.to_string()),
                employee.status.as_str(),
                employee.hire_date.to_string(),
                employee.end_date.map(|date| date.to_string()),
                employee.birth_date.map(|date| date.to_string()),
                employee.ptkp_status,
                employee.dependents,
                employee.jkk_risk_class,
                employee.npwp,
                employee.bank_name,
                employee.bank_account,
                employee.bpjs_kesehatan_no,
                employee.bpjs_ketenagakerjaan_no,
                employee.created_at.millis(),
                employee.updated_at.millis(),
                employee.version,
            ],
        )?;
        if changed == 0 {
            return Err(StoreError::Conflict {
                entity: "employee",
                id: employee.id.to_string(),
            });
        }
        Ok(())
    }

    pub fn employee(&self, id: EmployeeId) -> StoreResult<Employee> {
        let row = self
            .conn
            .query_row(
                "SELECT id, employee_no, full_name, preferred_name, email, phone, job_title,
                        org_unit, manager_id, status, hire_date, end_date, birth_date, ptkp_status,
                        dependents, jkk_risk_class, npwp, bank_name, bank_account,
                        bpjs_kesehatan_no, bpjs_ketenagakerjaan_no, created_at, updated_at, version
                 FROM employees WHERE id = ?1",
                params![id.to_string()],
                employee_row,
            )
            .optional()?;
        row.ok_or_else(|| StoreError::NotFound {
            entity: "employee",
            id: id.to_string(),
        })
    }

    pub fn employee_by_no(&self, employee_no: &str) -> StoreResult<Option<Employee>> {
        self.conn
            .query_row(
                "SELECT id, employee_no, full_name, preferred_name, email, phone, job_title,
                        org_unit, manager_id, status, hire_date, end_date, birth_date, ptkp_status,
                        dependents, jkk_risk_class, npwp, bank_name, bank_account,
                        bpjs_kesehatan_no, bpjs_ketenagakerjaan_no, created_at, updated_at, version
                 FROM employees WHERE employee_no = ?1",
                params![employee_no],
                employee_row,
            )
            .optional()
            .map_err(StoreError::from)
    }

    pub fn list_employees(&self) -> StoreResult<Vec<Employee>> {
        let mut statement = self
            .conn
            .prepare("SELECT id, employee_no, full_name, preferred_name, email, phone, job_title, org_unit, manager_id, status, hire_date, end_date, birth_date, ptkp_status, dependents, jkk_risk_class, npwp, bank_name, bank_account, bpjs_kesehatan_no, bpjs_ketenagakerjaan_no, created_at, updated_at, version FROM employees ORDER BY full_name")?;
        let rows = statement.query_map([], employee_row)?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn search_employees(&self, query: &str, limit: usize) -> StoreResult<Vec<Employee>> {
        let fts = fts_query(query);
        if fts.is_empty() {
            return Ok(Vec::new());
        }
        let mut statement = self.conn.prepare(
            "SELECT e.id, e.employee_no, e.full_name, e.preferred_name, e.email, e.phone,
                    e.job_title, e.org_unit, e.manager_id, e.status, e.hire_date, e.end_date,
                    e.birth_date, e.ptkp_status, e.dependents, e.jkk_risk_class, e.npwp,
                    e.bank_name, e.bank_account, e.bpjs_kesehatan_no, e.bpjs_ketenagakerjaan_no,
                    e.created_at, e.updated_at, e.version
             FROM employees_fts f JOIN employees e ON e.rowid = f.rowid
             WHERE employees_fts MATCH ?1
             ORDER BY bm25(employees_fts) LIMIT ?2",
        )?;
        let rows = statement.query_map(params![fts, limit as i64], employee_row)?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn save_contract(&mut self, contract: &Contract) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO contracts (id, employee_id, kind, start_date, end_date, status, document_id, created_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8)
             ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, start_date=excluded.start_date,
                end_date=excluded.end_date, status=excluded.status, document_id=excluded.document_id",
            params![
                contract.id.to_string(),
                contract.employee_id.to_string(),
                contract_kind(contract.kind),
                contract.start_date.to_string(),
                contract.end_date.map(|date| date.to_string()),
                contract_status(contract.status),
                contract.document_id.map(|id| id.to_string()),
                contract.created_at.millis(),
            ],
        )?;
        Ok(())
    }

    // ------------------------------------------------------------------
    // Onboarding
    // ------------------------------------------------------------------

    pub fn save_onboarding_plan(&mut self, plan: &OnboardingPlan) -> StoreResult<()> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        tx.execute(
            "INSERT INTO onboarding_plans (id, employee_id, template_name, status, created_at, completed_at)
             VALUES (?1,?2,?3,?4,?5,?6)
             ON CONFLICT(id) DO UPDATE SET template_name=excluded.template_name,
                status=excluded.status, completed_at=excluded.completed_at",
            params![
                plan.id.to_string(),
                plan.employee_id.to_string(),
                plan.template_name,
                onboarding_status(plan.status),
                plan.created_at.millis(),
                plan.completed_at.map(|instant| instant.millis()),
            ],
        )?;
        for (position, step) in plan.steps.iter().enumerate() {
            tx.execute(
                "INSERT INTO onboarding_steps
                 (plan_id, step_key, title, category, required, status, due_date, completed_at,
                  completed_by, document_request_id, notes, position)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12)
                 ON CONFLICT(plan_id, step_key) DO UPDATE SET title=excluded.title,
                    category=excluded.category, required=excluded.required, status=excluded.status,
                    due_date=excluded.due_date, completed_at=excluded.completed_at,
                    completed_by=excluded.completed_by,
                    document_request_id=excluded.document_request_id, notes=excluded.notes,
                    position=excluded.position",
                params![
                    plan.id.to_string(),
                    step.key,
                    step.title,
                    step.category,
                    i64::from(step.required),
                    step_status(step.status),
                    step.due_date.map(|date| date.to_string()),
                    step.completed_at.map(|instant| instant.millis()),
                    step.completed_by,
                    step.document_request_id,
                    step.notes,
                    position as i64,
                ],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn onboarding_plan_for(
        &self,
        employee_id: EmployeeId,
    ) -> StoreResult<Option<OnboardingPlan>> {
        let plan = self
            .conn
            .query_row(
                "SELECT id, employee_id, template_name, status, created_at, completed_at
                 FROM onboarding_plans WHERE employee_id = ?1 ORDER BY created_at DESC LIMIT 1",
                params![employee_id.to_string()],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, i64>(4)?,
                        row.get::<_, Option<i64>>(5)?,
                    ))
                },
            )
            .optional()?;
        let Some((id, employee_id, template_name, status, created_at, completed_at)) = plan else {
            return Ok(None);
        };
        let mut statement = self.conn.prepare(
            "SELECT step_key, title, category, required, status, due_date, completed_at,
                    completed_by, document_request_id, notes
             FROM onboarding_steps WHERE plan_id = ?1 ORDER BY position",
        )?;
        let rows = statement.query_map(params![id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, i64>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, Option<String>>(5)?,
                row.get::<_, Option<i64>>(6)?,
                row.get::<_, Option<String>>(7)?,
                row.get::<_, Option<String>>(8)?,
                row.get::<_, Option<String>>(9)?,
            ))
        })?;
        let mut steps = Vec::new();
        for row in rows {
            let row = row?;
            steps.push(OnboardingStep {
                key: row.0,
                title: row.1,
                category: row.2,
                required: row.3 != 0,
                status: parse_step_status(&row.4)?,
                due_date: row.5.as_deref().map(parse_date).transpose()?,
                completed_at: row.6.map(instant).transpose()?,
                completed_by: row.7,
                document_request_id: row.8,
                notes: row.9,
            });
        }
        Ok(Some(OnboardingPlan {
            id: parse_id(&id, "onboarding_plan")?,
            employee_id: parse_id(&employee_id, "employee")?,
            template_name,
            status: parse_onboarding_status(&status)?,
            steps,
            created_at: instant(created_at)?,
            completed_at: completed_at.map(instant).transpose()?,
        }))
    }

    // ------------------------------------------------------------------
    // Documents
    // ------------------------------------------------------------------

    pub fn save_document(&mut self, document: &Document, storage_path: &str) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO documents
             (id, owner_type, owner_id, filename, mime_type, sha256, size_bytes, storage_path,
              status, expires_on, uploaded_at, verified_at, verified_by, rejection_reason, tags_json)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15)
             ON CONFLICT(id) DO UPDATE SET status=excluded.status, expires_on=excluded.expires_on,
                verified_at=excluded.verified_at, verified_by=excluded.verified_by,
                rejection_reason=excluded.rejection_reason, tags_json=excluded.tags_json,
                storage_path=excluded.storage_path",
            params![
                document.id.to_string(),
                owner_type(document.owner_type),
                document.owner_id,
                document.filename,
                document.mime_type,
                document.sha256,
                document.size_bytes,
                storage_path,
                document_status(document.status),
                document.expires_on.map(|date| date.to_string()),
                document.uploaded_at.millis(),
                document.verified_at.map(|instant| instant.millis()),
                document.verified_by,
                document.rejection_reason,
                serde_json::to_string(&document.tags)?,
            ],
        )?;
        Ok(())
    }

    pub fn document(&self, id: DocumentId) -> StoreResult<Document> {
        let mut document = self
            .conn
            .query_row(
                "SELECT id, owner_type, owner_id, filename, mime_type, sha256, size_bytes, status,
                        expires_on, uploaded_at, verified_at, verified_by, rejection_reason, tags_json
                 FROM documents WHERE id = ?1",
                params![id.to_string()],
                |row| {
                    Ok(Document {
                        id: parse_id(&row.get::<_, String>(0)?, "document")?,
                        owner_type: parse_owner_type(&row.get::<_, String>(1)?)?,
                        owner_id: row.get(2)?,
                        filename: row.get(3)?,
                        mime_type: row.get(4)?,
                        sha256: row.get(5)?,
                        size_bytes: row.get(6)?,
                        status: parse_document_status(&row.get::<_, String>(7)?)?,
                        expires_on: row.get::<_, Option<String>>(8)?.as_deref().map(parse_date).transpose()?,
                        uploaded_at: instant(row.get(9)?)?,
                        verified_at: row.get::<_, Option<i64>>(10)?.map(instant).transpose()?,
                        verified_by: row.get(11)?,
                        rejection_reason: row.get(12)?,
                        tags: serde_json::from_str(&row.get::<_, String>(13)?).map_err(json_err)?,
                    })
                },
            )
            .optional()?;
        document.take().ok_or_else(|| StoreError::NotFound {
            entity: "document",
            id: id.to_string(),
        })
    }

    pub fn document_path(&self, id: DocumentId) -> StoreResult<String> {
        self.conn
            .query_row(
                "SELECT storage_path FROM documents WHERE id = ?1",
                params![id.to_string()],
                |row| row.get(0),
            )
            .optional()?
            .ok_or_else(|| StoreError::NotFound {
                entity: "document",
                id: id.to_string(),
            })
    }

    // ------------------------------------------------------------------
    // Hiring
    // ------------------------------------------------------------------

    pub fn save_job(&mut self, job: &Job) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO jobs (id, title, org_unit, location, employment_type, status, openings, rubric_json, created_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)
             ON CONFLICT(id) DO UPDATE SET title=excluded.title, org_unit=excluded.org_unit,
                location=excluded.location, employment_type=excluded.employment_type,
                status=excluded.status, openings=excluded.openings, rubric_json=excluded.rubric_json",
            params![
                job.id.to_string(),
                job.title,
                job.org_unit,
                job.location,
                job.employment_type,
                job_status(job.status),
                job.openings,
                job.rubric_id,
                job.created_at.millis(),
            ],
        )?;
        Ok(())
    }

    pub fn job(&self, id: JobId) -> StoreResult<Job> {
        self.conn
            .query_row(
                "SELECT id, title, org_unit, location, employment_type, status, openings, rubric_json, created_at
                 FROM jobs WHERE id = ?1",
                params![id.to_string()],
                |row| {
                    Ok(Job {
                        id: parse_id(&row.get::<_, String>(0)?, "job")?,
                        title: row.get(1)?,
                        org_unit: row.get(2)?,
                        location: row.get(3)?,
                        employment_type: row.get(4)?,
                        status: parse_job_status(&row.get::<_, String>(5)?)?,
                        openings: row.get::<_, i64>(6)? as u16,
                        rubric_id: row.get(7)?,
                        created_at: instant(row.get(8)?)?,
                    })
                },
            )
            .optional()?
            .ok_or_else(|| StoreError::NotFound { entity: "job", id: id.to_string() })
    }

    pub fn list_jobs(&self) -> StoreResult<Vec<Job>> {
        let mut statement = self.conn.prepare(
            "SELECT id, title, org_unit, location, employment_type, status, openings, rubric_json, created_at
             FROM jobs ORDER BY created_at DESC",
        )?;
        let rows = statement.query_map([], |row| {
            Ok(Job {
                id: parse_id(&row.get::<_, String>(0)?, "job")?,
                title: row.get(1)?,
                org_unit: row.get(2)?,
                location: row.get(3)?,
                employment_type: row.get(4)?,
                status: parse_job_status(&row.get::<_, String>(5)?)?,
                openings: row.get::<_, i64>(6)? as u16,
                rubric_id: row.get(7)?,
                created_at: instant(row.get(8)?)?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn save_candidate(&mut self, candidate: &Candidate) -> StoreResult<()> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        tx.execute(
            "INSERT INTO candidates (id, full_name, email, phone, source, headline, location, consent, created_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)
             ON CONFLICT(id) DO UPDATE SET full_name=excluded.full_name, email=excluded.email,
                phone=excluded.phone, source=excluded.source, headline=excluded.headline,
                location=excluded.location, consent=excluded.consent",
            params![
                candidate.id.to_string(),
                candidate.full_name,
                candidate.email,
                candidate.phone,
                candidate.source,
                candidate.headline,
                candidate.location,
                consent_status(candidate.consent),
                candidate.created_at.millis(),
            ],
        )?;
        tx.execute(
            "DELETE FROM candidate_documents WHERE candidate_id = ?1",
            params![candidate.id.to_string()],
        )?;
        for document_id in &candidate.document_ids {
            tx.execute(
                "INSERT OR IGNORE INTO candidate_documents (candidate_id, document_id) VALUES (?1,?2)",
                params![candidate.id.to_string(), document_id.to_string()],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn candidate(&self, id: CandidateId) -> StoreResult<Candidate> {
        let row = self
            .conn
            .query_row(
                "SELECT id, full_name, email, phone, source, headline, location, consent, created_at
                 FROM candidates WHERE id = ?1",
                params![id.to_string()],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, Option<String>>(2)?,
                        row.get::<_, Option<String>>(3)?,
                        row.get::<_, String>(4)?,
                        row.get::<_, Option<String>>(5)?,
                        row.get::<_, Option<String>>(6)?,
                        row.get::<_, String>(7)?,
                        row.get::<_, i64>(8)?,
                    ))
                },
            )
            .optional()?
            .ok_or_else(|| StoreError::NotFound { entity: "candidate", id: id.to_string() })?;
        let mut document_statement = self.conn.prepare(
            "SELECT document_id FROM candidate_documents WHERE candidate_id = ?1 ORDER BY document_id",
        )?;
        let raw_documents = document_statement
            .query_map(params![id.to_string()], |row| row.get::<_, String>(0))?
            .collect::<Result<Vec<_>, _>>()?;
        let document_ids = raw_documents
            .into_iter()
            .map(|raw| parse_id(&raw, "document"))
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(Candidate {
            id: parse_id(&row.0, "candidate")?,
            full_name: row.1,
            email: row.2,
            phone: row.3,
            source: row.4,
            headline: row.5,
            location: row.6,
            consent: parse_consent(&row.7)?,
            document_ids,
            created_at: instant(row.8)?,
        })
    }

    pub fn list_candidates(&self) -> StoreResult<Vec<Candidate>> {
        let mut statement = self.conn.prepare(
            "SELECT id, full_name, email, phone, source, headline, location, consent, created_at
             FROM candidates ORDER BY created_at DESC",
        )?;
        let rows = statement.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, Option<String>>(2)?,
                row.get::<_, Option<String>>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, Option<String>>(5)?,
                row.get::<_, Option<String>>(6)?,
                row.get::<_, String>(7)?,
                row.get::<_, i64>(8)?,
            ))
        })?;
        let mut candidates = Vec::new();
        for row in rows {
            let row = row?;
            candidates.push(Candidate {
                id: parse_id(&row.0, "candidate")?,
                full_name: row.1,
                email: row.2,
                phone: row.3,
                source: row.4,
                headline: row.5,
                location: row.6,
                consent: parse_consent(&row.7)?,
                document_ids: Vec::new(),
                created_at: instant(row.8)?,
            });
        }
        Ok(candidates)
    }

    pub fn search_candidates(&self, query: &str, limit: usize) -> StoreResult<Vec<Candidate>> {
        let fts = fts_query(query);
        if fts.is_empty() {
            return Ok(Vec::new());
        }
        let mut statement = self.conn.prepare(
            "SELECT c.id, c.full_name, c.email, c.phone, c.source, c.headline, c.location, c.consent, c.created_at
             FROM candidates_fts f JOIN candidates c ON c.rowid = f.rowid
             WHERE candidates_fts MATCH ?1 ORDER BY bm25(candidates_fts) LIMIT ?2",
        )?;
        let rows = statement.query_map(params![fts, limit as i64], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, Option<String>>(2)?,
                row.get::<_, Option<String>>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, Option<String>>(5)?,
                row.get::<_, Option<String>>(6)?,
                row.get::<_, String>(7)?,
                row.get::<_, i64>(8)?,
            ))
        })?;
        let mut candidates = Vec::new();
        for row in rows {
            let row = row?;
            candidates.push(Candidate {
                id: parse_id(&row.0, "candidate")?,
                full_name: row.1,
                email: row.2,
                phone: row.3,
                source: row.4,
                headline: row.5,
                location: row.6,
                consent: parse_consent(&row.7)?,
                document_ids: Vec::new(),
                created_at: instant(row.8)?,
            });
        }
        Ok(candidates)
    }

    pub fn save_application(&mut self, application: &Application) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO applications (id, candidate_id, job_id, stage, priority, created_at, updated_at, rejection_reason, rejected_by)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)
             ON CONFLICT(id) DO UPDATE SET stage=excluded.stage, priority=excluded.priority,
                updated_at=excluded.updated_at, rejection_reason=excluded.rejection_reason,
                rejected_by=excluded.rejected_by",
            params![
                application.id.to_string(),
                application.candidate_id.to_string(),
                application.job_id.to_string(),
                application.stage.as_str(),
                application.priority,
                application.created_at.millis(),
                application.updated_at.millis(),
                application.rejection_reason,
                application.rejected_by.map(|id| id.to_string()),
            ],
        )?;
        Ok(())
    }

    pub fn application(&self, id: ApplicationId) -> StoreResult<Application> {
        self.conn
            .query_row(
                "SELECT id, candidate_id, job_id, stage, priority, created_at, updated_at, rejection_reason, rejected_by
                 FROM applications WHERE id = ?1",
                params![id.to_string()],
                application_row,
            )
            .optional()?
            .ok_or_else(|| StoreError::NotFound { entity: "application", id: id.to_string() })
    }

    pub fn list_applications(&self, job_id: Option<JobId>) -> StoreResult<Vec<Application>> {
        let mut applications = Vec::new();
        match job_id {
            Some(job_id) => {
                let mut statement = self.conn.prepare(
                    "SELECT id, candidate_id, job_id, stage, priority, created_at, updated_at, rejection_reason, rejected_by
                     FROM applications WHERE job_id = ?1 ORDER BY priority DESC, created_at",
                )?;
                let rows = statement.query_map(params![job_id.to_string()], application_row)?;
                for row in rows {
                    applications.push(row?);
                }
            }
            None => {
                let mut statement = self.conn.prepare(
                    "SELECT id, candidate_id, job_id, stage, priority, created_at, updated_at, rejection_reason, rejected_by
                     FROM applications ORDER BY priority DESC, created_at",
                )?;
                let rows = statement.query_map([], application_row)?;
                for row in rows {
                    applications.push(row?);
                }
            }
        }
        Ok(applications)
    }

    pub fn save_evaluation(&mut self, evaluation: &Evaluation) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO evaluations
             (id, application_id, rubric_id, dimension_scores_json, overall_bp, sigma_bp, runs,
              evidence_json, flags_json, created_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)
             ON CONFLICT(id) DO UPDATE SET dimension_scores_json=excluded.dimension_scores_json,
                overall_bp=excluded.overall_bp, sigma_bp=excluded.sigma_bp, runs=excluded.runs,
                evidence_json=excluded.evidence_json, flags_json=excluded.flags_json",
            params![
                evaluation.id.to_string(),
                evaluation.application_id.to_string(),
                evaluation.rubric_id,
                serde_json::to_string(&evaluation.dimension_scores)?,
                evaluation.overall_bp,
                evaluation.sigma_bp,
                evaluation.runs as i64,
                serde_json::to_string(&evaluation.evidence)?,
                serde_json::to_string(&evaluation.flags)?,
                evaluation.created_at.millis(),
            ],
        )?;
        Ok(())
    }

    pub fn evaluation_for(&self, application_id: ApplicationId) -> StoreResult<Option<Evaluation>> {
        self.conn
            .query_row(
                "SELECT id, application_id, rubric_id, dimension_scores_json, overall_bp, sigma_bp,
                        runs, evidence_json, flags_json, created_at
                 FROM evaluations WHERE application_id = ?1 ORDER BY created_at DESC LIMIT 1",
                params![application_id.to_string()],
                |row| {
                    Ok(Evaluation {
                        id: parse_id(&row.get::<_, String>(0)?, "evaluation")?,
                        application_id: parse_id(&row.get::<_, String>(1)?, "application")?,
                        rubric_id: row.get(2)?,
                        dimension_scores: serde_json::from_str(&row.get::<_, String>(3)?)
                            .map_err(json_err)?,
                        overall_bp: row.get(4)?,
                        sigma_bp: row.get(5)?,
                        runs: row.get::<_, i64>(6)? as usize,
                        evidence: serde_json::from_str(&row.get::<_, String>(7)?)
                            .map_err(json_err)?,
                        flags: serde_json::from_str(&row.get::<_, String>(8)?).map_err(json_err)?,
                        created_at: instant(row.get(9)?)?,
                    })
                },
            )
            .optional()
            .map_err(StoreError::from)
    }

    // ------------------------------------------------------------------
    // Leave
    // ------------------------------------------------------------------

    pub fn save_leave_type(&mut self, leave_type: &LeaveType) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO leave_types (id, name, annual_quota_x2, carry_over_max_x2, requires_attachment, active)
             VALUES (?1,?2,?3,?4,?5,?6)
             ON CONFLICT(id) DO UPDATE SET name=excluded.name, annual_quota_x2=excluded.annual_quota_x2,
                carry_over_max_x2=excluded.carry_over_max_x2,
                requires_attachment=excluded.requires_attachment, active=excluded.active",
            params![
                leave_type.id.to_string(),
                leave_type.name,
                leave_type.annual_quota_x2,
                leave_type.carry_over_max_x2,
                i64::from(leave_type.requires_attachment),
                i64::from(leave_type.active),
            ],
        )?;
        Ok(())
    }

    pub fn list_leave_types(&self) -> StoreResult<Vec<LeaveType>> {
        let mut statement = self.conn.prepare(
            "SELECT id, name, annual_quota_x2, carry_over_max_x2, requires_attachment, active
             FROM leave_types WHERE active = 1 ORDER BY name",
        )?;
        let rows = statement.query_map([], |row| {
            Ok(LeaveType {
                id: parse_id(&row.get::<_, String>(0)?, "leave_type")?,
                name: row.get(1)?,
                annual_quota_x2: row.get(2)?,
                carry_over_max_x2: row.get(3)?,
                requires_attachment: row.get::<_, i64>(4)? != 0,
                active: row.get::<_, i64>(5)? != 0,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn save_leave_balance(&mut self, balance: &LeaveBalance) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO leave_balances
             (employee_id, leave_type_id, year, entitled_x2, adjustment_x2, used_x2, pending_x2)
             VALUES (?1,?2,?3,?4,?5,?6,?7)
             ON CONFLICT(employee_id, leave_type_id, year) DO UPDATE SET
                entitled_x2=excluded.entitled_x2, adjustment_x2=excluded.adjustment_x2,
                used_x2=excluded.used_x2, pending_x2=excluded.pending_x2",
            params![
                balance.employee_id.to_string(),
                balance.leave_type_id.to_string(),
                balance.year,
                balance.entitled_x2,
                balance.adjustment_x2,
                balance.used_x2,
                balance.pending_x2,
            ],
        )?;
        Ok(())
    }

    pub fn leave_balance(
        &self,
        employee_id: EmployeeId,
        leave_type_id: LeaveTypeId,
        year: i32,
    ) -> StoreResult<Option<LeaveBalance>> {
        self.conn
            .query_row(
                "SELECT employee_id, leave_type_id, year, entitled_x2, adjustment_x2, used_x2, pending_x2
                 FROM leave_balances WHERE employee_id=?1 AND leave_type_id=?2 AND year=?3",
                params![employee_id.to_string(), leave_type_id.to_string(), year],
                |row| {
                    Ok(LeaveBalance {
                        employee_id: parse_id(&row.get::<_, String>(0)?, "employee")?,
                        leave_type_id: parse_id(&row.get::<_, String>(1)?, "leave_type")?,
                        year: row.get(2)?,
                        entitled_x2: row.get(3)?,
                        adjustment_x2: row.get(4)?,
                        used_x2: row.get(5)?,
                        pending_x2: row.get(6)?,
                    })
                },
            )
            .optional()
            .map_err(StoreError::from)
    }

    pub fn list_leave_balances(&self, year: i32) -> StoreResult<Vec<LeaveBalance>> {
        let mut statement = self.conn.prepare(
            "SELECT employee_id, leave_type_id, year, entitled_x2, adjustment_x2, used_x2, pending_x2
             FROM leave_balances WHERE year = ?1 ORDER BY employee_id",
        )?;
        let rows = statement.query_map(params![year], |row| {
            Ok(LeaveBalance {
                employee_id: parse_id(&row.get::<_, String>(0)?, "employee")?,
                leave_type_id: parse_id(&row.get::<_, String>(1)?, "leave_type")?,
                year: row.get(2)?,
                entitled_x2: row.get(3)?,
                adjustment_x2: row.get(4)?,
                used_x2: row.get(5)?,
                pending_x2: row.get(6)?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn save_leave_request(&mut self, request: &LeaveRequest) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO leave_requests
             (id, employee_id, leave_type_id, start_date, end_date, days_x2, half_day_start,
              half_day_end, reason, status, recorded_by, decided_by, decided_at, decision_note,
              attachment_document_id, created_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16)
             ON CONFLICT(id) DO UPDATE SET status=excluded.status, decided_by=excluded.decided_by,
                decided_at=excluded.decided_at, decision_note=excluded.decision_note,
                attachment_document_id=excluded.attachment_document_id",
            params![
                request.id.to_string(),
                request.employee_id.to_string(),
                request.leave_type_id.to_string(),
                request.start_date.to_string(),
                request.end_date.to_string(),
                request.days_x2,
                i64::from(request.half_day_start),
                i64::from(request.half_day_end),
                request.reason,
                leave_status(request.status),
                request.recorded_by.to_string(),
                request.decided_by.map(|id| id.to_string()),
                request.decided_at.map(|instant| instant.millis()),
                request.decision_note,
                request.attachment_document_id,
                request.created_at.millis(),
            ],
        )?;
        Ok(())
    }

    /// Balance and request move together: a crash between the two writes would
    /// leave days reserved without a request, or a request without its hold.
    pub fn save_balance_and_request(
        &mut self,
        balance: &LeaveBalance,
        request: &LeaveRequest,
    ) -> StoreResult<()> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        tx.execute(
            "INSERT INTO leave_balances
             (employee_id, leave_type_id, year, entitled_x2, adjustment_x2, used_x2, pending_x2)
             VALUES (?1,?2,?3,?4,?5,?6,?7)
             ON CONFLICT(employee_id, leave_type_id, year) DO UPDATE SET
                entitled_x2=excluded.entitled_x2, adjustment_x2=excluded.adjustment_x2,
                used_x2=excluded.used_x2, pending_x2=excluded.pending_x2",
            params![
                balance.employee_id.to_string(),
                balance.leave_type_id.to_string(),
                balance.year,
                balance.entitled_x2,
                balance.adjustment_x2,
                balance.used_x2,
                balance.pending_x2,
            ],
        )?;
        tx.execute(
            "INSERT INTO leave_requests
             (id, employee_id, leave_type_id, start_date, end_date, days_x2, half_day_start,
              half_day_end, reason, status, recorded_by, decided_by, decided_at, decision_note,
              attachment_document_id, created_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16)
             ON CONFLICT(id) DO UPDATE SET status=excluded.status, decided_by=excluded.decided_by,
                decided_at=excluded.decided_at, decision_note=excluded.decision_note,
                attachment_document_id=excluded.attachment_document_id",
            params![
                request.id.to_string(),
                request.employee_id.to_string(),
                request.leave_type_id.to_string(),
                request.start_date.to_string(),
                request.end_date.to_string(),
                request.days_x2,
                i64::from(request.half_day_start),
                i64::from(request.half_day_end),
                request.reason,
                leave_status(request.status),
                request.recorded_by.to_string(),
                request.decided_by.map(|id| id.to_string()),
                request.decided_at.map(|instant| instant.millis()),
                request.decision_note,
                request.attachment_document_id,
                request.created_at.millis(),
            ],
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn leave_request(&self, id: LeaveRequestId) -> StoreResult<LeaveRequest> {
        self.conn
            .query_row(
                "SELECT id, employee_id, leave_type_id, start_date, end_date, days_x2,
                        half_day_start, half_day_end, reason, status, recorded_by, decided_by,
                        decided_at, decision_note, attachment_document_id, created_at
                 FROM leave_requests WHERE id = ?1",
                params![id.to_string()],
                leave_request_row,
            )
            .optional()?
            .ok_or_else(|| StoreError::NotFound {
                entity: "leave_request",
                id: id.to_string(),
            })
    }

    pub fn list_leave_requests(
        &self,
        status: Option<LeaveStatus>,
    ) -> StoreResult<Vec<LeaveRequest>> {
        let mut requests = Vec::new();
        match status {
            Some(status) => {
                let mut statement = self.conn.prepare(
                    "SELECT id, employee_id, leave_type_id, start_date, end_date, days_x2,
                            half_day_start, half_day_end, reason, status, recorded_by, decided_by,
                            decided_at, decision_note, attachment_document_id, created_at
                     FROM leave_requests WHERE status = ?1 ORDER BY start_date",
                )?;
                let rows = statement.query_map(params![leave_status(status)], leave_request_row)?;
                for row in rows {
                    requests.push(row?);
                }
            }
            None => {
                let mut statement = self.conn.prepare(
                    "SELECT id, employee_id, leave_type_id, start_date, end_date, days_x2,
                            half_day_start, half_day_end, reason, status, recorded_by, decided_by,
                            decided_at, decision_note, attachment_document_id, created_at
                     FROM leave_requests ORDER BY start_date DESC",
                )?;
                let rows = statement.query_map([], leave_request_row)?;
                for row in rows {
                    requests.push(row?);
                }
            }
        }
        Ok(requests)
    }

    // ------------------------------------------------------------------
    // Payroll and rate tables
    // ------------------------------------------------------------------

    pub fn save_rate_table(&mut self, table: &RateTable) -> StoreResult<()> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        tx.execute(
            "INSERT INTO rate_tables
             (id, kind, effective_from, effective_to, verified, verified_by, verified_at, source_note)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8)
             ON CONFLICT(kind, effective_from) DO UPDATE SET effective_to=excluded.effective_to,
                verified=excluded.verified, verified_by=excluded.verified_by,
                verified_at=excluded.verified_at, source_note=excluded.source_note",
            params![
                table.id.to_string(),
                table.kind.as_str(),
                table.effective_from.to_string(),
                table.effective_to.map(|date| date.to_string()),
                i64::from(table.verified),
                table.verified_by,
                table.verified_at.map(|instant| instant.millis()),
                table.source_note,
            ],
        )?;
        let stored_id: String = tx.query_row(
            "SELECT id FROM rate_tables WHERE kind=?1 AND effective_from=?2",
            params![table.kind.as_str(), table.effective_from.to_string()],
            |row| row.get(0),
        )?;
        tx.execute(
            "DELETE FROM rate_entries WHERE table_id = ?1",
            params![stored_id],
        )?;
        for (position, entry) in table.entries.iter().enumerate() {
            tx.execute(
                "INSERT INTO rate_entries
                 (table_id, position, entry_key, employee_share_bp, employer_share_bp, wage_cap_sen,
                  flat_amount_sen, multiplier_bp, lower_bound_sen, upper_bound_sen, hours_per_month, note)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12)",
                params![
                    stored_id,
                    position as i64,
                    entry.key,
                    entry.employee_share_bp,
                    entry.employer_share_bp,
                    entry.wage_cap.map(|money| money.sen()),
                    entry.flat_amount.map(|money| money.sen()),
                    entry.multiplier_bp,
                    entry.lower_bound.map(|money| money.sen()),
                    entry.upper_bound.map(|money| money.sen()),
                    entry.hours_per_month,
                    entry.note,
                ],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn rate_tables(&self, on: BusinessDate) -> StoreResult<RateTableSet> {
        let mut statement = self.conn.prepare(
            "SELECT id, kind, effective_from, effective_to, verified, verified_by, verified_at, source_note
             FROM rate_tables
             WHERE effective_from <= ?1 AND (effective_to IS NULL OR effective_to >= ?1)
             ORDER BY effective_from DESC",
        )?;
        let rows = statement.query_map(params![on.to_string()], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, Option<String>>(3)?,
                row.get::<_, i64>(4)?,
                row.get::<_, Option<String>>(5)?,
                row.get::<_, Option<i64>>(6)?,
                row.get::<_, Option<String>>(7)?,
            ))
        })?;
        let mut set = RateTableSet::default();
        let mut seen = std::collections::BTreeSet::new();
        for row in rows {
            let row = row?;
            let kind = parse_rate_kind(&row.1)?;
            if !seen.insert(kind) {
                continue;
            }
            let entries = self.rate_entries(&row.0)?;
            set.insert(RateTable {
                id: parse_id(&row.0, "rate_table")?,
                kind,
                effective_from: parse_date(&row.2)?,
                effective_to: row.3.as_deref().map(parse_date).transpose()?,
                verified: row.4 != 0,
                verified_by: row.5,
                verified_at: row.6.map(instant).transpose()?,
                source_note: row.7,
                entries,
            });
        }
        Ok(set)
    }

    pub fn all_rate_tables(&self) -> StoreResult<Vec<RateTable>> {
        let mut statement = self.conn.prepare(
            "SELECT id, kind, effective_from, effective_to, verified, verified_by, verified_at, source_note
             FROM rate_tables ORDER BY kind, effective_from DESC",
        )?;
        let rows = statement.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, Option<String>>(3)?,
                row.get::<_, i64>(4)?,
                row.get::<_, Option<String>>(5)?,
                row.get::<_, Option<i64>>(6)?,
                row.get::<_, Option<String>>(7)?,
            ))
        })?;
        let mut tables = Vec::new();
        for row in rows {
            let row = row?;
            tables.push(RateTable {
                id: parse_id(&row.0, "rate_table")?,
                kind: parse_rate_kind(&row.1)?,
                effective_from: parse_date(&row.2)?,
                effective_to: row.3.as_deref().map(parse_date).transpose()?,
                verified: row.4 != 0,
                verified_by: row.5,
                verified_at: row.6.map(instant).transpose()?,
                source_note: row.7,
                entries: self.rate_entries(&row.0)?,
            });
        }
        Ok(tables)
    }

    fn rate_entries(&self, table_id: &str) -> StoreResult<Vec<RateEntry>> {
        let mut statement = self.conn.prepare(
            "SELECT entry_key, employee_share_bp, employer_share_bp, wage_cap_sen, flat_amount_sen,
                    multiplier_bp, lower_bound_sen, upper_bound_sen, hours_per_month, note
             FROM rate_entries WHERE table_id = ?1 ORDER BY position",
        )?;
        let rows = statement.query_map(params![table_id], |row| {
            Ok(RateEntry {
                key: row.get(0)?,
                employee_share_bp: row.get(1)?,
                employer_share_bp: row.get(2)?,
                wage_cap: row.get::<_, Option<i64>>(3)?.map(Money::from_sen),
                flat_amount: row.get::<_, Option<i64>>(4)?.map(Money::from_sen),
                multiplier_bp: row.get(5)?,
                lower_bound: row.get::<_, Option<i64>>(6)?.map(Money::from_sen),
                upper_bound: row.get::<_, Option<i64>>(7)?.map(Money::from_sen),
                hours_per_month: row.get(8)?,
                note: row.get(9)?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn save_payroll_run(&mut self, run: &PayrollRun) -> StoreResult<()> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        tx.execute(
            "INSERT INTO payroll_runs
             (id, kind, period, status, anomalies_json, totals_json, rate_table_ids_json,
              created_at, computed_at, approved_at, approved_by, supersede_reason)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12)
             ON CONFLICT(id) DO UPDATE SET status=excluded.status, anomalies_json=excluded.anomalies_json,
                totals_json=excluded.totals_json, rate_table_ids_json=excluded.rate_table_ids_json,
                computed_at=excluded.computed_at, approved_at=excluded.approved_at,
                approved_by=excluded.approved_by, supersede_reason=excluded.supersede_reason",
            params![
                run.id.to_string(),
                payroll_kind(run.kind),
                run.period.to_string(),
                run_status(run.status),
                serde_json::to_string(&run.anomalies)?,
                serde_json::to_string(&run.totals)?,
                serde_json::to_string(&run.rate_table_ids.iter().map(|id| id.to_string()).collect::<Vec<_>>())?,
                run.created_at.millis(),
                run.computed_at.map(|instant| instant.millis()),
                run.approved_at.map(|instant| instant.millis()),
                run.approved_by.map(|id| id.to_string()),
                run.supersede_reason,
            ],
        )?;
        tx.execute(
            "DELETE FROM payroll_lines WHERE run_id = ?1",
            params![run.id.to_string()],
        )?;
        for (position, line) in run.lines.iter().enumerate() {
            tx.execute(
                "INSERT INTO payroll_lines (run_id, employee_id, employee_name, line_json, position)
                 VALUES (?1,?2,?3,?4,?5)",
                params![
                    run.id.to_string(),
                    line.employee_id.to_string(),
                    line.employee_name,
                    serde_json::to_string(line)?,
                    position as i64,
                ],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn payroll_run(&self, id: PayrollRunId) -> StoreResult<PayrollRun> {
        let row = self
            .conn
            .query_row(
                "SELECT id, kind, period, status, anomalies_json, totals_json, rate_table_ids_json,
                        created_at, computed_at, approved_at, approved_by, supersede_reason
                 FROM payroll_runs WHERE id = ?1",
                params![id.to_string()],
                payroll_run_row,
            )
            .optional()?
            .ok_or_else(|| StoreError::NotFound {
                entity: "payroll_run",
                id: id.to_string(),
            })?;
        self.hydrate_run(row)
    }

    pub fn list_payroll_runs(&self) -> StoreResult<Vec<PayrollRun>> {
        let mut statement = self.conn.prepare(
            "SELECT id, kind, period, status, anomalies_json, totals_json, rate_table_ids_json,
                    created_at, computed_at, approved_at, approved_by, supersede_reason
             FROM payroll_runs ORDER BY period DESC, created_at DESC",
        )?;
        let rows = statement.query_map([], payroll_run_row)?;
        let mut runs = Vec::new();
        for row in rows {
            runs.push(self.hydrate_run(row?)?);
        }
        Ok(runs)
    }

    fn hydrate_run(&self, header: RunHeader) -> StoreResult<PayrollRun> {
        let mut statement = self
            .conn
            .prepare("SELECT line_json FROM payroll_lines WHERE run_id = ?1 ORDER BY position")?;
        let lines = statement
            .query_map(params![header.id.to_string()], |row| {
                row.get::<_, String>(0)
            })?
            .collect::<Result<Vec<_>, _>>()?
            .into_iter()
            .map(|raw| serde_json::from_str::<PayrollLine>(&raw).map_err(StoreError::from))
            .collect::<StoreResult<Vec<_>>>()?;
        Ok(PayrollRun {
            id: header.id,
            kind: header.kind,
            period: header.period,
            status: header.status,
            lines,
            anomalies: header.anomalies,
            totals: header.totals,
            rate_table_ids: header.rate_table_ids,
            created_at: header.created_at,
            computed_at: header.computed_at,
            approved_at: header.approved_at,
            approved_by: header.approved_by,
            supersede_reason: header.supersede_reason,
        })
    }

    // ------------------------------------------------------------------
    // Approvals, consent
    // ------------------------------------------------------------------

    pub fn save_approval(&mut self, approval: &ApprovalRequest) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO approvals
             (id, kind, title, summary, subject_type, subject_id, status, priority, due_on,
              requested_by, created_at, decided_by, decided_at, decision_note)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14)
             ON CONFLICT(id) DO UPDATE SET status=excluded.status, priority=excluded.priority,
                due_on=excluded.due_on, decided_by=excluded.decided_by,
                decided_at=excluded.decided_at, decision_note=excluded.decision_note",
            params![
                approval.id,
                approval_kind(approval.kind),
                approval.title,
                approval.summary,
                approval.subject_type,
                approval.subject_id,
                approval_status(approval.status),
                priority(approval.priority),
                approval.due_on.map(|date| date.to_string()),
                approval.requested_by.map(|id| id.to_string()),
                approval.created_at.millis(),
                approval.decided_by.map(|id| id.to_string()),
                approval.decided_at.map(|instant| instant.millis()),
                approval.decision_note,
            ],
        )?;
        Ok(())
    }

    pub fn list_approvals(&self, open_only: bool) -> StoreResult<Vec<ApprovalRequest>> {
        let sql = if open_only {
            "SELECT id, kind, title, summary, subject_type, subject_id, status, priority, due_on,
                    requested_by, created_at, decided_by, decided_at, decision_note
             FROM approvals WHERE status = 'open' ORDER BY
             CASE priority WHEN 'urgent' THEN 3 WHEN 'high' THEN 2 WHEN 'normal' THEN 1 ELSE 0 END DESC,
             due_on IS NULL, due_on, created_at"
        } else {
            "SELECT id, kind, title, summary, subject_type, subject_id, status, priority, due_on,
                    requested_by, created_at, decided_by, decided_at, decision_note
             FROM approvals ORDER BY created_at DESC"
        };
        let mut statement = self.conn.prepare(sql)?;
        let rows = statement.query_map([], |row| {
            Ok(ApprovalRequest {
                id: row.get(0)?,
                kind: parse_approval_kind(&row.get::<_, String>(1)?)?,
                title: row.get(2)?,
                summary: row.get(3)?,
                subject_type: row.get(4)?,
                subject_id: row.get(5)?,
                status: parse_approval_status(&row.get::<_, String>(6)?)?,
                priority: parse_priority(&row.get::<_, String>(7)?)?,
                due_on: row
                    .get::<_, Option<String>>(8)?
                    .as_deref()
                    .map(parse_date)
                    .transpose()?,
                requested_by: optional_id::<OperatorId>(
                    row.get::<_, Option<String>>(9)?.as_deref(),
                    "operator",
                )?,
                created_at: instant(row.get(10)?)?,
                decided_by: optional_id::<OperatorId>(
                    row.get::<_, Option<String>>(11)?.as_deref(),
                    "operator",
                )?,
                decided_at: row.get::<_, Option<i64>>(12)?.map(instant).transpose()?,
                decision_note: row.get(13)?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn save_consent(&mut self, consent: &ConsentRecord) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO consents
             (id, subject_type, subject_id, purpose, state, source, granted_at, withdrawn_at, expires_on, note)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)
             ON CONFLICT(id) DO UPDATE SET state=excluded.state, granted_at=excluded.granted_at,
                withdrawn_at=excluded.withdrawn_at, expires_on=excluded.expires_on, note=excluded.note",
            params![
                consent.id.to_string(),
                subject_type(consent.subject_type),
                consent.subject_id,
                consent_purpose(consent.purpose),
                consent_state(consent.state),
                consent.source,
                consent.granted_at.map(|instant| instant.millis()),
                consent.withdrawn_at.map(|instant| instant.millis()),
                consent.expires_on.map(|date| date.to_string()),
                consent.note,
            ],
        )?;
        Ok(())
    }

    pub fn consent_for(
        &self,
        subject_kind: SubjectType,
        subject_id: &str,
    ) -> StoreResult<Option<ConsentRecord>> {
        self.conn
            .query_row(
                "SELECT id, subject_type, subject_id, purpose, state, source, granted_at,
                        withdrawn_at, expires_on, note
                 FROM consents WHERE subject_type=?1 AND subject_id=?2
                 ORDER BY COALESCE(granted_at, 0) DESC LIMIT 1",
                params![subject_type(subject_kind), subject_id],
                |row| {
                    Ok(ConsentRecord {
                        id: parse_id(&row.get::<_, String>(0)?, "consent")?,
                        subject_type: parse_subject_type(&row.get::<_, String>(1)?)?,
                        subject_id: row.get(2)?,
                        purpose: parse_consent_purpose(&row.get::<_, String>(3)?)?,
                        state: parse_consent_state(&row.get::<_, String>(4)?)?,
                        source: row.get(5)?,
                        granted_at: row.get::<_, Option<i64>>(6)?.map(instant).transpose()?,
                        withdrawn_at: row.get::<_, Option<i64>>(7)?.map(instant).transpose()?,
                        expires_on: row
                            .get::<_, Option<String>>(8)?
                            .as_deref()
                            .map(parse_date)
                            .transpose()?,
                        note: row.get(9)?,
                    })
                },
            )
            .optional()
            .map_err(StoreError::from)
    }

    // ------------------------------------------------------------------
    // Backup and integrity
    // ------------------------------------------------------------------

    pub fn backup_to(&self, path: impl AsRef<Path>) -> StoreResult<u64> {
        let path = path.as_ref();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|error| StoreError::Backup(error.to_string()))?;
        }
        let mut destination =
            Connection::open(path).map_err(|error| StoreError::Backup(error.to_string()))?;
        {
            let backup = rusqlite::backup::Backup::new(&self.conn, &mut destination)
                .map_err(|error| StoreError::Backup(error.to_string()))?;
            backup
                .run_to_completion(128, Duration::from_millis(5), None)
                .map_err(|error| StoreError::Backup(error.to_string()))?;
        }
        let check: String = destination
            .query_row("PRAGMA integrity_check", [], |row| row.get(0))
            .map_err(|error| StoreError::Backup(error.to_string()))?;
        if check != "ok" {
            return Err(StoreError::Backup(format!(
                "integrity check failed: {check}"
            )));
        }
        drop(destination);
        Ok(std::fs::metadata(path)
            .map_err(|error| StoreError::Backup(error.to_string()))?
            .len())
    }

    pub fn integrity_check(&self) -> StoreResult<String> {
        Ok(self
            .conn
            .query_row("PRAGMA integrity_check", [], |row| row.get(0))?)
    }

    pub fn checkpoint(&self) -> StoreResult<()> {
        self.conn
            .execute_batch("PRAGMA wal_checkpoint(TRUNCATE);")?;
        Ok(())
    }

    /// Test/import helper: run arbitrary SQL. Not exposed over IPC.
    pub fn execute_batch(&self, sql: &str) -> StoreResult<()> {
        self.conn.execute_batch(sql)?;
        Ok(())
    }

    pub fn query_count(&self, table: &str) -> StoreResult<i64> {
        let allowed = [
            "company",
            "operator",
            "employees",
            "candidates",
            "applications",
            "documents",
            "onboarding_plans",
            "leave_requests",
            "payroll_runs",
            "audit_log",
            "approvals",
            "rate_tables",
            "consents",
            "jobs",
        ];
        if !allowed.contains(&table) {
            return Err(StoreError::Corrupt(format!(
                "table {table} is not countable"
            )));
        }
        Ok(self
            .conn
            .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
                row.get(0)
            })?)
    }
}

// ----------------------------------------------------------------------
// Row helpers and enum mappings
// ----------------------------------------------------------------------

type RunHeader = PayrollRunHeader;

#[derive(Debug)]
struct PayrollRunHeader {
    id: PayrollRunId,
    kind: PayrollKind,
    period: BusinessDate,
    status: RunStatus,
    anomalies: Vec<hragents_core::payroll::PayrollAnomaly>,
    totals: PayrollTotals,
    rate_table_ids: Vec<RateTableId>,
    created_at: UtcInstant,
    computed_at: Option<UtcInstant>,
    approved_at: Option<UtcInstant>,
    approved_by: Option<OperatorId>,
    supersede_reason: Option<String>,
}

fn payroll_run_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<RunHeader> {
    Ok(PayrollRunHeader {
        id: parse_id(&row.get::<_, String>(0)?, "payroll_run")?,
        kind: parse_payroll_kind(&row.get::<_, String>(1)?)?,
        period: parse_date(&row.get::<_, String>(2)?)?,
        status: parse_run_status(&row.get::<_, String>(3)?)?,
        anomalies: serde_json::from_str(&row.get::<_, String>(4)?).map_err(json_err)?,
        totals: serde_json::from_str(&row.get::<_, String>(5)?).map_err(json_err)?,
        rate_table_ids: {
            let raw: Vec<String> =
                serde_json::from_str(&row.get::<_, String>(6)?).map_err(json_err)?;
            raw.into_iter()
                .map(|id| parse_id(&id, "rate_table"))
                .collect::<Result<Vec<_>, _>>()?
        },
        created_at: instant(row.get(7)?)?,
        computed_at: row.get::<_, Option<i64>>(8)?.map(instant).transpose()?,
        approved_at: row.get::<_, Option<i64>>(9)?.map(instant).transpose()?,
        approved_by: optional_id::<OperatorId>(
            row.get::<_, Option<String>>(10)?.as_deref(),
            "operator",
        )?,
        supersede_reason: row.get(11)?,
    })
}

fn employee_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Employee> {
    Ok(Employee {
        id: parse_id(&row.get::<_, String>(0)?, "employee")?,
        employee_no: row.get(1)?,
        full_name: row.get(2)?,
        preferred_name: row.get(3)?,
        email: row.get(4)?,
        phone: row.get(5)?,
        job_title: row.get(6)?,
        org_unit: row.get(7)?,
        manager_id: optional_id::<EmployeeId>(
            row.get::<_, Option<String>>(8)?.as_deref(),
            "operator",
        )?,
        status: parse_employment_status(&row.get::<_, String>(9)?)?,
        hire_date: parse_date(&row.get::<_, String>(10)?)?,
        end_date: row
            .get::<_, Option<String>>(11)?
            .as_deref()
            .map(parse_date)
            .transpose()?,
        birth_date: row
            .get::<_, Option<String>>(12)?
            .as_deref()
            .map(parse_date)
            .transpose()?,
        ptkp_status: row.get(13)?,
        dependents: row.get(14)?,
        jkk_risk_class: row.get::<_, Option<i64>>(15)?.map(|value| value as u8),
        npwp: row.get(16)?,
        bank_name: row.get(17)?,
        bank_account: row.get(18)?,
        bpjs_kesehatan_no: row.get(19)?,
        bpjs_ketenagakerjaan_no: row.get(20)?,
        created_at: instant(row.get(21)?)?,
        updated_at: instant(row.get(22)?)?,
        version: row.get(23)?,
    })
}

fn application_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Application> {
    Ok(Application {
        id: parse_id(&row.get::<_, String>(0)?, "application")?,
        candidate_id: parse_id(&row.get::<_, String>(1)?, "candidate")?,
        job_id: parse_id(&row.get::<_, String>(2)?, "job")?,
        stage: parse_application_stage(&row.get::<_, String>(3)?)?,
        priority: row.get::<_, i64>(4)? as u8,
        created_at: instant(row.get(5)?)?,
        updated_at: instant(row.get(6)?)?,
        rejection_reason: row.get(7)?,
        rejected_by: optional_id::<OperatorId>(
            row.get::<_, Option<String>>(8)?.as_deref(),
            "operator",
        )?,
    })
}

fn leave_request_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<LeaveRequest> {
    Ok(LeaveRequest {
        id: parse_id(&row.get::<_, String>(0)?, "leave_request")?,
        employee_id: parse_id(&row.get::<_, String>(1)?, "employee")?,
        leave_type_id: parse_id(&row.get::<_, String>(2)?, "leave_type")?,
        start_date: parse_date(&row.get::<_, String>(3)?)?,
        end_date: parse_date(&row.get::<_, String>(4)?)?,
        days_x2: row.get(5)?,
        half_day_start: row.get::<_, i64>(6)? != 0,
        half_day_end: row.get::<_, i64>(7)? != 0,
        reason: row.get(8)?,
        status: parse_leave_status(&row.get::<_, String>(9)?)?,
        recorded_by: parse_id(&row.get::<_, String>(10)?, "operator")?,
        decided_by: optional_id::<OperatorId>(
            row.get::<_, Option<String>>(11)?.as_deref(),
            "operator",
        )?,
        decided_at: row.get::<_, Option<i64>>(12)?.map(instant).transpose()?,
        decision_note: row.get(13)?,
        attachment_document_id: row.get(14)?,
        created_at: instant(row.get(15)?)?,
    })
}

fn fts_query(input: &str) -> String {
    let terms: Vec<String> = input
        .split(|ch: char| !ch.is_alphanumeric())
        .filter(|term| term.len() >= 2)
        .map(|term| format!("\"{}\"", term.replace('"', "")))
        .collect();
    terms.join(" OR ")
}

fn json_err(error: serde_json::Error) -> rusqlite::Error {
    rusqlite::Error::FromSqlConversionFailure(0, rusqlite::types::Type::Text, Box::new(error))
}

fn optional_id<T: std::str::FromStr>(
    raw: Option<&str>,
    entity: &'static str,
) -> rusqlite::Result<Option<T>> {
    raw.map(|raw| parse_id(raw, entity)).transpose()
}

fn parse_id<T: std::str::FromStr>(raw: &str, entity: &'static str) -> rusqlite::Result<T> {
    raw.parse().map_err(|_| {
        rusqlite::Error::FromSqlConversionFailure(
            0,
            rusqlite::types::Type::Text,
            Box::new(StoreError::Corrupt(format!("invalid {entity} id {raw}"))),
        )
    })
}

fn parse_date(raw: &str) -> rusqlite::Result<BusinessDate> {
    BusinessDate::parse(raw).map_err(|error| {
        rusqlite::Error::FromSqlConversionFailure(
            0,
            rusqlite::types::Type::Text,
            Box::new(StoreError::Corrupt(error.to_string())),
        )
    })
}

fn instant(millis: i64) -> rusqlite::Result<UtcInstant> {
    UtcInstant::from_millis(millis).map_err(|error| {
        rusqlite::Error::FromSqlConversionFailure(
            0,
            rusqlite::types::Type::Integer,
            Box::new(StoreError::Corrupt(error.to_string())),
        )
    })
}

macro_rules! enum_mapping {
    ($encode:ident, $decode:ident, $ty:ty, $($variant:path => $text:literal),+ $(,)?) => {
        #[allow(dead_code)]
        fn $encode(value: $ty) -> &'static str {
            match value {
                $($variant => $text,)+
            }
        }

        #[allow(dead_code)]
        fn $decode(raw: &str) -> rusqlite::Result<$ty> {
            match raw {
                $($text => Ok($variant),)+
                other => Err(rusqlite::Error::FromSqlConversionFailure(
                    0,
                    rusqlite::types::Type::Text,
                    Box::new(StoreError::Corrupt(format!("unknown enum value {other}"))),
                )),
            }
        }
    };
}

enum_mapping!(contract_kind, parse_contract_kind, ContractKind,
    ContractKind::Permanent => "permanent", ContractKind::FixedTerm => "fixed_term",
    ContractKind::Probation => "probation", ContractKind::Intern => "intern");
enum_mapping!(contract_status, parse_contract_status, ContractStatus,
    ContractStatus::Draft => "draft", ContractStatus::Active => "active",
    ContractStatus::Expired => "expired", ContractStatus::Terminated => "terminated");
enum_mapping!(onboarding_status, parse_onboarding_status, OnboardingStatus,
    OnboardingStatus::Draft => "draft", OnboardingStatus::InProgress => "in_progress",
    OnboardingStatus::Completed => "completed", OnboardingStatus::Cancelled => "cancelled");
enum_mapping!(step_status, parse_step_status, StepStatus,
    StepStatus::Pending => "pending", StepStatus::InProgress => "in_progress",
    StepStatus::Done => "done", StepStatus::Skipped => "skipped");
enum_mapping!(document_status, parse_document_status, DocumentStatus,
    DocumentStatus::Pending => "pending", DocumentStatus::Verified => "verified",
    DocumentStatus::Rejected => "rejected", DocumentStatus::Expired => "expired");
enum_mapping!(owner_type, parse_owner_type, DocumentOwnerType,
    DocumentOwnerType::Employee => "employee", DocumentOwnerType::Candidate => "candidate",
    DocumentOwnerType::Company => "company", DocumentOwnerType::PayrollRun => "payroll_run");
enum_mapping!(job_status, parse_job_status, JobStatus,
    JobStatus::Draft => "draft", JobStatus::Open => "open",
    JobStatus::Paused => "paused", JobStatus::Closed => "closed");
enum_mapping!(consent_status, parse_consent, ConsentStatus,
    ConsentStatus::Pending => "pending", ConsentStatus::Granted => "granted",
    ConsentStatus::Withdrawn => "withdrawn", ConsentStatus::Expired => "expired");
enum_mapping!(application_stage, parse_application_stage, ApplicationStage,
    ApplicationStage::Imported => "imported", ApplicationStage::Screening => "screening",
    ApplicationStage::Review => "review", ApplicationStage::Interview => "interview",
    ApplicationStage::Offer => "offer", ApplicationStage::Hired => "hired",
    ApplicationStage::Rejected => "rejected", ApplicationStage::Withdrawn => "withdrawn");
enum_mapping!(leave_status, parse_leave_status, LeaveStatus,
    LeaveStatus::Pending => "pending", LeaveStatus::Approved => "approved",
    LeaveStatus::Rejected => "rejected", LeaveStatus::Cancelled => "cancelled");
enum_mapping!(payroll_kind, parse_payroll_kind, PayrollKind,
    PayrollKind::Monthly => "monthly", PayrollKind::Thr => "thr",
    PayrollKind::Final => "final", PayrollKind::Adjustment => "adjustment");
enum_mapping!(run_status, parse_run_status, RunStatus,
    RunStatus::Draft => "draft", RunStatus::Computed => "computed",
    RunStatus::Approved => "approved", RunStatus::Cancelled => "cancelled",
    RunStatus::Superseded => "superseded");
enum_mapping!(approval_kind, parse_approval_kind, hragents_core::approvals::ApprovalKind,
    hragents_core::approvals::ApprovalKind::RejectionOverride => "rejection_override",
    hragents_core::approvals::ApprovalKind::PayrollSignOff => "payroll_sign_off",
    hragents_core::approvals::ApprovalKind::OfferApproval => "offer_approval",
    hragents_core::approvals::ApprovalKind::Erasure => "erasure",
    hragents_core::approvals::ApprovalKind::Leave => "leave",
    hragents_core::approvals::ApprovalKind::Document => "document");
enum_mapping!(approval_status, parse_approval_status, ApprovalStatus,
    ApprovalStatus::Open => "open", ApprovalStatus::Approved => "approved",
    ApprovalStatus::Rejected => "rejected", ApprovalStatus::Expired => "expired",
    ApprovalStatus::Cancelled => "cancelled");
enum_mapping!(priority, parse_priority, Priority,
    Priority::Low => "low", Priority::Normal => "normal",
    Priority::High => "high", Priority::Urgent => "urgent");
enum_mapping!(consent_state, parse_consent_state, ConsentState,
    ConsentState::Pending => "pending", ConsentState::Granted => "granted",
    ConsentState::Withdrawn => "withdrawn", ConsentState::Expired => "expired");
enum_mapping!(consent_purpose, parse_consent_purpose, ConsentPurpose,
    ConsentPurpose::Recruitment => "recruitment", ConsentPurpose::Employment => "employment",
    ConsentPurpose::Payroll => "payroll", ConsentPurpose::BackgroundCheck => "background_check",
    ConsentPurpose::Marketing => "marketing");
enum_mapping!(subject_type, parse_subject_type, SubjectType,
    SubjectType::Candidate => "candidate", SubjectType::Employee => "employee");
enum_mapping!(employment_status, parse_employment_status, EmploymentStatus,
    EmploymentStatus::Active => "active", EmploymentStatus::Probation => "probation",
    EmploymentStatus::Notice => "notice", EmploymentStatus::Exited => "exited");

fn parse_rate_kind(raw: &str) -> StoreResult<RateTableKind> {
    Ok(match raw {
        "bpjs_kesehatan" => RateTableKind::BpjsKesehatan,
        "bpjs_ketenagakerjaan_jht" => RateTableKind::BpjsKetenagakerjaanJht,
        "bpjs_ketenagakerjaan_jp" => RateTableKind::BpjsKetenagakerjaanJp,
        "bpjs_jkk" => RateTableKind::BpjsJkk,
        "bpjs_jkm" => RateTableKind::BpjsJkm,
        "pph21_ter" => RateTableKind::Pph21Ter,
        "pph21_ptkp" => RateTableKind::Pph21Ptkp,
        "overtime_premium" => RateTableKind::OvertimePremium,
        "thr_formula" => RateTableKind::ThrFormula,
        "minimum_wage" => RateTableKind::MinimumWage,
        other => return Err(StoreError::Corrupt(format!("unknown rate kind {other}"))),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use hragents_core::audit::AuditActor;
    use hragents_core::auth::Operator;
    use hragents_core::password::hash_password;
    use hragents_core::payroll::Severity;

    fn now() -> UtcInstant {
        UtcInstant::from_millis(1_760_000_000_000).unwrap()
    }

    fn store() -> Store {
        Store::open_in_memory().unwrap()
    }

    fn employee(store: &Store) -> Employee {
        let employee = Employee::new(
            "E-001",
            "Ayu Lestari",
            "Engineer",
            "Product",
            BusinessDate::parse("2025-02-01").unwrap(),
            now(),
        );
        let _ = store;
        employee
    }

    #[test]
    fn schema_migrates_and_reports_version() {
        let store = store();
        assert_eq!(store.schema_version().unwrap(), 1);
        assert_eq!(store.integrity_check().unwrap(), "ok");
        assert_eq!(store.query_count("employees").unwrap(), 0);
    }

    #[test]
    fn operator_roundtrip() {
        let mut store = store();
        let operator = Operator::new(
            "rina",
            "Rina",
            hash_password("correct horse battery staple").unwrap(),
            now(),
        );
        store.insert_operator(&operator).unwrap();
        let loaded = store.operator_by_username("rina").unwrap().unwrap();
        assert_eq!(loaded.id, operator.id);
        assert_eq!(loaded.role, Role::HrOperator);
        assert_eq!(store.operator_count().unwrap(), 1);
    }

    #[test]
    fn employee_roundtrip_and_optimistic_concurrency() {
        let mut store = store();
        let mut employee = employee(&store);
        store.save_employee(&employee).unwrap();
        let loaded = store.employee(employee.id).unwrap();
        assert_eq!(loaded.full_name, "Ayu Lestari");
        employee.full_name = "Ayu L. Putri".into();
        employee.updated_at = now().plus_seconds(1);
        employee.version = 2;
        store.save_employee(&employee).unwrap();
        assert_eq!(
            store.employee(employee.id).unwrap().full_name,
            "Ayu L. Putri"
        );
        // Replaying version 2 is a conflict, not a lost update.
        employee.version = 2;
        assert!(matches!(
            store.save_employee(&employee),
            Err(StoreError::Conflict { .. })
        ));
    }

    #[test]
    fn employee_search_uses_fts() {
        let mut store = store();
        store.save_employee(&employee(&store)).unwrap();
        let hits = store.search_employees("Ayu", 10).unwrap();
        assert_eq!(hits.len(), 1);
        assert!(
            store
                .search_employees("engineering", 10)
                .unwrap()
                .is_empty()
        );
    }

    #[test]
    fn onboarding_roundtrip() {
        let mut store = store();
        let employee = employee(&store);
        store.save_employee(&employee).unwrap();
        let mut plan = OnboardingPlan::start(
            employee.id,
            "Standard",
            vec![
                OnboardingStep::new("contract", "Sign contract", "documents"),
                OnboardingStep::new("laptop", "Issue laptop", "assets"),
            ],
            now(),
        )
        .unwrap();
        plan.complete_step("contract", "Rina", now()).unwrap();
        store.save_onboarding_plan(&plan).unwrap();
        let loaded = store.onboarding_plan_for(employee.id).unwrap().unwrap();
        assert_eq!(loaded.steps.len(), 2);
        assert_eq!(loaded.steps[0].status, StepStatus::Done);
        assert_eq!(loaded.status, OnboardingStatus::InProgress);
    }

    #[test]
    fn audit_chain_persists_and_verifies() {
        let mut store = store();
        let actor = AuditActor::human(OperatorId::new(), "Rina");
        store
            .append_audit(
                &actor,
                "employee.created",
                "employee",
                "e1",
                serde_json::json!({"name": "Ayu"}),
                now(),
            )
            .unwrap();
        store
            .append_audit(
                &actor,
                "employee.updated",
                "employee",
                "e1",
                serde_json::json!({"field": "phone"}),
                now().plus_seconds(1),
            )
            .unwrap();
        let verification = store.verify_audit().unwrap();
        assert_eq!(verification.entries, 2);
        assert_eq!(store.audit_head().unwrap(), verification.head_hash);
        // Tamper with the persisted payload directly and verify detection.
        store
            .execute_batch(
                "UPDATE audit_log SET payload_json = '{\"name\":\"Not Ayu\"}' WHERE seq = 0",
            )
            .unwrap();
        assert!(store.verify_audit().is_err());
    }

    #[cfg(feature = "sqlcipher")]
    #[test]
    fn encrypted_database_reopens_with_the_key_and_rejects_a_wrong_one() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("encrypted.db");
        let mut store = Store::open_encrypted(&path, "correct horse battery staple").unwrap();
        store
            .set_company("Nusantara Labs", None, None, now())
            .unwrap();
        assert_eq!(
            store.company_name().unwrap().as_deref(),
            Some("Nusantara Labs")
        );
        drop(store);
        let reopened = Store::open_encrypted(&path, "correct horse battery staple").unwrap();
        assert_eq!(
            reopened.company_name().unwrap().as_deref(),
            Some("Nusantara Labs")
        );
        assert!(Store::open_encrypted(&path, "wrong key").is_err());
    }

    #[test]
    fn backup_copies_a_verifiable_database() {
        let mut store = store();
        store.save_employee(&employee(&store)).unwrap();
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("backup.db");
        let size = store.backup_to(&path).unwrap();
        assert!(size > 0);
        let copy = Store::open(&path).unwrap();
        assert_eq!(copy.query_count("employees").unwrap(), 1);
    }

    #[test]
    fn leave_and_payroll_roundtrip() {
        let mut store = store();
        let mut employee = employee(&store);
        employee.version = 1;
        store.save_employee(&employee).unwrap();
        let leave_type = LeaveType::annual("Annual leave", 12);
        store.save_leave_type(&leave_type).unwrap();
        let mut balance = LeaveBalance::new(employee.id, leave_type.id, 2026, 24);
        let mut request = LeaveRequest::record(
            employee.id,
            leave_type.id,
            BusinessDate::parse("2026-11-09").unwrap(),
            BusinessDate::parse("2026-11-10").unwrap(),
            4,
            OperatorId::new(),
            "family event",
            now(),
        )
        .unwrap();
        request.submit(&mut balance).unwrap();
        store.save_leave_balance(&balance).unwrap();
        store.save_leave_request(&request).unwrap();
        assert_eq!(
            store
                .list_leave_requests(Some(LeaveStatus::Pending))
                .unwrap()
                .len(),
            1
        );
        assert_eq!(
            store
                .leave_balance(employee.id, leave_type.id, 2026)
                .unwrap()
                .unwrap()
                .pending_x2,
            4
        );

        let mut run = PayrollRun::new(
            PayrollKind::Monthly,
            BusinessDate::parse("2026-11-01").unwrap(),
            now(),
        );
        run.status = RunStatus::Computed;
        run.anomalies
            .push(hragents_core::payroll::PayrollAnomaly::error(
                "test",
                Some(employee.id),
                "fixture",
            ));
        run.totals = PayrollTotals::default();
        store.save_payroll_run(&run).unwrap();
        let loaded = store.payroll_run(run.id).unwrap();
        assert_eq!(loaded.status, RunStatus::Computed);
        assert_eq!(loaded.anomalies[0].severity, Severity::Error);
    }
}
