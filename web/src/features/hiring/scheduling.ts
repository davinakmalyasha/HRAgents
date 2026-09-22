import type { components } from '@/api/schema'

import type { ApplicationSummary } from './pipeline'

export type SchedulingProposal = components['schemas']['SchedulingProposalView']
export type ProposalStatus = components['schemas']['ProposalStatus']
export type TimeSlot = components['schemas']['TimeSlot']

export type ProposalPresentation =
  'auto' | 'needs_approval' | 'reconciliation' | 'confirmed' | 'cancelled' | 'superseded'

/**
 * Presentation state for a proposal row. Reconciliation outranks the approval
 * flag while a proposal is still open; decided states are terminal and win.
 */
export function proposalStatus(proposal: SchedulingProposal): ProposalPresentation {
  if (proposal.status === 'confirmed') {
    return 'confirmed'
  }
  if (proposal.status === 'cancelled') {
    return 'cancelled'
  }
  if (proposal.status === 'superseded') {
    return 'superseded'
  }
  if (proposal.needs_human_reconciliation) {
    return 'reconciliation'
  }
  return proposal.status === 'auto_scheduled' ? 'auto' : 'needs_approval'
}

export type ProposalAction = 'confirm' | 'cancel' | 'reschedule'

export function actionsFor(status: ProposalStatus): ProposalAction[] {
  switch (status) {
    case 'confirmed':
      return ['cancel', 'reschedule']
    case 'cancelled':
    case 'superseded':
      return []
    default:
      return ['confirm', 'cancel', 'reschedule']
  }
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
