import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge } from '@/components/status/StatusBadge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useEmployees } from '@/features/records/useRecords'

import {
  LEAVE_TYPE_LABELS,
  balanceTone,
  type BalanceView,
  pendingFirst,
  withEmployeeNames,
  type LeaveRequestWithEmployee,
} from './leaveApi'
import { useCancelLeaveRequest, useEmployeeBalances, useLeaveRequests } from './useLeave'

/**
 * Leave board: who is out, and what each person has left this year.
 *
 * Read-only. The queue room is where a request is cancelled or a balance adjusted, because
 * both need a recorded reason and a named human -- neither belongs on a glanceable
 * summary that people would expect to act from.
 */
export function LeaveBoard() {
  const { t } = useTranslation()
  const requests = useLeaveRequests()
  const employees = useEmployees()

  const names = useMemo(() => {
    const map = new Map<string, string>()
    for (const employee of employees.data ?? []) {
      map.set(employee.id, employee.full_name)
    }
    return map
  }, [employees.data])

  const rows = useMemo(() => withEmployeeNames(requests.data ?? [], names), [requests.data, names])

  const away = rows.filter((row) => ['approved', 'pending'].includes(row.request.status))

  if (requests.isLoading) {
    return <Skeleton className="h-40" />
  }

  return (
    <section aria-labelledby="leave-board" className="flex flex-col gap-4">
      <h2 id="leave-board" className="text-ink-strong text-lg font-medium">
        {t('leave.boardTitle')}
      </h2>
      {away.length === 0 ? (
        <EmptyState title={t('leave.boardEmpty')} />
      ) : (
        <ul className="flex flex-col gap-2">
          {away.map(({ request, employeeName }) => (
            <li key={request.id} className="border-line rounded-lg border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-ink-strong font-medium">{employeeName}</span>
                <StatusBadge
                  // Icon + label, never colour alone: the status is the whole point of
                  // this row, and a colour-blind reader must still be able to act on it.
                  tone={request.status === 'approved' ? 'done' : 'waiting'}
                  labelKey={`leave.status.${request.status}`}
                />
              </div>
              <p className="text-ink-muted text-sm">
                {LEAVE_TYPE_LABELS[request.leave_type]} &middot; {request.start_date} &rarr;{' '}
                {request.end_date} &middot; {t('leave.days', { count: request.days })}
              </p>
            </li>
          ))}
        </ul>
      )}

      <BalancePanel names={names} />
    </section>
  )
}

