import type { components } from '@/api/schema'

import type { ApplicationSummary } from './pipeline'

export type SchedulingProposal = components['schemas']['SchedulingProposalView']
export type TimeSlot = components['schemas']['TimeSlot']

export type ProposalStatus = 'auto' | 'needs_approval' | 'reconciliation'

/**
 * Reconciliation outranks the approval flag: a proposal without mutual slots
 * cannot proceed no matter what the evaluation scored, so it is surfaced as
 * its own state instead of hiding behind "needs approval".
 */
export function proposalStatus(proposal: SchedulingProposal): ProposalStatus {
  if (proposal.needs_human_reconciliation) {
    return 'reconciliation'
  }
  return proposal.requires_human_approval ? 'needs_approval' : 'auto'
}

export function newestFirst(proposals: SchedulingProposal[]): SchedulingProposal[] {
  return [...proposals].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
}

export function formatSlot(slot: TimeSlot, timezone: string, locale: string): string {
  const day = new Intl.DateTimeFormat(locale, {
    timeZone: timezone,
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
  const time = new Intl.DateTimeFormat(locale, {
    timeZone: timezone,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
  const start = new Date(slot.start_utc)
  const end = new Date(slot.end_utc)
  return `${day.format(start)} · ${time.format(start)}–${time.format(end)}`
}

export function applicationForCandidate(
  applications: ApplicationSummary[],
  candidateId: string,
): ApplicationSummary | undefined {
  return applications.find((application) => application.candidate_id === candidateId)
}
