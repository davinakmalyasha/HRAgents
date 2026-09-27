import { describe, expect, it } from 'vitest'

import {
  canQueueRejection,
  dispatchEvidence,
  newestFirstCommunications,
  newestFirstReplies,
  type CommunicationView,
  type OverrideView,
  type ReplyView,
} from './communication'

function override(overrides: Partial<OverrideView>): OverrideView {
  return {
    id: 'override-1',
    evaluation_id: 'eval-1',
    reviewer_id: 'lead-1',
    reviewer_role: 'engineering_lead',
    override_decision: 'hitl_soft_rejection',
    reason_code: 'below_bar',
    notes: null,
    decided_at: '2026-09-10T10:00:00Z',
    ...overrides,
  }
}

function communication(overrides: Partial<CommunicationView>): CommunicationView {
  return {
    id: 'comm-1',
    candidate_id: 'cand-1',
    application_id: 'app-1',
    evaluation_id: 'eval-1',
    kind: 'rejection',
    channel: 'email',
    language: 'en',
    subject: null,
    body: 'Body',
    status: 'queued',
    approved_by: 'hr-admin',
    approved_at: '2026-09-20T03:00:00Z',
    sent_by: null,
    sent_at: null,
    recipient: null,
    recipient_phone: null,
    provider: null,
    provider_message_id: null,
    send_attempts: 0,
    last_error: null,
    created_at: '2026-09-20T03:00:00Z',
    ...overrides,
  }
}

function reply(overrides: Partial<ReplyView>): ReplyView {
  return {
    id: 'reply-1',
    candidate_id: 'cand-1',
    communication_id: 'comm-1',
    channel: 'email',
    sender: 'budi@example.com',
    subject: 'Re: Your offer',
    body: 'Saya tertarik, terima kasih.',
    provider: 'email.imap_poll',
    provider_message_id: '<reply-1@example.com>',
    received_at: '2026-09-22T02:15:00Z',
    ...overrides,
  }
}

describe('canQueueRejection', () => {
  it('allows documented automatic rejections', () => {
    expect(canQueueRejection('reject_auto', [])).toBe(true)
  })

  it('blocks without a recorded decision', () => {
    expect(canQueueRejection('hitl_soft_rejection', [])).toBe(false)
    expect(canQueueRejection(undefined, [])).toBe(false)
  })

  it('allows when the latest override is a rejection', () => {
    expect(canQueueRejection('hitl_soft_rejection', [override({})])).toBe(true)
  })

  it('blocks when a later override supersedes the rejection', () => {
    const overrides = [
      override({ id: 'a', decided_at: '2026-09-10T10:00:00Z' }),
      override({
        id: 'b',
        override_decision: 'auto_schedule',
        decided_at: '2026-09-11T10:00:00Z',
      }),
    ]

    expect(canQueueRejection('hitl_soft_rejection', overrides)).toBe(false)
  })
})

describe('newestFirstCommunications', () => {
  it('orders messages by creation time, newest first', () => {
    const older = communication({ id: 'older', created_at: '2026-09-18T03:00:00Z' })
    const newer = communication({ id: 'newer', created_at: '2026-09-20T03:00:00Z' })

    expect(newestFirstCommunications([older, newer]).map((item) => item.id)).toEqual([
      'newer',
      'older',
    ])
  })
})

describe('newestFirstReplies', () => {
  it('orders replies by receipt time, newest first', () => {
    const older = reply({ id: 'older', received_at: '2026-09-20T02:15:00Z' })
    const newer = reply({ id: 'newer', received_at: '2026-09-22T02:15:00Z' })

    expect(newestFirstReplies([older, newer]).map((item) => item.id)).toEqual(['newer', 'older'])
  })
})

describe('dispatchEvidence', () => {
  it('reports nothing for a freshly queued message', () => {
    expect(dispatchEvidence(communication({}))).toEqual({
      provider: null,
      attempts: 0,
      error: null,
    })
  })

  it('surfaces the failure while the message is still queued', () => {
    const evidence = dispatchEvidence(
      communication({
        provider: 'email.smtp',
        send_attempts: 3,
        last_error: 'mailbox unavailable',
      }),
    )

    expect(evidence).toEqual({
      provider: 'email.smtp',
      attempts: 3,
      error: 'mailbox unavailable',
    })
  })

  it('hides a stale error once the message was sent', () => {
    const evidence = dispatchEvidence(
      communication({ status: 'sent', provider: 'email.smtp', last_error: 'mailbox unavailable' }),
    )

    expect(evidence.error).toBeNull()
  })
})
