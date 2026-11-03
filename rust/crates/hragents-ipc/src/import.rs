//! One-way import of `hragents-export/1` JSON files.
//!
//! Slice 1 covers `org_units` (for names) and `employees` (with manager links
//! by natural key). Every other table is reported as skipped with its row
//! count, never silently dropped. Dry-run is the default: validation and
//! counts without writing a byte. `--commit` runs the whole import in one
//! store transaction.

use crate::{AppError, AppResult};
use hragents_core::ids::{EmployeeId, LeaveRequestId, LeaveTypeId, OperatorId};
use hragents_core::leave::{LeaveRequest, LeaveStatus, LeaveType};
use hragents_core::money::Money;
use hragents_core::payroll::{
    PayrollAnomaly, PayrollKind, PayrollLine, PayrollRun, RunStatus, Severity,
};
use hragents_core::people::{Employee, EmploymentStatus};
use hragents_core::time::{BusinessDate, UtcInstant};
use hragents_store::{
    ImportReport, LeaveImportBatch, LeaveImportReport, PayrollImportBatch, Store,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::Path;

pub const SUPPORTED_FORMAT: &str = "hragents-export/1";
pub const KNOWN_TABLES: &[&str] = &[
    "org_units",
    "employees",
    "leave_policies",
    "leave_requests",
    "payroll_runs",
    "payroll_lines",
];

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
    pub drafts_skipped: usize,
    pub non_final_skipped: usize,
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
    leave_types: Vec<LeaveType>,
    leave_requests: Vec<LeaveRequest>,
    drafts_skipped: usize,
    payroll: Vec<(PayrollRun, Vec<PayrollLine>)>,
    non_final_skipped: usize,
    tables: Vec<TableOutcome>,
    skipped_tables: Vec<TableSkipped>,
    source_hash: String,
}

fn round_days_x2(days: f64, what: &str) -> Result<i32, String> {
    if !days.is_finite() || days <= 0.0 {
        return Err(format!("{what} must be positive, got {days}"));
    }
    let doubled = (days * 2.0).round();
    if doubled > i32::MAX as f64 {
        return Err(format!("{what} is unreasonably large: {days}"));
    }
    Ok(doubled as i32)
}

fn map_leave_type(value: &serde_json::Value) -> Result<LeaveType, String> {
    let key = value
        .get("leave_type")
        .and_then(|item| item.as_str())
        .unwrap_or("")
        .trim();
    if key.is_empty() {
        return Err("leave policy without a leave_type cannot be imported".into());
    }
    let policy = value
        .get("policy")
        .ok_or_else(|| format!("leave policy {key}: policy payload is missing"))?;
    let name = policy
        .get("name")
        .and_then(|item| item.as_str())
        .unwrap_or(key)
        .trim()
        .to_owned();
    let quota = match policy.get("days_per_year") {
        None => 0,
        Some(item) if item.is_null() => 0,
        Some(item) => {
            let days = item
                .as_f64()
                .ok_or_else(|| format!("leave policy {key}: days_per_year is not a number"))?;
            round_days_x2(days, &format!("leave policy {key} days_per_year"))?
        }
    };
    let carryover = if policy
        .get("carryover_allowed")
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(false)
    {
        match policy.get("carryover_max_days") {
            None => {
                return Err(format!(
                    "leave policy {key}: carryover is allowed but carryover_max_days is missing"
                ));
            }
            Some(item) if item.is_null() => {
                return Err(format!(
                    "leave policy {key}: carryover is allowed but carryover_max_days is null"
                ));
            }
            Some(item) => {
                let days = item.as_f64().ok_or_else(|| {
                    format!("leave policy {key}: carryover_max_days is not a number")
                })?;
                round_days_x2(days, &format!("leave policy {key} carryover_max_days"))?
            }
        }
    } else {
        0
    };
    let id: LeaveTypeId = value
        .get("id")
        .and_then(|item| item.as_str())
        .unwrap_or("")
        .parse()
        .map_err(|_| format!("leave policy {key}: id is not a UUID"))?;
    Ok(LeaveType {
        id,
        name,
        annual_quota_x2: quota,
        carry_over_max_x2: carryover,
        requires_attachment: policy
            .get("requires_document")
            .and_then(serde_json::Value::as_bool)
            .unwrap_or(false),
        active: true,
    })
}

