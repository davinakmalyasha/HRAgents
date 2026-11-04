//! Tauri commands for hiring workflows: scheduling, offers, messaging, feedback.

use super::{AppState, CmdResult, parse_id, with_service};
use hragents_core::hiring_comms::{
    CandidateMessage, FeedbackReport, InterviewSlot, MessageChannel, MessageKind, Offer,
    ScheduleProposal,
};
use hragents_core::ids::{ApplicationId, CandidateId, MessageId, OfferId, ScheduleId};
use hragents_core::time::BusinessDate;
use tauri::State;

#[tauri::command]
pub fn propose_schedule(
    state: State<'_, AppState>,
    application_id: String,
    slots: Vec<InterviewSlot>,
) -> CmdResult<ScheduleProposal> {
    let application_id: ApplicationId = parse_id(&application_id)?;
    with_service(&state, |service| {
        service.propose_schedule(application_id, slots)
    })
}

#[tauri::command]
pub fn confirm_schedule(
    state: State<'_, AppState>,
    proposal_id: String,
    index: usize,
) -> CmdResult<ScheduleProposal> {
    let proposal_id: ScheduleId = parse_id(&proposal_id)?;
    with_service(&state, |service| {
        service.confirm_schedule(proposal_id, index)
    })
}

#[tauri::command]
pub fn decline_schedule(
    state: State<'_, AppState>,
    proposal_id: String,
    reason: String,
) -> CmdResult<ScheduleProposal> {
    let proposal_id: ScheduleId = parse_id(&proposal_id)?;
    with_service(&state, |service| {
        service.decline_schedule(proposal_id, &reason)
    })
}

#[tauri::command]
pub fn list_schedule_proposals(
    state: State<'_, AppState>,
    application_id: Option<String>,
) -> CmdResult<Vec<ScheduleProposal>> {
    let application_id = application_id
        .as_deref()
        .map(parse_id::<ApplicationId>)
        .transpose()?;
    with_service(&state, |service| {
        service.list_schedule_proposals(application_id)
    })
}

#[tauri::command]
pub fn create_offer(
    state: State<'_, AppState>,
    application_id: String,
    position_title: String,
    salary_sen: Option<i64>,
    start_date: Option<BusinessDate>,
    expires_on: Option<BusinessDate>,
) -> CmdResult<Offer> {
    let application_id: ApplicationId = parse_id(&application_id)?;
    with_service(&state, |service| {
        service.create_offer(
            application_id,
            &position_title,
            salary_sen,
            start_date,
            expires_on,
        )
    })
}

#[tauri::command]
pub fn approve_offer(state: State<'_, AppState>, offer_id: String) -> CmdResult<Offer> {
    let offer_id: OfferId = parse_id(&offer_id)?;
    with_service(&state, |service| service.approve_offer(offer_id))
}

#[tauri::command]
pub fn send_offer(state: State<'_, AppState>, offer_id: String) -> CmdResult<Offer> {
    let offer_id: OfferId = parse_id(&offer_id)?;
    with_service(&state, |service| service.send_offer(offer_id))
}

#[tauri::command]
pub fn accept_offer(state: State<'_, AppState>, offer_id: String) -> CmdResult<Offer> {
    let offer_id: OfferId = parse_id(&offer_id)?;
    with_service(&state, |service| service.accept_offer(offer_id))
}

#[tauri::command]
pub fn decline_offer(
    state: State<'_, AppState>,
    offer_id: String,
    reason: String,
) -> CmdResult<Offer> {
    let offer_id: OfferId = parse_id(&offer_id)?;
    with_service(&state, |service| service.decline_offer(offer_id, &reason))
}

#[tauri::command]
pub fn sweep_expired_offers(state: State<'_, AppState>, today: BusinessDate) -> CmdResult<usize> {
    with_service(&state, |service| service.sweep_expired_offers(today))
}

#[tauri::command]
pub fn list_offers(
    state: State<'_, AppState>,
    application_id: Option<String>,
) -> CmdResult<Vec<Offer>> {
    let application_id = application_id
        .as_deref()
        .map(parse_id::<ApplicationId>)
        .transpose()?;
    with_service(&state, |service| service.list_offers(application_id))
}

#[tauri::command]
pub fn draft_message(
    state: State<'_, AppState>,
    candidate_id: String,
    application_id: Option<String>,
    kind: MessageKind,
    channel: MessageChannel,
    subject: Option<String>,
    body: String,
) -> CmdResult<CandidateMessage> {
    let candidate_id: CandidateId = parse_id(&candidate_id)?;
    let application_id = application_id
        .as_deref()
        .map(parse_id::<ApplicationId>)
        .transpose()?;
    with_service(&state, |service| {
        service.draft_message(candidate_id, application_id, kind, channel, subject, &body)
    })
}

#[tauri::command]
pub fn queue_message(
    state: State<'_, AppState>,
    message_id: String,
) -> CmdResult<CandidateMessage> {
    let message_id: MessageId = parse_id(&message_id)?;
    with_service(&state, |service| service.queue_message(message_id))
}

#[tauri::command]
pub fn mark_message_sent(
    state: State<'_, AppState>,
    message_id: String,
) -> CmdResult<CandidateMessage> {
    let message_id: MessageId = parse_id(&message_id)?;
    with_service(&state, |service| service.mark_message_sent(message_id))
}

#[tauri::command]
pub fn cancel_message(
    state: State<'_, AppState>,
    message_id: String,
    reason: String,
) -> CmdResult<CandidateMessage> {
    let message_id: MessageId = parse_id(&message_id)?;
    with_service(&state, |service| {
        service.cancel_message(message_id, &reason)
    })
}

#[tauri::command]
pub fn record_inbound_reply(
    state: State<'_, AppState>,
    candidate_id: String,
    application_id: Option<String>,
    body: String,
) -> CmdResult<CandidateMessage> {
    let candidate_id: CandidateId = parse_id(&candidate_id)?;
    let application_id = application_id
        .as_deref()
        .map(parse_id::<ApplicationId>)
        .transpose()?;
    with_service(&state, |service| {
        service.record_inbound_reply(candidate_id, application_id, &body)
    })
}

#[tauri::command]
pub fn list_messages(
    state: State<'_, AppState>,
    application_id: Option<String>,
) -> CmdResult<Vec<CandidateMessage>> {
    let application_id = application_id
        .as_deref()
        .map(parse_id::<ApplicationId>)
        .transpose()?;
    with_service(&state, |service| service.list_messages(application_id))
}

#[tauri::command]
pub fn generate_feedback(
    state: State<'_, AppState>,
    application_id: String,
) -> CmdResult<FeedbackReport> {
    let application_id: ApplicationId = parse_id(&application_id)?;
    with_service(&state, |service| service.generate_feedback(application_id))
}

#[tauri::command]
pub fn feedback_for(
    state: State<'_, AppState>,
    application_id: String,
) -> CmdResult<Option<FeedbackReport>> {
    let application_id: ApplicationId = parse_id(&application_id)?;
    with_service(&state, |service| service.feedback_for(application_id))
}