function BalancePanel({ names }: { names: ReadonlyMap<string, string> }) {
  const { t } = useTranslation()
  const employees = useEmployees()
  const [selected, setSelected] = useState<string | null>(null)
  const balances = useEmployeeBalances(selected)

  return (
    <section aria-labelledby="leave-balances" className="flex flex-col gap-3">
      <h3 id="leave-balances" className="text-ink-strong text-base font-medium">
        {t('leave.balancesTitle')}
      </h3>
      <div className="flex flex-wrap gap-2">
        {(employees.data ?? []).map((employee) => (
          <Button
            key={employee.id}
            variant={selected === employee.id ? 'default' : 'outline'}
            size="sm"
            onClick={() => setSelected(selected === employee.id ? null : employee.id)}
          >
            {employee.full_name}
          </Button>
        ))}
      </div>

      {selected === null ? (
        <p className="text-ink-muted text-sm">{t('leave.balancesPick')}</p>
      ) : balances.isLoading ? (
        <Skeleton className="h-24" />
      ) : (balances.data ?? []).length === 0 ? (
        <EmptyState title={t('leave.balancesEmpty', { name: names.get(selected) ?? '' })} />
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2">
          {(balances.data ?? []).map((balance) => (
            <li key={balance.leave_type} className="border-line rounded-lg border p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-ink-strong text-sm font-medium">
                  {LEAVE_TYPE_LABELS[balance.leave_type]}
                </span>
                <StatusBadge
                  tone={toneForBalance(balance)}
                  labelKey="leave.availableLabel"
                  className="tabular-nums"
                />
                <span className="text-ink-muted text-xs">
                  {t('leave.available', { count: balance.available })}
                </span>
              </div>
              <dl className="text-ink-muted mt-2 grid grid-cols-2 gap-x-3 text-xs">
                <dt>{t('leave.entitled')}</dt>
                <dd className="text-right tabular-nums">{balance.entitled}</dd>
                <dt>{t('leave.used')}</dt>
                <dd className="text-right tabular-nums">{balance.used}</dd>
                <dt>{t('leave.pendingDays')}</dt>
                <dd className="text-right tabular-nums">{balance.pending}</dd>
                {balance.adjustment !== 0 ? (
                  <>
                    <dt>{t('leave.adjustment')}</dt>
                    <dd className="text-right tabular-nums">{balance.adjustment}</dd>
                  </>
                ) : null}
              </dl>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/**
 * Leave queue: requests waiting on a decision.
 *
 * Deciding a request is not offered here. Approval happens through the approvals inbox,
 * which is the one surface that records who decided what; a second way to decide the same
 * thing is how two people end up approving a request neither knew about. Cancelling is
 * offered because the requester's own withdrawal is not a decision about somebody else.
 */
export function LeaveQueue() {
  const { t } = useTranslation()
  const requests = useLeaveRequests()
  const employees = useEmployees()
  const cancel = useCancelLeaveRequest()

  const names = useMemo(() => {
    const map = new Map<string, string>()
    for (const employee of employees.data ?? []) {
      map.set(employee.id, employee.full_name)
    }
    return map
  }, [employees.data])

  const rows = useMemo(
    () => pendingFirst(withEmployeeNames(requests.data ?? [], names)),
    [requests.data, names],
  )

  if (requests.isLoading) {
    return <Skeleton className="h-40" />
  }
  if (rows.length === 0) {
    return <EmptyState title={t('leave.queueEmpty')} />
  }

  return (
    <section aria-labelledby="leave-queue" className="flex flex-col gap-3">
      <h2 id="leave-queue" className="text-ink-strong text-lg font-medium">
        {t('leave.queueTitle', { count: rows.length })}
      </h2>
      <ul className="flex flex-col gap-2">
        {rows.map((row) => (
          <LeaveQueueRow
            key={row.request.id}
            row={row}
            busy={cancel.isPending}
            onCancel={(reason) => cancel.mutate({ requestId: row.request.id, reason })}
          />
        ))}
      </ul>
      {cancel.isError ? (
        <p role="alert" className="text-danger text-sm">
          {t('leave.cancelFailed')}
        </p>
      ) : null}
    </section>
  )
}

function LeaveQueueRow({
  row,
  busy,
  onCancel,
}: {
  row: LeaveRequestWithEmployee
  busy: boolean
  onCancel: (reason: string) => void
}) {
  const { t } = useTranslation()
  const { request, employeeName } = row
  const cancellable = ['pending', 'approved'].includes(request.status)
  const [asking, setAsking] = useState(false)
  const [reason, setReason] = useState('')
  const blank = reason.trim() === ''

  return (
    <li className="border-line rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-ink-strong font-medium">{employeeName}</p>
          <p className="text-ink-muted text-sm">
            {LEAVE_TYPE_LABELS[request.leave_type]} &middot; {request.start_date} &rarr;{' '}
            {request.end_date} &middot; {t('leave.days', { count: request.days })}
          </p>
          {request.reason ? (
            <p className="text-ink-muted mt-1 text-xs italic">{request.reason}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge
            tone={toneForStatus(request.status)}
            labelKey={`leave.status.${request.status}`}
          />
          {cancellable && !asking ? (
            <Button variant="outline" size="sm" disabled={busy} onClick={() => setAsking(true)}>
              {t('leave.cancel')}
            </Button>
          ) : null}
        </div>
      </div>

      {asking ? (
        <div className="mt-2 flex flex-col gap-2">
          <label className="text-ink-muted text-xs" htmlFor={`cancel-reason-${request.id}`}>
            {t('leave.cancelReasonLabel')}
          </label>
          <textarea
            id={`cancel-reason-${request.id}`}
            className="border-line w-full rounded border p-2 text-sm"
            rows={2}
            placeholder={t('leave.cancelReasonPlaceholder')}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="flex flex-wrap items-center gap-2">
            {/**
             * Cancelling withdraws somebody's time off, and the server refuses a blank
             * reason -- it used to accept one and drop it, leaving a record that said
             * only "cancelled". The button waits for a real reason instead of firing a
             * request that cannot succeed.
             */}
            <Button
              variant="destructive"
              size="sm"
              disabled={busy || blank}
              onClick={() => onCancel(reason.trim())}
            >
              {t('leave.confirmCancel')}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setAsking(false)
                setReason('')
              }}
            >
              {t('leave.keepRequest')}
            </Button>
            {blank ? (
              <p className="text-ink-muted text-xs">{t('leave.cancelReasonRequired')}</p>
            ) : null}
          </div>
        </div>
      ) : null}
    </li>
  )
}

function toneForStatus(status: string): 'waiting' | 'error' | 'done' {
  if (status === 'approved') return 'done'
  if (status === 'rejected' || status === 'cancelled') return 'error'
  return 'waiting'
}

/** Over-drawn is an error; thin is waiting; healthy is done. Never colour alone. */
function toneForBalance(balance: BalanceView): 'waiting' | 'error' | 'done' {
  const tone = balanceTone(balance)
  if (tone === 'over') return 'error'
  return tone === 'warn' ? 'waiting' : 'done'
}