fn map_leave_status(raw: &str, request: &str) -> Result<Option<LeaveStatus>, String> {
    match raw {
        "pending" => Ok(Some(LeaveStatus::Pending)),
        "approved" => Ok(Some(LeaveStatus::Approved)),
        "rejected" => Ok(Some(LeaveStatus::Rejected)),
        "cancelled" => Ok(Some(LeaveStatus::Cancelled)),
        // Drafts were never submitted. Importing them as pending would invent
        // demand, so the importer counts and skips them instead.
        "draft" => Ok(None),
        other => Err(format!(
            "leave request {request}: unknown status {other:?}; expected one of draft, pending, approved, rejected, cancelled"
        )),
    }
}

#[allow(clippy::too_many_arguments)]
fn map_leave_request(
    value: &serde_json::Value,
    policy_ids: &std::collections::BTreeMap<String, LeaveTypeId>,
    known_employees: &std::collections::BTreeSet<EmployeeId>,
    now: UtcInstant,
) -> Result<Option<LeaveRequest>, String> {
    let id: LeaveRequestId = value
        .get("id")
        .and_then(|item| item.as_str())
        .unwrap_or("")
        .parse()
        .map_err(|_| "leave request without a UUID id cannot be imported".to_owned())?;
    let label = id.to_string();
    let employee_id: EmployeeId = value
        .get("employee_id")
        .and_then(|item| item.as_str())
        .unwrap_or("")
        .parse()
        .map_err(|_| format!("leave request {label}: employee_id is not a UUID"))?;
    if !known_employees.contains(&employee_id) {
        return Err(format!(
            "leave request {label}: employee {employee_id} is in neither the database nor this import"
        ));
    }
    let leave_type = value
        .get("leave_type")
        .and_then(|item| item.as_str())
        .unwrap_or("")
        .trim();
    let leave_type_id = policy_ids.get(leave_type).copied().ok_or_else(|| {
        format!("leave request {label}: leave type {leave_type:?} has no policy in this export")
    })?;
    let status = map_leave_status(
        value
            .get("status")
            .and_then(|item| item.as_str())
            .unwrap_or(""),
        &label,
    )?;
    let Some(status) = status else {
        return Ok(None);
    };
    if value
        .get("document_id")
        .and_then(|item| item.as_str())
        .is_some()
    {
        return Err(format!(
            "leave request {label}: attachments live in object storage, which the database export excludes; attach the document after import"
        ));
    }
    let start_date = value
        .get("start_date")
        .and_then(|item| item.as_str())
        .unwrap_or("");
    let start_date = BusinessDate::parse(start_date)
        .map_err(|_| format!("leave request {label}: start_date {start_date:?} is not ISO-8601"))?;
    let end_date = value
        .get("end_date")
        .and_then(|item| item.as_str())
        .unwrap_or("");
    let end_date = BusinessDate::parse(end_date)
        .map_err(|_| format!("leave request {label}: end_date {end_date:?} is not ISO-8601"))?;
    if end_date < start_date {
        return Err(format!(
            "leave request {label}: end date {end_date} precedes start date {start_date}"
        ));
    }
    let days = value
        .get("days")
        .and_then(serde_json::Value::as_f64)
        .unwrap_or(0.0);
    let days_x2 = round_days_x2(days, &format!("leave request {label} days"))?;
    Ok(Some(LeaveRequest {
        id,
        employee_id,
        leave_type_id,
        start_date,
        end_date,
        days_x2,
        half_day_start: false,
        half_day_end: false,
        reason: value
            .get("reason")
            .and_then(|item| item.as_str())
            .unwrap_or("")
            .to_owned(),
        status,
        recorded_by: OperatorId::from_uuid(uuid::Uuid::nil()),
        decided_by: None,
        decided_at: None,
        decision_note: None,
        attachment_document_id: None,
        created_at: now,
    }))
}

