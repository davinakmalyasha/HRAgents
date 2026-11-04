//! Attendance, reports, org chart, hiring-flow completion, and share-out
//! helpers (mailto links and calendar files). No network, no SMTP: the human
//! sends through their own mail app; the app only prepares exact text.

use super::{AppError, AppResult, AppService};
use hragents_core::attendance::{self, CheckinSource, Shift};
use hragents_core::error::DomainError;
use hragents_core::hiring::{ApplicationStage, JobStatus};
use hragents_core::ids::{ApplicationId, EmployeeId, JobId, MessageId, ShiftId};
use hragents_core::reports::{self, CompanyReport, HiringFunnelRow, LeaveRecapRow, PayrollCostRow};
use hragents_core::time::{BusinessDate, UtcInstant};

fn stage_from_str(raw: &str) -> AppResult<ApplicationStage> {
    match raw {
        "imported" => Ok(ApplicationStage::Imported),
        "screening" => Ok(ApplicationStage::Screening),
        "review" => Ok(ApplicationStage::Review),
        "interview" => Ok(ApplicationStage::Interview),
        "offer" => Ok(ApplicationStage::Offer),
        "hired" => Ok(ApplicationStage::Hired),
        _ => Err(AppError::Domain(
            hragents_core::error::DomainError::validation(
                "E_STAGE",
                "unknown application stage; use imported/screening/review/interview/offer/hired",
            ),
        )),
    }
}

fn job_status_from_str(raw: &str) -> AppResult<JobStatus> {
    match raw {
        "draft" => Ok(JobStatus::Draft),
        "open" => Ok(JobStatus::Open),
        "paused" => Ok(JobStatus::Paused),
        "closed" => Ok(JobStatus::Closed),
        _ => Err(AppError::Domain(
            hragents_core::error::DomainError::validation(
                "E_JOB_STATUS",
                "unknown job status; use draft/open/paused/closed",
            ),
        )),
    }
}

fn mailto_escape(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    for byte in input.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(byte as char);
            }
            b' ' => out.push_str("%20"),
            b'\n' => out.push_str("%0A"),
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}

