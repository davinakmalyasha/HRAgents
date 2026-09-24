import type { components } from '@/api/schema'

export type CommunicationView = components['schemas']['CommunicationView']
export type OverrideView = components['schemas']['OverrideView']
export type PolicyDecision = components['schemas']['PolicyDecision']
export type Channel = components['schemas']['Channel']
export type ReplyView = components['schemas']['ReplyView']

export const REJECTION_DECISIONS: readonly PolicyDecision[] = ['hitl_soft_rejection', 'reject_auto']

export const COMMUNICATION_CHANNELS = ['email', 'whatsapp'] as const satisfies readonly Channel[]

/**
 * Mirrors the server gate (`CommunicationService._require_rejection_proof`):
 * queueing a rejection message needs a documented automatic rejection or the
 * latest recorded override to be a rejection decision.
 */
export function canQueueRejection(
  policyDecision: PolicyDecision | undefined,
  overrides: OverrideView[],
): boolean {
  if (policyDecision === 'reject_auto') {
    return true
  }
  const latest = [...overrides].sort(
    (a, b) => Date.parse(b.decided_at) - Date.parse(a.decided_at),
  )[0]
  return latest !== undefined && REJECTION_DECISIONS.includes(latest.override_decision)
}

export function newestFirstCommunications(items: CommunicationView[]): CommunicationView[] {
  return [...items].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
}

export function newestFirstReplies(items: ReplyView[]): ReplyView[] {
  return [...items].sort((a, b) => Date.parse(b.received_at) - Date.parse(a.received_at))
}

/**
 * What the transport did with a queued message: a provider, an attempt count, or
 * the error that kept it queued. Returns null when nothing has been attempted
 * yet, so a freshly queued message never shows an error line.
 */
export function dispatchEvidence(item: CommunicationView): {
  provider: string | null
  attempts: number
  error: string | null
} {
  return {
    provider: item.provider,
    attempts: item.send_attempts,
    error: item.status === 'queued' ? item.last_error : null,
  }
}
