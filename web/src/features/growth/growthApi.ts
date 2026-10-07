import type { components } from '@/api/schema'

import { api } from '@/lib/api'

export type CycleView = components['schemas']['CycleView']
export type AssignmentView = components['schemas']['AssignmentView']
export type GoalView = components['schemas']['GoalView']
export type CycleStatus = components['schemas']['ReviewCycleStatus']
export type GoalStatus = components['schemas']['GoalStatus']
export type CycleKind = components['schemas']['ReviewCycleKind']
export type AssignmentStatus = components['schemas']['AssignmentStatus']
export type CycleCreate = components['schemas']['CycleCreate']
export type GoalCreate = components['schemas']['GoalCreate']

export const CYCLE_STATUS_LABELS: Record<CycleStatus, string> = {
  draft: 'Draft',
  active: 'Active',
  reviewing: 'In review',
  completed: 'Completed',
  cancelled: 'Cancelled',
}

export const GOAL_STATUS_LABELS: Record<GoalStatus, string> = {
  draft: 'Draft',
  active: 'Active',
  completed: 'Completed',
  cancelled: 'Cancelled',
}

export const ASSIGNMENT_STATUS_LABELS: Record<AssignmentStatus, string> = {
  pending: 'Not written yet',
  submitted: 'Written',
  skipped: 'Skipped',
}

/**
 * Cycles that are open for new assignments or progress.
 */
export function isOpenCycle(status: CycleStatus): boolean {
  return status === 'draft' || status === 'active'
}

/**
 * Cycles a review may still be filed into.
 *
 * `active`, and only `active`: `GrowthService.submit_assignment` refuses a form unless
 * `cycle.status is ACTIVE`, and `AdvanceCycleStatus.REVIEWING` is where the summaries get
 * drafted. The reviewing cycle is the one being summarised, not the one being written to,
 * so a button offered there would be refused every time.
 */
export function isReviewable(status: CycleStatus): boolean {
  return status === 'active'
}

/**
 * Goals that can still take progress.
 *
 * A completed or cancelled goal is closed; recording progress against it would move a
 * figure nobody reads.
 */
export function isProgressable(status: GoalStatus): boolean {
  return status === 'active' || status === 'draft'
}

/** A goal past its due date that is still open -- the list worth surfacing. */
export function overdueGoals(goals: GoalView[], asOf: string): GoalView[] {
  return goals.filter(
    (goal) => isProgressable(goal.status) && goal.due_on !== null && goal.due_on < asOf,
  )
}

/**
 * Assignments a given reviewer still owes.
 *
 * A skipped assignment is *not* outstanding: skipping is a recorded decision, and listing
 * it as work still to do would tell a manager they owe a review they deliberately did not
 * write.
 */
export function outstandingAssignments(assignments: AssignmentView[]): AssignmentView[] {
  return assignments.filter((item) => item.status === 'pending')
}

/** Progress as a whole percentage, clamped, for a progress bar. */
export function progressPercent(goal: GoalView): number {
  return Math.max(0, Math.min(100, Math.round(goal.progress_percent)))
}

export async function listCycles(): Promise<CycleView[]> {
  const { data } = await api.GET('/v1/growth/cycles')
  return data ?? []
}

/**
 * The caller's own review assignments, across every cycle.
 *
 * `/assignments/mine` rather than `?reviewer_id=`: `reviewer_id` is the authenticated
 * principal's id, and a client cannot know its own. Making a person type the string that
 * decides whose reviews they see is how the wrong person's reviews get read.
 */
export async function myAssignments(): Promise<AssignmentView[]> {
  const { data } = await api.GET('/v1/growth/assignments/mine')
  return data ?? []
}

/** Every form in a cycle, for the HR view of one cycle. */
export async function cycleAssignments(cycleId: string): Promise<AssignmentView[]> {
  const { data } = await api.GET('/v1/growth/cycles/{cycle_id}/assignments', {
    params: { path: { cycle_id: cycleId } },
  })
  return data ?? []
}

