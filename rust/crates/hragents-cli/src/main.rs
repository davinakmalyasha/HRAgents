use hragents_core::hiring::{ConsentStatus, Dimension, Evidence, Rubric, RunScores};
use hragents_core::money::Money;
use hragents_core::payroll::{PayrollInput, PayrollKind};
use hragents_core::time::{BusinessDate, UtcInstant};
use hragents_ipc::{
    AppService, CreateEmployeeInput, EvaluateInput, ImportCandidateInput, RecordLeaveInput,
    SetupInput,
};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

fn main() {
    if let Err(error) = run() {
        eprintln!("error: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("demo") => demo(args.get(1).map(PathBuf::from)),
        Some("verify") => verify(&args[1..]),
        Some("backup") => backup(&args[1..]),
        Some("restore") => restore(&args[1..]),
        Some("rewrap") => rewrap(&args[1..]),
        Some("backup-set") => backup_set(&args[1..]),
        Some("restore-set") => restore_set(&args[1..]),
        Some("--version") | Some("-V") => {
            println!("hragents {}", env!("CARGO_PKG_VERSION"));
            Ok(())
        }
        _ => {
            println!("hragents {}", env!("CARGO_PKG_VERSION"));
            println!("usage:");
            println!("  hragents-cli demo [db-path]");
            println!("  hragents-cli verify <db-path> [--key <key> | --key-file <path>]");
            println!(
                "  hragents-cli backup <db-path> <output-path> [--key <key> | --key-file <path>]"
            );
            println!(
                "  hragents-cli restore <backup-path> <db-path> [--force] [--key <key> | --key-file <path>]"
            );
            println!("  hragents-cli backup-set <db-path> <output.hrbackup> [--key <key>]");
            println!(
                "  hragents-cli restore-set <archive.hrbackup> <data-dir> [--key <recovery-key>]"
            );
            println!("  hragents-cli rewrap <data-dir> --key <recovery-key>");
            println!("    verify the encrypted database, then re-protect the key for this OS user");
            println!("    verify-first; refuse to overwrite a newer live DB without --force;");
            println!("    snapshot live DB to <db-path>.pre-restore-<epoch> before swap");
            println!(
                "    encrypted databases need a SQLCipher build: cargo run -p hragents-cli --features sqlcipher"
            );
            Ok(())
        }
    }
}

fn positional(args: &[String], index: usize) -> Result<PathBuf, Box<dyn std::error::Error>> {
    args.iter()
        .filter(|arg| !arg.starts_with("--"))
        .nth(index)
        .map(PathBuf::from)
        .ok_or_else(|| format!("missing argument {}", index + 1).into())
}

fn parse_key(args: &[String]) -> Result<Option<String>, Box<dyn std::error::Error>> {
    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--key" => {
                return args
                    .get(index + 1)
                    .cloned()
                    .map(Some)
                    .ok_or_else(|| "--key needs a value".into());
            }
            "--key-file" => {
                let path = args.get(index + 1).ok_or("--key-file needs a path")?;
                return Ok(Some(hragents_store::keyfile::read_key(
                    std::path::Path::new(path),
                )?));
            }
            _ => index += 1,
        }
    }
    Ok(None)
}

fn open_store(
    path: &std::path::Path,
    key: Option<&str>,
) -> Result<hragents_store::Store, Box<dyn std::error::Error>> {
    Ok(match key {
        Some(key) => hragents_store::Store::open_encrypted(path, key)?,
        None => hragents_store::Store::open(path)?,
    })
}

