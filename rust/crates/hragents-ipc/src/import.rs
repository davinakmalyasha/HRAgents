//! One-way import of `hragents-export/1` JSON files.
//!
//! Slice 1 covers `org_units` (for names) and `employees` (with manager links
//! by natural key). Every other table is reported as skipped with its row
//! count, never silently dropped. Dry-run is the default: validation and
//! counts without writing a byte. `--commit` runs the whole import in one
//! store transaction.

use crate::{AppError, AppResult};
use hragents_core::people::{Employee, EmploymentStatus};
use hragents_core::time::{BusinessDate, UtcInstant};
use hragents_store::{ImportReport, Store};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::Path;

pub const SUPPORTED_FORMAT: &str = "hragents-export/1";
pub const KNOWN_TABLES: &[&str] = &["org_units", "employees"];

#[derive(Debug, Clone, Deserialize)]
struct ExportFile {
    manifest: Manifest,
    data: BTreeMap<String, ExportTable>,
}

#[derive(Debug, Clone, Deserialize)]
struct Manifest {
    format: String,
}

#[derive(Debug, Clone, Deserialize)]
struct ExportTable {
    count: usize,
    rows: Vec<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize)]
pub struct TableOutcome {
    pub table: String,
    pub rows: usize,
    pub inserted: usize,
    pub skipped: usize,
    pub errors: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ImportOutcome {
    pub source_hash: String,
    pub committed: bool,
    pub tables: Vec<TableOutcome>,
    pub skipped_tables: Vec<TableSkipped>,
    pub managers_linked: usize,
    pub managers_unresolved: usize,
    pub already_imported: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct TableSkipped {
    pub table: String,
    pub rows: usize,
}

fn map_status(raw: &str, employee_no: &str) -> Result<EmploymentStatus, String> {
    match raw {
        "active" => Ok(EmploymentStatus::Active),
        "probation" | "onboarding" => Ok(EmploymentStatus::Probation),
        "notice_period" => Ok(EmploymentStatus::Notice),
        "offboarded" => Ok(EmploymentStatus::Exited),
        other => Err(format!(
            "employee {employee_no}: unknown status {other:?}; expected one of active, probation, onboarding, notice_period, offboarded"
        )),
    }
}

fn map_employee(
    value: &serde_json::Value,
    org_names: &BTreeMap<String, String>,
    now: UtcInstant,
) -> Result<Employee, String> {
    let get = |key: &str| -> &str { value.get(key).and_then(|item| item.as_str()).unwrap_or("") };
    let employee_no = value
        .get("employee_number")
        .and_then(|item| item.as_str())
        .unwrap_or("")
        .trim()
        .to_owned();
    if employee_no.is_empty() {
        return Err("employee row without an employee_number cannot be imported".into());
    }
    let full_name = get("full_name").trim().to_owned();
    let job_title = get("job_title").trim().to_owned();
    if job_title.is_empty() {
        return Err(format!("employee {employee_no}: job_title is required"));
    }
    let org_unit = match value.get("org_unit_id").and_then(|item| item.as_str()) {
        Some(id) => org_names.get(id).cloned().ok_or_else(|| {
            format!("employee {employee_no}: org unit {id} is not in the export's org_units table")
        })?,
        None => "Imported".to_owned(),
    };
    let hire_date = match value.get("hire_date").and_then(|item| item.as_str()) {
        Some(raw) => BusinessDate::parse(raw)
            .map_err(|_| format!("employee {employee_no}: hire_date {raw:?} is not ISO-8601"))?,
        None => {
            return Err(format!(
                "employee {employee_no}: hire_date is required and missing"
            ));
        }
    };
    let status = map_status(get("status"), &employee_no)?;
    let end_date = if status == EmploymentStatus::Exited {
        match value.get("offboarded_on").and_then(|item| item.as_str()) {
            Some(raw) => Some(BusinessDate::parse(raw).map_err(|_| {
                format!("employee {employee_no}: offboarded_on {raw:?} is not ISO-8601")
            })?),
            None => {
                return Err(format!(
                    "employee {employee_no}: offboarded status needs offboarded_on"
                ));
            }
        }
    } else {
        None
    };
    let id: hragents_core::ids::EmployeeId = value
        .get("id")
        .and_then(|item| item.as_str())
        .unwrap_or("")
        .parse()
        .map_err(|_| format!("employee {employee_no}: id is not a UUID"))?;
    let manager_id = match value.get("manager_id").and_then(|item| item.as_str()) {
        Some(raw) => Some(
            raw.parse()
                .map_err(|_| format!("employee {employee_no}: manager_id is not a UUID"))?,
        ),
        None => None,
    };
    let mut employee = Employee::new(employee_no, full_name, job_title, org_unit, hire_date, now);
    employee.id = id;
    employee.email = value
        .get("email")
        .and_then(|item| item.as_str())
        .map(str::to_owned);
    employee.phone = value
        .get("phone")
        .and_then(|item| item.as_str())
        .map(str::to_owned);
    employee.manager_id = manager_id;
    employee.status = status;
    employee.end_date = end_date;
    employee.created_at = now;
    employee.updated_at = now;
    employee
        .validate()
        .map_err(|error| format!("employee {}: {error}", employee.employee_no))?;
    Ok(employee)
}

struct PreparedImport {
    employees: Vec<Employee>,
    tables: Vec<TableOutcome>,
    skipped_tables: Vec<TableSkipped>,
    source_hash: String,
}

/// Parse and validate an export file. Returns the mapped employees, per-table
/// outcomes for the dry-run report, and skipped tables. Writes nothing.
fn prepare(path: &Path) -> AppResult<PreparedImport> {
    let raw = std::fs::read(path).map_err(|error| {
        AppError::Export(format!("read import file {}: {error}", path.display()))
    })?;
    let source_hash = {
        use sha2::Digest;
        let digest = sha2::Sha256::digest(&raw);
        const HEX: &[u8; 16] = b"0123456789abcdef";
        let mut out = String::with_capacity(digest.len() * 2);
        for byte in digest {
            out.push(HEX[(byte >> 4) as usize] as char);
            out.push(HEX[(byte & 0x0f) as usize] as char);
        }
        out
    };
    let file: ExportFile = serde_json::from_slice(&raw)
        .map_err(|error| AppError::Export(format!("parse {}: {error}", path.display())))?;
    if file.manifest.format != SUPPORTED_FORMAT {
        return Err(AppError::Export(format!(
            "unsupported export format {:?}; expected {SUPPORTED_FORMAT}",
            file.manifest.format
        )));
    }
    let mut outcomes = Vec::new();
    let mut skipped_tables = Vec::new();
    for (name, table) in &file.data {
        if !KNOWN_TABLES.contains(&name.as_str()) {
            skipped_tables.push(TableSkipped {
                table: name.clone(),
                rows: table.rows.len(),
            });
            continue;
        }
        if table.rows.len() != table.count {
            outcomes.push(TableOutcome {
                table: name.clone(),
                rows: table.rows.len(),
                inserted: 0,
                skipped: 0,
                errors: vec![format!(
                    "manifest count {} does not match {} rows",
                    table.count,
                    table.rows.len()
                )],
            });
        }
    }
    if outcomes.iter().any(|outcome| !outcome.errors.is_empty()) {
        return Ok(PreparedImport {
            employees: Vec::new(),
            tables: outcomes,
            skipped_tables,
            source_hash,
        });
    }

    let org_names: BTreeMap<String, String> = file
        .data
        .get("org_units")
        .map(|table| {
            table
                .rows
                .iter()
                .filter_map(|row| {
                    Some((
                        row.get("id")?.as_str()?.to_owned(),
                        row.get("name")?.as_str()?.to_owned(),
                    ))
                })
                .collect()
        })
        .unwrap_or_default();

    let now = UtcInstant::now();
    let mut employees = Vec::new();
    let mut errors = Vec::new();
    if let Some(table) = file.data.get("employees") {
        for row in &table.rows {
            match map_employee(row, &org_names, now) {
                Ok(employee) => employees.push(employee),
                Err(error) => errors.push(error),
            }
        }
        outcomes.push(TableOutcome {
            table: "employees".into(),
            rows: table.rows.len(),
            inserted: 0,
            skipped: 0,
            errors,
        });
    }
    Ok(PreparedImport {
        employees,
        tables: outcomes,
        skipped_tables,
        source_hash,
    })
}

/// Dry-run: validate everything, report counts and errors, write nothing.
pub fn dry_run(path: &Path) -> AppResult<ImportOutcome> {
    let prepared = prepare(path)?;
    Ok(ImportOutcome {
        source_hash: prepared.source_hash,
        committed: false,
        tables: prepared.tables,
        skipped_tables: prepared.skipped_tables,
        managers_linked: 0,
        managers_unresolved: 0,
        already_imported: false,
    })
}

/// Commit: validate, then import employees in one transaction with one audit
/// entry. Re-running the same file is a no-op.
pub fn commit(store: &mut Store, path: &Path, source: &str) -> AppResult<ImportOutcome> {
    let prepared = prepare(path)?;
    let PreparedImport {
        employees,
        mut tables,
        skipped_tables,
        source_hash,
    } = prepared;
    if tables.iter().any(|table| !table.errors.is_empty()) {
        return Ok(ImportOutcome {
            source_hash,
            committed: false,
            tables,
            skipped_tables,
            managers_linked: 0,
            managers_unresolved: 0,
            already_imported: false,
        });
    }
    let actor = hragents_core::audit::AuditActor::system("hragents-import");
    let now = UtcInstant::now();
    let report: ImportReport = store.import_employees(
        &employees,
        &actor,
        source,
        &source_hash,
        SUPPORTED_FORMAT,
        now,
    )?;
    for table in &mut tables {
        if table.table == "employees" {
            table.inserted = report.inserted;
            table.skipped = report.skipped;
        }
    }
    Ok(ImportOutcome {
        source_hash,
        committed: !report.already_imported,
        tables,
        skipped_tables,
        managers_linked: report.managers_linked,
        managers_unresolved: report.managers_unresolved,
        already_imported: report.already_imported,
    })
}