fn prepare(store: &Store, path: &Path) -> AppResult<PreparedImport> {
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
            leave_types: Vec::new(),
            leave_requests: Vec::new(),
            drafts_skipped: 0,
            payroll: Vec::new(),
            non_final_skipped: 0,
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

    let mut leave_types = Vec::new();
    let mut policy_ids = BTreeMap::new();
    let mut policy_errors = Vec::new();
    if let Some(table) = file.data.get("leave_policies") {
        for row in &table.rows {
            match map_leave_type(row) {
                Ok(leave_type) => {
                    policy_ids.insert(
                        row.get("leave_type")
                            .and_then(|item| item.as_str())
                            .unwrap_or("")
                            .to_owned(),
                        leave_type.id,
                    );
                    leave_types.push(leave_type);
                }
                Err(error) => policy_errors.push(error),
            }
        }
        outcomes.push(TableOutcome {
            table: "leave_policies".into(),
            rows: table.rows.len(),
            inserted: 0,
            skipped: 0,
            errors: policy_errors,
        });
    }

    let mut known_employees: std::collections::BTreeSet<EmployeeId> =
        employees.iter().map(|employee| employee.id).collect();
    for existing in store.list_employees()? {
        known_employees.insert(existing.id);
    }

    let mut payroll: Vec<(PayrollRun, Vec<PayrollLine>)> = Vec::new();
    let mut non_final_skipped = 0usize;
    let mut payroll_errors = Vec::new();
    if let Some(table) = file.data.get("payroll_runs") {
        let mut runs = BTreeMap::new();
        for row in &table.rows {
            match map_payroll_run(row, now) {
                Ok(Some(run)) => {
                    runs.insert(run.id.to_string(), run);
                }
                Ok(None) => non_final_skipped += 1,
                Err(error) => payroll_errors.push(error),
            }
        }
        if let Some(table) = file.data.get("payroll_lines") {
            let mut by_run: BTreeMap<String, Vec<PayrollLine>> = BTreeMap::new();
            for row in &table.rows {
                let run_id = row
                    .get("run_id")
                    .and_then(|item| item.as_str())
                    .unwrap_or("")
                    .to_owned();
                match map_payroll_line(row, &run_id, &known_employees) {
                    Ok(line) => by_run.entry(run_id).or_default().push(line),
                    Err(error) => payroll_errors.push(error),
                }
            }
            for (run_id, lines) in by_run {
                match runs.remove(&run_id) {
                    Some(mut run) => {
                        run.totals = hragents_core::payroll::PayrollTotals::from_lines(&lines)
                            .map_err(|error| {
                                AppError::Export(format!(
                                    "payroll run {run_id}: totals do not reconcile: {error}"
                                ))
                            })?;
                        payroll.push((run, lines));
                    }
                    None => {
                        payroll_errors.push(format!("payroll lines reference unknown run {run_id}"))
                    }
                }
            }
        }
        let mut rows = table.rows.len();
        if let Some(lines) = file.data.get("payroll_lines") {
            rows += lines.rows.len();
        }
        outcomes.push(TableOutcome {
            table: "payroll_runs".into(),
            rows,
            inserted: 0,
            skipped: 0,
            errors: payroll_errors,
        });
    }

    let mut leave_requests = Vec::new();
    let mut request_errors = Vec::new();
    let mut drafts_skipped = 0usize;
    if let Some(table) = file.data.get("leave_requests") {
        for row in &table.rows {
            match map_leave_request(row, &policy_ids, &known_employees, now) {
                Ok(Some(request)) => leave_requests.push(request),
                Ok(None) => drafts_skipped += 1,
                Err(error) => request_errors.push(error),
            }
        }
        outcomes.push(TableOutcome {
            table: "leave_requests".into(),
            rows: table.rows.len(),
            inserted: 0,
            skipped: 0,
            errors: request_errors,
        });
    }
    Ok(PreparedImport {
        employees,
        leave_types,
        leave_requests,
        drafts_skipped,
        payroll,
        non_final_skipped,
        tables: outcomes,
        skipped_tables,
        source_hash,
    })
}