fn demo(path: Option<PathBuf>) -> Result<(), Box<dyn std::error::Error>> {
    let path = path.unwrap_or_else(|| PathBuf::from("hragents-demo.db"));
    if path.exists() {
        std::fs::remove_file(&path)?;
    }
    let mut service = AppService::open(&path)?;
    let session = service.setup_first_run(SetupInput {
        company_name: "Nusantara Labs".into(),
        operator_name: "Rina".into(),
        username: "rina".into(),
        password: "correct horse battery staple".into(),
    })?;
    println!("login: {} ({})", session.display_name, session.role);

    let employee = service.create_employee(CreateEmployeeInput {
        employee_no: "E-001".into(),
        full_name: "Ayu Lestari".into(),
        job_title: "Backend Engineer".into(),
        org_unit: "Product".into(),
        hire_date: BusinessDate::parse("2025-02-01")?,
        email: Some("ayu@example.com".into()),
        phone: Some("+62 812 0000 0000".into()),
        ptkp_status: Some("TK/1".into()),
        dependents: 1,
        jkk_risk_class: Some(1),
        bank_name: Some("BCA".into()),
        bank_account: Some("1234567890".into()),
    })?;
    println!(
        "employee: {} {}",
        employee.full_name,
        employee.id.short_ref()
    );

    let plan = service.start_onboarding(employee.id, None)?;
    service.complete_onboarding_step(employee.id, "contract")?;
    service.complete_onboarding_step(employee.id, "identity")?;
    let plan = service.onboarding_for(employee.id)?.unwrap_or(plan);
    println!(
        "onboarding: {} ({}/{} steps)",
        plan.template_name,
        plan.progress().0,
        plan.progress().1
    );

    let job = service.create_job("Backend Engineer", "Product")?;
    let (candidate, application) = service.import_candidate(ImportCandidateInput {
        full_name: "Budi Santoso".into(),
        email: Some("budi@example.com".into()),
        phone: None,
        source: "LinkedIn".into(),
        headline: Some("Backend engineer, 6 years".into()),
        job_id: job.id,
        consent: ConsentStatus::Granted,
        document: None,
    })?;
    let rubric = Rubric {
        id: "backend-v1".into(),
        name: "Backend Engineer".into(),
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
    let runs = vec![
        RunScores {
            dimension_scores: BTreeMap::from([("skills".into(), 8_500), ("impact".into(), 7_500)]),
        },
        RunScores {
            dimension_scores: BTreeMap::from([("skills".into(), 8_300), ("impact".into(), 7_700)]),
        },
        RunScores {
            dimension_scores: BTreeMap::from([("skills".into(), 8_600), ("impact".into(), 7_400)]),
        },
    ];
    let _ = Evidence {
        dimension: "skills".into(),
        quote: "Built a Rust ingestion pipeline handling 2M events/day".into(),
        source_document_id: hragents_core::ids::DocumentId::new(),
        confidence_bp: 9_000,
        page: Some(2),
    };
    let evaluation = service.evaluate_candidate(EvaluateInput {
        application_id: application.id,
        rubric,
        runs,
        evidence: vec![],
    })?;
    println!(
        "evaluation: {} score {:.1}% sigma {:.1}% policy {:?}",
        candidate.full_name,
        evaluation.evaluation.overall_bp as f64 / 100.0,
        evaluation.evaluation.sigma_bp as f64 / 100.0,
        evaluation.policy
    );
    service.reject_candidate(application.id, "lacks the required on-call experience")?;
    println!("decision: rejected with a named reason and audit receipt");

    let leave_type = service.create_leave_type("Annual leave", 12)?;
    service.set_leave_entitlement(employee.id, leave_type.id, 2026, 12)?;
    let leave = service.record_leave(RecordLeaveInput {
        employee_id: employee.id,
        leave_type_id: leave_type.id,
        start_date: BusinessDate::parse("2026-11-09")?,
        end_date: BusinessDate::parse("2026-11-10")?,
        days_x2: 4,
        reason: "family event".into(),
    })?;
    let leave = service.decide_leave(leave.request.id, true, "approved")?;
    println!(
        "leave: {} day(s) approved, {} day(s) remaining",
        leave.request.days_x2 / 2,
        leave.balance.available_x2() / 2
    );

    service.seed_demo_rate_tables(BusinessDate::parse("2026-01-01")?)?;
    let mut input = PayrollInput::new(
        employee.id,
        employee.full_name.clone(),
        Money::from_rupiah(10_000_000)?,
    );
    input.fixed_allowances = Money::from_rupiah(2_000_000)?;
    input.service_months = 30;
    let payroll = service.compute_payroll(
        PayrollKind::Monthly,
        BusinessDate::parse("2026-11-01")?,
        vec![input],
    )?;
    println!(
        "payroll: {} employee(s), gross {}, net {}, blocking {}",
        payroll.run.totals.employees,
        payroll.run.totals.gross,
        payroll.run.totals.net,
        payroll.blocking
    );
    let approved = service.approve_payroll(payroll.run.id)?;
    println!(
        "payroll sign-off: {} at {}",
        approved.status_as_str(),
        approved
            .approved_at
            .map(|instant| instant.to_string())
            .unwrap_or_default()
    );

    let verification = service.audit_verify()?;
    println!(
        "audit: {} entries, head {}",
        verification.entries,
        &verification.head_hash.unwrap_or_default()[..12]
    );
    let dir = path.parent().unwrap_or_else(|| std::path::Path::new("."));
    let backup = dir.join("hragents-demo-backup.db");
    let size = service.backup(&backup)?;
    println!("backup: {} bytes at {}", size, backup.display());
    let hits = service.search("Ayu")?;
    println!("search: {} hit(s) for 'Ayu'", hits.len());
    println!("demo complete");
    Ok(())
}

fn verify(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let path = positional(args, 0)?;
    let key = parse_key(args)?;
    let store = open_store(&path, key.as_deref())?;
    let verification = store.verify_audit()?;
    println!(
        "ok: {} audit entries, head {}",
        verification.entries,
        verification.head_hash.unwrap_or_else(|| "(empty)".into())
    );
    println!("integrity: {}", store.integrity_check()?);
    println!(
        "encrypted: {}",
        if store.is_encrypted() { "yes" } else { "no" }
    );
    Ok(())
}

fn backup(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let path = positional(args, 0)?;
    let output = positional(args, 1)?;
    let key = parse_key(args)?;
    let store = open_store(&path, key.as_deref())?;
    let size = match key.as_deref() {
        Some(key) if !store.is_encrypted() => store.backup_to_key(&output, key)?,
        _ => store.backup_to(&output)?,
    };
    println!("backup: {size} bytes at {}", output.display());
    Ok(())
}

fn backup_set(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let db = positional(args, 0)?;
    let output = positional(args, 1)?;
    let key = parse_key(args)?;
    let store = open_store(&db, key.as_deref())?;
    store.checkpoint()?;
    drop(store);
    let data_dir = db.parent().unwrap_or_else(|| Path::new("."));
    let size = hragents_ipc::backup_set::create(
        &output,
        &db,
        &data_dir.join("documents"),
        Some(&data_dir.join("hragents.key")),
        key.as_deref(),
    )?;
    println!("backup set: {size} bytes at {}", output.display());
    Ok(())
}

fn restore_set(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let archive = positional(args, 0)?;
    let dest = positional(args, 1)?;
    let key = parse_key(args)?;
    let snapshot = if dest.exists() {
        let epoch = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_secs())
            .unwrap_or(0);
        let snapshot = dest.with_extension(format!("pre-restore-{epoch}"));
        std::fs::rename(&dest, &snapshot)?;
        println!("existing data snapshotted at {}", snapshot.display());
        Some(snapshot)
    } else {
        None
    };
    match hragents_ipc::backup_set::restore(&archive, &dest, key.as_deref()) {
        Ok(manifest) => {
            println!(
                "restore set: {} document(s), {} audit entries at {}",
                manifest.documents,
                manifest.audit_entries,
                dest.display()
            );
            Ok(())
        }
        Err(error) => {
            if let Some(snapshot) = snapshot {
                let _ = std::fs::rename(snapshot, &dest);
            }
            Err(error.into())
        }
    }
}

