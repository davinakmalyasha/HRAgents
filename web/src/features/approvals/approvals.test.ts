import { describe, expect, it } from 'vitest'

import type { components } from '@/api/schema'

import {
  DECIDABLE_STATUSES,
  NO_VIEWER,
  blockedBecause,
  byUrgency,
  canDecide,
  isBlocked,
  isDecidable,
  requiresReason,
  subjectLabel,
  type ApproverRole,
  type RoleId,
  type Viewer,
} from './approvalsApi'

type Approval = components['schemas']['ApprovalView']

function approval(overrides: Partial<Approval> = {}): Approval {
  return {
    id: 'apr-1',
    title: 'Annual leave for 12-20 Nov',
    subject: 'leave_request',
    subject_id: 'req-1',
    assignee_role: 'manager',
    status: 'pending',
    urgency: 'normal',
    requested_by: 'system',
    requested_by_agent: true,
    created_at: '2026-01-01T00:00:00Z',
    sla_deadline: null,
    is_overdue: false,
    escalation_count: 0,
    summary: 'Sari requested 9 days of annual leave.',
    ...overrides,
  }
}

/**
 * A viewer, as `/v1/session` describes them.
 *
 * `approverRoles` is the server's answer, so these fixtures mirror the real
 * `APPROVER_ROLE_HOLDERS` rows for each role rather than guessing.
 */
function viewer(role: RoleId, approverRoles: ApproverRole[], actorId = 'someone'): Viewer {
  return { actorId, role, approverRoles }
}

const boss = viewer(
  'hr_admin',
  ['data_protection', 'engineering_lead', 'finance', 'hr_admin', 'manager', 'recruiter_lead'],
  'Rina',
)
const lead = viewer('manager', ['engineering_lead', 'manager', 'recruiter_lead'], 'Budi')
const finance = viewer('finance', ['finance'], 'Fajar')

describe('only an active approval can be decided', () => {
  it('accepts pending and escalated', () => {
    /**`ApprovalRequest.active` is exactly these two. An escalated approval is still
     * open -- escalation re-raises it, it does not answer it.
     */
    expect([...DECIDABLE_STATUSES]).toEqual(['pending', 'escalated'])
    expect(isDecidable('pending')).toBe(true)
    expect(isDecidable('escalated')).toBe(true)
  })

  it('refuses everything already answered', () => {
    for (const status of ['approved', 'rejected', 'expired', 'withdrawn'] as const) {
      expect(isDecidable(status)).toBe(false)
      expect(canDecide(approval({ status }), lead)).toBe(false)
    }
  })
})

describe('authority comes from the server, not from a table copied into the client', () => {
  it('lets a manager decide what the server says they may', () => {
    expect(canDecide(approval({ assignee_role: 'engineering_lead' }), lead)).toBe(true)
    expect(canDecide(approval({ assignee_role: 'recruiter_lead' }), lead)).toBe(true)
  })

  it('keeps data_protection with hr_admin alone', () => {
    expect(canDecide(approval({ assignee_role: 'data_protection' }), boss)).toBe(true)
    expect(canDecide(approval({ assignee_role: 'data_protection' }), lead)).toBe(false)
  })

  it('keeps finance with finance', () => {
    expect(canDecide(approval({ assignee_role: 'finance' }), finance)).toBe(true)
    expect(canDecide(approval({ assignee_role: 'finance' }), lead)).toBe(false)
    expect(canDecide(approval({ assignee_role: 'manager' }), finance)).toBe(false)
  })

  it('grants nothing to a viewer the server says holds no approver authority', () => {
    /**An empty list is an answer. A client defaulting a missing field to "can decide
     * everything" would turn this endpoint into the hole it exists to close.
     */
    const nobodyCanDecide = viewer('employee', [], 'Sari')
    expect(canDecide(approval(), nobodyCanDecide)).toBe(false)
    expect(canDecide(approval(), NO_VIEWER)).toBe(false)
  })
})

describe('you cannot decide what you raised', () => {
  it('blocks a manager who raised it', () => {
    const subject = approval({ requested_by: 'Budi' })
    expect(canDecide(subject, lead)).toBe(false)
    expect(blockedBecause(subject, lead)).toBe('ownRequest')
  })

  it('exempts hr_admin, because at a one-person shop nobody else can', () => {
    /**`ApprovalService.decide` exempts hr_admin for exactly this reason, and the
     * exemption stays visible on the record: one actor for both events.
     */
    const subject = approval({ requested_by: 'Rina' })
    expect(canDecide(subject, boss)).toBe(true)
    expect(blockedBecause(subject, boss)).toBeNull()
  })

  it('lets a manager decide one a colleague raised', () => {
    expect(canDecide(approval({ requested_by: 'Sari' }), lead)).toBe(true)
  })
})

describe('the reason for hiding a decision is named, not implied', () => {
  it('distinguishes already-decided from not-yours from own-request', () => {
    /**A disabled button with no explanation is the thing this screen exists to avoid;
     * "already decided", "not your role" and "you raised it" need different words.
     */
    expect(blockedBecause(approval({ status: 'approved' }), boss)).toBe('decided')
    expect(blockedBecause(approval({ assignee_role: 'finance' }), lead)).toBe('otherRole')
    expect(blockedBecause(approval({ requested_by: 'Budi' }), lead)).toBe('ownRequest')
    expect(blockedBecause(approval(), NO_VIEWER)).toBe('unknownViewer')
    expect(blockedBecause(approval(), lead)).toBeNull()
  })
})

describe('rejection asks for a reason; approval does not', () => {
  it('requires one only to reject', () => {
    expect(requiresReason(false)).toBe(true)
    expect(requiresReason(true)).toBe(false)
  })

  it('treats whitespace as no reason', () => {
    expect(isBlocked('   ')).toBe(true)
    expect(isBlocked('')).toBe(true)
    expect(isBlocked('budget was spent')).toBe(false)
    expect(isBlocked(null)).toBe(false)
  })
})

describe('the queue is worked in the order a person works it', () => {
  it('puts overdue first', () => {
    const list = [
      approval({ id: 'fresh', created_at: '2026-01-01T00:00:00Z' }),
      approval({ id: 'late', is_overdue: true, created_at: '2026-06-01T00:00:00Z' }),
    ]
    expect(byUrgency(list).map((item) => item.id)).toEqual(['late', 'fresh'])
  })

  it('puts the most escalated next', () => {
    const list = [
      approval({ id: 'once', escalation_count: 1 }),
      approval({ id: 'thrice', escalation_count: 3 }),
      approval({ id: 'none', escalation_count: 0 }),
    ]
    expect(byUrgency(list).map((item) => item.id)).toEqual(['thrice', 'once', 'none'])
  })

  it('falls back to oldest first within the same band', () => {
    const list = [
      approval({ id: 'newer', created_at: '2026-02-01T00:00:00Z' }),
      approval({ id: 'older', created_at: '2026-01-01T00:00:00Z' }),
    ]
    expect(byUrgency(list).map((item) => item.id)).toEqual(['older', 'newer'])
  })

  it('does not mutate the input it was given', () => {
    const list = [approval({ id: 'b' }), approval({ id: 'a', created_at: '2025-01-01T00:00:00Z' })]
    const before = list.map((item) => item.id)
    byUrgency(list)
    expect(list.map((item) => item.id)).toEqual(before)
  })
})

describe('a subject label is readable without a translation', () => {
  it('turns the enum into words', () => {
    expect(subjectLabel('leave_request')).toBe('leave request')
    expect(subjectLabel('erasure_request')).toBe('erasure request')
  })
})
