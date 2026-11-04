//! Agent helpers: read-only, deterministic preparation for the HR operator.
//!
//! The product rule holds here: agents extract and communicate; deterministic
//! code decides; a named human gates every consequential outcome. Every helper
//! below only reads and explains. Nothing here approves, rejects, sends,
//! locks, deletes, or pays. The operator acts through the existing gated
//! operations; these helpers just remove the reading and copying work.

use super::{AppError, AppResult, AppService};
use hragents_core::ids::{EmployeeId, JobId, PayrollRunId};
use hragents_core::payroll::Severity;
use hragents_core::policy::{PolicyCorpus, PolicyDocument, PolicyHit};
use hragents_core::time::BusinessDate;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RankedApplication {
    pub application_id: String,
    pub candidate_name: String,
    pub stage: String,
    pub overall_bp: Option<i64>,
    pub sigma_bp: Option<i64>,
    pub flags: Vec<String>,
    pub has_evaluation: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PayrollReadiness {
    pub run_id: String,
    pub blocking: usize,
    pub warnings: usize,
    pub lines: usize,
    pub ready: bool,
    pub sentences: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AttendanceFinding {
    pub kind: String,
    pub date: Option<String>,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentHealth {
    pub expiring: Vec<String>,
    pub overdue_requests: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DailyBriefing {
    pub sentences: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AskResponse {
    pub body: String,
    pub citations: Vec<PolicyHit>,
    pub matched: bool,
    pub provider_used: bool,
}

/// The product's own documented rules, as citable sources. These are not
/// guesses: each mirrors a gate or policy the deterministic code enforces.
fn builtin_corpus() -> PolicyCorpus {
    PolicyCorpus::new(vec![
        PolicyDocument {
            slug: "leave-accrual".into(),
            title: "Annual leave policy".into(),
            body: "Employees receive 12 days of annual leave per year. Leave is recorded by HR on the person's behalf; this edition has no employee login. Balances are shown in days; a half day counts as 0.5.".into(),
            effective_from: None,
            owner: Some("HR".into()),
        },
        PolicyDocument {
            slug: "probation".into(),
            title: "Probation and fixed-term contracts".into(),
            body: "The standard probation period is three months, with one extension of up to three months only in writing. A fixed-term contract must state its end date and the reason for the term; expiry reminders are generated 30 days ahead.".into(),
            effective_from: None,
            owner: Some("HR".into()),
        },
        PolicyDocument {
            slug: "gated-rejection".into(),
            title: "Hiring policy: gated rejection".into(),
            body: "A rejection at or above the merit floor is a gated decision: it needs an authenticated HR operator, a reason of at least 10 characters, and a fresh password. The audit chain stores the operator, reason, and payload hash. Never reject automatically.".into(),
            effective_from: None,
            owner: Some("HR".into()),
        },
        PolicyDocument {
            slug: "payroll-signoff".into(),
            title: "Payroll runbook: pre-flight and sign-off".into(),
            body: "Payroll needs seven verified statutory tables (BPJS Kesehatan, JHT, JP, JKK, JKM, PPh 21 TER, PTKP), a complete payroll profile for each employee, and no blocking anomalies. Sign-off requires a fresh password and freezes the run. The app never executes a payment; it exports a review packet.".into(),
            effective_from: None,
            owner: Some("Finance".into()),
        },
        PolicyDocument {
            slug: "consent-erasure".into(),
            title: "Data governance: consent and erasure".into(),
            body: "Withdrawing consent stops processing immediately: scoring, messaging, and offers are blocked, and the withdrawal is audited. Erasure is a separate gated action: approval and execution are both named, retention holds block it, and audit rows plus statutory payroll records survive.".into(),
            effective_from: None,
            owner: Some("HR".into()),
        },
    ])
}

const ASK_SYSTEM: &str = "You paraphrase a company policy answer for an HR operator. \
Reply with plain prose only, no new facts, no decisions, no instructions to approve, \
reject, send, erase, or pay. Keep every cited source. If the input says no source \
was found, say so and stop.";

fn try_provider_paraphrase(question: &str, deterministic_body: &str) -> Option<String> {
    if std::env::var("OPENCODE_API_KEY").is_err() {
        return None;
    }
    let config = hragents_agents::provider::ProviderConfig {
        provider: "opencode_go".into(),
        base_url: None,
        model: "deepseek-v4.1-flash".into(),
        api_key_env: "OPENCODE_API_KEY".into(),
    };
    let client = hragents_agents::provider::RigLlmClient::new(config).ok()?;
    use hragents_agents::provider::LlmClient;
    let user = format!("Question: {question}\nDraft answer: {deterministic_body}");
    client.complete(ASK_SYSTEM, &user).ok().filter(|reply| {
        let trimmed = reply.trim();
        !trimmed.is_empty() && trimmed.len() <= 2_000
    })
}

impl AppService {
    /// Ranked shortlist for one job: evaluated applications first by overall
    /// score, unevaluated last, stable id tiebreak. Flags (e.g. high sigma)
    /// travel with the row so HR sees why a score needs a second look.
    pub fn rank_applications(&self, job_id: JobId) -> AppResult<Vec<RankedApplication>> {
        self.require_session_pub()?;
        // Fail closed on unknown jobs: an empty ranking for a job that does
        // not exist would look like "no applicants".
        let _ = self.store().job(job_id)?;
        let candidates = self.store().list_candidates()?;
        let names: BTreeMap<String, String> = candidates
            .into_iter()
            .map(|candidate| (candidate.id.to_string(), candidate.full_name))
            .collect();
        let mut ranked: Vec<RankedApplication> = Vec::new();
        for application in self.store().list_applications(Some(job_id))? {
            let evaluation = self.store().evaluation_for(application.id)?;
            let (overall_bp, sigma_bp, flags, has_evaluation) = match evaluation {
                Some(evaluation) => (
                    Some(evaluation.overall_bp),
                    Some(evaluation.sigma_bp),
                    evaluation.flags.clone(),
                    true,
                ),
                None => (None, None, Vec::new(), false),
            };
            ranked.push(RankedApplication {
                application_id: application.id.to_string(),
                candidate_name: names
                    .get(&application.candidate_id.to_string())
                    .cloned()
                    .unwrap_or_else(|| "Unknown candidate".into()),
                stage: format!("{:?}", application.stage).to_lowercase(),
                overall_bp,
                sigma_bp,
                flags,
                has_evaluation,
            });
        }
        ranked.sort_by(|a, b| {
            b.has_evaluation
                .cmp(&a.has_evaluation)
                .then_with(|| b.overall_bp.cmp(&a.overall_bp))
                .then_with(|| a.application_id.cmp(&b.application_id))
        });
        Ok(ranked)
    }

    /// Plain-words payroll pre-flight: counts plus one sentence per anomaly.
    /// `ready` is true only when no blocking (error-severity) anomaly remains.
    /// Read-only; sign-off stays the gated operation.
    pub fn payroll_readiness(&self, run_id: PayrollRunId) -> AppResult<PayrollReadiness> {
        self.require_session_pub()?;
        let run = self.store().payroll_run(run_id)?;
        let mut blocking = 0_usize;
        let mut warnings = 0_usize;
        let mut sentences = Vec::new();
        for anomaly in &run.anomalies {
            match anomaly.severity {
                Severity::Error => {
                    blocking += 1;
                    sentences.push(format!("Must fix: {} — {}", anomaly.code, anomaly.detail));
                }
                Severity::Warning => {
                    warnings += 1;
                    sentences.push(format!("Check: {} — {}", anomaly.code, anomaly.detail));
                }
                Severity::Info => {
                    sentences.push(format!("Note: {} — {}", anomaly.code, anomaly.detail));
                }
            }
        }
        sentences.push(format!(
            "{} people, net {}.",
            run.totals.employees, run.totals.net
        ));
        Ok(PayrollReadiness {
            run_id: run.id.to_string(),
            blocking,
            warnings,
            lines: run.lines.len(),
            ready: blocking == 0,
            sentences,
        })
    }

    /// Attendance findings for one month: late days, overtime days, and the
    /// absent-day count, each as a plain sentence. Leave-approved absences are
    /// not subtracted here; the caller owns that data.
    pub fn attendance_findings(
        &self,
        employee_id: EmployeeId,
        year: i32,
        month: u32,
    ) -> AppResult<Vec<AttendanceFinding>> {
        self.require_session_pub()?;
        let _ = self.store().employee(employee_id)?;
        let shifts = self.store().list_shifts()?;
        let Some(shift) = shifts.into_iter().next() else {
            return Ok(vec![AttendanceFinding {
                kind: "no_shift".into(),
                date: None,
                detail: "No shift is defined yet, so lateness and overtime cannot be measured. Create a shift first.".into(),
            }]);
        };
        let month_start =
            BusinessDate::parse(&format!("{year:04}-{month:02}-01")).map_err(|_| {
                AppError::Domain(hragents_core::error::DomainError::validation(
                    "E_MONTH",
                    "month must be 1..=12",
                ))
            })?;
        let end = month_start.add_days(31);
        let checkins = self.store().list_checkins(&employee_id, month_start, end)?;
        let mut per_day: BTreeMap<BusinessDate, (i64, i64)> = BTreeMap::new();
        for checkin in &checkins {
            per_day
                .entry(checkin.date)
                .and_modify(|slot| {
                    slot.0 = slot.0.min(checkin.in_minute);
                    slot.1 = slot.1.max(checkin.out_minute);
                })
                .or_insert((checkin.in_minute, checkin.out_minute));
        }
        let mut findings = Vec::new();
        for (date, (in_minute, out_minute)) in &per_day {
            let late = shift.late_minutes(*in_minute);
            if late > 0 {
                findings.push(AttendanceFinding {
                    kind: "late".into(),
                    date: Some(date.to_string()),
                    detail: format!("{late} minutes late on {date}."),
                });
            }
            let overtime = shift.overtime_minutes(*out_minute);
            if overtime > 0 {
                findings.push(AttendanceFinding {
                    kind: "overtime".into(),
                    date: Some(date.to_string()),
                    detail: format!("{overtime} minutes overtime on {date}."),
                });
            }
        }
        let workdays = month_start.working_days_in_month();
        let absent = workdays.saturating_sub(per_day.len() as u32);
        if absent > 0 {
            findings.push(AttendanceFinding {
                kind: "absent".into(),
                date: None,
                detail: format!("{absent} of {workdays} workdays have no check-in this month."),
            });
        }
        if findings.is_empty() {
            findings.push(AttendanceFinding {
                kind: "clean".into(),
                date: None,
                detail: "Full attendance: every workday has a check-in, no lateness, no overtime."
                    .into(),
            });
        }
        Ok(findings)
    }

    /// Document health: expiring soon plus overdue requests. Read-only; the
    /// verify and sweep operations stay gated.
    pub fn document_health(&self) -> AppResult<DocumentHealth> {
        self.require_session_pub()?;
        let limit = BusinessDate::today().add_days(30);
        let mut expiring: Vec<String> = self
            .store()
            .expiring_documents(limit)?
            .into_iter()
            .map(|(document, _owner)| {
                format!(
                    "{} expires on {}.",
                    document.filename,
                    document
                        .expires_on
                        .map_or("an unknown date".into(), |date| date.to_string())
                )
            })
            .collect();
        expiring.sort();
        expiring.truncate(50);
        let today = BusinessDate::today();
        let mut overdue_requests: Vec<String> = self
            .store()
            .list_document_requests(None)?
            .into_iter()
            .filter(|request| {
                request.status == hragents_core::documents::DocumentRequestStatus::Requested
                    && request.due_on.is_some_and(|due| due < today)
            })
            .map(|request| {
                format!(
                    "{} requested for {} is overdue (due {}).",
                    request.document_type,
                    request.employee_id,
                    request.due_on.map_or("?".into(), |due| due.to_string())
                )
            })
            .collect();
        overdue_requests.sort();
        overdue_requests.truncate(50);
        Ok(DocumentHealth {
            expiring,
            overdue_requests,
        })
    }

    /// One deterministic morning list: approvals, reminders, outbox, drafts,
    /// expiring documents. Sentences only; acting stays with the operator.
    pub fn daily_briefing(&self) -> AppResult<DailyBriefing> {
        self.require_session_pub()?;
        let mut sentences = Vec::new();
        let approvals = self.store().list_approvals(true)?;
        let urgent = approvals
            .iter()
            .filter(|approval| approval.priority == hragents_core::approvals::Priority::Urgent)
            .count();
        sentences.push(format!(
            "{} open approvals{}.",
            approvals.len(),
            if urgent > 0 {
                format!(", {urgent} urgent")
            } else {
                String::new()
            }
        ));
        let outbox = self.store().list_messages(None)?;
        let queued = outbox
            .iter()
            .filter(|message| message.status == hragents_core::hiring_comms::MessageStatus::Queued)
            .count();
        if queued > 0 {
            sentences.push(format!(
                "{queued} messages are queued and waiting for you to send."
            ));
        }
        let drafts = self
            .store()
            .list_payroll_runs()?
            .into_iter()
            .filter(|run| run.status == hragents_core::payroll::RunStatus::Computed)
            .count();
        if drafts > 0 {
            sentences.push(format!(
                "{drafts} payroll runs are computed and awaiting sign-off."
            ));
        }
        let health = self.document_health()?;
        if !health.expiring.is_empty() {
            sentences.push(format!(
                "{} documents expire within 30 days.",
                health.expiring.len()
            ));
        }
        if !health.overdue_requests.is_empty() {
            sentences.push(format!(
                "{} document requests are overdue.",
                health.overdue_requests.len()
            ));
        }
        if sentences.len() == 1 {
            sentences.push("Nothing else needs attention.".into());
        }
        Ok(DailyBriefing { sentences })
    }

    /// Policy answers with citations from the built-in rule corpus. Offline by
    /// default; when `OPENCODE_API_KEY` is present, DeepSeek V4.1 Flash (the
    /// only live model) may paraphrase the deterministic draft — citations and
    /// the no-match refusal never change. Never decides, sends, or changes a
    /// record: the reply is text for the operator to read.
    pub fn ask_assistant(&self, question: &str) -> AppResult<AskResponse> {
        self.require_session_pub()?;
        let answer = hragents_agents::answer_question(&builtin_corpus(), question);
        if !answer.matched {
            return Ok(AskResponse {
                body: answer.body,
                citations: answer.citations,
                matched: false,
                provider_used: false,
            });
        }
        let paraphrased = try_provider_paraphrase(question, &answer.body);
        Ok(AskResponse {
            body: paraphrased.clone().unwrap_or(answer.body),
            citations: answer.citations,
            matched: true,
            provider_used: paraphrased.is_some(),
        })
    }
}