/// Recover on another machine (or Windows user): verify the database with the
/// exported recovery key, then write a locally protected `hragents.key`.
fn rewrap(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let data_dir = positional(args, 0)?;
    let key = parse_key(args)?.ok_or("rewrap requires --key <recovery-key>")?;
    let db = data_dir.join("hragents.db");
    if !db.exists() {
        return Err(format!("database not found: {}", db.display()).into());
    }
    let store = open_store(&db, Some(&key))?;
    if store.integrity_check()? != "ok" {
        return Err("refusing rewrap: database integrity_check failed".into());
    }
    drop(store);
    hragents_store::keyfile::write_key(&data_dir, &key)?;
    println!(
        "key rewrapped for {} (database verified)",
        data_dir.display()
    );
    Ok(())
}

/// Restore a verified backup over a live path.
///
/// Contract (mirrors 16-restore-drill): verify the backup's integrity and
/// audit chain first and fail closed; refuse to overwrite a live DB that is
/// newer than the backup unless `--force`; snapshot the live DB aside before
/// swapping; copy via temp file + atomic rename; re-open and re-verify.
fn restore(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let backup_path = positional(args, 0)?;
    let target = positional(args, 1)?;
    let force = args.iter().any(|arg| arg == "--force");
    let key = parse_key(args)?;
    if !backup_path.exists() {
        return Err(format!("backup not found: {}", backup_path.display()).into());
    }

    // 1. Verify first, on the backup itself. Fail closed.
    let backup_store = open_store(&backup_path, key.as_deref())?;
    if backup_store.integrity_check()? != "ok" {
        return Err("refusing restore: backup integrity_check failed".into());
    }
    let verification = backup_store.verify_audit()?;
    let backup_entries = verification.entries;
    drop(backup_store);

    // 2. Refuse to overwrite a newer live DB without --force; snapshot the
    // live DB aside before touching it in every case.
    if target.exists() {
        // Flush any live WAL before snapshotting; a stale WAL must never be
        // replayed over the restored file.
        open_store(&target, key.as_deref())?.checkpoint()?;
        let live_mtime = std::fs::metadata(&target)?.modified()?;
        let backup_mtime = std::fs::metadata(&backup_path)?.modified()?;
        if live_mtime > backup_mtime && !force {
            return Err(format!(
                "refusing restore: live DB {} is newer than the backup; re-run with --force",
                target.display()
            )
            .into());
        }
        // Snapshot the live DB aside before touching it.
        let epoch = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_secs())
            .unwrap_or(0);
        let snapshot = target.with_extension(format!("pre-restore-{epoch}"));
        std::fs::copy(&target, &snapshot)?;
        println!("live DB snapshotted at {}", snapshot.display());
    }

    // 3. Copy via temp file + atomic rename, then re-open and re-verify.
    if let Some(parent) = target.parent().filter(|dir| !dir.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)?;
    }
    let staging = target.with_extension("restore-staging");
    std::fs::copy(&backup_path, &staging)?;
    std::fs::rename(&staging, &target)?;
    for suffix in ["-wal", "-shm"] {
        let sidecar = PathBuf::from(format!("{}{suffix}", target.display()));
        if sidecar.exists() {
            std::fs::remove_file(sidecar)?;
        }
    }
    let restored = open_store(&target, key.as_deref())?;
    if restored.integrity_check()? != "ok" {
        return Err("restore failed: restored DB integrity_check failed".into());
    }
    let after = restored.verify_audit()?;
    if after.entries != backup_entries {
        return Err("restore failed: audit entry count changed during copy".into());
    }
    println!(
        "restore: {} audit entries verified at {}",
        after.entries,
        target.display()
    );
    Ok(())
}

trait StatusLabel {
    fn status_as_str(&self) -> &'static str;
}

impl StatusLabel for hragents_core::payroll::PayrollRun {
    fn status_as_str(&self) -> &'static str {
        match self.status {
            hragents_core::payroll::RunStatus::Draft => "draft",
            hragents_core::payroll::RunStatus::Computed => "computed",
            hragents_core::payroll::RunStatus::Approved => "approved",
            hragents_core::payroll::RunStatus::Cancelled => "cancelled",
            hragents_core::payroll::RunStatus::Superseded => "superseded",
        }
    }
}

#[allow(dead_code)]
fn _unused_now() -> UtcInstant {
    UtcInstant::now()
}