export async function listGoals(): Promise<GoalView[]> {
  const { data } = await api.GET('/v1/growth/goals')
  return data ?? []
}

export async function listOverdueGoals(): Promise<GoalView[]> {
  const { data } = await api.GET('/v1/growth/goals/overdue')
  return data ?? []
}

export async function createCycle(body: CycleCreate): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/growth/cycles', { body })
  return { status: response.status }
}

export async function createGoal(body: GoalCreate): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/growth/goals', { body })
  return { status: response.status }
}

async function cycleTransition(
  path:
    | '/v1/growth/cycles/{cycle_id}/activate'
    | '/v1/growth/cycles/{cycle_id}/reviewing'
    | '/v1/growth/cycles/{cycle_id}/close',
  cycleId: string,
  body: Record<string, unknown>,
): Promise<{ status: number }> {
  const { response } = await api.POST(path, {
    params: { path: { cycle_id: cycleId } },
    body,
  })
  return { status: response.status }
}

export function activateCycle(cycleId: string): Promise<{ status: number }> {
  return cycleTransition('/v1/growth/cycles/{cycle_id}/activate', cycleId, {})
}

export function openReviewing(cycleId: string): Promise<{ status: number }> {
  return cycleTransition('/v1/growth/cycles/{cycle_id}/reviewing', cycleId, {})
}

/**
 * Close a cycle.
 *
 * The server demands a reason -- a closed review cycle is a record nobody may quietly
 * discard, so the UI sends one and an empty reason comes back as `reason_required`.
 */
export function closeCycle(cycleId: string, reason: string): Promise<{ status: number }> {
  return cycleTransition('/v1/growth/cycles/{cycle_id}/close', cycleId, { reason })
}

export async function submitAssignment(
  assignmentId: string,
  body: { ratings: Record<string, number>; comments: string },
): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/growth/assignments/{assignment_id}/submit', {
    params: { path: { assignment_id: assignmentId } },
    body,
  })
  return { status: response.status }
}

/** Skipping is an admission that a review did not happen, so it needs a reason too. */
export async function skipAssignment(
  assignmentId: string,
  reason: string,
): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/growth/assignments/{assignment_id}/skip', {
    params: { path: { assignment_id: assignmentId } },
    body: { reason },
  })
  return { status: response.status }
}

/**
 * Record progress against a goal.
 *
 * percent, not progress_percent -- the wire field is named differently from the field
 * the view reads, and mapping it here is the only place that has to know.
 */
export async function recordGoalProgress(
  goalId: string,
  percent: number,
  note: string,
): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/growth/goals/{goal_id}/progress', {
    params: { path: { goal_id: goalId } },
    body: { percent, note },
  })
  return { status: response.status }
}

/** Dimensions offered on a review form. */
export const REVIEW_DIMENSIONS: readonly string[] = [
  'delivery',
  'collaboration',
  'reliability',
  'craft',
]

/**
 * Parse the rating inputs into the wire shape.
 *
 * A blank box is omitted rather than sent as zero: the server rejects a rating outside
 * the cycle's scale, and a person who has not decided should not be recorded as having
 * scored zero. Values outside the scale are dropped for the same reason -- the button
 * stays disabled rather than the server refusing.
 */
export function collectRatings(
  draft: Record<string, string>,
  cycle: CycleView | undefined,
): Record<string, number> {
  if (cycle === undefined) {
    return {}
  }
  const ratings: Record<string, number> = {}
  for (const dimension of REVIEW_DIMENSIONS) {
    const raw = (draft[dimension] ?? '').trim()
    if (raw === '') {
      continue
    }
    const value = Number(raw)
    if (Number.isNaN(value)) {
      continue
    }
    if (value < cycle.rating_scale_min || value > cycle.rating_scale_max) {
      continue
    }
    ratings[dimension] = value
  }
  return ratings
}