fn parse_sen(value: &serde_json::Value, what: &str) -> Result<Money, String> {
    match value {
        serde_json::Value::String(raw) => {
            Money::parse(raw).map_err(|_| format!("{what} {raw:?} is not a decimal amount"))
        }
        serde_json::Value::Number(number) => {
            let amount = number
                .as_f64()
                .ok_or_else(|| format!("{what} {number} is not a finite number"))?;
            Ok(Money::from_sen((amount * 100.0).round() as i64))
        }
        _ => Err(format!("{what} is missing or not a number")),
    }
}

fn parse_optional_datetime(
    value: Option<&serde_json::Value>,
    what: &str,
) -> Result<Option<UtcInstant>, String> {
    match value {
        None | Some(serde_json::Value::Null) => Ok(None),
        Some(serde_json::Value::String(raw)) => UtcInstant::from_rfc3339(raw)
            .map(Some)
            .map_err(|_| format!("{what} {raw:?} is not RFC 3339")),
        Some(other) => Err(format!("{what} {other} is not a datetime string")),
    }
}

fn map_payroll_run(
    value: &serde_json::Value,
    now: UtcInstant,
) -> Result<Option<PayrollRun>, String> {
    let id = value.get("id").and_then(|item| item.as_str()).unwrap_or("");
    let year = value.get("period_year").and_then(serde_json::Value::as_i64);
    let month = value
        .get("period_month")
        .and_then(serde_json::Value::as_i64);
    let (year, month) = match (year, month) {
        (Some(year), Some(month)) => (year, month),
        _ => {
            return Err(format!(
                "payroll run {id}: period_year/month must be integers"
            ));
        }
    };
    let period = BusinessDate::parse(&format!("{year:04}-{month:02}-01"))
        .map_err(|_| format!("payroll run {id}: invalid period {year}-{month}"))?;
    let kind = match value
        .get("kind")
        .and_then(|item| item.as_str())
        .unwrap_or("")
    {
        "monthly" => PayrollKind::Monthly,
        "thr" => PayrollKind::Thr,
        "final" => PayrollKind::Final,
        "adjustment" => PayrollKind::Adjustment,
        other => return Err(format!("payroll run {id}: unknown kind {other:?}")),
    };
    // Only immutable final states transfer. Drafts, pending sign-off, and
    // rejections are source-system workflow: re-export after sign-off.
    let status = match value
        .get("status")
        .and_then(|item| item.as_str())
        .unwrap_or("")
    {
        "approved" | "exported" => RunStatus::Approved,
        "cancelled" => RunStatus::Cancelled,
        "superseded" => RunStatus::Superseded,
        _ => return Ok(None),
    };
    let anomalies = match value.get("anomalies") {
        None | Some(serde_json::Value::Null) => Vec::new(),
        Some(serde_json::Value::Array(items)) => items
            .iter()
            .map(|item| {
                let severity = match item.get("severity").and_then(|entry| entry.as_str()) {
                    Some("info") => Severity::Info,
                    Some("warning") => Severity::Warning,
                    Some("error") => Severity::Error,
                    other => {
                        return Err(format!(
                            "payroll run {id}: unknown anomaly severity {other:?}"
                        ));
                    }
                };
                Ok(PayrollAnomaly {
                    code: item
                        .get("code")
                        .and_then(|entry| entry.as_str())
                        .unwrap_or("imported")
                        .to_owned(),
                    severity,
                    employee_id: None,
                    detail: item
                        .get("detail")
                        .and_then(|entry| entry.as_str())
                        .unwrap_or("")
                        .to_owned(),
                })
            })
            .collect::<Result<Vec<_>, String>>()?,
        Some(_) => {
            return Err(format!("payroll run {id}: anomalies must be a list"));
        }
    };
    let created_at = parse_optional_datetime(value.get("created_at"), "created_at")?.unwrap_or(now);
    Ok(Some(PayrollRun {
        id: id
            .parse()
            .map_err(|_| format!("payroll run {id}: id is not a UUID"))?,
        kind,
        period,
        status,
        lines: Vec::new(),
        anomalies,
        totals: hragents_core::payroll::PayrollTotals::default(),
        rate_table_ids: Vec::new(),
        created_at,
        computed_at: Some(created_at),
        approved_at: parse_optional_datetime(value.get("signed_off_at"), "signed_off_at")?,
        approved_by: None,
        supersede_reason: value
            .get("cancel_reason")
            .and_then(|item| item.as_str())
            .map(str::to_owned),
    }))
}

