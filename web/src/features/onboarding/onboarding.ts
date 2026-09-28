import type { components } from '@/api/schema'

type PlanView = components['schemas']['hr_agents__api__onboarding_schemas__PlanView']
type StepView = components['schemas']['hr_agents__api__onboarding_schemas__StepView']
type TemplateView = components['schemas']['hr_agents__api__onboarding_schemas__TemplateView']

export type OnboardingPlan = PlanView
export type OnboardingStep = StepView
export type OnboardingTemplate = TemplateView
export type StepStatus = components['schemas']['StepStatus']
export type StepKind = components['schemas']['StepKind']
export type EmployeeView = components['schemas']['EmployeeView']
export type EmployeeDocument = components['schemas']['DocumentView']
export type ApproverRole = components['schemas']['ApproverRole']
export type DocumentKind = components['schemas']['DocumentKind']
export type DocumentStatus = 'claimed' | 'verified' | 'unverified' | 'expired' | 'failed' | string

export const STEP_STATUS_TONES: Record<StepStatus, 'waiting' | 'error' | 'done'> = {
  pending: 'waiting',
  in_progress: 'waiting',
  blocked: 'error',
  done: 'done',
  waived: 'done',
}

/** Step kinds that cannot be completed until a document is linked and verified. */
export const DOCUMENT_STEP_KINDS: readonly StepKind[] = ['document']

export function needsDocument(step: OnboardingStep): boolean {
  return DOCUMENT_STEP_KINDS.includes(step.kind)
}

export function pendingSteps(plan: OnboardingPlan): OnboardingStep[] {
  return plan.steps.filter((step) => step.status === 'pending' || step.status === 'blocked')
}

export function completedSteps(plan: OnboardingPlan): OnboardingStep[] {
  return plan.steps.filter((step) => step.status === 'done')
}

export function waivedSteps(plan: OnboardingPlan): OnboardingStep[] {
  return plan.steps.filter((step) => step.status === 'waived')
}

export function isOpen(plan: OnboardingPlan): boolean {
  return !plan.is_complete
}

export function isOverdue(step: OnboardingStep): boolean {
  return step.is_overdue && step.status !== 'done' && step.status !== 'waived'
}

/** Checklist order: what needs a human now (document steps, then tasks), then the rest. */
export function checklistOrder(steps: OnboardingStep[]): OnboardingStep[] {
  const rank = (step: OnboardingStep): number => {
    if (step.status === 'done' || step.status === 'waived') {
      return 3
    }
    if (isOverdue(step)) {
      return 0
    }
    if (needsDocument(step)) {
      return 1
    }
    return 2
  }
  return [...steps].sort((a, b) => {
    const delta = rank(a) - rank(b)
    if (delta !== 0) {
      return delta
    }
    return (a.due_on ?? '9999-12-31').localeCompare(b.due_on ?? '9999-12-31')
  })
}

/** Board order: blocked first, then overdue work, then plain pending, done last. */
export function boardOrder(plans: OnboardingPlan[]): OnboardingPlan[] {
  const score = (plan: OnboardingPlan): number => {
    if (plan.is_complete) {
      return 4
    }
    if (plan.blockers.length > 0) {
      return 0
    }
    if (plan.steps.some(isOverdue)) {
      return 1
    }
    return 2
  }
  return [...plans].sort((a, b) => {
    const delta = score(a) - score(b)
    if (delta !== 0) {
      return delta
    }
    return Date.parse(b.started_at) - Date.parse(a.started_at)
  })
}

export function progressPercent(plan: OnboardingPlan): number {
  const percent = Number.isFinite(plan.progress) ? Math.round(plan.progress * 100) : 0
  return Math.min(100, Math.max(0, percent))
}

/** Blocks: blockers the server reports plus overdue steps, deduped by step key. */
export function blockingSteps(plan: OnboardingPlan): OnboardingStep[] {
  const keys = new Set(plan.blockers)
  return plan.steps.filter(
    (step) => (keys.has(step.key) || isOverdue(step)) && step.status !== 'done',
  )
}
