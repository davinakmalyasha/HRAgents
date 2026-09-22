import { describe, expect, it } from 'vitest'

import {
  canQueueRejection,
  newestFirstCommunications,
  type CommunicationView,
  type OverrideView,
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
    created_at: '2026-09-20T03:00:00Z',
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
