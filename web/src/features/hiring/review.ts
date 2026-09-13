import type { PolicyDecision } from './hiringApi'

export const REVIEWER_ROLES = ['engineering_lead', 'recruiter_lead', 'hr_partner'] as const
export type ReviewerRole = (typeof REVIEWER_ROLES)[number]

export const DECISIONS: readonly PolicyDecision[] = [
  'auto_schedule',
  'hitl_soft_rejection',
  'hitl_anomaly',
  'hitl_calendar',
  'hitl_manual',
  'reject_auto',
]
