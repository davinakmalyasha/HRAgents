use crate::error::{DomainError, DomainResult};
use crate::hiring::Evaluation;
use crate::ids::{ApplicationId, CandidateId, FeedbackId, MessageId, OfferId, ScheduleId};
use crate::money::Money;
use crate::time::{BusinessDate, UtcInstant};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum SlotMode {
    Onsite,
    Remote,
    Phone,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct InterviewSlot {
    pub starts_at: UtcInstant,
    pub duration_minutes: u16,
    pub mode: SlotMode,
    pub location: Option<String>,
}

impl InterviewSlot {
    pub fn validate(&self) -> DomainResult<()> {
        if self.duration_minutes == 0 || self.duration_minutes > 480 {
            return Err(DomainError::validation(
                "E_SLOT_DURATION",
                "an interview slot lasts between 1 and 480 minutes",
            ));
        }
        if self.mode == SlotMode::Onsite
            && self
                .location
                .as_deref()
                .is_none_or(|location| location.trim().is_empty())
        {
            return Err(DomainError::validation(
                "E_SLOT_LOCATION",
                "an onsite interview needs a location",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ProposalStatus {
    Proposed,
    Confirmed,
    Declined,
    Expired,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct ScheduleProposal {
    pub id: ScheduleId,
    pub application_id: ApplicationId,
    pub slots: Vec<InterviewSlot>,
    pub status: ProposalStatus,
    pub confirmed_index: Option<usize>,
    pub created_at: UtcInstant,
    pub decided_at: Option<UtcInstant>,
}

impl ScheduleProposal {
    pub fn propose(
        application_id: ApplicationId,
        slots: Vec<InterviewSlot>,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        if slots.is_empty() || slots.len() > 5 {
            return Err(DomainError::validation(
                "E_SLOTS_COUNT",
                "propose between 1 and 5 interview slots",
            ));
        }
        for slot in &slots {
            slot.validate()?;
        }
        let mut starts: Vec<UtcInstant> = slots.iter().map(|slot| slot.starts_at).collect();
        starts.sort();
        starts.dedup();
        if starts.len() != slots.len() {
            return Err(DomainError::validation(
                "E_SLOTS_DUPLICATE",
                "interview slots must not overlap exactly",
            ));
        }
        Ok(Self {
            id: ScheduleId::new(),
            application_id,
            slots,
            status: ProposalStatus::Proposed,
            confirmed_index: None,
            created_at: now,
            decided_at: None,
        })
    }

    pub fn confirm(&mut self, index: usize, now: UtcInstant) -> DomainResult<()> {
        if self.status != ProposalStatus::Proposed {
            return Err(DomainError::conflict(
                "E_PROPOSAL_CLOSED",
                "only a proposed schedule can be confirmed",
            ));
        }
        if index >= self.slots.len() {
            return Err(DomainError::validation(
                "E_SLOT_INDEX",
                "slot index is out of range",
            ));
        }
        self.status = ProposalStatus::Confirmed;
        self.confirmed_index = Some(index);
        self.decided_at = Some(now);
        Ok(())
    }

    pub fn decline(&mut self, reason: &str, now: UtcInstant) -> DomainResult<()> {
        if self.status != ProposalStatus::Proposed {
            return Err(DomainError::conflict(
                "E_PROPOSAL_CLOSED",
                "only a proposed schedule can be declined",
            ));
        }
        if reason.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_DECLINE_REASON",
                "declining a schedule needs a reason",
            ));
        }
        self.status = ProposalStatus::Declined;
        self.decided_at = Some(now);
        Ok(())
    }

    pub fn confirmed_slot(&self) -> Option<&InterviewSlot> {
        self.confirmed_index.and_then(|index| self.slots.get(index))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum OfferStatus {
    Draft,
    Approved,
    Sent,
    Accepted,
    Declined,
    Expired,
}

impl OfferStatus {
    pub fn is_terminal(self) -> bool {
        matches!(self, Self::Accepted | Self::Declined | Self::Expired)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct Offer {
    pub id: OfferId,
    pub application_id: ApplicationId,
    pub position_title: String,
    pub salary_sen: Option<Money>,
    pub start_date: Option<BusinessDate>,
    pub expires_on: Option<BusinessDate>,
    pub status: OfferStatus,
    pub note: Option<String>,
    pub created_at: UtcInstant,
    pub decided_at: Option<UtcInstant>,
}

impl Offer {
    pub fn draft(
        application_id: ApplicationId,
        position_title: impl Into<String>,
        salary_sen: Option<Money>,
        start_date: Option<BusinessDate>,
        expires_on: Option<BusinessDate>,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        let position_title = position_title.into();
        if position_title.trim().len() < 2 {
            return Err(DomainError::validation(
                "E_OFFER_TITLE",
                "an offer needs a position title",
            ));
        }
        if let Some(salary) = salary_sen
            && salary.is_negative()
        {
            return Err(DomainError::validation(
                "E_OFFER_SALARY",
                "offer salary cannot be negative",
            ));
        }
        if let (Some(start), Some(expires)) = (start_date, expires_on)
            && expires < start
        {
            return Err(DomainError::validation(
                "E_OFFER_EXPIRY",
                "offer expiry cannot precede the start date",
            ));
        }
        Ok(Self {
            id: OfferId::new(),
            application_id,
            position_title,
            salary_sen,
            start_date,
            expires_on,
            status: OfferStatus::Draft,
            note: None,
            created_at: now,
            decided_at: None,
        })
    }

    /// HR approval of the offer terms. The command layer requires a fresh
    /// re-auth before calling this; the approval is named in the audit row.
    pub fn approve(&mut self) -> DomainResult<()> {
        if self.status != OfferStatus::Draft {
            return Err(DomainError::conflict(
                "E_OFFER_STATE",
                "only a draft offer can be approved",
            ));
        }
        self.status = OfferStatus::Approved;
        Ok(())
    }

    pub fn send(&mut self) -> DomainResult<()> {
        if self.status != OfferStatus::Approved {
            return Err(DomainError::conflict(
                "E_OFFER_STATE",
                "only an approved offer can be sent",
            ));
        }
        self.status = OfferStatus::Sent;
        Ok(())
    }

    pub fn accept(&mut self, now: UtcInstant) -> DomainResult<()> {
        if self.status != OfferStatus::Sent {
            return Err(DomainError::conflict(
                "E_OFFER_STATE",
                "only a sent offer can be accepted",
            ));
        }
        self.status = OfferStatus::Accepted;
        self.decided_at = Some(now);
        Ok(())
    }

    pub fn decline(&mut self, reason: &str, now: UtcInstant) -> DomainResult<()> {
        if self.status != OfferStatus::Sent {
            return Err(DomainError::conflict(
                "E_OFFER_STATE",
                "only a sent offer can be declined",
            ));
        }
        if reason.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_OFFER_DECLINE_REASON",
                "recording a declined offer needs a reason",
            ));
        }
        self.status = OfferStatus::Declined;
        self.decided_at = Some(now);
        self.note = Some(reason.trim().to_owned());
        Ok(())
    }

    pub fn expire_if_past(&mut self, today: BusinessDate, now: UtcInstant) -> bool {
        if self.status == OfferStatus::Sent
            && self.expires_on.is_some_and(|expires| expires < today)
        {
            self.status = OfferStatus::Expired;
            self.decided_at = Some(now);
            return true;
        }
        false
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum MessageKind {
    Rejection,
    Offer,
    Interview,
    Update,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum MessageChannel {
    Email,
    Whatsapp,
    Phone,
    Note,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum MessageStatus {
    Draft,
    Queued,
    Sent,
    Cancelled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum MessageDirection {
    Outbound,
    Inbound,
}

/// A candidate-facing message. Drafting and preview are free; queueing needs a
/// named operator, and sending is recorded with the actor. There is no
/// automatic dispatch in this edition: `mark_sent` records that the HR operator
/// sent the text through their own email/WhatsApp, or a future transport did.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct CandidateMessage {
    pub id: MessageId,
    pub candidate_id: CandidateId,
    pub application_id: Option<ApplicationId>,
    pub kind: MessageKind,
    pub channel: MessageChannel,
    pub subject: Option<String>,
    pub body: String,
    pub status: MessageStatus,
    pub direction: MessageDirection,
    pub created_at: UtcInstant,
    pub sent_at: Option<UtcInstant>,
}

impl CandidateMessage {
    pub fn draft(
        candidate_id: CandidateId,
        application_id: Option<ApplicationId>,
        kind: MessageKind,
        channel: MessageChannel,
        subject: Option<String>,
        body: impl Into<String>,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        let body = body.into();
        if body.trim().len() < 10 {
            return Err(DomainError::validation(
                "E_MESSAGE_BODY",
                "a candidate message needs at least 10 characters",
            ));
        }
        if channel == MessageChannel::Email {
            let subject = subject.as_deref().unwrap_or("").trim();
            if subject.len() < 3 {
                return Err(DomainError::validation(
                    "E_MESSAGE_SUBJECT",
                    "an email needs a subject",
                ));
            }
        }
        Ok(Self {
            id: MessageId::new(),
            candidate_id,
            application_id,
            kind,
            channel,
            subject,
            body,
            status: MessageStatus::Draft,
            direction: MessageDirection::Outbound,
            created_at: now,
            sent_at: None,
        })
    }

    /// Queue behind the named human: the preview was shown, the operator
    /// approved this exact body. The body hash is recorded by the caller.
    pub fn queue(&mut self) -> DomainResult<()> {
        if self.status != MessageStatus::Draft {
            return Err(DomainError::conflict(
                "E_MESSAGE_STATE",
                "only a draft message can be queued",
            ));
        }
        self.status = MessageStatus::Queued;
        Ok(())
    }

    pub fn mark_sent(&mut self, now: UtcInstant) -> DomainResult<()> {
        if self.status != MessageStatus::Queued {
            return Err(DomainError::conflict(
                "E_MESSAGE_STATE",
                "only a queued message can be marked sent",
            ));
        }
        self.status = MessageStatus::Sent;
        self.sent_at = Some(now);
        Ok(())
    }

    pub fn cancel(&mut self, reason: &str) -> DomainResult<()> {
        if self.status == MessageStatus::Sent {
            return Err(DomainError::conflict(
                "E_MESSAGE_STATE",
                "a sent message cannot be cancelled",
            ));
        }
        if reason.trim().len() < 5 {
            return Err(DomainError::validation(
                "E_MESSAGE_CANCEL_REASON",
                "cancelling a message needs a reason",
            ));
        }
        self.status = MessageStatus::Cancelled;
        Ok(())
    }

    /// An inbound reply recorded by the HR operator (IMAP polling fills the
    /// same shape in a later slice).
    pub fn inbound(
        candidate_id: CandidateId,
        application_id: Option<ApplicationId>,
        body: impl Into<String>,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        let body = body.into();
        if body.trim().is_empty() {
            return Err(DomainError::validation(
                "E_MESSAGE_BODY",
                "an inbound reply needs a body",
            ));
        }
        Ok(Self {
            id: MessageId::new(),
            candidate_id,
            application_id,
            kind: MessageKind::Update,
            channel: MessageChannel::Email,
            subject: None,
            body,
            status: MessageStatus::Sent,
            direction: MessageDirection::Inbound,
            created_at: now,
            sent_at: Some(now),
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct FeedbackReport {
    pub id: FeedbackId,
    pub application_id: ApplicationId,
    pub candidate_name: String,
    pub job_title: String,
    pub summary: String,
    pub strengths: Vec<String>,
    pub growth_areas: Vec<String>,
    pub created_at: UtcInstant,
}

impl FeedbackReport {
    /// Candidate-facing text only: no raw scores, no σ, no internal flags.
    /// Derived deterministically from the evaluation the HR operator reviewed.
    pub fn from_evaluation(
        application_id: ApplicationId,
        candidate_name: impl Into<String>,
        job_title: impl Into<String>,
        evaluation: &Evaluation,
        now: UtcInstant,
    ) -> DomainResult<Self> {
        if evaluation.evidence.is_empty() {
            return Err(DomainError::conflict(
                "E_FEEDBACK_NO_EVIDENCE",
                "feedback needs an evaluation with recorded evidence",
            ));
        }
        let mut strengths: Vec<String> = evaluation
            .dimension_scores
            .iter()
            .filter(|(_, score)| **score >= 7_000)
            .map(|(dimension, _)| human_dimension(dimension))
            .collect();
        strengths.sort();
        strengths.truncate(3);
        let mut growth_areas: Vec<String> = evaluation
            .dimension_scores
            .iter()
            .filter(|(_, score)| **score < 6_000)
            .map(|(dimension, _)| human_dimension(dimension))
            .collect();
        growth_areas.sort();
        growth_areas.truncate(3);
        let summary = format!(
            "Thank you for interviewing for the {job} role. Our review recognised {strong} while \
             noting {growth} as areas to develop. We encourage you to apply again as you grow in \
             those areas.",
            job = job_title.into(),
            strong = if strengths.is_empty() {
                "your experience".to_owned()
            } else {
                strengths.join(", ")
            },
            growth = if growth_areas.is_empty() {
                "continued growth".to_owned()
            } else {
                growth_areas.join(", ")
            },
        );
        Ok(Self {
            id: FeedbackId::new(),
            application_id,
            candidate_name: candidate_name.into(),
            job_title: String::new(),
            summary,
            strengths,
            growth_areas,
            created_at: now,
        })
    }

    pub fn render_text(&self) -> String {
        let mut text = format!(
            "Feedback for {name}\n\n{summary}\n",
            name = self.candidate_name,
            summary = self.summary
        );
        if !self.strengths.is_empty() {
            text.push_str("\nStrengths:\n");
            for strength in &self.strengths {
                text.push_str(&format!("- {strength}\n"));
            }
        }
        if !self.growth_areas.is_empty() {
            text.push_str("\nAreas to develop:\n");
            for area in &self.growth_areas {
                text.push_str(&format!("- {area}\n"));
            }
        }
        text
    }
}

fn human_dimension(key: &str) -> String {
    key.replace('_', " ")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::hiring::{Dimension, Rubric, RunScores};
    use std::collections::BTreeMap;

    fn now() -> UtcInstant {
        UtcInstant::from_millis(1_760_000_000_000).unwrap()
    }

    fn slot() -> InterviewSlot {
        InterviewSlot {
            starts_at: UtcInstant::from_millis(1_760_100_000_000).unwrap(),
            duration_minutes: 60,
            mode: SlotMode::Remote,
            location: None,
        }
    }

    #[test]
    fn schedule_propose_confirm_decline() {
        let mut proposal = ScheduleProposal::propose(
            ApplicationId::new(),
            vec![
                slot(),
                InterviewSlot {
                    starts_at: UtcInstant::from_millis(1_760_200_000_000).unwrap(),
                    ..slot()
                },
            ],
            now(),
        )
        .unwrap();
        proposal.confirm(1, now()).unwrap();
        assert_eq!(proposal.status, ProposalStatus::Confirmed);
        assert!(proposal.confirm(0, now()).is_err());
        let mut proposal =
            ScheduleProposal::propose(ApplicationId::new(), vec![slot()], now()).unwrap();
        assert!(proposal.decline("no", now()).is_err());
        proposal.decline("candidate withdrew", now()).unwrap();
        assert_eq!(proposal.status, ProposalStatus::Declined);
    }

    #[test]
    fn onsite_slot_needs_location() {
        let slot = InterviewSlot {
            mode: SlotMode::Onsite,
            location: None,
            ..slot()
        };
        assert!(slot.validate().is_err());
    }

    #[test]
    fn offer_lifecycle_with_gates() {
        let mut offer = Offer::draft(
            ApplicationId::new(),
            "Backend Engineer",
            Some(Money::from_rupiah(12_000_000).unwrap()),
            Some(BusinessDate::parse("2026-12-01").unwrap()),
            Some(BusinessDate::parse("2026-12-15").unwrap()),
            now(),
        )
        .unwrap();
        assert!(offer.send().is_err());
        offer.approve().unwrap();
        offer.send().unwrap();
        offer.accept(now()).unwrap();
        assert_eq!(offer.status, OfferStatus::Accepted);
        assert!(!offer.expire_if_past(BusinessDate::parse("2026-12-20").unwrap(), now()));
    }

    #[test]
    fn expired_offer_sweeps_to_expired() {
        let mut offer = Offer::draft(
            ApplicationId::new(),
            "Backend Engineer",
            None,
            None,
            Some(BusinessDate::parse("2026-11-10").unwrap()),
            now(),
        )
        .unwrap();
        offer.approve().unwrap();
        offer.send().unwrap();
        assert!(offer.expire_if_past(BusinessDate::parse("2026-11-11").unwrap(), now()));
        assert_eq!(offer.status, OfferStatus::Expired);
    }

    #[test]
    fn message_draft_queue_send() {
        let mut message = CandidateMessage::draft(
            CandidateId::new(),
            Some(ApplicationId::new()),
            MessageKind::Rejection,
            MessageChannel::Email,
            Some("Your application".into()),
            "Thank you for interviewing with us last week.",
            now(),
        )
        .unwrap();
        assert!(message.mark_sent(now()).is_err());
        message.queue().unwrap();
        message.mark_sent(now()).unwrap();
        assert_eq!(message.status, MessageStatus::Sent);
    }

    #[test]
    fn email_needs_subject_and_body() {
        assert!(
            CandidateMessage::draft(
                CandidateId::new(),
                None,
                MessageKind::Update,
                MessageChannel::Email,
                None,
                "Short.",
                now(),
            )
            .is_err()
        );
    }

    #[test]
    fn feedback_hides_scores() {
        let rubric = Rubric {
            id: "r".into(),
            name: "R".into(),
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
        let evaluation = Evaluation::from_runs(
            ApplicationId::new(),
            &rubric,
            &[RunScores {
                dimension_scores: BTreeMap::from([
                    ("skills".into(), 8_000),
                    ("impact".into(), 4_000),
                ]),
            }],
            vec![crate::hiring::Evidence {
                dimension: "skills".into(),
                quote: "Shipped the migration on schedule.".into(),
                source_document_id: crate::ids::DocumentId::new(),
                confidence_bp: 8_000,
                page: None,
            }],
            now(),
        )
        .unwrap();
        let report = FeedbackReport::from_evaluation(
            evaluation.application_id,
            "Dimas",
            "Backend",
            &evaluation,
            now(),
        )
        .unwrap();
        let text = report.render_text();
        assert!(!text.contains("8000"));
        assert!(text.contains("Feedback for Dimas"));
        assert!(!text.contains("8000"));
        assert!(report.growth_areas.iter().any(|area| area == "impact"));
    }
}