impl AppService {
    pub fn create_shift(
        &mut self,
        name: &str,
        start_minute: i64,
        end_minute: i64,
        grace_minutes: i64,
        workdays_mask: u8,
    ) -> AppResult<Shift> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let shift = Shift::new(
            name,
            start_minute,
            end_minute,
            grace_minutes,
            workdays_mask,
            now,
        )?;
        self.store_mut().save_shift(&shift)?;
        self.append_audit_pub(
            "attendance.shift_created",
            "shift",
            &shift.id.to_string(),
            serde_json::json!({"name": shift.name}),
            now,
        )?;
        Ok(shift)
    }

    pub fn list_shifts(&self) -> AppResult<Vec<Shift>> {
        self.require_session_pub()?;
        Ok(self.store().list_shifts()?)
    }

    pub fn record_checkin(
        &mut self,
        employee_id: EmployeeId,
        date: BusinessDate,
        in_minute: i64,
        out_minute: i64,
        source: CheckinSource,
        note: Option<String>,
    ) -> AppResult<hragents_core::attendance::Checkin> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        // Fail closed when the employee does not exist.
        let _ = self.store().employee(employee_id)?;
        let checkin = hragents_core::attendance::Checkin::record(
            employee_id,
            date,
            in_minute,
            out_minute,
            source,
            note,
            now,
        )?;
        self.store_mut().save_checkin(&checkin)?;
        self.append_audit_pub(
            "attendance.checkin_recorded",
            "checkin",
            &checkin.id.to_string(),
            serde_json::json!({"employee": employee_id.to_string(), "date": date.to_string()}),
            now,
        )?;
        Ok(checkin)
    }

    pub fn attendance_summary(
        &self,
        employee_id: EmployeeId,
        shift_id: Option<ShiftId>,
        year: i32,
        month: u32,
    ) -> AppResult<hragents_core::attendance::AttendanceSummary> {
        self.require_session_pub()?;
        let shifts = self.store().list_shifts()?;
        let shift = match shift_id {
            Some(id) => shifts
                .into_iter()
                .find(|shift| shift.id == id)
                .ok_or_else(|| {
                    AppError::Domain(DomainError::NotFound {
                        entity: "shift",
                        id: id.to_string(),
                    })
                })?,
            None => shifts.into_iter().next().ok_or_else(|| {
                AppError::Domain(hragents_core::error::DomainError::validation(
                    "E_NO_SHIFT",
                    "create a shift before summarising attendance",
                ))
            })?,
        };
        let month_start =
            BusinessDate::parse(&format!("{year:04}-{month:02}-01")).map_err(|_| {
                AppError::Domain(hragents_core::error::DomainError::validation(
                    "E_MONTH",
                    "month must be 1..=12",
                ))
            })?;
        let workdays = month_start.working_days_in_month();
        let end = month_start.add_days(31);
        let checkins = self.store().list_checkins(&employee_id, month_start, end)?;
        Ok(attendance::summarize_month(
            employee_id,
            year,
            month,
            &shift,
            &checkins,
            workdays,
        ))
    }

    pub fn set_job_status(
        &mut self,
        job_id: JobId,
        status: &str,
    ) -> AppResult<hragents_core::hiring::Job> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let next = job_status_from_str(status)?;
        let mut job = self.store().job(job_id)?;
        let allowed = match (&job.status, &next) {
            (current, next) if current == next => true,
            (JobStatus::Closed, _) => false,
            (JobStatus::Draft, JobStatus::Open) => true,
            (JobStatus::Open, JobStatus::Paused) => true,
            (JobStatus::Open, JobStatus::Closed) => true,
            (JobStatus::Paused, JobStatus::Open) => true,
            (JobStatus::Paused, JobStatus::Closed) => true,
            _ => false,
        };
        if !allowed {
            return Err(AppError::Domain(
                hragents_core::error::DomainError::conflict(
                    "E_JOB_TRANSITION",
                    "that job status change is not allowed",
                ),
            ));
        }
        job.status = next;
        self.store_mut().save_job(&job)?;
        self.append_audit_pub(
            "job.status_changed",
            "job",
            &job.id.to_string(),
            serde_json::json!({"status": status}),
            now,
        )?;
        Ok(job)
    }

    pub fn advance_application(
        &mut self,
        application_id: ApplicationId,
        stage: &str,
    ) -> AppResult<hragents_core::hiring::Application> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let to = stage_from_str(stage)?;
        let mut application = self.store().application(application_id)?;
        application.advance(to, now)?;
        self.store_mut().save_application(&application)?;
        self.append_audit_pub(
            "application.advanced",
            "application",
            &application.id.to_string(),
            serde_json::json!({"stage": stage}),
            now,
        )?;
        Ok(application)
    }

    pub fn company_report(&self) -> AppResult<CompanyReport> {
        self.require_session_pub()?;
        let employees = self.store().list_employees()?;
        let mut units: Vec<(String, u32)> = Vec::new();
        for employee in &employees {
            if matches!(
                employee.status,
                hragents_core::people::EmploymentStatus::Exited
            ) {
                continue;
            }
            units.push((employee.org_unit.clone(), 1));
        }
        let headcount = reports::headcount_by_org(units);
        let total_active = headcount.iter().map(|row| row.active).sum();

        let mut payroll_cost: Vec<PayrollCostRow> = Vec::new();
        for run in self.store().list_payroll_runs()? {
            if !matches!(
                run.status,
                hragents_core::payroll::RunStatus::Approved
                    | hragents_core::payroll::RunStatus::Computed
            ) {
                continue;
            }
            payroll_cost.push(PayrollCostRow {
                year: 0,
                month: 0,
                employees: run.totals.employees as u32,
                net_sen: run.totals.net.sen(),
            });
            if payroll_cost.len() >= 12 {
                break;
            }
        }

        let all_requests = self.store().list_leave_requests(None)?;
        let mut leave_recap: Vec<LeaveRecapRow> = Vec::new();
        for employee in employees.iter().take(200) {
            let approved = all_requests
                .iter()
                .filter(|request| {
                    request.employee_id == employee.id
                        && matches!(request.status, hragents_core::leave::LeaveStatus::Approved)
                })
                .count() as u32;
            let pending = all_requests
                .iter()
                .filter(|request| {
                    request.employee_id == employee.id
                        && matches!(request.status, hragents_core::leave::LeaveStatus::Pending)
                })
                .count() as u32;
            if approved > 0 || pending > 0 {
                leave_recap.push(LeaveRecapRow {
                    employee_id: employee.id,
                    employee_no: employee.employee_no.clone(),
                    full_name: employee.full_name.clone(),
                    approved,
                    pending,
                });
            }
        }

        let jobs = self.store().list_jobs()?;
        let mut hiring_funnel: Vec<HiringFunnelRow> = Vec::new();
        for job in &jobs {
            let applications = self.store().list_applications(Some(job.id))?;
            let interviewed = applications
                .iter()
                .filter(|application| {
                    matches!(
                        application.stage,
                        ApplicationStage::Interview
                            | ApplicationStage::Offer
                            | ApplicationStage::Hired
                    )
                })
                .count() as u32;
            let offered = applications
                .iter()
                .filter(|application| {
                    matches!(
                        application.stage,
                        ApplicationStage::Offer | ApplicationStage::Hired
                    )
                })
                .count() as u32;
            let hired = applications
                .iter()
                .filter(|application| matches!(application.stage, ApplicationStage::Hired))
                .count() as u32;
            hiring_funnel.push(HiringFunnelRow {
                job_id: job.id.to_string(),
                title: job.title.clone(),
                applied: applications.len() as u32,
                interviewed,
                offered,
                hired,
            });
        }

        Ok(CompanyReport {
            headcount,
            total_active,
            payroll_cost,
            leave_recap,
            hiring_funnel,
        })
    }

    pub fn org_tree(&self) -> AppResult<Vec<(String, String, String)>> {
        self.require_session_pub()?;
        Ok(self.store().org_tree()?)
    }

    pub fn message_mailto(&self, message_id: MessageId) -> AppResult<String> {
        self.require_session_pub()?;
        let messages = self.store().list_messages(None)?;
        let message = messages
            .into_iter()
            .find(|candidate| candidate.id == message_id)
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "message",
                    id: message_id.to_string(),
                })
            })?;
        let candidates = self.store().list_candidates()?;
        let to = candidates
            .iter()
            .find(|candidate| candidate.id == message.candidate_id)
            .and_then(|candidate| candidate.email.clone())
            .unwrap_or_default();
        let subject = mailto_escape(message.subject.as_deref().unwrap_or(""));
        let body = mailto_escape(&message.body);
        Ok(format!("mailto:{to}?subject={subject}&body={body}"))
    }

    pub fn interview_ics(&self, proposal_id: hragents_core::ids::ScheduleId) -> AppResult<String> {
        self.require_session_pub()?;
        let proposals = self.store().list_schedule_proposals(None)?;
        let proposal = proposals
            .into_iter()
            .find(|item| item.id == proposal_id)
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "schedule",
                    id: proposal_id.to_string(),
                })
            })?;
        let slot = proposal.slots.first().ok_or_else(|| {
            AppError::Domain(hragents_core::error::DomainError::validation(
                "E_NO_SLOT",
                "this proposal has no time slot yet",
            ))
        })?;
        Ok(format!(
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//HRAgents//Interview//EN\r\nBEGIN:VEVENT\r\nUID:{}\r\nDTSTAMP:{}\r\nDTSTART:{}\r\nDURATION:PT30M\r\nSUMMARY:Interview\r\nLOCATION:{}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n",
            proposal.id,
            slot.starts_at.millis(),
            slot.starts_at.millis(),
            slot.location.as_deref().unwrap_or(""),
        ))
    }

    pub fn employee_file(&self, employee_id: EmployeeId) -> AppResult<serde_json::Value> {
        self.require_session_pub()?;
        let employee = self.store().employee(employee_id)?;
        let contracts = self
            .store()
            .list_contracts()?
            .into_iter()
            .filter(|contract| contract.employee_id == employee_id)
            .collect::<Vec<_>>();
        Ok(serde_json::json!({
            "employee": employee,
            "contracts": contracts,
        }))
    }
}
