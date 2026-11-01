use hragents_core::hiring::{ConsentStatus, Dimension, Evidence, Rubric, RunScores};
use hragents_core::money::Money;
use hragents_core::payroll::{PayrollInput, PayrollKind};
use hragents_core::time::{BusinessDate, UtcInstant};
use hragents_ipc::{
    AppService, CreateEmployeeInput, EvaluateInput, ImportCandidateInput, RecordLeaveInput,
    SetupInput,
};
use std::collections::BTreeMap;
use std::path::PathBuf;

fn main() {
    if let Err(error) = run() {
        eprintln!("error: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    match args.next().as_deref() {
        Some("demo") => demo(args.next().map(PathBuf::from)),
        Some("verify") => verify(args.next().map(PathBuf::from)),
        Some("backup") => backup(
            args.next().map(PathBuf::from),
            args.next().map(PathBuf::from),
        ),
        Some("--version") | Some("-V") => {
            println!("hragents {}", env!("CARGO_PKG_VERSION"));
            Ok(())
        }
        _ => {
            println!("hragents {}", env!("CARGO_PKG_VERSION"));
            println!("usage:");
            println!("  hragents-cli demo [db-path]");
            println!("  hragents-cli verify <db-path>");
            println!("  hragents-cli backup <db-path> <output-path>");
            Ok(())
        }
    }
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

fn verify(path: Option<PathBuf>) -> Result<(), Box<dyn std::error::Error>> {
    let path = path.ok_or("verify requires a database path")?;
    let store = hragents_store::Store::open(&path)?;
    let verification = store.verify_audit()?;
    println!(
        "ok: {} audit entries, head {}",
        verification.entries,
        verification.head_hash.unwrap_or_else(|| "(empty)".into())
    );
    println!("integrity: {}", store.integrity_check()?);
    Ok(())
}

fn backup(
    path: Option<PathBuf>,
    output: Option<PathBuf>,
) -> Result<(), Box<dyn std::error::Error>> {
    let path = path.ok_or("backup requires a database path")?;
    let output = output.ok_or("backup requires an output path")?;
    let store = hragents_store::Store::open(&path)?;
    let size = store.backup_to(&output)?;
    println!("backup: {} bytes at {}", size, output.display());
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
