import { describe, expect, it } from 'vitest'

import type { ApplicationSummary } from './pipeline'
import {
  actionsFor,
  applicationForCandidate,
  formatSlot,
  newestFirst,
  proposalStatus,
  type SchedulingProposal,
} from './scheduling'

function proposal(overrides: Partial<SchedulingProposal>): SchedulingProposal {
  return {
    id: 'proposal-1',
    created_at: '2026-09-20T03:00:00Z',
    created_by: 'scheduling_service',
    status: 'auto_scheduled',
    decided_by: null,
    decided_at: null,
    supersedes_id: null,
    needs_human_reconciliation: false,
    requires_human_approval: false,
    payload: {
      candidate_id: 'cand-1',
      job_id: 'job-1',
      interviewer_ids: ['int-1'],
      slots: [],
      timezone: 'Asia/Jakarta',
      channel: 'email',
      auto_scheduled: false,
      policy: { decision: 'auto_schedule' },
    },
    ...overrides,
  }
}

describe('proposalStatus', () => {
  it('reports auto-scheduled proposals', () => {
    expect(proposalStatus(proposal({}))).toBe('auto')
  })

  it('reports proposals waiting on a human decision', () => {
    expect(proposalStatus(proposal({ status: 'pending_approval' }))).toBe('needs_approval')
  })

  it('keeps legacy proposed rows in the waiting presentation', () => {
    expect(proposalStatus(proposal({ status: 'proposed' }))).toBe('needs_approval')
  })

  it('prefers reconciliation over the approval flag while open', () => {
    expect(
      proposalStatus(proposal({ status: 'pending_approval', needs_human_reconciliation: true })),
    ).toBe('reconciliation')
  })

  it('reports decided states as terminal', () => {
    expect(proposalStatus(proposal({ status: 'confirmed' }))).toBe('confirmed')
    expect(proposalStatus(proposal({ status: 'cancelled' }))).toBe('cancelled')
    expect(proposalStatus(proposal({ status: 'superseded' }))).toBe('superseded')
  })
})

describe('actionsFor', () => {
  it('offers the full set while a proposal is open', () => {
    expect(actionsFor('pending_approval')).toEqual(['confirm', 'cancel', 'reschedule'])
    expect(actionsFor('auto_scheduled')).toEqual(['confirm', 'cancel', 'reschedule'])
  })

  it('keeps cancel and reschedule for confirmed proposals', () => {
    expect(actionsFor('confirmed')).toEqual(['cancel', 'reschedule'])
  })

  it('offers nothing for terminal proposals', () => {
    expect(actionsFor('cancelled')).toEqual([])
    expect(actionsFor('superseded')).toEqual([])
  })
})

describe('newestFirst', () => {
  it('orders proposals by creation time, newest first', () => {
    const older = proposal({ id: 'older', created_at: '2026-09-18T03:00:00Z' })
    const newer = proposal({ id: 'newer', created_at: '2026-09-20T03:00:00Z' })

    expect(newestFirst([older, newer]).map((item) => item.id)).toEqual(['newer', 'older'])
  })
})

describe('formatSlot', () => {
  it('renders the range in the proposal timezone', () => {
    const label = formatSlot(
      { start_utc: '2026-09-21T02:00:00Z', end_utc: '2026-09-21T03:00:00Z', tentative: false },
      'Asia/Jakarta',
      'en-US',
    )

    expect(label).toContain('Mon')
    expect(label).toContain('09:00')
    expect(label).toContain('10:00')
  })
})

function application(applicationId: string, candidateId: string): ApplicationSummary {
  return {
    application_id: applicationId,
    candidate_id: candidateId,
    job_id: 'job-1',
    status: 'scheduled',
    priority_score: 0.9,
    s_tech: 0.9,
    hours_waiting: 4,
  }
}

describe('applicationForCandidate', () => {
  const applications = [application('app-1', 'cand-1'), application('app-2', 'cand-2')]

  it('finds the application for a candidate', () => {
    expect(applicationForCandidate(applications, 'cand-2')?.application_id).toBe('app-2')
  })

  it('returns undefined when the candidate has no application in view', () => {
    expect(applicationForCandidate(applications, 'cand-9')).toBeUndefined()
  })
})
