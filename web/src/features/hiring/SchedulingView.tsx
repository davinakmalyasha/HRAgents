import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge, type StatusTone } from '@/components/status/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

import { ProposalActionDialog } from './ProposalActionDialog'
import { shortId } from './pipeline'
import {
  actionsFor,
  applicationForCandidate,
  formatSlot,
  newestFirst,
  proposalStatus,
  type ProposalAction,
  type ProposalPresentation,
  type SchedulingProposal,
} from './scheduling'
import { useApplications } from './useHiring'
import { useSchedulingProposals } from './useScheduling'

const TONES: Partial<Record<ProposalPresentation, StatusTone>> = {
  auto: 'done',
  needs_approval: 'waiting',
  reconciliation: 'waiting',
  confirmed: 'done',
}

function ProposalItem({
  proposal,
  applicationId,
  onAction,
}: {
  proposal: SchedulingProposal
  applicationId: string | undefined
  onAction: (action: ProposalAction) => void
}) {
  const { t, i18n } = useTranslation()
  const status = proposalStatus(proposal)
  const candidateLabel = shortId(proposal.payload.candidate_id)
  const tone = TONES[status]
  const actions = actionsFor(proposal.status)

  return (
    <li className="flex flex-col gap-2 px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
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
          {tone === undefined ? (
            <Badge variant="outline">{t(`scheduling.status.${status}`)}</Badge>
          ) : (
            <StatusBadge tone={tone} labelKey={`scheduling.status.${status}`} />
          )}
        </div>
        <span className="text-2xs text-ink-muted">
          {t(`review.decisions.${proposal.payload.policy.decision}`)}
        </span>
      </div>

      <span className="text-2xs text-ink-muted">
        {t('scheduling.slotCount', { count: proposal.payload.slots.length })} ·{' '}
        {t('scheduling.requestedBy', { name: proposal.created_by })}
        {proposal.decided_by === null || proposal.decided_by === undefined
          ? ''
          : ` · ${t('scheduling.decidedBy', { name: proposal.decided_by })}`}
      </span>

      {proposal.supersedes_id === null || proposal.supersedes_id === undefined ? null : (
        <p className="text-2xs text-ink-muted">{t('scheduling.replacesEarlier')}</p>
      )}

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

      {actions.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {actions.map((action) => (
            <Button
              key={action}
              variant={action === 'confirm' ? 'default' : 'outline'}
              size="xs"
              onClick={() => onAction(action)}
            >
              {t(`scheduling.actions.${action}`)}
            </Button>
          ))}
        </div>
      ) : null}
    </li>
  )
}

/**
 * Interview proposals over the scheduling registry.
 *
 * A proposal follows the policy gate (`S_tech ≥ 0.85 ∧ σ ≤ 0.05`, mutual
 * slots, no flags); confirm/cancel/reschedule go through the decision
 * endpoint — the single writer that also decides the linked approval in the
 * named human's name.
 */
export function SchedulingView() {
  const { t } = useTranslation()
  const proposals = useSchedulingProposals()
  const applications = useApplications(null)
  const [dialog, setDialog] = useState<{
    proposal: SchedulingProposal
    action: ProposalAction
  } | null>(null)

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
              onAction={(action) => setDialog({ proposal, action })}
            />
          ))}
        </ul>
      )}

      {dialog !== null ? (
        <ProposalActionDialog
          key={`${dialog.proposal.id}-${dialog.action}`}
          proposal={dialog.proposal}
          action={dialog.action}
          open
          onOpenChange={(next) => {
            if (!next) {
              setDialog(null)
            }
          }}
        />
      ) : null}
    </section>
  )
}
