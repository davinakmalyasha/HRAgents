import { describe, expect, it } from 'vitest'

import type { components } from '@/api/schema'

import {
  isOpenCycle,
  isProgressable,
  isReviewable,
  outstandingAssignments,
  collectRatings,
  overdueGoals,
  progressPercent,
  REVIEW_DIMENSIONS,
  type CycleStatus,
  type GoalStatus,
} from './growthApi'

type Goal = components['schemas']['GoalView']
type Assignment = components['schemas']['AssignmentView']

function goal(overrides: Partial<Goal> = {}): Goal {
  return {
    id: 'goal-1',
    employee_id: 'emp-1',
    cycle_id: null,
    title: 'Close the year-end audit',
    description: '',
    metric: 'Audits closed',
    start_on: '2026-01-01',
    due_on: '2026-06-30',
    progress_percent: 40,
    status: 'active',
    created_by: 'hr-admin',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    updates: [],
    ...overrides,
  }
}

function assignment(overrides: Partial<Assignment> = {}): Assignment {
  return {
    id: 'asg-1',
    cycle_id: 'cyc-1',
    employee_id: 'emp-1',
    reviewer_id: 'mgr-1',
    reviewer_role: 'manager',
    ratings: {},
    comments: '',
    status: 'pending',
    due_on: null,
    submitted_at: null,
    submitted_by: null,
    skipped_at: null,
    skipped_by: null,
    skip_reason: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('a review is filed while the cycle is active', () => {
  it('accepts active and nothing else', () => {
    /**GrowthService.submit_assignment refuses unless the cycle is ACTIVE. The
    *
eviewing stage is where summaries get drafted, so a form offered there would
    * be refused every single time -- and the button would look broken rather than
    * the rule looking wrong.
    */
    expect(isReviewable('active')).toBe(true)
    for (const status of ['draft', 'reviewing', 'completed', 'cancelled'] as CycleStatus[]) {
      expect(isReviewable(status)).toBe(false)
    }
  })

  it('treats draft and active as the cycles worth listing', () => {
    expect(isOpenCycle('draft')).toBe(true)
    expect(isOpenCycle('active')).toBe(true)
    expect(isOpenCycle('completed')).toBe(false)
    expect(isOpenCycle('cancelled')).toBe(false)
  })
})

describe('a closed goal takes no more progress', () => {
  it('accepts progress only on open goals', () => {
    expect(isProgressable('active')).toBe(true)
    expect(isProgressable('draft')).toBe(true)
    expect(isProgressable('completed')).toBe(false)
    expect(isProgressable('cancelled')).toBe(false)
  })
})

describe('overdue means past due and still open', () => {
  it('lists a goal past its due date that is still open', () => {
    const late = goal({ due_on: '2026-01-31', status: 'active' })
    expect(overdueGoals([late], '2026-02-01').map((item) => item.id)).toEqual(['goal-1'])
  })

  it('does not list a completed goal just because its date passed', () => {
    /**The due date passed, but nothing is outstanding. Showing it would re-open work
     * that was formally finished.
     */
    const done = goal({ due_on: '2026-01-31', status: 'completed' })
    expect(overdueGoals([done], '2026-02-01')).toHaveLength(0)
  })

  it('does not treat the due date itself as overdue', () => {
    expect(overdueGoals([goal({ due_on: '2026-02-01' })], '2026-02-01')).toHaveLength(0)
  })

  it('ignores goals with no due date', () => {
    /**No date was ever agreed, so there is nothing to be late against -- inventing a
     * deadline here would report lateness that was never promised.
     */
    expect(overdueGoals([goal({ due_on: null })], '2026-02-01')).toHaveLength(0)
  })
})

describe('a skipped assignment is not work still to do', () => {
  it('keeps pending and drops both submitted and skipped', () => {
    const list = [
      assignment({ id: 'pending-1', status: 'pending' }),
      assignment({ id: 'written-1', status: 'submitted' }),
      assignment({ id: 'skipped-1', status: 'skipped', skip_reason: 'Manager left' }),
    ]

    expect(outstandingAssignments(list).map((item) => item.id)).toEqual(['pending-1'])
  })

  it('reports nothing outstanding when every assignment was written or skipped', () => {
    const list = [assignment({ status: 'submitted' }), assignment({ status: 'skipped' })]
    expect(outstandingAssignments(list)).toHaveLength(0)
  })
})

describe('progress is clamped for display', () => {
  it('keeps a value the server sent in range', () => {
    expect(progressPercent(goal({ progress_percent: 40 }))).toBe(40)
  })

  it('clamps rather than rendering an overflowing bar', () => {
    expect(progressPercent(goal({ progress_percent: 140 }))).toBe(100)
    expect(progressPercent(goal({ progress_percent: -5 }))).toBe(0)
  })

  it('rounds a fractional figure so the label matches the bar', () => {
    expect(progressPercent(goal({ progress_percent: 66.6 }))).toBe(67)
  })
})

describe('GoalStatus stays a closed set', () => {
  it('covers exactly the four statuses the API declares', () => {
    const everyStatus: GoalStatus[] = ['draft', 'active', 'completed', 'cancelled']
    for (const status of everyStatus) {
      expect(typeof isProgressable(status)).toBe('boolean')
    }
  })
})

describe('the rating form sends only what the server would accept', () => {
  const cycle = {
    id: 'cyc-1',
    rating_scale_min: 1,
    rating_scale_max: 5,
  } as components['schemas']['CycleView']

  it('sends the dimensions that were filled in', () => {
    const ratings = collectRatings({ delivery: '4', collaboration: '3.5' }, cycle)
    expect(ratings).toEqual({ delivery: 4, collaboration: 3.5 })
  })

  it('omits an empty box instead of recording a zero', () => {
    /**The server refuses a submission with no ratings at all, and it rejects a value
     * outside the cycle's scale. A person who has not decided has not scored zero, and
     * writing that down would put a fabricated number in their review.
     */
    expect(collectRatings({ delivery: '', collaboration: '   ' }, cycle)).toEqual({})
  })

  it('drops a value outside the cycle scale rather than sending it', () => {
    expect(collectRatings({ delivery: '9' }, cycle)).toEqual({})
    expect(collectRatings({ delivery: '0' }, cycle)).toEqual({})
  })

  it('drops a value at the edge of the scale only when it is outside it', () => {
    expect(collectRatings({ delivery: '5' }, cycle)).toEqual({ delivery: 5 })
    expect(collectRatings({ delivery: '1' }, cycle)).toEqual({ delivery: 1 })
  })

  it('ignores text that is not a number', () => {
    expect(collectRatings({ delivery: 'excellent' }, cycle)).toEqual({})
  })

  it('reads nothing when the cycle is unknown', () => {
    /**Without the cycle there is no scale to check against, and inventing one would
     * let a rating through that the server would refuse.
     */
    expect(collectRatings({ delivery: '4' }, undefined)).toEqual({})
  })

  it('offers dimensions that cover delivery, collaboration, reliability and craft', () => {
    expect([...REVIEW_DIMENSIONS].sort()).toEqual([
      'collaboration',
      'craft',
      'delivery',
      'reliability',
    ])
  })
})
