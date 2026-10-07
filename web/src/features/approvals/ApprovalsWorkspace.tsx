import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge } from '@/components/status/StatusBadge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDateTime } from '@/lib/dates'

import {
  blockedBecause,
  byUrgency,
  canDecide,
  requiresReason,
  subjectLabel,
  NO_VIEWER,
  type ApprovalView,
  type ApproverRole,
  type Viewer,
} from './approvalsApi'
import { useApprovals, useDecideApproval, useEscalateOverdue, useSession } from './useApprovals'

/**
 * Approvals inbox — the one place a named human decides anything.
 *
 * The leave, payroll, offboarding, compliance-erasure and growth queues all defer here
 * on purpose. A decision needs an accountable person and an audit entry, and it needs the
 * same accountability wherever it is taken; scattering approve/reject across five
 * workspaces is how five slightly different rules end up enforcing one policy.
 */
export function ApprovalsBoard() {
  const { t } = useTranslation()
  const approvals = useApprovals()
  const session = useSession()
  const escalate = useEscalateOverdue()

  if (approvals.isLoading || session.isLoading) {
    return <Skeleton className="h-40" />
  }

  const list = byUrgency(approvals.data ?? [])
  const overdue = list.filter((item) => item.is_overdue)

  return (
    <section aria-labelledby="approvals-board" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="approvals-board" className="text-ink-strong text-lg font-medium">
          {t('approvals.boardTitle')}
        </h2>
        <div className="flex items-center gap-2">
          {session.data ? (
            <StatusBadge tone="waiting" labelKey={`approvals.role.${session.data.role}`} />
          ) : null}
          <Button size="sm" disabled={escalate.isPending} onClick={() => escalate.mutate()}>
            {t('approvals.escalateOverdue')}
          </Button>
        </div>
      </div>

      {overdue.length > 0 ? (
        <p className="text-error text-sm">
          {t('approvals.overdueCount', { count: overdue.length })}
        </p>
      ) : null}

      {list.length === 0 ? (
        <EmptyState title={t('approvals.empty')} />
      ) : (
        <ul className="flex flex-col gap-2">
          {list.map((approval) => (
            <ApprovalCard key={approval.id} approval={approval} />
          ))}
        </ul>
      )}

      {escalate.isError ? (
        <p role="alert" className="text-error text-sm">
          {t('approvals.escalateFailed')}
        </p>
      ) : null}
    </section>
  )
}

/**
 * Where a decision is actually taken.
 *
 * The board above is a glance; a decision is a commitment with an audit entry, so it does
 * not sit one click away from a list people skim.
 */
export function ApprovalsQueue() {
  const { t } = useTranslation()
  const approvals = useApprovals()
  const session = useSession()
  const decide = useDecideApproval()

  if (approvals.isLoading || session.isLoading) {
    return <Skeleton className="h-40" />
  }

  const list = byUrgency(approvals.data ?? [])
  if (list.length === 0) {
    return <EmptyState title={t('approvals.empty')} />
  }

  const viewer: Viewer = session.data
    ? {
        actorId: session.data.actor_id,
        role: session.data.role,
        approverRoles: (session.data.decides_approver_roles ?? []) as ApproverRole[],
      }
    : NO_VIEWER
  const actionable = list.filter((approval) => canDecide(approval, viewer)).length

  return (
    <section aria-labelledby="approvals-queue" className="flex flex-col gap-3">
      <h2 id="approvals-queue" className="text-ink-strong text-lg font-medium">
        {t('approvals.queueTitle', { count: list.length })}
      </h2>
      {actionable === 0 ? (
        <p className="text-ink-muted text-xs">{t('approvals.noneYoursToDecide')}</p>
      ) : (
        <p className="text-ink-muted text-xs">
          {t('approvals.yoursToDecide', { count: actionable })}
        </p>
      )}
      <ul className="flex flex-col gap-3">
        {list.map((approval) => (
          <ApprovalCard
            key={approval.id}
            approval={approval}
            viewer={viewer}
            onDecide={(approve, reason) =>
              decide.mutate({ approvalId: approval.id, approve, reason })
            }
            busy={decide.isPending}
          />
        ))}
      </ul>
      {decide.isError ? (
        <p role="alert" className="text-error text-sm">
          {t('approvals.decideFailed')}
        </p>
      ) : null}
    </section>
  )
}

function ApprovalCard({
  approval,
  viewer,
  onDecide,
  busy,
}: {
  approval: ApprovalView
  viewer?: Viewer
  onDecide?: (approve: boolean, reason: string) => void
  busy?: boolean
}) {
  const { t } = useTranslation()
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')

  const blocked = viewer === undefined ? 'decided' : blockedBecause(approval, viewer)
  const decidable = viewer !== undefined && onDecide !== undefined && blocked === null
  /**
   * Rejecting is the consequential direction: it refuses a person's leave, a candidate,
   * a payroll run, an erasure. It is a deliberate step, so it asks for the reason and a
   * confirmation rather than firing on one click.
   */
  const reasonMissing = requiresReason(false) && reason.trim() === ''

  return (
    <li className="border-line rounded-lg border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-ink-strong font-medium">{approval.title}</p>
          <p className="text-ink-muted text-xs">
            {t(`approvals.subject.${approval.subject}`, {
              defaultValue: subjectLabel(approval.subject),
            })}
            {' · '}
            {t(`approvals.assigneeRole.${approval.assignee_role}`)}
            {' · '}
            {t('approvals.raisedBy', { who: approval.requested_by })}
          </p>
          {approval.summary ? (
            <p className="text-ink-muted mt-1 text-xs">{approval.summary}</p>
          ) : null}
          {approval.sla_deadline ? (
            <p className="text-ink-muted mt-1 text-xs">
              {t('approvals.dueBy', { when: formatDateTime(approval.sla_deadline) })}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {approval.requested_by_agent ? (
            <StatusBadge tone="waiting" labelKey="approvals.raisedByAgent" />
          ) : null}
          <StatusBadge
            tone={approval.is_overdue ? 'error' : 'waiting'}
            labelKey={
              approval.is_overdue ? 'approvals.overdue' : `approvals.status.${approval.status}`
            }
          />
          {approval.escalation_count > 0 ? (
            <StatusBadge tone="error" labelKey="approvals.escalated" />
          ) : null}
        </div>
      </div>

      {viewer !== undefined && blocked !== null ? (
        <p className="text-ink-muted mt-2 text-xs">{t(`approvals.blocked.${blocked}`)}</p>
      ) : null}

      {decidable ? (
        <div className="mt-3 flex flex-col gap-2">
          {rejecting ? (
            <>
              <label className="text-ink-muted text-xs" htmlFor={`reason-${approval.id}`}>
                {t('approvals.reasonLabel')}
              </label>
              <textarea
                id={`reason-${approval.id}`}
                className="border-line w-full rounded border p-2 text-sm"
                rows={2}
                placeholder={t('approvals.reasonPlaceholder')}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={busy || reasonMissing}
                  onClick={() => onDecide(false, reason.trim())}
                >
                  {t('approvals.confirmReject')}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setRejecting(false)
                    setReason('')
                  }}
                >
                  {t('approvals.cancel')}
                </Button>
                {reasonMissing ? (
                  <p className="text-ink-muted text-xs">{t('approvals.reasonRequired')}</p>
                ) : null}
              </div>
            </>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" disabled={busy} onClick={() => onDecide(true, '')}>
                {t('approvals.approve')}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => setRejecting(true)}
              >
                {t('approvals.reject')}
              </Button>
            </div>
          )}
        </div>
      ) : null}
    </li>
  )
}
