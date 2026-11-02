//! Hiring workflow services: scheduling, offers, messaging, feedback.
//!
//! Same pattern as growth_services: session/audit/store rules shared with the
//! core AppService. Every consequential transition is named and audited.

use super::{AppError, AppResult, AppService};
use hragents_core::error::DomainError;
use hragents_core::hiring_comms::{
    CandidateMessage, FeedbackReport, InterviewSlot, MessageChannel, MessageKind, Offer,
    ScheduleProposal,
};
use hragents_core::ids::{ApplicationId, CandidateId, MessageId, OfferId, ScheduleId};
use hragents_core::money::Money;
use hragents_core::time::{BusinessDate, UtcInstant};

impl AppService {
    // ------------------------------------------------------------------
    // Scheduling
    // ------------------------------------------------------------------

    pub fn propose_schedule(
        &mut self,
        application_id: ApplicationId,
        slots: Vec<InterviewSlot>,
    ) -> AppResult<ScheduleProposal> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        self.store().application(application_id)?;
        let proposal = ScheduleProposal::propose(application_id, slots, now)?;
        self.store_mut().save_schedule_proposal(&proposal)?;
        self.append_audit_pub(
            "schedule.proposed",
            "schedule_proposal",
            &proposal.id.to_string(),
            serde_json::json!({
                "application_id": application_id.to_string(),
                "slots": proposal.slots.len(),
            }),
            now,
        )?;
        Ok(proposal)
    }

    fn schedule_proposal(&self, id: ScheduleId) -> AppResult<ScheduleProposal> {
        self.store()
            .list_schedule_proposals(None)?
            .into_iter()
            .find(|proposal| proposal.id == id)
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "schedule_proposal",
                    id: id.to_string(),
                })
            })
    }

    pub fn confirm_schedule(
        &mut self,
        id: ScheduleId,
        index: usize,
    ) -> AppResult<ScheduleProposal> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut proposal = self.schedule_proposal(id)?;
        proposal.confirm(index, now)?;
        self.store_mut().save_schedule_proposal(&proposal)?;
        self.append_audit_pub(
            "schedule.confirmed",
            "schedule_proposal",
            &proposal.id.to_string(),
            serde_json::json!({"slot_index": index}),
            now,
        )?;
        Ok(proposal)
    }

    pub fn decline_schedule(
        &mut self,
        id: ScheduleId,
        reason: &str,
    ) -> AppResult<ScheduleProposal> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut proposal = self.schedule_proposal(id)?;
        proposal.decline(reason, now)?;
        self.store_mut().save_schedule_proposal(&proposal)?;
        self.append_audit_pub(
            "schedule.declined",
            "schedule_proposal",
            &proposal.id.to_string(),
            serde_json::json!({"reason": reason}),
            now,
        )?;
        Ok(proposal)
    }

    pub fn list_schedule_proposals(
        &self,
        application_id: Option<ApplicationId>,
    ) -> AppResult<Vec<ScheduleProposal>> {
        self.require_session_pub()?;
        Ok(self.store().list_schedule_proposals(application_id)?)
    }

    // ------------------------------------------------------------------
    // Offers
    // ------------------------------------------------------------------

    pub fn create_offer(
        &mut self,
        application_id: ApplicationId,
        position_title: &str,
        salary_sen: Option<i64>,
        start_date: Option<BusinessDate>,
        expires_on: Option<BusinessDate>,
    ) -> AppResult<Offer> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        self.store().application(application_id)?;
        let offer = Offer::draft(
            application_id,
            position_title,
            salary_sen.map(Money::from_sen),
            start_date,
            expires_on,
            now,
        )?;
        self.store_mut().save_offer(&offer)?;
        self.append_audit_pub(
            "offer.created",
            "offer",
            &offer.id.to_string(),
            serde_json::json!({
                "application_id": application_id.to_string(),
                "position": offer.position_title,
            }),
            now,
        )?;
        Ok(offer)
    }

    fn offer(&self, id: OfferId) -> AppResult<Offer> {
        self.store()
            .list_offers(None)?
            .into_iter()
            .find(|offer| offer.id == id)
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "offer",
                    id: id.to_string(),
                })
            })
    }

    /// Offer approval is a named-human gate: fresh re-auth required.
    pub fn approve_offer(&mut self, id: OfferId) -> AppResult<Offer> {
        let now = UtcInstant::now();
        self.require_reauth_pub()?;
        let mut offer = self.offer(id)?;
        // Rehydrate the human-readable terms lost to the slim offers table.
        offer.approve()?;
        self.store_mut().save_offer(&offer)?;
        self.append_audit_pub(
            "offer.approved",
            "offer",
            &offer.id.to_string(),
            serde_json::json!({"reauth": true}),
            now,
        )?;
        Ok(offer)
    }

    pub fn send_offer(&mut self, id: OfferId) -> AppResult<Offer> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut offer = self.offer(id)?;
        offer.send()?;
        self.store_mut().save_offer(&offer)?;
        self.append_audit_pub(
            "offer.sent",
            "offer",
            &offer.id.to_string(),
            serde_json::json!({}),
            now,
        )?;
        Ok(offer)
    }

    pub fn accept_offer(&mut self, id: OfferId) -> AppResult<Offer> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut offer = self.offer(id)?;
        offer.accept(now)?;
        self.store_mut().save_offer(&offer)?;
        // Acceptance starts onboarding: the application moves to hired.
        let mut application = self.store().application(offer.application_id)?;
        application.stage = hragents_core::hiring::ApplicationStage::Hired;
        application.updated_at = now;
        self.store_mut().save_application(&application)?;
        self.append_audit_pub(
            "offer.accepted",
            "offer",
            &offer.id.to_string(),
            serde_json::json!({"application_id": offer.application_id.to_string()}),
            now,
        )?;
        Ok(offer)
    }

    pub fn decline_offer(&mut self, id: OfferId, reason: &str) -> AppResult<Offer> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut offer = self.offer(id)?;
        offer.decline(reason, now)?;
        self.store_mut().save_offer(&offer)?;
        self.append_audit_pub(
            "offer.declined",
            "offer",
            &offer.id.to_string(),
            serde_json::json!({"reason": reason}),
            now,
        )?;
        Ok(offer)
    }

    pub fn sweep_expired_offers(&mut self, today: BusinessDate) -> AppResult<usize> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut expired = 0;
        for mut offer in self.store().list_offers(None)? {
            if offer.expire_if_past(today, now) {
                self.store_mut().save_offer(&offer)?;
                self.append_audit_pub(
                    "offer.expired",
                    "offer",
                    &offer.id.to_string(),
                    serde_json::json!({}),
                    now,
                )?;
                expired += 1;
            }
        }
        Ok(expired)
    }

    pub fn list_offers(&self, application_id: Option<ApplicationId>) -> AppResult<Vec<Offer>> {
        self.require_session_pub()?;
        Ok(self.store().list_offers(application_id)?)
    }

    // ------------------------------------------------------------------
    // Messaging
    // ------------------------------------------------------------------

    pub fn draft_message(
        &mut self,
        candidate_id: CandidateId,
        application_id: Option<ApplicationId>,
        kind: MessageKind,
        channel: MessageChannel,
        subject: Option<String>,
        body: &str,
    ) -> AppResult<CandidateMessage> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        self.store().candidate(candidate_id)?;
        if let Some(application_id) = application_id {
            self.store().application(application_id)?;
        }
        let message = CandidateMessage::draft(
            candidate_id,
            application_id,
            kind,
            channel,
            subject,
            body,
            now,
        )?;
        self.store_mut().save_message(&message)?;
        self.append_audit_pub(
            "message.drafted",
            "message",
            &message.id.to_string(),
            serde_json::json!({
                "candidate_id": candidate_id.to_string(),
                "kind": format!("{kind:?}"),
                "channel": format!("{channel:?}"),
            }),
            now,
        )?;
        Ok(message)
    }

    fn message(&self, id: MessageId) -> AppResult<CandidateMessage> {
        self.store()
            .list_messages(None)?
            .into_iter()
            .find(|message| message.id == id)
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "message",
                    id: id.to_string(),
                })
            })
    }

    /// Queueing is the human gate: the operator saw the exact preview and
    /// approved this body. Requires a fresh re-auth like every consequential
    /// candidate-facing act.
    pub fn queue_message(&mut self, id: MessageId) -> AppResult<CandidateMessage> {
        let now = UtcInstant::now();
        self.require_reauth_pub()?;
        let mut message = self.message(id)?;
        message.queue()?;
        self.store_mut().save_message(&message)?;
        let body_hash = hragents_core::audit::hex_sha256(message.body.as_bytes());
        self.append_audit_pub(
            "message.queued",
            "message",
            &message.id.to_string(),
            serde_json::json!({"body_sha256": body_hash, "reauth": true}),
            now,
        )?;
        Ok(message)
    }

    pub fn mark_message_sent(&mut self, id: MessageId) -> AppResult<CandidateMessage> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut message = self.message(id)?;
        message.mark_sent(now)?;
        self.store_mut().save_message(&message)?;
        self.append_audit_pub(
            "message.sent",
            "message",
            &message.id.to_string(),
            serde_json::json!({
                "channel": format!("{:?}", message.channel),
                "candidate_id": message.candidate_id.to_string(),
            }),
            now,
        )?;
        Ok(message)
    }

    pub fn cancel_message(&mut self, id: MessageId, reason: &str) -> AppResult<CandidateMessage> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let mut message = self.message(id)?;
        message.cancel(reason)?;
        self.store_mut().save_message(&message)?;
        self.append_audit_pub(
            "message.cancelled",
            "message",
            &message.id.to_string(),
            serde_json::json!({"reason": reason}),
            now,
        )?;
        Ok(message)
    }

    pub fn record_inbound_reply(
        &mut self,
        candidate_id: CandidateId,
        application_id: Option<ApplicationId>,
        body: &str,
    ) -> AppResult<CandidateMessage> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let message = CandidateMessage::inbound(candidate_id, application_id, body, now)?;
        self.store_mut().save_message(&message)?;
        self.append_audit_pub(
            "message.reply_recorded",
            "message",
            &message.id.to_string(),
            serde_json::json!({"candidate_id": candidate_id.to_string()}),
            now,
        )?;
        Ok(message)
    }

    pub fn list_messages(
        &self,
        application_id: Option<ApplicationId>,
    ) -> AppResult<Vec<CandidateMessage>> {
        self.require_session_pub()?;
        Ok(self.store().list_messages(application_id)?)
    }

    // ------------------------------------------------------------------
    // Feedback
    // ------------------------------------------------------------------

    pub fn generate_feedback(
        &mut self,
        application_id: ApplicationId,
    ) -> AppResult<FeedbackReport> {
        let now = UtcInstant::now();
        self.require_active_pub()?;
        let application = self.store().application(application_id)?;
        let candidate = self.store().candidate(application.candidate_id)?;
        let job = self.store().job(application.job_id)?;
        let evaluation = self
            .store()
            .evaluation_for(application_id)?
            .ok_or_else(|| {
                AppError::Domain(DomainError::NotFound {
                    entity: "evaluation",
                    id: application_id.to_string(),
                })
            })?;
        let report = FeedbackReport::from_evaluation(
            application_id,
            candidate.full_name,
            job.title,
            &evaluation,
            now,
        )?;
        self.store_mut().save_feedback(&report)?;
        self.append_audit_pub(
            "feedback.generated",
            "feedback",
            &report.id.to_string(),
            serde_json::json!({"application_id": application_id.to_string()}),
            now,
        )?;
        Ok(report)
    }

    pub fn feedback_for(&self, application_id: ApplicationId) -> AppResult<Option<FeedbackReport>> {
        self.require_session_pub()?;
        Ok(self.store().feedback_for(application_id)?)
    }
}