fn map_payroll_line(
    value: &serde_json::Value,
    run_id: &str,
    known_employees: &std::collections::BTreeSet<EmployeeId>,
) -> Result<PayrollLine, String> {
    let get = |key: &str| {
        value
            .get(key)
            .ok_or_else(|| format!("payroll line in run {run_id}: {key} is missing"))
    };
    let employee_id: EmployeeId = value
        .get("employee_id")
        .and_then(|item| item.as_str())
        .unwrap_or("")
        .parse()
        .map_err(|_| format!("payroll line in run {run_id}: employee_id is not a UUID"))?;
    if !known_employees.contains(&employee_id) {
        return Err(format!(
            "payroll line in run {run_id}: employee {employee_id} is in neither the database nor this import"
        ));
    }
    let money = |key: &str| parse_sen(get(key)?, &format!("payroll line {key}"));
    let thr_months = value
        .get("thr_months")
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(0);
    if !(0..=24).contains(&thr_months) {
        return Err(format!(
            "payroll line in run {run_id}: thr_months {thr_months} out of range"
        ));
    }
    let notes = match value.get("notes") {
        None | Some(serde_json::Value::Null) => Vec::new(),
        Some(serde_json::Value::Array(items)) => items
            .iter()
            .map(|item| match item {
                serde_json::Value::String(text) => text.clone(),
                other => other.to_string(),
            })
            .collect(),
        Some(_) => {
            return Err(format!(
                "payroll line in run {run_id}: notes must be a list"
            ));
        }
    };
    let line = PayrollLine {
        employee_id,
        employee_name: value
            .get("employee_name")
            .and_then(|item| item.as_str())
            .unwrap_or("")
            .to_owned(),
        base_salary: money("base_salary")?,
        allowances: money("allowances")?,
        overtime_pay: money("overtime_pay")?,
        bonus: money("bonus")?,
        gross: money("gross")?,
        bpjs_kesehatan_employee: money("bpjs_kesehatan_employee")?,
        bpjs_jht_employee: money("bpjs_jht_employee")?,
        bpjs_jp_employee: money("bpjs_jp_employee")?,
        pph21: money("pph21")?,
        other_deductions: money("other_deductions")?,
        total_deductions: money("total_deductions")?,
        net: money("net")?,
        bpjs_kesehatan_employer: money("bpjs_kesehatan_employer")?,
        bpjs_jht_employer: money("bpjs_jht_employer")?,
        bpjs_jp_employer: money("bpjs_jp_employer")?,
        bpjs_jkk_employer: money("bpjs_jkk_employer")?,
        bpjs_jkm_employer: money("bpjs_jkm_employer")?,
        employer_cost: money("employer_cost")?,
        thr_months_bp: Some(thr_months * 10_000),
        severance_pay: Money::ZERO,
        leave_payout: Money::ZERO,
        notes,
    };
    // Reconcile on the way in so a dry-run already catches a tampered export;
    // the store re-checks at commit time.
    line.check_invariants()
        .map_err(|error| format!("payroll line in run {run_id} fails reconciliation: {error}"))?;
    Ok(line)
}

