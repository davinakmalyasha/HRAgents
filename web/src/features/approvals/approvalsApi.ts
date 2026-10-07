import type { components } from '@/api/schema'

import { api } from '@/lib/api'

export type ApprovalView = components['schemas']['ApprovalView']
export type ApprovalStatus = components['schemas']['ApprovalStatus']
export type ApprovalSubject = components['schemas']['ApprovalSubject']

/**
 * `assignee_role` is an approver role, a wider set than the roles a principal can hold.
 * An `engineering_lead` is what a leave request is assigned to, while the people who can
 * act for it authenticate as `manager` or `hr_admin`.
 */
export type ApproverRole = components['schemas']['ApproverRole']
export type RoleId = components['schemas']['RoleId']
export type SessionView = components['schemas']['SessionView']
export type Urgency = components['schemas']['Urgency']
export type ApprovalDecisionRequest = components['schemas']['ApprovalDecisionRequest']

/**
 * Statuses a person can still act on.
 *
 * ApprovalRequest.active is exactly this set. Deciding anything else is refused by the
 * service, so the buttons never appear on a decided, escalated, expired or withdrawn
 * request.
 */
export const DECIDABLE_STATUSES: readonly ApprovalStatus[] = ['pending', 'escalated']

export function isDecidable(status: ApprovalStatus): boolean {
  return DECIDABLE_STATUSES.includes(status)
}

/**
 * Whether the viewer is entitled to decide this one.
 *
 * Two of the three gates in `ApprovalService.decide` are knowable before deciding: the
 * approval must be assigned to the viewer's role, and the viewer must not be the person
 * who raised it. The third -- that the actor is a human at all -- is not something a
 * browser can know, so it stays the server's to enforce.
 *
 * Hiding a button the server would refuse is not the same as enforcing the rule: the
 * refusal still happens. But "cannot decide what you raised" arriving as a 409 after the
 * click tells the user nothing about which of the three gates they failed.
 */
/**
 * The caller, as the server described them.
 *
 * `approverRoles` comes from `/v1/session`, which answers from the same
 * `APPROVER_ROLE_HOLDERS` table the service enforces with. The client holds no copy:
 * that mapping is many-to-many and a local copy would be one table edit away from hiding
 * every decision, or offering one the caller has no authority for.
 */
export interface Viewer {
  actorId: string | null
  role: RoleId | null
  approverRoles: ApproverRole[]
}

export const NO_VIEWER: Viewer = { actorId: null, role: null, approverRoles: [] }

export function canDecide(approval: ApprovalView, viewer: Viewer): boolean {
  if (!isDecidable(approval.status)) {
    return false
  }
  if (viewer.role === null || viewer.actorId === null) {
    return false
  }
  if (!viewer.approverRoles.includes(approval.assignee_role)) {
    return false
  }
  /**
   * Separation of duties. The service exempts `hr_admin` because at a small company the
   * same person is often both requester and only available approver, and an
   * unattributable approval is worse than a rubber-stamped one.
   */
  if (approval.requested_by === viewer.actorId && viewer.role !== 'hr_admin') {
    return false
  }
  return true
}

/**
 * Why a decision is not available.
 *
 * Returned so the UI can say *why* rather than rendering a disabled button with no
 * explanation -- "not yours to decide" and "already decided" need different words.
 */
export function blockedBecause(
  approval: ApprovalView,
  viewer: Viewer,
): 'decided' | 'otherRole' | 'ownRequest' | 'unknownViewer' | null {
  if (!isDecidable(approval.status)) {
    return 'decided'
  }
  if (viewer.actorId === null || viewer.role === null) {
    return 'unknownViewer'
  }
  if (approval.requested_by === viewer.actorId && viewer.role !== 'hr_admin') {
    return 'ownRequest'
  }
  if (!viewer.approverRoles.includes(approval.assignee_role)) {
    return 'otherRole'
  }
  return null
}

/** The authenticated session, or null when /v1/session is unavailable. */
export async function readSession(): Promise<SessionView> {
  const { data } = await api.GET('/v1/session')
  if (data === undefined) {
    throw new Error('session returned nothing')
  }
  return data
}

/**
 * A rejection needs a reason; an approval does not.
 *
 * Rejecting someone is the consequential direction -- it refuses a person's leave, a
 * candidate, an erasure -- and the record outlives the tool. This mirrors what the
 * server requires elsewhere for a one-way, hard-to-reverse act.
 */
export function requiresReason(approve: boolean): boolean {
  return !approve
}

export function isBlocked(reason: string | null): boolean {
  return reason !== null && reason.trim() === ''
}

export async function listApprovals(filters?: {
  status?: ApprovalStatus
  role?: ApproverRole
}): Promise<ApprovalView[]> {
  const { data } = await api.GET('/v1/approvals', {
    params: { query: { status: filters?.status, role: filters?.role } },
  })
  return data ?? []
}

/**
 * Decide an approval.
 *
 * The request carries no assignee or approver name: the server resolves the actor from the
 * session, so a decision cannot be filed in somebody else's name.
 */
export async function decideApproval(
  approvalId: string,
  body: ApprovalDecisionRequest,
): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/approvals/{approval_id}/decide', {
    params: { path: { approval_id: approvalId } },
    body,
  })
  return { status: response.status }
}

/**
 * Escalate every overdue approval.
 *
 * A system move rather than a decision: it re-raises what has gone stale without anyone
 * having to pick each one out by hand.
 */
export async function escalateOverdue(): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/approvals/escalate-overdue')
  return { status: response.status }
}

/** Overdue first, then oldest: the order somebody actually works the list in. */
export function byUrgency(approvals: ApprovalView[]): ApprovalView[] {
  return [...approvals].sort((left, right) => {
    if (left.is_overdue !== right.is_overdue) {
      return left.is_overdue ? -1 : 1
    }
    if (left.escalation_count !== right.escalation_count) {
      return right.escalation_count - left.escalation_count
    }
    return left.created_at.localeCompare(right.created_at)
  })
}

export function subjectLabel(subject: ApprovalSubject): string {
  return subject.replace(/_/g, ' ')
}
