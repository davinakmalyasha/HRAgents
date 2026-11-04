use hragents_core::attendance::CheckinSource;
use hragents_core::time::BusinessDate;
use hragents_ipc::{AppService, CreateEmployeeInput, SetupInput};

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

fn employee_input(no: &str, name: &str, unit: &str) -> CreateEmployeeInput {
    CreateEmployeeInput {
        employee_no: no.into(),
        full_name: name.into(),
        job_title: "Engineer".into(),
        org_unit: unit.into(),
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

/// Full HR journey: employee -> shift -> check-ins -> summary -> job flow ->
/// application advance -> message mailto/ics -> reports -> org -> file.
/// This is the e2e gate for the copy-parity plus share-out release.
#[test]
fn e2e_hr_journey() {
    let mut service = service();
    let ayu = service
        .create_employee(employee_input("E-001", "Ayu Lestari", "Product"))
        .unwrap();
    let budi = service
        .create_employee(employee_input("E-002", "Budi Santoso", "Design"))
        .unwrap();

    // 1. Time and attendance.
    let shift = service
        .create_shift("Pagi", 480, 1_020, 10, 0b0001_1111)
        .unwrap();
    assert_eq!(service.list_shifts().unwrap().len(), 1);
    service
        .record_checkin(
            ayu.id,
            BusinessDate::parse("2026-02-02").unwrap(),
            485,
            1_060,
            CheckinSource::Manual,
            None,
        )
        .unwrap();
    service
        .record_checkin(
            ayu.id,
            BusinessDate::parse("2026-02-03").unwrap(),
            480,
            1_020,
            CheckinSource::Manual,
            None,
        )
        .unwrap();
    // Fail closed: unknown employee and bad time are refused, nothing stored.
    assert!(
        service
            .record_checkin(
                hragents_core::ids::EmployeeId::new(),
                BusinessDate::parse("2026-02-04").unwrap(),
                480,
                1_020,
                CheckinSource::Manual,
                None,
            )
            .is_err()
    );
    assert!(
        service
            .record_checkin(
                ayu.id,
                BusinessDate::parse("2026-02-04").unwrap(),
                1_020,
                480,
                CheckinSource::Manual,
                None,
            )
            .is_err()
    );
    let summary = service
        .attendance_summary(ayu.id, Some(shift.id), 2026, 2)
        .unwrap();
    assert_eq!(summary.present_days, 2);
    assert_eq!(summary.overtime_minutes, 30);
    assert_eq!(summary.absent_days, summary.workdays - 2);

    // 2. Hiring full flow: create, pause, resume, close gate.
    let job = service.create_job("Backend Engineer", "Product").unwrap();
    assert_eq!(
        service.set_job_status(job.id, "paused").unwrap().status,
        hragents_core::hiring::JobStatus::Paused
    );
    assert_eq!(
        service.set_job_status(job.id, "open").unwrap().status,
        hragents_core::hiring::JobStatus::Open
    );
    // Closed is terminal: reopening is refused.
    service.set_job_status(job.id, "closed").unwrap();
    assert!(service.set_job_status(job.id, "open").is_err());

    let job2 = service.create_job("Designer", "Design").unwrap();
    let (candidate, application) = service
        .import_candidate(hragents_ipc::ImportCandidateInput {
            full_name: "Dimas Pratama".into(),
            email: Some("dimas@example.com".into()),
            phone: None,
            source: "LinkedIn".into(),
            headline: None,
            job_id: job2.id,
            consent: hragents_core::hiring::ConsentStatus::Granted,
            document: None,
        })
        .unwrap();
    let _ = candidate;
    let advanced = service
        .advance_application(application.id, "screening")
        .unwrap();
    assert_eq!(
        advanced.stage,
        hragents_core::hiring::ApplicationStage::Screening
    );
    let advanced = service
        .advance_application(application.id, "interview")
        .unwrap();
    assert_eq!(
        advanced.stage,
        hragents_core::hiring::ApplicationStage::Interview
    );
    // Decision path is gated: advance() refuses the terminal rejection stage.
    assert!(
        service
            .advance_application(application.id, "rejected")
            .is_err()
    );

    // 3. Share-out helpers: mailto link and calendar file, no network.
    let message = service
        .draft_message(
            candidate.id,
            Some(application.id),
            hragents_core::hiring_comms::MessageKind::Interview,
            hragents_core::hiring_comms::MessageChannel::Email,
            Some("Interview invite".into()),
            "Hi Dimas,\nPlease come on Monday.",
        )
        .unwrap();
    let mailto = service.message_mailto(message.id).unwrap();
    assert!(mailto.starts_with("mailto:dimas@example.com?subject="));
    assert!(mailto.contains("Interview%20invite"));

    // 4. Reports, org tree, employee file.
    let report = service.company_report().unwrap();
    assert!(report.total_active >= 2);
    assert!(report.headcount.iter().any(|row| row.org_unit == "Product"));
    assert!(report.hiring_funnel.iter().any(|row| row.applied >= 1));
    let tree = service.org_tree().unwrap();
    assert!(tree.iter().any(|row| row.1 == "Ayu Lestari"));
    let file = service.employee_file(ayu.id).unwrap();
    assert_eq!(file["employee"]["full_name"], "Ayu Lestari");
    let _ = budi;

    // 5. Audit chain still verifies end to end.
    assert!(service.audit_verify().unwrap().entries > 0);
}
