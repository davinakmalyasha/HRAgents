import type { components } from '../../api/schema'
import type { PolicyDecision } from './hiringApi'

type ApproverRole = components['schemas']['ApproverRole']

/**
 * The roles the API will accept on an override.
 *
 * This list used to be a hand-written literal that included `hr_partner` --
 * a role that does not exist in the server's `ApproverRole` enum, so choosing it
 * produced a 422 from the one screen whose job is a human sign-off. Deriving the
 * type from the generated schema means the compiler rejects the next invented
 * role; the `satisfies` clause keeps the runtime list honest too, since a plain
 * annotation would widen it silently back to `ApproverRole`.
 */
export const REVIEWER_ROLES = [
  'hr_admin',
  'recruiter_lead',
  'engineering_lead',
] as const satisfies readonly ApproverRole[]

export type ReviewerRole = (typeof REVIEWER_ROLES)[number]

export const DECISIONS: readonly PolicyDecision[] = [
  'auto_schedule',
  'hitl_soft_rejection',
  'hitl_anomaly',
  'hitl_calendar',
  'hitl_manual',
  'reject_auto',
]
