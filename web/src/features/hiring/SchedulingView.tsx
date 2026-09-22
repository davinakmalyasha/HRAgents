import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge, type StatusTone } from '@/components/status/StatusBadge'
import { Skeleton } from '@/components/ui/skeleton'

import { shortId } from './pipeline'
import {
  applicationForCandidate,
  formatSlot,
  newestFirst,
  proposalStatus,
  type ProposalStatus,
  type SchedulingProposal,
} from './scheduling'
import { useApplications } from './useHiring'
import { useSchedulingProposals } from './useScheduling'

const TONES: Record<ProposalStatus, StatusTone> = {
  auto: 'done',
  needs_approval: 'waiting',
  reconciliation: 'waiting',
}

function ProposalItem({
  proposal,
  applicationId,
}: {
  proposal: SchedulingProposal
  applicationId: string | undefined
}) {
  const { t, i18n } = useTranslation()
  const status = proposalStatus(proposal)
  const candidateLabel = shortId(proposal.payload.candidate_id)

  return (
    <li className="flex flex-col gap-2 px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {applicationId === undefined ? (
            <span className="text-ink-strong font-mono text-xs">{candidateLabel}</span>
          ) : (
            <Link
              to={`/w/hiring/applications/${applicationId}`}
              className="text-primary font-mono text-xs underline-offset-2 hover:underline"
            >
              {candidateLabel}
            </Link>
          )}
          <StatusBadge tone={TONES[status]} labelKey={`scheduling.status.${status}`} />
        </div>
        <span className="text-2xs text-ink-muted">
          {t(`review.decisions.${proposal.payload.policy.decision}`)}
        </span>
      </div>

      <span className="text-2xs text-ink-muted">
        {t('scheduling.slotCount', { count: proposal.payload.slots.length })} ·{' '}
        {t('scheduling.requestedBy', { name: proposal.created_by })}
      </span>

      {proposal.payload.slots.length > 0 ? (
        <ul className="flex flex-wrap gap-x-4 gap-y-1">
          {proposal.payload.slots.map((slot) => (
            <li
              key={`${slot.start_utc}-${slot.end_utc}`}
              className="text-ink-strong text-2xs font-mono tabular-nums"
            >
              {formatSlot(slot, proposal.payload.timezone, i18n.language)}
            </li>
          ))}
        </ul>
      ) : null}

      {proposal.payload.policy.reasons !== undefined &&
      proposal.payload.policy.reasons.length > 0 ? (
        <p className="text-2xs text-ink-muted">{proposal.payload.policy.reasons.join(' · ')}</p>
      ) : null}

      {status === 'reconciliation' ? (
        <p className="text-waiting text-2xs flex items-center gap-1">
          <span aria-hidden="true">▲</span>
          {t('scheduling.reconciliationHint')}
        </p>
      ) : null}
      {status === 'needs_approval' ? (
        <p className="text-2xs text-ink-muted">{t('scheduling.approvalHint')}</p>
      ) : null}
    </li>
  )
}

/**
 * Interview proposals over the scheduling registry.
 *
 * Read-only: a proposal follows the policy gate (`S_tech ≥ 0.85 ∧ σ ≤ 0.05`,
 * mutual slots, no flags). Human decisions stay on the review queue — the
 * override endpoint is the only writer, never this view.
 */
export function SchedulingView() {
  const { t } = useTranslation()
  const proposals = useSchedulingProposals()
  const applications = useApplications(null)

  return (
    <section aria-labelledby="hiring-scheduling" className="flex flex-col gap-3">
      <h2 id="hiring-scheduling" className="text-ink-strong text-lg font-medium">
        {t('scheduling.title')}
      </h2>

      {proposals.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : (proposals.data ?? []).length === 0 ? (
        <EmptyState title={t('scheduling.empty')} />
      ) : (
        <ul className="divide-line border-line flex flex-col divide-y rounded-lg border">
          {newestFirst(proposals.data ?? []).map((proposal) => (
            <ProposalItem
              key={proposal.id}
              proposal={proposal}
              applicationId={
                applicationForCandidate(applications.data ?? [], proposal.payload.candidate_id)
                  ?.application_id
              }
            />
          ))}
        </ul>
      )}
    </section>
  )
}
