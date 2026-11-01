use crate::error::{DomainError, DomainResult};
use crate::ids::{ApplicationId, CandidateId, DocumentId, EvaluationId, JobId, OperatorId};
use crate::time::UtcInstant;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ConsentStatus {
    Pending,
    Granted,
    Withdrawn,
    Expired,
}

impl ConsentStatus {
    pub fn permits_processing(self) -> bool {
        self == Self::Granted
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum JobStatus {
    Draft,
    Open,
    Paused,
    Closed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Job {
    pub id: JobId,
    pub title: String,
    pub org_unit: String,
    pub location: String,
    pub employment_type: String,
    pub status: JobStatus,
    pub openings: u16,
    pub rubric_id: Option<String>,
    pub created_at: UtcInstant,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Candidate {
    pub id: CandidateId,
    pub full_name: String,
    pub email: Option<String>,
    pub phone: Option<String>,
    pub source: String,
    pub headline: Option<String>,
    pub location: Option<String>,
    pub consent: ConsentStatus,
    pub document_ids: Vec<DocumentId>,
    pub created_at: UtcInstant,
}

impl Candidate {
    pub fn new(full_name: impl Into<String>, source: impl Into<String>, now: UtcInstant) -> Self {
        Self {
            id: CandidateId::new(),
            full_name: full_name.into(),
            email: None,
            phone: None,
            source: source.into(),
            headline: None,
            location: None,
            consent: ConsentStatus::Pending,
            document_ids: Vec::new(),
            created_at: now,
        }
    }

    pub fn has_identity(&self) -> bool {
        self.email.is_some() || self.phone.is_some()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ApplicationStage {
    Imported,
    Screening,
    Review,
    Interview,
    Offer,
    Hired,
    Rejected,
    Withdrawn,
}

impl ApplicationStage {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Imported => "imported",
            Self::Screening => "screening",
            Self::Review => "review",
            Self::Interview => "interview",
            Self::Offer => "offer",
            Self::Hired => "hired",
            Self::Rejected => "rejected",
            Self::Withdrawn => "withdrawn",
        }
    }

    pub fn is_terminal(self) -> bool {
        matches!(self, Self::Hired | Self::Rejected | Self::Withdrawn)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Application {
    pub id: ApplicationId,
    pub candidate_id: CandidateId,
    pub job_id: JobId,
    pub stage: ApplicationStage,
    pub priority: u8,
    pub created_at: UtcInstant,
    pub updated_at: UtcInstant,
    pub rejection_reason: Option<String>,
    pub rejected_by: Option<OperatorId>,
}

impl Application {
    pub fn new(candidate_id: CandidateId, job_id: JobId, now: UtcInstant) -> Self {
        Self {
            id: ApplicationId::new(),
            candidate_id,
            job_id,
            stage: ApplicationStage::Imported,
            priority: 0,
            created_at: now,
            updated_at: now,
            rejection_reason: None,
            rejected_by: None,
        }
    }

    pub fn advance(&mut self, to: ApplicationStage, now: UtcInstant) -> DomainResult<()> {
        if self.stage.is_terminal() {
            return Err(DomainError::conflict(
                "E_APPLICATION_CLOSED",
                "this application is already closed",
            ));
        }
        if matches!(to, ApplicationStage::Rejected | ApplicationStage::Withdrawn) {
            return Err(DomainError::validation(
                "E_DECISION_PATH",
                "use the decision operation for rejection or withdrawal",
            ));
        }
        if to == self.stage {
            return Ok(());
        }
        self.stage = to;
        self.updated_at = now;
        Ok(())
    }

    /// Rejection is always a named-human decision with a reason. It is never
    /// automatic, and it is never executed by an agent.
    pub fn reject(
        &mut self,
        operator_id: OperatorId,
        reason: &str,
        now: UtcInstant,
    ) -> DomainResult<()> {
        if self.stage.is_terminal() {
            return Err(DomainError::conflict(
                "E_APPLICATION_CLOSED",
                "this application is already closed",
            ));
        }
        if reason.trim().chars().count() < 10 {
            return Err(DomainError::validation(
                "E_REJECT_REASON",
                "a rejection needs a reason of at least 10 characters",
            ));
        }
        self.stage = ApplicationStage::Rejected;
        self.rejection_reason = Some(reason.trim().to_owned());
        self.rejected_by = Some(operator_id);
        self.updated_at = now;
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Dimension {
    pub key: String,
    pub label: String,
    pub weight_bp: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Rubric {
    pub id: String,
    pub name: String,
    pub dimensions: Vec<Dimension>,
    /// Minimum score, in basis points, at which rejection becomes a gated
    /// decision that requires an explicit named-human sign-off.
    pub merit_floor_bp: i64,
    /// Extraction disagreement above this σ flags the evaluation for review.
    pub sigma_limit_bp: i64,
}

impl Rubric {
    pub fn validate(&self) -> DomainResult<()> {
        if self.dimensions.is_empty() {
            return Err(DomainError::validation(
                "E_RUBRIC_EMPTY",
                "a rubric needs at least one dimension",
            ));
        }
        let mut keys = BTreeSet::new();
        let mut total = 0_i64;
        for dimension in &self.dimensions {
            if dimension.key.trim().is_empty() {
                return Err(DomainError::validation(
                    "E_RUBRIC_KEY",
                    "every dimension needs a key",
                ));
            }
            if !keys.insert(dimension.key.as_str()) {
                return Err(DomainError::validation(
                    "E_RUBRIC_DUPLICATE",
                    format!("duplicate dimension {}", dimension.key),
                ));
            }
            if !(0..=10_000).contains(&dimension.weight_bp) {
                return Err(DomainError::validation(
                    "E_RUBRIC_WEIGHT",
                    "dimension weights are basis points between 0 and 10000",
                ));
            }
            total += dimension.weight_bp;
        }
        if total != 10_000 {
            return Err(DomainError::validation(
                "E_RUBRIC_WEIGHTS",
                format!("dimension weights must sum to 10000 bp, got {total}"),
            ));
        }
        if !(0..=10_000).contains(&self.merit_floor_bp) {
            return Err(DomainError::validation(
                "E_MERIT_FLOOR",
                "merit floor is a basis-point score between 0 and 10000",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Evidence {
    pub dimension: String,
    pub quote: String,
    pub source_document_id: DocumentId,
    /// 0–10000; how strongly the quote supports the dimension.
    pub confidence_bp: i64,
    pub page: Option<u32>,
}

impl Evidence {
    pub fn validate(&self) -> DomainResult<()> {
        if self.quote.trim().len() < 3 {
            return Err(DomainError::validation(
                "E_EVIDENCE_QUOTE",
                "evidence needs a quotable excerpt",
            ));
        }
        if !(0..=10_000).contains(&self.confidence_bp) {
            return Err(DomainError::validation(
                "E_EVIDENCE_CONFIDENCE",
                "evidence confidence is a basis point value between 0 and 10000",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct RunScores {
    pub dimension_scores: BTreeMap<String, i64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Evaluation {
    pub id: EvaluationId,
    pub application_id: ApplicationId,
    pub rubric_id: String,
    pub dimension_scores: BTreeMap<String, i64>,
    pub overall_bp: i64,
    pub sigma_bp: i64,
    pub runs: usize,
    pub evidence: Vec<Evidence>,
    pub flags: Vec<String>,
    pub created_at: UtcInstant,
}

impl Evaluation {
    /// Merge k extraction runs into one deterministic evaluation.
    ///
    /// Each dimension takes the **mean** of the runs; the overall score is the
    /// rubric-weighted sum of those means. σ is the population standard
    /// deviation of the per-run weighted totals, so it measures extraction
    /// disagreement rather than the final answer. This mirrors Python's
    /// `aggregate_runs`.
    pub fn from_runs(
        application_id: ApplicationId,
        rubric: &Rubric,
        runs: &[RunScores],
        evidence: Vec<Evidence>,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        rubric.validate()?;
        if runs.is_empty() {
            return Err(DomainError::validation(
                "E_EVAL_NO_RUNS",
                "an evaluation needs at least one extraction run",
            ));
        }
        if runs.len() > 7 {
            return Err(DomainError::validation(
                "E_EVAL_TOO_MANY_RUNS",
                "at most seven extraction runs are merged",
            ));
        }
        for evidence in &evidence {
            evidence.validate()?;
        }

        let mut dimension_scores = BTreeMap::new();
        for dimension in &rubric.dimensions {
            let mut values = Vec::with_capacity(runs.len());
            for run in runs {
                let value = *run.dimension_scores.get(&dimension.key).ok_or_else(|| {
                    DomainError::validation(
                        "E_EVAL_MISSING_DIMENSION",
                        format!("run is missing dimension {}", dimension.key),
                    )
                })?;
                if !(0..=10_000).contains(&value) {
                    return Err(DomainError::validation(
                        "E_EVAL_RANGE",
                        format!("dimension {} is outside 0..=10000", dimension.key),
                    ));
                }
                values.push(value);
            }
            // Mean across runs, matching the Python oracle's aggregate_runs.
            // Integer basis points keep it exact; round once, half away.
            let total: i64 = values.iter().sum();
            let n = i64::try_from(values.len()).unwrap_or(1);
            let mean = if total >= 0 {
                (total + n / 2) / n
            } else {
                (total - n / 2) / n
            };
            dimension_scores.insert(dimension.key.clone(), mean);
        }

        let overall_bp = weighted_score(rubric, &dimension_scores)?;
        let per_run_totals: Vec<i64> = runs
            .iter()
            .map(|run| weighted_score(rubric, &run.dimension_scores))
            .collect::<DomainResult<_>>()?;
        let sigma_bp = population_stddev(&per_run_totals);

        let mut flags = Vec::new();
        if sigma_bp > rubric.sigma_limit_bp {
            flags.push("inconsistent_extraction".to_owned());
        }
        for dimension in &rubric.dimensions {
            let has_evidence = evidence.iter().any(|item| item.dimension == dimension.key);
            if !has_evidence {
                flags.push(format!("missing_evidence:{}", dimension.key));
            }
        }

        Ok(Self {
            id: EvaluationId::new(),
            application_id,
            rubric_id: rubric.id.clone(),
            dimension_scores,
            overall_bp,
            sigma_bp,
            runs: runs.len(),
            evidence,
            flags,
            created_at: now,
        })
    }

    pub fn meets_merit_floor(&self, rubric: &Rubric) -> bool {
        self.overall_bp >= rubric.merit_floor_bp
    }
}

fn weighted_score(rubric: &Rubric, scores: &BTreeMap<String, i64>) -> DomainResult<i64> {
    let mut total = 0_i64;
    for dimension in &rubric.dimensions {
        let score = *scores.get(&dimension.key).ok_or_else(|| {
            DomainError::validation(
                "E_EVAL_MISSING_DIMENSION",
                format!("scores are missing dimension {}", dimension.key),
            )
        })?;
        if !(0..=10_000).contains(&score) {
            return Err(DomainError::validation(
                "E_EVAL_RANGE",
                format!("dimension {} is outside 0..=10000", dimension.key),
            ));
        }
        total += score * dimension.weight_bp;
    }
    // Weights sum to 10000, so divide by 10000 with half-away-from-zero.
    Ok((total + 5_000) / 10_000)
}

fn population_stddev(values: &[i64]) -> i64 {
    if values.len() < 2 {
        return 0;
    }
    // Python's statistics.pstdev is a float; compute in f64 and round once to
    // the nearest basis point. The inputs are already integer scores, so this
    // only affects the final representation, never a decision threshold beyond
    // the rubric's own sigma limit.
    let n = values.len() as f64;
    let mean = values.iter().map(|value| *value as f64).sum::<f64>() / n;
    let variance = values
        .iter()
        .map(|value| {
            let delta = *value as f64 - mean;
            delta * delta
        })
        .sum::<f64>()
        / n;
    variance.sqrt().round() as i64
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub enum PolicyOutcome {
    /// Consent is missing or withdrawn: no processing, no outreach.
    Blocked { code: String, message: String },
    /// A human must read the case and decide.
    HumanReview,
    /// Score is at or above the merit floor. Rejection remains possible, but it
    /// requires a named human, a reason, and a sign-off.
    GatedRejection { requires_signoff: bool },
}

/// Deterministic policy over structured facts. No LLM and no randomness.
pub fn evaluate_policy(
    consent: ConsentStatus,
    evaluation: Option<&Evaluation>,
    rubric: &Rubric,
) -> PolicyOutcome {
    if !consent.permits_processing() {
        return PolicyOutcome::Blocked {
            code: "E_CONSENT_REQUIRED".to_owned(),
            message: "candidate consent is not granted; processing and messaging are blocked"
                .to_owned(),
        };
    }
    match evaluation {
        None => PolicyOutcome::HumanReview,
        Some(evaluation) if evaluation.meets_merit_floor(rubric) => PolicyOutcome::GatedRejection {
            requires_signoff: true,
        },
        Some(_) => PolicyOutcome::HumanReview,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rubric() -> Rubric {
        Rubric {
            id: "engineering-v1".into(),
            name: "Engineering".into(),
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

    fn run(skills: i64, impact: i64) -> RunScores {
        RunScores {
            dimension_scores: BTreeMap::from([
                ("skills".into(), skills),
                ("impact".into(), impact),
            ]),
        }
    }

    fn now() -> UtcInstant {
        UtcInstant::from_millis(1_760_000_000_000).unwrap()
    }

    #[test]
    fn weighted_score_is_deterministic() {
        let evaluation = Evaluation::from_runs(
            ApplicationId::new(),
            &rubric(),
            &[run(8_000, 6_000), run(8_000, 6_000), run(8_000, 6_000)],
            vec![],
            now(),
        )
        .unwrap();
        assert_eq!(evaluation.overall_bp, 7_200);
        assert_eq!(evaluation.sigma_bp, 0);
        assert_eq!(evaluation.dimension_scores["skills"], 8_000);
    }

    #[test]
    fn sigma_flags_inconsistent_extraction() {
        let evaluation = Evaluation::from_runs(
            ApplicationId::new(),
            &rubric(),
            &[run(9_000, 9_000), run(4_000, 4_000)],
            vec![],
            now(),
        )
        .unwrap();
        assert!(evaluation.sigma_bp > 500);
        assert!(
            evaluation
                .flags
                .iter()
                .any(|flag| flag == "inconsistent_extraction")
        );
    }

    #[test]
    fn consent_blocks_processing() {
        let outcome = evaluate_policy(ConsentStatus::Withdrawn, None, &rubric());
        assert!(matches!(outcome, PolicyOutcome::Blocked { .. }));
    }

    #[test]
    fn high_score_rejection_requires_signoff_not_automation() {
        let evaluation = Evaluation::from_runs(
            ApplicationId::new(),
            &rubric(),
            &[run(9_000, 9_000)],
            vec![],
            now(),
        )
        .unwrap();
        let outcome = evaluate_policy(ConsentStatus::Granted, Some(&evaluation), &rubric());
        assert_eq!(
            outcome,
            PolicyOutcome::GatedRejection {
                requires_signoff: true
            }
        );
    }

    #[test]
    fn rejection_needs_reason_and_named_operator() {
        let mut application = Application::new(CandidateId::new(), JobId::new(), now());
        assert!(application.reject(OperatorId::new(), "no", now()).is_err());
        application
            .reject(
                OperatorId::new(),
                "lacks the required on-call experience",
                now(),
            )
            .unwrap();
        assert_eq!(application.stage, ApplicationStage::Rejected);
    }
}
