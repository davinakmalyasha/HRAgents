use crate::error::{DomainError, DomainResult};
use crate::ids::{EmployeeId, GoalId, ReviewAssignmentId, ReviewCycleId};
use crate::time::{BusinessDate, UtcInstant};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum CycleStatus {
    Draft,
    Active,
    Closed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct ReviewCycle {
    pub id: ReviewCycleId,
    pub name: String,
    pub status: CycleStatus,
    pub starts_on: BusinessDate,
    pub ends_on: BusinessDate,
    pub created_at: UtcInstant,
}

impl ReviewCycle {
    pub fn new(
        name: impl Into<String>,
        starts_on: BusinessDate,
        ends_on: BusinessDate,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        if ends_on < starts_on {
            return Err(DomainError::validation(
                "E_CYCLE_DATES",
                "review cycle end date cannot precede the start date",
            ));
        }
        Ok(Self {
            id: ReviewCycleId::new(),
            name: name.into(),
            status: CycleStatus::Draft,
            starts_on,
            ends_on,
            created_at: now,
        })
    }

    pub fn activate(&mut self) -> DomainResult<()> {
        if self.status != CycleStatus::Draft {
            return Err(DomainError::conflict(
                "E_CYCLE_STATE",
                "only a draft cycle can be activated",
            ));
        }
        self.status = CycleStatus::Active;
        Ok(())
    }

    pub fn close(&mut self) -> DomainResult<()> {
        if self.status != CycleStatus::Active {
            return Err(DomainError::conflict(
                "E_CYCLE_STATE",
                "only an active cycle can be closed",
            ));
        }
        self.status = CycleStatus::Closed;
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum QuestionKind {
    Rating,
    Text,
    YesNo,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct ReviewQuestion {
    pub key: String,
    pub prompt: String,
    pub kind: QuestionKind,
    pub required: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct ReviewForm {
    pub questions: Vec<ReviewQuestion>,
}

impl ReviewForm {
    pub fn standard() -> Self {
        Self {
            questions: vec![
                ReviewQuestion {
                    key: "outcomes".into(),
                    prompt: "What outcomes did this person deliver?".into(),
                    kind: QuestionKind::Text,
                    required: true,
                },
                ReviewQuestion {
                    key: "collaboration".into(),
                    prompt: "How effectively did they collaborate?".into(),
                    kind: QuestionKind::Rating,
                    required: true,
                },
                ReviewQuestion {
                    key: "would_rehire".into(),
                    prompt: "Would you hire this person again?".into(),
                    kind: QuestionKind::YesNo,
                    required: false,
                },
            ],
        }
    }

    pub fn validate(&self) -> DomainResult<()> {
        if self.questions.is_empty() {
            return Err(DomainError::validation(
                "E_FORM_EMPTY",
                "a review form needs at least one question",
            ));
        }
        let mut keys = BTreeSet::new();
        for question in &self.questions {
            if !keys.insert(question.key.as_str()) {
                return Err(DomainError::validation(
                    "E_FORM_DUPLICATE",
                    format!("duplicate question key {}", question.key),
                ));
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct ReviewAnswer {
    pub rating: Option<u8>,
    pub text: Option<String>,
    pub yes_no: Option<bool>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum AssignmentStatus {
    Pending,
    Sent,
    Submitted,
    Summarized,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct ReviewAssignment {
    pub id: ReviewAssignmentId,
    pub cycle_id: ReviewCycleId,
    pub employee_id: EmployeeId,
    pub reviewer_name: String,
    pub reviewer_email: Option<String>,
    pub status: AssignmentStatus,
    pub form: ReviewForm,
    pub response: Option<BTreeMap<String, ReviewAnswer>>,
    pub created_at: UtcInstant,
    pub sent_at: Option<UtcInstant>,
    pub submitted_at: Option<UtcInstant>,
}

impl ReviewAssignment {
    pub fn new(
        cycle_id: ReviewCycleId,
        employee_id: EmployeeId,
        reviewer_name: impl Into<String>,
        form: ReviewForm,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        form.validate()?;
        Ok(Self {
            id: ReviewAssignmentId::new(),
            cycle_id,
            employee_id,
            reviewer_name: reviewer_name.into(),
            reviewer_email: None,
            status: AssignmentStatus::Pending,
            form,
            response: None,
            created_at: now,
            sent_at: None,
            submitted_at: None,
        })
    }

    pub fn send(&mut self, now: UtcInstant) -> DomainResult<()> {
        if self.status != AssignmentStatus::Pending {
            return Err(DomainError::conflict(
                "E_ASSIGNMENT_STATE",
                "only a pending assignment can be sent",
            ));
        }
        self.status = AssignmentStatus::Sent;
        self.sent_at = Some(now);
        Ok(())
    }

    pub fn submit(
        &mut self,
        answers: BTreeMap<String, ReviewAnswer>,
        now: UtcInstant,
    ) -> DomainResult<()> {
        if self.status != AssignmentStatus::Sent {
            return Err(DomainError::conflict(
                "E_ASSIGNMENT_STATE",
                "responses can only be submitted for a sent assignment",
            ));
        }
        for question in &self.form.questions {
            let answer = answers.get(&question.key);
            if question.required {
                let Some(answer) = answer else {
                    return Err(DomainError::validation(
                        "E_FORM_REQUIRED",
                        format!("question {} is required", question.key),
                    ));
                };
                let present = match question.kind {
                    QuestionKind::Rating => answer.rating.is_some(),
                    QuestionKind::Text => answer
                        .text
                        .as_deref()
                        .is_some_and(|text| !text.trim().is_empty()),
                    QuestionKind::YesNo => answer.yes_no.is_some(),
                };
                if !present {
                    return Err(DomainError::validation(
                        "E_FORM_REQUIRED",
                        format!("question {} is required", question.key),
                    ));
                }
            }
            if let Some(answer) = answer
                && let Some(rating) = answer.rating
                && !(1..=5).contains(&rating)
            {
                return Err(DomainError::validation(
                    "E_RATING_RANGE",
                    "ratings are 1 through 5",
                ));
            }
        }
        self.response = Some(answers);
        self.status = AssignmentStatus::Submitted;
        self.submitted_at = Some(now);
        Ok(())
    }

    pub fn summarize(&mut self) -> DomainResult<()> {
        if self.status != AssignmentStatus::Submitted {
            return Err(DomainError::conflict(
                "E_ASSIGNMENT_STATE",
                "only a submitted review can be summarized",
            ));
        }
        self.status = AssignmentStatus::Summarized;
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum GoalStatus {
    Draft,
    Active,
    Completed,
    Cancelled,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Goal {
    pub id: GoalId,
    pub employee_id: EmployeeId,
    pub title: String,
    pub status: GoalStatus,
    pub due_on: Option<BusinessDate>,
    pub progress_bp: i64,
    pub created_at: UtcInstant,
}

impl Goal {
    pub fn new(
        employee_id: EmployeeId,
        title: impl Into<String>,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        let title = title.into();
        if title.trim().len() < 3 {
            return Err(DomainError::validation(
                "E_GOAL_TITLE",
                "a goal needs a title",
            ));
        }
        Ok(Self {
            id: GoalId::new(),
            employee_id,
            title,
            status: GoalStatus::Draft,
            due_on: None,
            progress_bp: 0,
            created_at: now,
        })
    }

    pub fn activate(&mut self) -> DomainResult<()> {
        if self.status != GoalStatus::Draft {
            return Err(DomainError::conflict(
                "E_GOAL_STATE",
                "only a draft goal can be activated",
            ));
        }
        self.status = GoalStatus::Active;
        Ok(())
    }

    pub fn set_progress(&mut self, progress_bp: i64) -> DomainResult<()> {
        if self.status == GoalStatus::Cancelled || self.status == GoalStatus::Completed {
            return Err(DomainError::conflict(
                "E_GOAL_CLOSED",
                "this goal is already closed",
            ));
        }
        if !(0..=10_000).contains(&progress_bp) {
            return Err(DomainError::validation(
                "E_GOAL_PROGRESS",
                "goal progress is a basis-point value between 0 and 10000",
            ));
        }
        self.progress_bp = progress_bp;
        if progress_bp == 10_000 {
            self.status = GoalStatus::Completed;
        }
        Ok(())
    }

    pub fn cancel(&mut self) -> DomainResult<()> {
        if self.status == GoalStatus::Completed {
            return Err(DomainError::conflict(
                "E_GOAL_CLOSED",
                "a completed goal cannot be cancelled",
            ));
        }
        self.status = GoalStatus::Cancelled;
        Ok(())
    }

    pub fn is_overdue(&self, today: BusinessDate) -> bool {
        self.status == GoalStatus::Active && self.due_on.is_some_and(|due| due < today)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn now() -> UtcInstant {
        UtcInstant::from_millis(1_760_000_000_000).unwrap()
    }

    fn date(value: &str) -> BusinessDate {
        BusinessDate::parse(value).unwrap()
    }

    #[test]
    fn cycle_activation_and_dates() {
        assert!(
            ReviewCycle::new("2026 H2", date("2026-12-01"), date("2026-11-01"), now()).is_err()
        );
        let mut cycle =
            ReviewCycle::new("2026 H2", date("2026-07-01"), date("2026-12-31"), now()).unwrap();
        cycle.activate().unwrap();
        assert_eq!(cycle.status, CycleStatus::Active);
        cycle.close().unwrap();
    }

    #[test]
    fn assignment_requires_required_answers_then_summarizes() {
        let mut assignment = ReviewAssignment::new(
            ReviewCycleId::new(),
            EmployeeId::new(),
            "Ayu",
            ReviewForm::standard(),
            now(),
        )
        .unwrap();
        assert!(assignment.submit(BTreeMap::new(), now()).is_err());
        assignment.send(now()).unwrap();
        let mut answers = BTreeMap::new();
        answers.insert(
            "outcomes".into(),
            ReviewAnswer {
                text: Some("Shipped the migration".into()),
                ..Default::default()
            },
        );
        answers.insert(
            "collaboration".into(),
            ReviewAnswer {
                rating: Some(4),
                ..Default::default()
            },
        );
        assignment.submit(answers, now()).unwrap();
        assignment.summarize().unwrap();
        assert_eq!(assignment.status, AssignmentStatus::Summarized);
    }

    #[test]
    fn rating_must_be_one_to_five() {
        let mut assignment = ReviewAssignment::new(
            ReviewCycleId::new(),
            EmployeeId::new(),
            "Ayu",
            ReviewForm::standard(),
            now(),
        )
        .unwrap();
        assignment.send(now()).unwrap();
        let mut answers = BTreeMap::new();
        answers.insert(
            "outcomes".into(),
            ReviewAnswer {
                text: Some("Shipped".into()),
                ..Default::default()
            },
        );
        answers.insert(
            "collaboration".into(),
            ReviewAnswer {
                rating: Some(9),
                ..Default::default()
            },
        );
        assert!(assignment.submit(answers, now()).is_err());
    }

    #[test]
    fn goal_progress_completes_at_full() {
        let mut goal = Goal::new(EmployeeId::new(), "Ship the desktop beta", now()).unwrap();
        goal.activate().unwrap();
        goal.set_progress(5_000).unwrap();
        assert_eq!(goal.progress_bp, 5_000);
        goal.set_progress(10_000).unwrap();
        assert_eq!(goal.status, GoalStatus::Completed);
        assert!(goal.set_progress(1_000).is_err());
    }
}
