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
use hragents_core::documents::{DocumentRequest, DocumentRequestStatus};
use hragents_core::error::DomainError;
use hragents_core::growth::{
    AssignmentStatus, CycleStatus, Goal, GoalStatus, ReviewAnswer, ReviewAssignment, ReviewCycle,
};
use hragents_core::hiring::{
    Application, ApplicationStage, Candidate, ConsentStatus, Evaluation, Job, JobStatus,
};
use hragents_core::ids::*;
use hragents_core::leave::{LeaveBalance, LeaveRequest, LeaveStatus, LeaveType};
use hragents_core::money::Money;
use hragents_core::offboarding::{
    OffboardingPlan, OffboardingStatus, OffboardingStep, OffboardingStepStatus,
};
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
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::Duration;

const SCHEMA: &str = include_str!("../migrations/0001_init.sql");
const INDEXES: &str = include_str!("../migrations/0002_indexes.sql");
const SCHEMA_VERSION: i64 = 2;

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

fn column_exists(tx: &rusqlite::Transaction<'_>, table: &str, column: &str) -> StoreResult<bool> {
    let mut statement = tx.prepare(&format!("PRAGMA table_info({table})"))?;
    let mut rows = statement.query([])?;
    while let Some(row) = rows.next()? {
        if row.get::<_, String>(1)? == column {
            return Ok(true);
        }
    }
    Ok(false)
}

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
        let mut version: i64 = self
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
                "INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?1)",
                params![now],
            )?;
            tx.pragma_update(None, "user_version", 1)?;
            tx.commit()?;
            version = 1;
        }
        if version < 2 {
            let tx = self
                .conn
                .transaction_with_behavior(TransactionBehavior::Immediate)?;
            // Version 1 shipped during development with a slightly smaller
            // growth/offboarding schema while still reporting user_version 1.
            // Add the missing columns before indexing them so real databases
            // upgrade in place instead of failing on first launch.
            for (table, column, declaration) in [
                ("growth_assignments", "reviewer_email", "TEXT"),
                (
                    "growth_assignments",
                    "created_at",
                    "INTEGER NOT NULL DEFAULT 0",
                ),
                ("growth_assignments", "sent_at", "INTEGER"),
                ("growth_assignments", "submitted_at", "INTEGER"),
                ("offboarding_plans", "final_pay_run_id", "TEXT"),
            ] {
                if !column_exists(&tx, table, column)? {
                    tx.execute_batch(&format!(
                        "ALTER TABLE {table} ADD COLUMN {column} {declaration}"
                    ))?;
                }
            }
            let now = UtcInstant::now().millis();
            tx.execute(
                "UPDATE growth_assignments SET created_at = ?1 WHERE created_at = 0",
                params![now],
            )?;
            tx.execute_batch(INDEXES)?;
            tx.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (2, ?1)",
                params![now],
            )?;
            tx.pragma_update(None, "user_version", 2)?;
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

    /// The newest `limit` audit entries, returned oldest-first. Today's
    /// receipt list must not load the whole chain as the log grows.
    pub fn audit_recent(&self, limit: usize) -> StoreResult<Vec<AuditEntry>> {
        let mut statement = self.conn.prepare(
            "SELECT seq, entry_id, created_at, actor_json, action, subject_type, subject_id,
                    payload_json, prev_hash, entry_hash
             FROM audit_log ORDER BY seq DESC LIMIT ?1",
        )?;
        let rows = statement.query_map(params![limit as i64], |row| {
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
        entries.reverse();
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

    /// Every plan with its steps, in two queries. Screens that need plan status
    /// for all employees (Today, reminders) must not query once per employee.
    pub fn list_onboarding_plans(&self) -> StoreResult<Vec<OnboardingPlan>> {
        let mut plans_statement = self.conn.prepare(
            "SELECT id, employee_id, template_name, status, created_at, completed_at
             FROM onboarding_plans ORDER BY created_at DESC",
        )?;
        let plan_rows = plans_statement.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, i64>(4)?,
                row.get::<_, Option<i64>>(5)?,
            ))
        })?;
        let mut plans = Vec::new();
        for row in plan_rows {
            let (id, employee_id, template_name, status, created_at, completed_at) = row?;
            plans.push(OnboardingPlan {
                id: parse_id(&id, "onboarding_plan")?,
                employee_id: parse_id(&employee_id, "employee")?,
                template_name,
                status: parse_onboarding_status(&status)?,
                steps: Vec::new(),
                created_at: instant(created_at)?,
                completed_at: completed_at.map(instant).transpose()?,
            });
        }
        if plans.is_empty() {
            return Ok(plans);
        }

        let mut steps_statement = self.conn.prepare(
            "SELECT plan_id, step_key, title, category, required, status, due_date,
                    completed_at, completed_by, document_request_id, notes
             FROM onboarding_steps ORDER BY plan_id, position",
        )?;
        let step_rows = steps_statement.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, i64>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, Option<String>>(6)?,
                row.get::<_, Option<i64>>(7)?,
                row.get::<_, Option<String>>(8)?,
                row.get::<_, Option<String>>(9)?,
                row.get::<_, Option<String>>(10)?,
            ))
        })?;
        let mut by_plan: HashMap<String, Vec<OnboardingStep>> = HashMap::new();
        for row in step_rows {
            let (
                plan_id,
                key,
                title,
                category,
                required,
                status,
                due_date,
                completed_at,
                completed_by,
                document_request_id,
                notes,
            ) = row?;
            by_plan.entry(plan_id).or_default().push(OnboardingStep {
                key,
                title,
                category,
                required: required != 0,
                status: parse_step_status(&status)?,
                due_date: due_date.as_deref().map(parse_date).transpose()?,
                completed_at: completed_at.map(instant).transpose()?,
                completed_by,
                document_request_id,
                notes,
            });
        }
        for plan in &mut plans {
            plan.steps = by_plan.remove(&plan.id.to_string()).unwrap_or_default();
        }
        Ok(plans)
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

    pub fn list_documents(
        &self,
        kind: DocumentOwnerType,
        owner_id: &str,
    ) -> StoreResult<Vec<Document>> {
        let mut statement = self.conn.prepare(
            "SELECT id, owner_type, owner_id, filename, mime_type, sha256, size_bytes, status,
                    expires_on, uploaded_at, verified_at, verified_by, rejection_reason, tags_json
             FROM documents WHERE owner_type = ?1 AND owner_id = ?2 ORDER BY uploaded_at DESC",
        )?;
        let rows = statement.query_map(params![owner_type(kind), owner_id], |row| {
            Ok(Document {
                id: parse_id(&row.get::<_, String>(0)?, "document")?,
                owner_type: parse_owner_type(&row.get::<_, String>(1)?)?,
                owner_id: row.get(2)?,
                filename: row.get(3)?,
                mime_type: row.get(4)?,
                sha256: row.get(5)?,
                size_bytes: row.get(6)?,
                status: parse_document_status(&row.get::<_, String>(7)?)?,
                expires_on: row
                    .get::<_, Option<String>>(8)?
                    .as_deref()
                    .map(parse_date)
                    .transpose()?,
                uploaded_at: instant(row.get(9)?)?,
                verified_at: row.get::<_, Option<i64>>(10)?.map(instant).transpose()?,
                verified_by: row.get(11)?,
                rejection_reason: row.get(12)?,
                tags: serde_json::from_str(&row.get::<_, String>(13)?).map_err(json_err)?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
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
    // Growth
    // ------------------------------------------------------------------

    pub fn save_review_cycle(&mut self, cycle: &ReviewCycle) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO growth_cycles (id, name, status, starts_on, ends_on, created_at)
             VALUES (?1,?2,?3,?4,?5,?6)
             ON CONFLICT(id) DO UPDATE SET name=excluded.name, status=excluded.status,
                starts_on=excluded.starts_on, ends_on=excluded.ends_on",
            params![
                cycle.id.to_string(),
                cycle.name,
                cycle_status(cycle.status),
                cycle.starts_on.to_string(),
                cycle.ends_on.to_string(),
                cycle.created_at.millis(),
            ],
        )?;
        Ok(())
    }

    pub fn list_review_cycles(&self) -> StoreResult<Vec<ReviewCycle>> {
        let mut statement = self.conn.prepare(
            "SELECT id, name, status, starts_on, ends_on, created_at
             FROM growth_cycles ORDER BY starts_on DESC",
        )?;
        let rows = statement.query_map([], |row| {
            Ok(ReviewCycle {
                id: parse_id(&row.get::<_, String>(0)?, "review_cycle")?,
                name: row.get(1)?,
                status: parse_cycle_status(&row.get::<_, String>(2)?)?,
                starts_on: parse_date(&row.get::<_, String>(3)?)?,
                ends_on: parse_date(&row.get::<_, String>(4)?)?,
                created_at: instant(row.get(5)?)?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn save_review_assignment(&mut self, assignment: &ReviewAssignment) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO growth_assignments
             (id, cycle_id, employee_id, reviewer_name, reviewer_email, status, form_json,
              response_json, created_at, sent_at, submitted_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)
             ON CONFLICT(id) DO UPDATE SET reviewer_name=excluded.reviewer_name,
                reviewer_email=excluded.reviewer_email, status=excluded.status,
                form_json=excluded.form_json, response_json=excluded.response_json,
                sent_at=excluded.sent_at, submitted_at=excluded.submitted_at",
            params![
                assignment.id.to_string(),
                assignment.cycle_id.to_string(),
                assignment.employee_id.to_string(),
                assignment.reviewer_name,
                assignment.reviewer_email,
                assignment_status(assignment.status),
                serde_json::to_string(&assignment.form)?,
                assignment
                    .response
                    .as_ref()
                    .map(serde_json::to_string)
                    .transpose()?,
                assignment.created_at.millis(),
                assignment.sent_at.map(|instant| instant.millis()),
                assignment.submitted_at.map(|instant| instant.millis()),
            ],
        )?;
        Ok(())
    }

    pub fn list_review_assignments(
        &self,
        cycle_id: Option<ReviewCycleId>,
    ) -> StoreResult<Vec<ReviewAssignment>> {
        let mut assignments = Vec::new();
        let mut push = |row: &rusqlite::Row<'_>| -> rusqlite::Result<ReviewAssignment> {
            Ok(ReviewAssignment {
                id: parse_id(&row.get::<_, String>(0)?, "review_assignment")?,
                cycle_id: parse_id(&row.get::<_, String>(1)?, "review_cycle")?,
                employee_id: parse_id(&row.get::<_, String>(2)?, "employee")?,
                reviewer_name: row.get(3)?,
                reviewer_email: row.get(4)?,
                status: parse_assignment_status(&row.get::<_, String>(5)?)?,
                form: serde_json::from_str(&row.get::<_, String>(6)?).map_err(json_err)?,
                response: row
                    .get::<_, Option<String>>(7)?
                    .map(|raw| {
                        serde_json::from_str::<std::collections::BTreeMap<String, ReviewAnswer>>(
                            &raw,
                        )
                    })
                    .transpose()
                    .map_err(json_err)?,
                created_at: instant(row.get(8)?)?,
                sent_at: row.get::<_, Option<i64>>(9)?.map(instant).transpose()?,
                submitted_at: row.get::<_, Option<i64>>(10)?.map(instant).transpose()?,
            })
        };
        match cycle_id {
            Some(cycle_id) => {
                let mut statement = self.conn.prepare(
                    "SELECT id, cycle_id, employee_id, reviewer_name, reviewer_email, status,
                            form_json, response_json, created_at, sent_at, submitted_at
                     FROM growth_assignments WHERE cycle_id = ?1 ORDER BY created_at",
                )?;
                for row in statement.query_map(params![cycle_id.to_string()], &mut push)? {
                    assignments.push(row?);
                }
            }
            None => {
                let mut statement = self.conn.prepare(
                    "SELECT id, cycle_id, employee_id, reviewer_name, reviewer_email, status,
                            form_json, response_json, created_at, sent_at, submitted_at
                     FROM growth_assignments ORDER BY created_at",
                )?;
                for row in statement.query_map([], &mut push)? {
                    assignments.push(row?);
                }
            }
        }
        Ok(assignments)
    }

    pub fn save_goal(&mut self, goal: &Goal) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO goals (id, employee_id, title, status, due_on, progress_bp, created_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7)
             ON CONFLICT(id) DO UPDATE SET title=excluded.title, status=excluded.status,
                due_on=excluded.due_on, progress_bp=excluded.progress_bp",
            params![
                goal.id.to_string(),
                goal.employee_id.to_string(),
                goal.title,
                goal_status(goal.status),
                goal.due_on.map(|date| date.to_string()),
                goal.progress_bp,
                goal.created_at.millis(),
            ],
        )?;
        Ok(())
    }

    pub fn list_goals(&self, employee_id: Option<EmployeeId>) -> StoreResult<Vec<Goal>> {
        let mut goals = Vec::new();
        let mut push = |row: &rusqlite::Row<'_>| -> rusqlite::Result<Goal> {
            Ok(Goal {
                id: parse_id(&row.get::<_, String>(0)?, "goal")?,
                employee_id: parse_id(&row.get::<_, String>(1)?, "employee")?,
                title: row.get(2)?,
                status: parse_goal_status(&row.get::<_, String>(3)?)?,
                due_on: row
                    .get::<_, Option<String>>(4)?
                    .as_deref()
                    .map(parse_date)
                    .transpose()?,
                progress_bp: row.get(5)?,
                created_at: instant(row.get(6)?)?,
            })
        };
        match employee_id {
            Some(employee_id) => {
                let mut statement = self.conn.prepare(
                    "SELECT id, employee_id, title, status, due_on, progress_bp, created_at
                     FROM goals WHERE employee_id = ?1 ORDER BY created_at DESC",
                )?;
                for row in statement.query_map(params![employee_id.to_string()], &mut push)? {
                    goals.push(row?);
                }
            }
            None => {
                let mut statement = self.conn.prepare(
                    "SELECT id, employee_id, title, status, due_on, progress_bp, created_at
                     FROM goals ORDER BY created_at DESC",
                )?;
                for row in statement.query_map([], &mut push)? {
                    goals.push(row?);
                }
            }
        }
        Ok(goals)
    }

    // ------------------------------------------------------------------
    // Offboarding
    // ------------------------------------------------------------------

    pub fn save_offboarding_plan(&mut self, plan: &OffboardingPlan) -> StoreResult<()> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        tx.execute(
            "INSERT INTO offboarding_plans
             (id, employee_id, status, last_day, final_pay_run_id, created_at, completed_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7)
             ON CONFLICT(id) DO UPDATE SET status=excluded.status, last_day=excluded.last_day,
                final_pay_run_id=excluded.final_pay_run_id, completed_at=excluded.completed_at",
            params![
                plan.id.to_string(),
                plan.employee_id.to_string(),
                offboarding_status(plan.status),
                plan.last_day.to_string(),
                plan.final_pay_run_id.map(|id| id.to_string()),
                plan.created_at.millis(),
                plan.completed_at.map(|instant| instant.millis()),
            ],
        )?;
        for (position, step) in plan.steps.iter().enumerate() {
            tx.execute(
                "INSERT INTO offboarding_steps
                 (plan_id, step_key, title, owner, status, completed_at, notes, position)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8)
                 ON CONFLICT(plan_id, step_key) DO UPDATE SET title=excluded.title,
                    owner=excluded.owner, status=excluded.status, completed_at=excluded.completed_at,
                    notes=excluded.notes, position=excluded.position",
                params![
                    plan.id.to_string(),
                    step.key,
                    step.title,
                    step.owner,
                    offboarding_step_status(step.status),
                    step.completed_at.map(|instant| instant.millis()),
                    step.notes,
                    position as i64,
                ],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn offboarding_plan_for(
        &self,
        employee_id: EmployeeId,
    ) -> StoreResult<Option<OffboardingPlan>> {
        let plan = self
            .conn
            .query_row(
                "SELECT id, employee_id, status, last_day, final_pay_run_id, created_at, completed_at
                 FROM offboarding_plans WHERE employee_id = ?1 ORDER BY created_at DESC LIMIT 1",
                params![employee_id.to_string()],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, Option<String>>(4)?,
                        row.get::<_, i64>(5)?,
                        row.get::<_, Option<i64>>(6)?,
                    ))
                },
            )
            .optional()?;
        let Some((id, employee_id, status, last_day, final_pay_run_id, created_at, completed_at)) =
            plan
        else {
            return Ok(None);
        };
        let mut statement = self.conn.prepare(
            "SELECT step_key, title, owner, status, completed_at, notes
             FROM offboarding_steps WHERE plan_id = ?1 ORDER BY position",
        )?;
        let rows = statement.query_map(params![id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, Option<i64>>(4)?,
                row.get::<_, Option<String>>(5)?,
            ))
        })?;
        let mut steps = Vec::new();
        for row in rows {
            let row = row?;
            steps.push(OffboardingStep {
                key: row.0,
                title: row.1,
                owner: row.2,
                required: true,
                status: parse_offboarding_step_status(&row.3)?,
                completed_at: row.4.map(instant).transpose()?,
                completed_by: None,
                notes: row.5,
            });
        }
        Ok(Some(OffboardingPlan {
            id: parse_id(&id, "offboarding_plan")?,
            employee_id: parse_id(&employee_id, "employee")?,
            last_day: parse_date(&last_day)?,
            status: parse_offboarding_status(&status)?,
            steps,
            final_pay_run_id: final_pay_run_id
                .as_deref()
                .map(|raw| parse_id::<PayrollRunId>(raw, "payroll_run"))
                .transpose()?,
            created_at: instant(created_at)?,
            completed_at: completed_at.map(instant).transpose()?,
        }))
    }

    // ------------------------------------------------------------------
    // Document requests
    // ------------------------------------------------------------------

    pub fn save_document_request(&mut self, request: &DocumentRequest) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO document_requests
             (id, employee_id, document_type, status, requested_at, due_on, document_id, note)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8)
             ON CONFLICT(id) DO UPDATE SET status=excluded.status, due_on=excluded.due_on,
                document_id=excluded.document_id, note=excluded.note",
            params![
                request.id.to_string(),
                request.employee_id.to_string(),
                request.document_type,
                document_request_status(request.status),
                request.requested_at.millis(),
                request.due_on.map(|date| date.to_string()),
                request.document_id.map(|id| id.to_string()),
                request.note,
            ],
        )?;
        Ok(())
    }

    pub fn list_document_requests(
        &self,
        employee_id: Option<EmployeeId>,
    ) -> StoreResult<Vec<DocumentRequest>> {
        let mut requests = Vec::new();
        let mut push = |row: &rusqlite::Row<'_>| -> rusqlite::Result<DocumentRequest> {
            Ok(DocumentRequest {
                id: parse_id(&row.get::<_, String>(0)?, "document_request")?,
                employee_id: parse_id(&row.get::<_, String>(1)?, "employee")?,
                document_type: row.get(2)?,
                status: parse_document_request_status(&row.get::<_, String>(3)?)?,
                requested_at: instant(row.get(4)?)?,
                due_on: row
                    .get::<_, Option<String>>(5)?
                    .as_deref()
                    .map(parse_date)
                    .transpose()?,
                document_id: row
                    .get::<_, Option<String>>(6)?
                    .as_deref()
                    .map(|raw| parse_id::<DocumentId>(raw, "document"))
                    .transpose()?,
                note: row.get(7)?,
            })
        };
        match employee_id {
            Some(employee_id) => {
                let mut statement = self.conn.prepare(
                    "SELECT id, employee_id, document_type, status, requested_at, due_on, document_id, note
                     FROM document_requests WHERE employee_id = ?1 ORDER BY requested_at DESC",
                )?;
                for row in statement.query_map(params![employee_id.to_string()], &mut push)? {
                    requests.push(row?);
                }
            }
            None => {
                let mut statement = self.conn.prepare(
                    "SELECT id, employee_id, document_type, status, requested_at, due_on, document_id, note
                     FROM document_requests ORDER BY requested_at DESC",
                )?;
                for row in statement.query_map([], &mut push)? {
                    requests.push(row?);
                }
            }
        }
        Ok(requests)
    }

    // ------------------------------------------------------------------
    // Hiring communications: scheduling, offers, messages, feedback
    // ------------------------------------------------------------------

    pub fn save_schedule_proposal(
        &mut self,
        proposal: &hragents_core::hiring_comms::ScheduleProposal,
    ) -> StoreResult<()> {
        use hragents_core::hiring_comms::ProposalStatus;
        let status = match proposal.status {
            ProposalStatus::Proposed => "proposed",
            ProposalStatus::Confirmed => "confirmed",
            ProposalStatus::Declined => "declined",
            ProposalStatus::Expired => "expired",
        };
        self.conn.execute(
            "INSERT INTO schedule_proposals (id, application_id, slots_json, status, created_at)
             VALUES (?1,?2,?3,?4,?5)
             ON CONFLICT(id) DO UPDATE SET slots_json=excluded.slots_json,
                status=excluded.status",
            params![
                proposal.id.to_string(),
                proposal.application_id.to_string(),
                serde_json::to_string(&proposal.slots)?,
                status,
                proposal.created_at.millis(),
            ],
        )?;
        Ok(())
    }

    pub fn list_schedule_proposals(
        &self,
        application_id: Option<ApplicationId>,
    ) -> StoreResult<Vec<hragents_core::hiring_comms::ScheduleProposal>> {
        use hragents_core::hiring_comms::{InterviewSlot, ProposalStatus, ScheduleProposal};
        let mut proposals = Vec::new();
        let mut push = |row: &rusqlite::Row<'_>| -> rusqlite::Result<ScheduleProposal> {
            let status = match row.get::<_, String>(3)?.as_str() {
                "confirmed" => ProposalStatus::Confirmed,
                "declined" => ProposalStatus::Declined,
                "expired" => ProposalStatus::Expired,
                _ => ProposalStatus::Proposed,
            };
            Ok(ScheduleProposal {
                id: parse_id(&row.get::<_, String>(0)?, "schedule")?,
                application_id: parse_id(&row.get::<_, String>(1)?, "application")?,
                slots: serde_json::from_str::<Vec<InterviewSlot>>(&row.get::<_, String>(2)?)
                    .map_err(json_err)?,
                status,
                confirmed_index: None,
                created_at: instant(row.get(4)?)?,
                decided_at: None,
            })
        };
        match application_id {
            Some(application_id) => {
                let mut statement = self.conn.prepare(
                    "SELECT id, application_id, slots_json, status, created_at
                     FROM schedule_proposals WHERE application_id = ?1 ORDER BY created_at DESC",
                )?;
                for row in statement.query_map(params![application_id.to_string()], &mut push)? {
                    proposals.push(row?);
                }
            }
            None => {
                let mut statement = self.conn.prepare(
                    "SELECT id, application_id, slots_json, status, created_at
                     FROM schedule_proposals ORDER BY created_at DESC",
                )?;
                for row in statement.query_map([], &mut push)? {
                    proposals.push(row?);
                }
            }
        }
        Ok(proposals)
    }

    pub fn save_offer(&mut self, offer: &hragents_core::hiring_comms::Offer) -> StoreResult<()> {
        use hragents_core::hiring_comms::OfferStatus;
        let status = match offer.status {
            OfferStatus::Draft => "draft",
            OfferStatus::Approved => "approved",
            OfferStatus::Sent => "sent",
            OfferStatus::Accepted => "accepted",
            OfferStatus::Declined => "declined",
            OfferStatus::Expired => "expired",
        };
        self.conn.execute(
            "INSERT INTO offers
             (id, application_id, status, salary_sen, start_date, expires_on, created_at, decided_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8)
             ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                salary_sen=excluded.salary_sen, start_date=excluded.start_date,
                expires_on=excluded.expires_on, decided_at=excluded.decided_at",
            params![
                offer.id.to_string(),
                offer.application_id.to_string(),
                status,
                offer.salary_sen.map(|money| money.sen()),
                offer.start_date.map(|date| date.to_string()),
                offer.expires_on.map(|date| date.to_string()),
                offer.created_at.millis(),
                offer.decided_at.map(|instant| instant.millis()),
            ],
        )?;
        Ok(())
    }

    pub fn list_offers(
        &self,
        application_id: Option<ApplicationId>,
    ) -> StoreResult<Vec<hragents_core::hiring_comms::Offer>> {
        use hragents_core::hiring_comms::{Offer, OfferStatus};
        let mut offers = Vec::new();
        let mut push = |row: &rusqlite::Row<'_>| -> rusqlite::Result<Offer> {
            let status = match row.get::<_, String>(2)?.as_str() {
                "approved" => OfferStatus::Approved,
                "sent" => OfferStatus::Sent,
                "accepted" => OfferStatus::Accepted,
                "declined" => OfferStatus::Declined,
                "expired" => OfferStatus::Expired,
                _ => OfferStatus::Draft,
            };
            Ok(Offer {
                id: parse_id(&row.get::<_, String>(0)?, "offer")?,
                application_id: parse_id(&row.get::<_, String>(1)?, "application")?,
                position_title: String::new(),
                salary_sen: row.get::<_, Option<i64>>(3)?.map(Money::from_sen),
                start_date: row
                    .get::<_, Option<String>>(4)?
                    .as_deref()
                    .map(parse_date)
                    .transpose()?,
                expires_on: row
                    .get::<_, Option<String>>(5)?
                    .as_deref()
                    .map(parse_date)
                    .transpose()?,
                status,
                note: None,
                created_at: instant(row.get(6)?)?,
                decided_at: row.get::<_, Option<i64>>(7)?.map(instant).transpose()?,
            })
        };
        match application_id {
            Some(application_id) => {
                let mut statement = self.conn.prepare(
                    "SELECT id, application_id, status, salary_sen, start_date, expires_on,
                            created_at, decided_at
                     FROM offers WHERE application_id = ?1 ORDER BY created_at DESC",
                )?;
                for row in statement.query_map(params![application_id.to_string()], &mut push)? {
                    offers.push(row?);
                }
            }
            None => {
                let mut statement = self.conn.prepare(
                    "SELECT id, application_id, status, salary_sen, start_date, expires_on,
                            created_at, decided_at
                     FROM offers ORDER BY created_at DESC",
                )?;
                for row in statement.query_map([], &mut push)? {
                    offers.push(row?);
                }
            }
        }
        Ok(offers)
    }

    pub fn save_message(
        &mut self,
        message: &hragents_core::hiring_comms::CandidateMessage,
    ) -> StoreResult<()> {
        use hragents_core::hiring_comms::{MessageChannel, MessageDirection, MessageStatus};
        let channel = match message.channel {
            MessageChannel::Email => "email",
            MessageChannel::Whatsapp => "whatsapp",
            MessageChannel::Phone => "phone",
            MessageChannel::Note => "note",
        };
        let direction = match message.direction {
            MessageDirection::Outbound => "outbound",
            MessageDirection::Inbound => "inbound",
        };
        let status = match message.status {
            MessageStatus::Draft => "draft",
            MessageStatus::Queued => "queued",
            MessageStatus::Sent => "sent",
            MessageStatus::Cancelled => "cancelled",
        };
        self.conn.execute(
            "INSERT INTO candidate_communications
             (id, candidate_id, application_id, channel, direction, subject, body, status, created_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)
             ON CONFLICT(id) DO UPDATE SET channel=excluded.channel, subject=excluded.subject,
                body=excluded.body, status=excluded.status",
            params![
                message.id.to_string(),
                message.candidate_id.to_string(),
                message.application_id.map(|id| id.to_string()),
                channel,
                direction,
                message.subject,
                message.body,
                status,
                message.created_at.millis(),
            ],
        )?;
        Ok(())
    }

    pub fn list_messages(
        &self,
        application_id: Option<ApplicationId>,
    ) -> StoreResult<Vec<hragents_core::hiring_comms::CandidateMessage>> {
        use hragents_core::hiring_comms::{
            CandidateMessage, MessageChannel, MessageDirection, MessageKind, MessageStatus,
        };
        let mut messages = Vec::new();
        let mut push = |row: &rusqlite::Row<'_>| -> rusqlite::Result<CandidateMessage> {
            let channel = match row.get::<_, String>(3)?.as_str() {
                "whatsapp" => MessageChannel::Whatsapp,
                "phone" => MessageChannel::Phone,
                "note" => MessageChannel::Note,
                _ => MessageChannel::Email,
            };
            let direction = match row.get::<_, String>(4)?.as_str() {
                "inbound" => MessageDirection::Inbound,
                _ => MessageDirection::Outbound,
            };
            let status = match row.get::<_, String>(7)?.as_str() {
                "queued" => MessageStatus::Queued,
                "sent" => MessageStatus::Sent,
                "cancelled" => MessageStatus::Cancelled,
                _ => MessageStatus::Draft,
            };
            Ok(CandidateMessage {
                id: parse_id(&row.get::<_, String>(0)?, "message")?,
                candidate_id: parse_id(&row.get::<_, String>(1)?, "candidate")?,
                application_id: row
                    .get::<_, Option<String>>(2)?
                    .as_deref()
                    .map(|raw| parse_id::<ApplicationId>(raw, "application"))
                    .transpose()?,
                kind: MessageKind::Update,
                channel,
                subject: row.get(5)?,
                body: row.get(6)?,
                status,
                direction,
                created_at: instant(row.get(8)?)?,
                sent_at: None,
            })
        };
        match application_id {
            Some(application_id) => {
                let mut statement = self.conn.prepare(
                    "SELECT id, candidate_id, application_id, channel, direction, subject, body,
                            status, created_at
                     FROM candidate_communications WHERE application_id = ?1 ORDER BY created_at",
                )?;
                for row in statement.query_map(params![application_id.to_string()], &mut push)? {
                    messages.push(row?);
                }
            }
            None => {
                let mut statement = self.conn.prepare(
                    "SELECT id, candidate_id, application_id, channel, direction, subject, body,
                            status, created_at
                     FROM candidate_communications ORDER BY created_at DESC LIMIT 200",
                )?;
                for row in statement.query_map([], &mut push)? {
                    messages.push(row?);
                }
            }
        }
        Ok(messages)
    }

    pub fn save_feedback(
        &mut self,
        report: &hragents_core::hiring_comms::FeedbackReport,
    ) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO feedback_reports (id, application_id, body, created_at)
             VALUES (?1,?2,?3,?4)
             ON CONFLICT(id) DO UPDATE SET body=excluded.body",
            params![
                report.id.to_string(),
                report.application_id.to_string(),
                serde_json::to_string(report)?,
                report.created_at.millis(),
            ],
        )?;
        Ok(())
    }

    pub fn feedback_for(
        &self,
        application_id: ApplicationId,
    ) -> StoreResult<Option<hragents_core::hiring_comms::FeedbackReport>> {
        use hragents_core::hiring_comms::FeedbackReport;
        let row = self
            .conn
            .query_row(
                "SELECT id, application_id, body, created_at
                 FROM feedback_reports WHERE application_id = ?1 ORDER BY created_at DESC LIMIT 1",
                params![application_id.to_string()],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, i64>(3)?,
                    ))
                },
            )
            .optional()?;
        let Some((id, application_id, body, created_at)) = row else {
            return Ok(None);
        };
        let mut report: FeedbackReport = serde_json::from_str(&body).map_err(json_err)?;
        // Backfill identity columns for rows written before they existed.
        if report.id.to_string() != id {
            report.id = parse_id(&id, "feedback")?;
        }
        if report.application_id.to_string() != application_id {
            report.application_id = parse_id(&application_id, "application")?;
        }
        if report.created_at.millis() != created_at {
            report.created_at = instant(created_at)?;
        }
        Ok(Some(report))
    }

    // ------------------------------------------------------------------
    // Compliance: retention, erasure, breach
    // ------------------------------------------------------------------

    pub fn save_retention_policy(
        &mut self,
        policy: &hragents_core::compliance::RetentionPolicy,
    ) -> StoreResult<()> {
        use hragents_core::compliance::RetentionAction;
        let action = match policy.action {
            RetentionAction::Purge => "purge",
            RetentionAction::Anonymize => "anonymize",
            RetentionAction::Archive => "archive",
        };
        self.conn.execute(
            "INSERT INTO retention_policies (id, record_type, retention_months, action, legal_basis, active)
             VALUES (?1,?2,?3,?4,?5,?6)
             ON CONFLICT(id) DO UPDATE SET record_type=excluded.record_type,
                retention_months=excluded.retention_months, action=excluded.action,
                legal_basis=excluded.legal_basis, active=excluded.active",
            params![
                policy.id,
                policy.record_type,
                policy.retention_months,
                action,
                policy.legal_basis,
                i64::from(policy.active),
            ],
        )?;
        Ok(())
    }

    pub fn list_retention_policies(
        &self,
    ) -> StoreResult<Vec<hragents_core::compliance::RetentionPolicy>> {
        use hragents_core::compliance::{RetentionAction, RetentionPolicy};
        let mut statement = self.conn.prepare(
            "SELECT id, record_type, retention_months, action, legal_basis, active
             FROM retention_policies ORDER BY record_type",
        )?;
        let rows = statement.query_map([], |row| {
            let action = match row.get::<_, String>(3)?.as_str() {
                "anonymize" => RetentionAction::Anonymize,
                "archive" => RetentionAction::Archive,
                _ => RetentionAction::Purge,
            };
            Ok(RetentionPolicy {
                id: row.get(0)?,
                record_type: row.get(1)?,
                retention_months: row.get(2)?,
                action,
                legal_basis: row.get(4)?,
                active: row.get::<_, i64>(5)? != 0,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn save_retention_hold(
        &mut self,
        hold: &hragents_core::compliance::RetentionHold,
    ) -> StoreResult<()> {
        self.conn.execute(
            "INSERT INTO retention_holds (id, subject_type, subject_id, reason, until, created_by, created_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7)
             ON CONFLICT(id) DO UPDATE SET reason=excluded.reason, until=excluded.until",
            params![
                hold.id,
                subject_type(hold.subject_type),
                hold.subject_id,
                hold.reason,
                hold.until.map(|date| date.to_string()),
                hold.created_by.to_string(),
                hold.created_at.millis(),
            ],
        )?;
        Ok(())
    }

    pub fn list_retention_holds(
        &self,
    ) -> StoreResult<Vec<hragents_core::compliance::RetentionHold>> {
        let mut statement = self.conn.prepare(
            "SELECT id, subject_type, subject_id, reason, until, created_by, created_at
             FROM retention_holds ORDER BY created_at DESC",
        )?;
        let rows = statement.query_map([], |row| {
            Ok(hragents_core::compliance::RetentionHold {
                id: row.get(0)?,
                subject_type: parse_subject_type(&row.get::<_, String>(1)?)?,
                subject_id: row.get(2)?,
                reason: row.get(3)?,
                until: row
                    .get::<_, Option<String>>(4)?
                    .as_deref()
                    .map(parse_date)
                    .transpose()?,
                created_by: parse_id(&row.get::<_, String>(5)?, "operator")?,
                created_at: instant(row.get(6)?)?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn delete_retention_hold(&mut self, id: &str) -> StoreResult<()> {
        self.conn
            .execute("DELETE FROM retention_holds WHERE id = ?1", params![id])?;
        Ok(())
    }

    pub fn save_erasure_request(
        &mut self,
        request: &hragents_core::compliance::ErasureRequest,
    ) -> StoreResult<()> {
        use hragents_core::compliance::ErasureStatus;
        let status = match request.status {
            ErasureStatus::Pending => "pending",
            ErasureStatus::Approved => "approved",
            ErasureStatus::Rejected => "rejected",
            ErasureStatus::Completed => "completed",
            ErasureStatus::Cancelled => "cancelled",
        };
        self.conn.execute(
            "INSERT INTO erasure_requests
             (id, subject_type, subject_id, reason, status, requested_at,
              decided_by, decided_at, executed_at, retained_json)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)
             ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                decided_by=excluded.decided_by, decided_at=excluded.decided_at,
                executed_at=excluded.executed_at, retained_json=excluded.retained_json",
            params![
                request.id.to_string(),
                subject_type(request.subject_type),
                request.subject_id,
                request.reason,
                status,
                request.requested_at.millis(),
                request.decided_by.map(|id| id.to_string()),
                request.decided_at.map(|instant| instant.millis()),
                request.executed_at.map(|instant| instant.millis()),
                serde_json::to_string(&request.retained)?,
            ],
        )?;
        Ok(())
    }

    pub fn list_erasure_requests(
        &self,
    ) -> StoreResult<Vec<hragents_core::compliance::ErasureRequest>> {
        use hragents_core::compliance::{ErasureRequest, ErasureStatus};
        let mut statement = self.conn.prepare(
            "SELECT id, subject_type, subject_id, reason, status, requested_at,
                    decided_by, decided_at, executed_at, retained_json
             FROM erasure_requests ORDER BY requested_at DESC",
        )?;
        let rows = statement.query_map([], |row| {
            let status = match row.get::<_, String>(4)?.as_str() {
                "approved" => ErasureStatus::Approved,
                "rejected" => ErasureStatus::Rejected,
                "completed" => ErasureStatus::Completed,
                "cancelled" => ErasureStatus::Cancelled,
                _ => ErasureStatus::Pending,
            };
            Ok(ErasureRequest {
                id: parse_id(&row.get::<_, String>(0)?, "erasure_request")?,
                subject_type: parse_subject_type(&row.get::<_, String>(1)?)?,
                subject_id: row.get(2)?,
                reason: row.get(3)?,
                status,
                requested_at: instant(row.get(5)?)?,
                decided_by: row
                    .get::<_, Option<String>>(6)?
                    .as_deref()
                    .map(|raw| parse_id::<OperatorId>(raw, "operator"))
                    .transpose()?,
                decided_at: row.get::<_, Option<i64>>(7)?.map(instant).transpose()?,
                executed_at: row.get::<_, Option<i64>>(8)?.map(instant).transpose()?,
                retained: serde_json::from_str(&row.get::<_, String>(9)?).map_err(json_err)?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    /// Execute an approved erasure: delete/purge the subject's personal data.
    /// Audit rows and payroll records survive by design. Returns the plan of
    /// what was purged vs retained.
    pub fn execute_erasure(
        &mut self,
        request: &mut hragents_core::compliance::ErasureRequest,
        hold: Option<&hragents_core::compliance::RetentionHold>,
    ) -> StoreResult<hragents_core::compliance::ErasurePlan> {
        use hragents_core::compliance::SubjectType;
        let today = BusinessDate::today();
        let now = UtcInstant::now();
        let plan = request
            .execute(OperatorId::new(), hold, today, now)
            .map_err(StoreError::Domain)?;
        match request.subject_type {
            SubjectType::Candidate => {
                let _: CandidateId = request
                    .subject_id
                    .parse()
                    .map_err(|_| StoreError::Corrupt("invalid candidate id".into()))?;
                // Purge order respects FKs: documents/links, messages, feedback, then candidate.
                let documents: Vec<String> = self
                    .conn
                    .prepare("SELECT document_id FROM candidate_documents WHERE candidate_id = ?1")?
                    .query_map(params![request.subject_id], |row| row.get(0))?
                    .collect::<Result<Vec<_>, _>>()?;
                self.conn.execute(
                    "DELETE FROM candidate_documents WHERE candidate_id = ?1",
                    params![request.subject_id],
                )?;
                for document_id in &documents {
                    self.conn
                        .execute("DELETE FROM documents WHERE id = ?1", params![document_id])?;
                }
                self.conn.execute(
                    "DELETE FROM candidate_communications WHERE candidate_id = ?1",
                    params![request.subject_id],
                )?;
                self.conn.execute(
                    "DELETE FROM feedback_reports WHERE application_id IN
                     (SELECT id FROM applications WHERE candidate_id = ?1)",
                    params![request.subject_id],
                )?;
                self.conn.execute(
                    "DELETE FROM evaluations WHERE application_id IN
                     (SELECT id FROM applications WHERE candidate_id = ?1)",
                    params![request.subject_id],
                )?;
                self.conn.execute(
                    "DELETE FROM applications WHERE candidate_id = ?1",
                    params![request.subject_id],
                )?;
                self.conn.execute(
                    "DELETE FROM candidates WHERE id = ?1",
                    params![request.subject_id],
                )?;
            }
            SubjectType::Employee => {
                // Employees keep their row (payroll history is statutory), but
                // contact and identity details are cleared.
                self.conn.execute(
                    "UPDATE employees SET email = NULL, phone = NULL, preferred_name = NULL,
                     birth_date = NULL, npwp = NULL, bank_name = NULL, bank_account = NULL,
                     bpjs_kesehatan_no = NULL, bpjs_ketenagakerjaan_no = NULL,
                     updated_at = ?1 WHERE id = ?2",
                    params![now.millis(), request.subject_id],
                )?;
            }
        }
        self.save_erasure_request(request)?;
        Ok(plan)
    }

    pub fn save_breach(
        &mut self,
        incident: &hragents_core::compliance::BreachIncident,
    ) -> StoreResult<()> {
        use hragents_core::compliance::{BreachSeverity, BreachStatus};
        let severity = match incident.severity {
            BreachSeverity::Low => "low",
            BreachSeverity::Medium => "medium",
            BreachSeverity::High => "high",
            BreachSeverity::Critical => "critical",
        };
        let status = match incident.status {
            BreachStatus::Open => "open",
            BreachStatus::Contained => "contained",
            BreachStatus::Notified => "notified",
            BreachStatus::Closed => "closed",
        };
        self.conn.execute(
            "INSERT INTO breach_incidents
             (id, title, description, severity, status, discovered_at,
              contained_at, notified_at, steps_json, owner)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)
             ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                contained_at=excluded.contained_at, notified_at=excluded.notified_at,
                steps_json=excluded.steps_json",
            params![
                incident.id,
                incident.title,
                incident.description,
                severity,
                status,
                incident.discovered_at.millis(),
                incident.contained_at.map(|instant| instant.millis()),
                incident.notified_at.map(|instant| instant.millis()),
                serde_json::to_string(&incident.steps)?,
                incident.owner.to_string(),
            ],
        )?;
        Ok(())
    }

    pub fn list_breaches(&self) -> StoreResult<Vec<hragents_core::compliance::BreachIncident>> {
        use hragents_core::compliance::{BreachIncident, BreachSeverity, BreachStatus};
        let mut statement = self.conn.prepare(
            "SELECT id, title, description, severity, status, discovered_at,
                    contained_at, notified_at, steps_json, owner
             FROM breach_incidents ORDER BY discovered_at DESC",
        )?;
        let rows = statement.query_map([], |row| {
            let severity = match row.get::<_, String>(3)?.as_str() {
                "medium" => BreachSeverity::Medium,
                "high" => BreachSeverity::High,
                "critical" => BreachSeverity::Critical,
                _ => BreachSeverity::Low,
            };
            let status = match row.get::<_, String>(4)?.as_str() {
                "contained" => BreachStatus::Contained,
                "notified" => BreachStatus::Notified,
                "closed" => BreachStatus::Closed,
                _ => BreachStatus::Open,
            };
            Ok(BreachIncident {
                id: row.get(0)?,
                title: row.get(1)?,
                description: row.get(2)?,
                severity,
                status,
                discovered_at: instant(row.get(5)?)?,
                contained_at: row.get::<_, Option<i64>>(6)?.map(instant).transpose()?,
                notified_at: row.get::<_, Option<i64>>(7)?.map(instant).transpose()?,
                steps: serde_json::from_str(&row.get::<_, String>(8)?).map_err(json_err)?,
                owner: parse_id(&row.get::<_, String>(9)?, "operator")?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn list_contracts(&self) -> StoreResult<Vec<Contract>> {
        let mut statement = self.conn.prepare(
            "SELECT id, employee_id, kind, start_date, end_date, status, document_id, created_at
             FROM contracts ORDER BY end_date IS NULL, end_date",
        )?;
        let rows = statement.query_map([], |row| {
            Ok(Contract {
                id: parse_id(&row.get::<_, String>(0)?, "contract")?,
                employee_id: parse_id(&row.get::<_, String>(1)?, "employee")?,
                kind: parse_contract_kind(&row.get::<_, String>(2)?)?,
                start_date: parse_date(&row.get::<_, String>(3)?)?,
                end_date: row
                    .get::<_, Option<String>>(4)?
                    .as_deref()
                    .map(parse_date)
                    .transpose()?,
                status: parse_contract_status(&row.get::<_, String>(5)?)?,
                document_id: row
                    .get::<_, Option<String>>(6)?
                    .as_deref()
                    .map(|raw| parse_id::<DocumentId>(raw, "document"))
                    .transpose()?,
                created_at: instant(row.get(7)?)?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    /// Documents with an expiry on or before `limit` (pending or verified).
    /// Used by the retention sweep and expiry reminders.
    pub fn expiring_documents(&self, limit: BusinessDate) -> StoreResult<Vec<(Document, String)>> {
        let mut statement = self.conn.prepare(
            "SELECT id, owner_type, owner_id, filename, mime_type, sha256, size_bytes, status,
                    expires_on, uploaded_at, verified_at, verified_by, rejection_reason, tags_json
             FROM documents
             WHERE expires_on IS NOT NULL AND expires_on <= ?1
             ORDER BY expires_on",
        )?;
        let rows = statement.query_map(params![limit.to_string()], |row| {
            Ok((
                Document {
                    id: parse_id(&row.get::<_, String>(0)?, "document")?,
                    owner_type: parse_owner_type(&row.get::<_, String>(1)?)?,
                    owner_id: row.get(2)?,
                    filename: row.get(3)?,
                    mime_type: row.get(4)?,
                    sha256: row.get(5)?,
                    size_bytes: row.get(6)?,
                    status: parse_document_status(&row.get::<_, String>(7)?)?,
                    expires_on: row
                        .get::<_, Option<String>>(8)?
                        .as_deref()
                        .map(parse_date)
                        .transpose()?,
                    uploaded_at: instant(row.get(9)?)?,
                    verified_at: row.get::<_, Option<i64>>(10)?.map(instant).transpose()?,
                    verified_by: row.get(11)?,
                    rejection_reason: row.get(12)?,
                    tags: serde_json::from_str(&row.get::<_, String>(13)?).map_err(json_err)?,
                },
                row.get::<_, String>(2)?,
            ))
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
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
enum_mapping!(cycle_status, parse_cycle_status, CycleStatus,
    CycleStatus::Draft => "draft", CycleStatus::Active => "active", CycleStatus::Closed => "closed");
enum_mapping!(assignment_status, parse_assignment_status, AssignmentStatus,
    AssignmentStatus::Pending => "pending", AssignmentStatus::Sent => "sent",
    AssignmentStatus::Submitted => "submitted", AssignmentStatus::Summarized => "summarized");
enum_mapping!(goal_status, parse_goal_status, GoalStatus,
    GoalStatus::Draft => "draft", GoalStatus::Active => "active",
    GoalStatus::Completed => "completed", GoalStatus::Cancelled => "cancelled");
enum_mapping!(offboarding_status, parse_offboarding_status, OffboardingStatus,
    OffboardingStatus::Draft => "draft", OffboardingStatus::InProgress => "in_progress",
    OffboardingStatus::Completed => "completed", OffboardingStatus::Cancelled => "cancelled");
enum_mapping!(offboarding_step_status, parse_offboarding_step_status, OffboardingStepStatus,
    OffboardingStepStatus::Pending => "pending", OffboardingStepStatus::InProgress => "in_progress",
    OffboardingStepStatus::Done => "done", OffboardingStepStatus::Skipped => "skipped");
enum_mapping!(document_request_status, parse_document_request_status, DocumentRequestStatus,
    DocumentRequestStatus::Requested => "requested", DocumentRequestStatus::Uploaded => "uploaded",
    DocumentRequestStatus::Verified => "verified", DocumentRequestStatus::Rejected => "rejected",
    DocumentRequestStatus::Cancelled => "cancelled");

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
    use hragents_core::documents::DocumentRequest;
    use hragents_core::growth::{Goal, ReviewAssignment, ReviewCycle, ReviewForm};
    use hragents_core::offboarding::{OffboardingPlan, OffboardingStep};
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
        assert_eq!(store.schema_version().unwrap(), 2);
        assert_eq!(store.integrity_check().unwrap(), "ok");
        assert_eq!(store.query_count("employees").unwrap(), 0);
    }

    #[test]
    fn hot_path_indexes_exist() {
        let store = store();
        let mut statement = store
            .conn
            .prepare("SELECT name FROM sqlite_master WHERE type = 'index'")
            .unwrap();
        let names = statement
            .query_map([], |row| row.get::<_, String>(0))
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        for expected in [
            "onboarding_plans_employee_status_idx",
            "offers_application_idx",
            "candidate_comms_application_idx",
            "offboarding_plans_employee_idx",
            "goals_employee_idx",
            "chat_messages_conversation_idx",
        ] {
            assert!(names.iter().any(|name| name == expected), "{expected}");
        }
    }

    #[test]
    fn foreign_key_lookups_use_indexes() {
        let store = store();
        let plan = |sql: &str| {
            let mut statement = store
                .conn
                .prepare(&format!("EXPLAIN QUERY PLAN {sql}"))
                .unwrap();
            statement
                .query_map([], |row| row.get::<_, String>(3))
                .unwrap()
                .collect::<Result<Vec<_>, _>>()
                .unwrap()
                .join(" | ")
        };
        for sql in [
            "SELECT id FROM offers WHERE application_id = 'a'",
            "SELECT id FROM goals WHERE employee_id = 'e'",
            "SELECT id FROM chat_messages WHERE conversation_id = 'c'",
            "SELECT id FROM offboarding_plans WHERE employee_id = 'e'",
        ] {
            let detail = plan(sql);
            assert!(detail.contains("INDEX"), "{sql} -> {detail}");
            assert!(!detail.contains("SCAN"), "{sql} -> {detail}");
        }
    }

    #[test]
    fn legacy_v1_schema_gains_missing_columns_on_upgrade() {
        let mut store = store();
        // Reproduce the v1 shape that shipped during development: it reported
        // user_version 1 without these columns, so the index migration failed.
        store
            .conn
            .execute_batch(
                "DROP INDEX IF EXISTS growth_assignments_cycle_idx;
                 ALTER TABLE growth_assignments DROP COLUMN reviewer_email;
                 ALTER TABLE growth_assignments DROP COLUMN created_at;
                 ALTER TABLE growth_assignments DROP COLUMN sent_at;
                 ALTER TABLE growth_assignments DROP COLUMN submitted_at;
                 ALTER TABLE offboarding_plans DROP COLUMN final_pay_run_id;
                 DELETE FROM schema_migrations WHERE version = 2;
                 PRAGMA user_version = 1;",
            )
            .unwrap();
        assert_eq!(store.schema_version().unwrap(), 1);
        store.migrate().unwrap();
        assert_eq!(store.schema_version().unwrap(), 2);
        for (table, column) in [
            ("growth_assignments", "reviewer_email"),
            ("growth_assignments", "created_at"),
            ("growth_assignments", "sent_at"),
            ("growth_assignments", "submitted_at"),
            ("offboarding_plans", "final_pay_run_id"),
        ] {
            let exists = {
                let mut statement = store
                    .conn
                    .prepare(&format!("PRAGMA table_info({table})"))
                    .unwrap();
                let mut rows = statement.query([]).unwrap();
                let mut found = false;
                while let Some(row) = rows.next().unwrap() {
                    if row.get::<_, String>(1).unwrap() == column {
                        found = true;
                        break;
                    }
                }
                found
            };
            assert!(exists, "{table}.{column} was not restored");
        }
        assert_eq!(store.integrity_check().unwrap(), "ok");
    }

    #[test]
    fn list_onboarding_plans_matches_single_lookup() {
        let mut store = store();
        let employee = employee(&store);
        store.save_employee(&employee).unwrap();
        let plan = OnboardingPlan::start(
            employee.id,
            "Standard",
            vec![
                OnboardingStep::new("contract", "Sign contract", "documents"),
                OnboardingStep::new("laptop", "Issue laptop", "assets"),
            ],
            now(),
        )
        .unwrap();
        store.save_onboarding_plan(&plan).unwrap();
        let plans = store.list_onboarding_plans().unwrap();
        assert_eq!(plans.len(), 1);
        let single = store.onboarding_plan_for(employee.id).unwrap().unwrap();
        assert_eq!(plans[0].id, single.id);
        assert_eq!(plans[0].steps.len(), single.steps.len());
        assert_eq!(plans[0].progress(), single.progress());
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
        let recent = store.audit_recent(1).unwrap();
        assert_eq!(recent.len(), 1);
        assert_eq!(recent[0].action, "employee.updated");
        let both = store.audit_recent(10).unwrap();
        assert_eq!(both.len(), 2);
        assert_eq!(both[0].action, "employee.created");
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
    fn growth_offboarding_and_document_requests_roundtrip() {
        let mut store = store();
        let employee = employee(&store);
        store.save_employee(&employee).unwrap();

        let cycle = ReviewCycle::new(
            "2026 H2",
            BusinessDate::parse("2026-07-01").unwrap(),
            BusinessDate::parse("2026-12-31").unwrap(),
            now(),
        )
        .unwrap();
        store.save_review_cycle(&cycle).unwrap();
        assert_eq!(store.list_review_cycles().unwrap().len(), 1);
        let mut assignment =
            ReviewAssignment::new(cycle.id, employee.id, "Ayu", ReviewForm::standard(), now())
                .unwrap();
        assignment.send(now()).unwrap();
        store.save_review_assignment(&assignment).unwrap();
        assert_eq!(
            store.list_review_assignments(Some(cycle.id)).unwrap().len(),
            1
        );

        let mut goal = Goal::new(employee.id, "Ship the desktop beta", now()).unwrap();
        goal.activate().unwrap();
        goal.set_progress(4_000).unwrap();
        store.save_goal(&goal).unwrap();
        assert_eq!(
            store.list_goals(Some(employee.id)).unwrap()[0].progress_bp,
            4_000
        );

        let mut plan = OffboardingPlan::start(
            employee.id,
            BusinessDate::parse("2026-12-31").unwrap(),
            vec![OffboardingStep::new("assets", "Return laptop", "IT")],
            now(),
        )
        .unwrap();
        plan.complete_step("assets", "IT", now()).unwrap();
        store.save_offboarding_plan(&plan).unwrap();
        let loaded = store.offboarding_plan_for(employee.id).unwrap().unwrap();
        assert_eq!(loaded.steps.len(), 1);

        let request = DocumentRequest::new(
            employee.id,
            "KTP",
            Some(BusinessDate::parse("2026-11-10").unwrap()),
            now(),
        )
        .unwrap();
        store.save_document_request(&request).unwrap();
        assert_eq!(
            store
                .list_document_requests(Some(employee.id))
                .unwrap()
                .len(),
            1
        );
    }

    #[test]
    fn hiring_comms_roundtrip() {
        use hragents_core::hiring_comms::{
            CandidateMessage, FeedbackReport, InterviewSlot, MessageChannel, MessageKind, Offer,
            ScheduleProposal, SlotMode,
        };
        use std::collections::BTreeMap;
        let mut store = store();
        let job = Job {
            id: JobId::new(),
            title: "Backend Engineer".into(),
            org_unit: "Product".into(),
            location: "Jakarta".into(),
            employment_type: "full_time".into(),
            status: JobStatus::Open,
            openings: 1,
            rubric_id: None,
            created_at: now(),
        };
        store.save_job(&job).unwrap();
        let candidate = Candidate {
            id: CandidateId::new(),
            full_name: "Dimas Pratama".into(),
            email: None,
            phone: None,
            source: "test".into(),
            headline: None,
            location: None,
            consent: ConsentStatus::Granted,
            document_ids: Vec::new(),
            created_at: now(),
        };
        store.save_candidate(&candidate).unwrap();
        let application = Application {
            id: ApplicationId::new(),
            candidate_id: candidate.id,
            job_id: job.id,
            stage: ApplicationStage::Review,
            priority: 0,
            created_at: now(),
            updated_at: now(),
            rejection_reason: None,
            rejected_by: None,
        };
        store.save_application(&application).unwrap();
        let application_id = application.id;
        let candidate_id = candidate.id;

        let proposal = ScheduleProposal::propose(
            application_id,
            vec![InterviewSlot {
                starts_at: now().plus_seconds(86_400),
                duration_minutes: 60,
                mode: SlotMode::Remote,
                location: None,
            }],
            now(),
        )
        .unwrap();
        store.save_schedule_proposal(&proposal).unwrap();
        let loaded = store.list_schedule_proposals(Some(application_id)).unwrap();
        assert_eq!(loaded.len(), 1);
        assert_eq!(loaded[0].slots.len(), 1);

        let mut offer = Offer::draft(
            application_id,
            "Backend Engineer",
            Some(Money::from_rupiah(12_000_000).unwrap()),
            None,
            None,
            now(),
        )
        .unwrap();
        offer.approve().unwrap();
        offer.send().unwrap();
        store.save_offer(&offer).unwrap();
        let loaded = store.list_offers(Some(application_id)).unwrap();
        assert_eq!(loaded.len(), 1);
        assert_eq!(
            loaded[0].salary_sen,
            Some(Money::from_rupiah(12_000_000).unwrap())
        );

        let mut message = CandidateMessage::draft(
            candidate_id,
            Some(application_id),
            MessageKind::Interview,
            MessageChannel::Email,
            Some("Interview invitation".into()),
            "We would like to invite you to interview next week.",
            now(),
        )
        .unwrap();
        message.queue().unwrap();
        message.mark_sent(now()).unwrap();
        store.save_message(&message).unwrap();
        assert_eq!(store.list_messages(Some(application_id)).unwrap().len(), 1);

        let report = FeedbackReport {
            id: FeedbackId::new(),
            application_id,
            candidate_name: "Dimas".into(),
            job_title: "Backend".into(),
            summary: "Strong interview.".into(),
            strengths: vec!["skills".into()],
            growth_areas: vec![],
            created_at: now(),
        };
        let _ = BTreeMap::<String, String>::new();
        store.save_feedback(&report).unwrap();
        let loaded = store.feedback_for(application_id).unwrap().unwrap();
        assert_eq!(loaded.strengths, vec!["skills".to_owned()]);
        assert!(loaded.summary.contains("Strong interview"));
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
