import { describe, expect, it } from 'vitest'

import {
  boardOrder,
  checklistOrder,
  completedSteps,
  isOverdue,
  needsDocument,
  pendingSteps,
  progressPercent,
  waivedSteps,
  type OnboardingPlan,
  type OnboardingStep,
} from './onboarding'

function step(overrides: Partial<OnboardingStep>): OnboardingStep {
  return {
    key: 'ktp',
    title: 'Collect KTP',
    kind: 'document',
    required: true,
    requires_human_signoff: false,
    assignee_role: 'hr_admin',
    status: 'pending',
    document_kind: 'ktp',
    due_on: null,
    is_overdue: false,
    linked_document_id: null,
    linked_task_id: null,
    ...overrides,
  }
}

function plan(overrides: Partial<OnboardingPlan>): OnboardingPlan {
  return {
    id: 'plan-1',
    employee_id: 'emp-1',
    template_id: 'tpl-1',
    template_name: 'Engineering onboarding',
    template_version_hash: 'abc',
    progress: 0.5,
    is_complete: false,
    started_at: '2026-09-20T03:00:00Z',
    completed_at: null,
    steps: [],
    blockers: [],
    ...overrides,
  }
}

describe('step grouping', () => {
  it('separates pending, done, and waived steps', () => {
    const current = plan({
      steps: [
        step({ key: 'a', status: 'pending' }),
        step({ key: 'b', status: 'blocked' }),
        step({ key: 'c', status: 'done' }),
        step({ key: 'd', status: 'waived' }),
      ],
    })

    expect(pendingSteps(current).map((item) => item.key)).toEqual(['a', 'b'])
    expect(completedSteps(current).map((item) => item.key)).toEqual(['c'])
    expect(waivedSteps(current).map((item) => item.key)).toEqual(['d'])
  })
})

describe('needsDocument', () => {
  it('is true only for document steps', () => {
    expect(needsDocument(step({ kind: 'document' }))).toBe(true)
    expect(needsDocument(step({ kind: 'task' }))).toBe(false)
    expect(needsDocument(step({ kind: 'contract' }))).toBe(false)
  })
})

describe('isOverdue', () => {
  it('never flags a finished step', () => {
    expect(isOverdue(step({ is_overdue: true }))).toBe(true)
    expect(isOverdue(step({ is_overdue: true, status: 'done' }))).toBe(false)
    expect(isOverdue(step({ is_overdue: true, status: 'waived' }))).toBe(false)
    expect(isOverdue(step({ is_overdue: false }))).toBe(false)
  })
})

describe('checklistOrder', () => {
  it('puts overdue, then document steps, then tasks, and finished work last', () => {
    const ordered = checklistOrder([
      step({ key: 'done', status: 'done' }),
      step({ key: 'task', kind: 'task' }),
      step({ key: 'waived', status: 'waived' }),
      step({ key: 'document', kind: 'document' }),
      step({ key: 'overdue', kind: 'task', is_overdue: true }),
    ])

    expect(ordered.map((item) => item.key)).toEqual(['overdue', 'document', 'task', 'done', 'waived'])
  })
})

describe('boardOrder', () => {
  it('surfaces blocked, then overdue, then open, then complete plans', () => {
    const ordered = boardOrder([
      plan({ id: 'complete', is_complete: true, progress: 1 }),
      plan({ id: 'open', started_at: '2026-09-21T03:00:00Z' }),
      plan({ id: 'blocked', blockers: ['contract'] }),
      plan({
        id: 'overdue',
        started_at: '2026-09-22T03:00:00Z',
        steps: [step({ is_overdue: true })],
      }),
    ])

    expect(ordered.map((item) => item.id)).toEqual(['blocked', 'overdue', 'open', 'complete'])
  })
})

describe('progressPercent', () => {
  it('rounds the server progress and stays inside 0-100', () => {
    expect(progressPercent(plan({ progress: 0.666 }))).toBe(67)
    expect(progressPercent(plan({ progress: 1 }))).toBe(100)
    expect(progressPercent(plan({ progress: 1.5 }))).toBe(100)
    expect(progressPercent(plan({ progress: -1 }))).toBe(0)
  })
})