/// Dry-run: validate everything, report counts and errors, write nothing.
/// Reads existing employees so request mapping resolves against the live
/// database as well as the import batch.
pub fn dry_run(store: &Store, path: &Path) -> AppResult<ImportOutcome> {
    let prepared = prepare(store, path)?;
    Ok(ImportOutcome {
        source_hash: prepared.source_hash,
        committed: false,
        tables: prepared.tables,
        skipped_tables: prepared.skipped_tables,
        managers_linked: 0,
        managers_unresolved: 0,
        drafts_skipped: prepared.drafts_skipped,
        non_final_skipped: prepared.non_final_skipped,
        already_imported: false,
    })
}

/// Commit: validate, then import each present slice in its own transaction
/// with its own audit entry. Each slice is idempotent on its own, so a retry
/// after a partial failure finishes the missing slices without duplicating
/// the finished ones. Re-running a fully imported file is a no-op.
pub fn commit(store: &mut Store, path: &Path, source: &str) -> AppResult<ImportOutcome> {
    let prepared = prepare(store, path)?;
    let PreparedImport {
        employees,
        leave_types,
        leave_requests,
        drafts_skipped,
        payroll,
        non_final_skipped,
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
            drafts_skipped,
            non_final_skipped,
            already_imported: false,
        });
    }
    let actor = hragents_core::audit::AuditActor::system("hragents-import");
    let now = UtcInstant::now();
    let want_employees = tables.iter().any(|table| table.table == "employees");
    let want_leave = tables
        .iter()
        .any(|table| table.table == "leave_policies" || table.table == "leave_requests");
    let want_payroll = tables.iter().any(|table| table.table == "payroll_runs");
    let report: ImportReport = if want_employees {
        store.import_employees(
            &employees,
            &actor,
            source,
            &source_hash,
            SUPPORTED_FORMAT,
            now,
        )?
    } else {
        ImportReport {
            inserted: 0,
            skipped: 0,
            managers_linked: 0,
            managers_unresolved: 0,
            already_imported: true,
        }
    };
    for table in &mut tables {
        if table.table == "employees" {
            table.inserted = report.inserted;
            table.skipped = report.skipped;
        }
    }
    let leave_report: LeaveImportReport = if want_leave {
        store.import_leave(LeaveImportBatch {
            types: &leave_types,
            requests: &leave_requests,
            drafts_skipped,
            actor: &actor,
            source,
            source_hash: &source_hash,
            source_format: SUPPORTED_FORMAT,
            created_at: now,
        })?
    } else {
        LeaveImportReport {
            types_inserted: 0,
            types_skipped: 0,
            requests_inserted: 0,
            requests_skipped: 0,
            drafts_skipped,
            already_imported: true,
        }
    };
    for table in &mut tables {
        if table.table == "leave_policies" {
            table.inserted = leave_report.types_inserted;
            table.skipped = leave_report.types_skipped;
        }
        if table.table == "leave_requests" {
            table.inserted = leave_report.requests_inserted;
            table.skipped = leave_report.requests_skipped;
        }
    }
    let payroll_report = if want_payroll {
        store.import_payroll(PayrollImportBatch {
            runs: &payroll,
            non_final_skipped,
            actor: &actor,
            source,
            source_hash: &source_hash,
            source_format: SUPPORTED_FORMAT,
            created_at: now,
        })?
    } else {
        hragents_store::PayrollImportReport {
            runs_inserted: 0,
            runs_skipped: 0,
            lines_inserted: 0,
            lines_skipped: 0,
            non_final_skipped,
            already_imported: true,
        }
    };
    for table in &mut tables {
        if table.table == "payroll_runs" {
            let inserted = payroll_report.runs_inserted + payroll_report.lines_inserted;
            table.inserted = inserted;
            table.skipped = table.rows.saturating_sub(inserted);
        }
    }
    Ok(ImportOutcome {
        source_hash,
        committed: !report.already_imported
            || !leave_report.already_imported
            || !payroll_report.already_imported,
        tables,
        skipped_tables,
        managers_linked: report.managers_linked,
        managers_unresolved: report.managers_unresolved,
        drafts_skipped,
        non_final_skipped,
        already_imported: report.already_imported
            && leave_report.already_imported
            && payroll_report.already_imported,
    })
}
