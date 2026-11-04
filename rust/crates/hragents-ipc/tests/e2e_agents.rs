use hragents_core::attendance::CheckinSource;
use hragents_core::hiring::{Dimension, RunScores};
use hragents_core::time::BusinessDate;
use hragents_ipc::{
    AppService, CreateEmployeeInput, EvaluateInput, ImportCandidateInput, SetupInput,
};
use std::collections::BTreeMap;

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

fn employee_input(no: &str, name: &str) -> CreateEmployeeInput {
    CreateEmployeeInput {
        employee_no: no.into(),
        full_name: name.into(),
        job_title: "Engineer".into(),
        org_unit: "Product".into(),
        hire_date: BusinessDate::parse("2025-02-01").unwrap(),
        email: Some(format!("{}@example.com", no.to_lowercase())),
        phone: None,
        ptkp_status: Some("TK/1".into()),
        dependents: 0,
        jkk_risk_class: Some(1),
        bank_name: Some("BCA".into()),
        bank_account: Some("1234567890".into()),
    }
}

fn rubric() -> hragents_core::hiring::Rubric {
    hragents_core::hiring::Rubric {
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
    }
}

fn evaluate(
    service: &mut AppService,
    application_id: hragents_core::ids::ApplicationId,
    overall: i64,
) {
    let run = RunScores {
        dimension_scores: BTreeMap::from([("skills".into(), overall), ("impact".into(), overall)]),
    };
    service
        .evaluate_candidate(EvaluateInput {
            application_id,
            rubric: rubric(),
            runs: vec![run],
            evidence: vec![],
        })
        .unwrap();
}

/// Hire helper: evaluated applications rank by score; unevaluated sink last.
#[test]
fn hire_helper_ranks_shortlist() {
    let mut service = service();
    let job = service.create_job("Backend Engineer", "Product").unwrap();
    let (_, low) = service
        .import_candidate(ImportCandidateInput {
            full_name: "Low Score".into(),
            email: None,
            phone: None,
            source: "Manual".into(),
            headline: None,
            job_id: job.id,
            consent: hragents_core::hiring::ConsentStatus::Granted,
            document: None,
        })
        .unwrap();
    let (_, high) = service
        .import_candidate(ImportCandidateInput {
            full_name: "High Score".into(),
            email: None,
            phone: None,
            source: "Manual".into(),
            headline: None,
            job_id: job.id,
            consent: hragents_core::hiring::ConsentStatus::Granted,
            document: None,
        })
        .unwrap();
    let (_, pending) = service
        .import_candidate(ImportCandidateInput {
            full_name: "No Score".into(),
            email: None,
            phone: None,
            source: "Manual".into(),
            headline: None,
            job_id: job.id,
            consent: hragents_core::hiring::ConsentStatus::Granted,
            document: None,
        })
        .unwrap();
    evaluate(&mut service, low.id, 5_000);
    evaluate(&mut service, high.id, 9_000);

    let ranked = service.rank_applications(job.id).unwrap();
    assert_eq!(ranked.len(), 3);
    assert_eq!(ranked[0].candidate_name, "High Score");
    assert_eq!(ranked[0].overall_bp, Some(9_000));
    assert_eq!(ranked[1].candidate_name, "Low Score");
    assert!(!ranked[2].has_evaluation);
    assert_eq!(ranked[2].candidate_name, "No Score");
    // Fail closed on unknown jobs.
    assert!(
        service
            .rank_applications(hragents_core::ids::JobId::new())
            .is_err()
    );
    let _ = pending;
}

/// Pay helper: clean demo run reads ready with plain sentences.
#[test]
fn pay_helper_readiness_explains_run() {
    let mut service = service();
    let employee = service
        .create_employee(employee_input("E-001", "Ayu Lestari"))
        .unwrap();
    service
        .seed_demo_rate_tables(BusinessDate::parse("2026-01-01").unwrap())
        .unwrap();
    let mut input = hragents_core::payroll::PayrollInput::new(
        employee.id,
        employee.full_name.clone(),
        hragents_core::Money::from_rupiah(10_000_000).unwrap(),
    );
    input.fixed_allowances = hragents_core::Money::from_rupiah(2_000_000).unwrap();
    input.service_months = 30;
    let view = service
        .compute_payroll(
            hragents_core::payroll::PayrollKind::Monthly,
            BusinessDate::parse("2026-11-01").unwrap(),
            vec![input],
        )
        .unwrap();
    let readiness = service.payroll_readiness(view.run.id).unwrap();
    assert_eq!(readiness.lines, 1);
    assert!(readiness.ready);
    assert!(!readiness.sentences.is_empty());
    assert!(
        service
            .payroll_readiness(hragents_core::ids::PayrollRunId::new())
            .is_err()
    );
}

/// Attendance cleaner: late days surface as findings; missing shift says so.
#[test]
fn attendance_cleaner_flags_late_days() {
    let mut service = service();
    let employee = service
        .create_employee(employee_input("E-001", "Ayu Lestari"))
        .unwrap();
    // No shift yet: the helper says what is missing instead of guessing.
    let findings = service.attendance_findings(employee.id, 2026, 2).unwrap();
    assert_eq!(findings.len(), 1);
    assert_eq!(findings[0].kind, "no_shift");

    service
        .create_shift("Pagi", 480, 1_020, 10, 0b0001_1111)
        .unwrap();
    service
        .record_checkin(
            employee.id,
            BusinessDate::parse("2026-02-02").unwrap(),
            500,
            1_020,
            CheckinSource::Manual,
            None,
        )
        .unwrap();
    let findings = service.attendance_findings(employee.id, 2026, 2).unwrap();
    assert!(findings.iter().any(|finding| finding.kind == "late"));
    assert!(findings.iter().any(|finding| finding.kind == "absent"));
    // Unknown employees fail closed.
    assert!(
        service
            .attendance_findings(hragents_core::ids::EmployeeId::new(), 2026, 2)
            .is_err()
    );
}

/// Document checker and daily briefing run read-only and never empty.
#[test]
fn document_checker_and_briefing_are_read_only() {
    let service = service();
    let health = service.document_health().unwrap();
    assert!(health.expiring.is_empty());
    assert!(health.overdue_requests.is_empty());
    let briefing = service.daily_briefing().unwrap();
    assert!(!briefing.sentences.is_empty());
}

/// Ask helper: matched questions cite sources offline; unknown questions say
/// so instead of guessing; gated behind login like everything else.
#[test]
fn ask_helper_cites_and_refuses_to_guess() {
    let mut service = service();
    let matched = service
        .ask_assistant("What is the probation period?")
        .unwrap();
    assert!(matched.matched);
    assert!(!matched.citations.is_empty());
    assert!(!matched.body.is_empty());
    // Offline in tests: no key, no network, deterministic draft.
    assert!(!matched.provider_used);

    let unknown = service
        .ask_assistant("quantum entanglement photosynthesis")
        .unwrap();
    assert!(!unknown.matched);
    assert!(unknown.citations.is_empty());

    service.logout().unwrap();
    assert!(service.ask_assistant("probation").is_err());
    assert!(
        service
            .rank_applications(hragents_core::ids::JobId::new())
            .is_err()
    );
    assert!(service.daily_briefing().is_err());
}
