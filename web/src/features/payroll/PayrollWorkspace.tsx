import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge } from '@/components/status/StatusBadge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

import {
  RUN_KIND_LABELS,
  amount,
  advisoryAnomalies,
  blockingAnomalies,
  blocksSignoff,
  isCancellable,
  isComputable,
  isExportable,
  isSubmittable,
  packetUrl,
  rupiah,
  type LineView,
  type RunStatus,
  type RunView,
} from './payrollApi'
import {
  useCancelRun,
  useComputeRun,
  useCreateRun,
  usePayrollRun,
  usePayrollRuns,
  useSubmitRun,
} from './usePayroll'

/**
 * Payroll board: the runs that exist and where each one has got to.
 *
 * Nothing here moves money. The board says what exists; the queue says what a person may
 * do about it. `blocking_count` is rendered from the server's own figure rather than
 * counted in the UI, so the number on screen cannot disagree with the gate that enforces
 * sign-off.
 */
export function PayrollBoard() {
  const { t } = useTranslation()
  const runs = usePayrollRuns()
  const create = useCreateRun()
  const now = new Date()
  const [periodYear, setPeriodYear] = useState(String(now.getFullYear()))
  const [periodMonth, setPeriodMonth] = useState(String(now.getMonth() + 1))
  const [kind, setKind] = useState<string>('monthly')

  if (runs.isLoading) {
    return <Skeleton className="h-40" />
  }

  const list = runs.data ?? []

  return (
    <section aria-labelledby="payroll-board" className="flex flex-col gap-4">
      <h2 id="payroll-board" className="text-ink-strong text-lg font-medium">
        {t('payroll.boardTitle')}
      </h2>

      <form
        className="border-line flex flex-wrap items-end gap-2 rounded-lg border p-3"
        onSubmit={(event) => {
          event.preventDefault()
          create.mutate({
            period_year: Number(periodYear),
            period_month: Number(periodMonth),
            kind: kind as RunView['kind'],
          })
        }}
      >
        <label className="flex flex-col text-xs" htmlFor="payroll-year">
          {t('payroll.year')}
          <input
            id="payroll-year"
            className="border-line rounded px-2 py-1"
            inputMode="numeric"
            value={periodYear}
            onChange={(event) => setPeriodYear(event.target.value)}
          />
        </label>
        <label className="flex flex-col text-xs" htmlFor="payroll-month">
          {t('payroll.month')}
          <input
            id="payroll-month"
            className="border-line rounded px-2 py-1"
            inputMode="numeric"
            min={1}
            max={12}
            value={periodMonth}
            onChange={(event) => setPeriodMonth(event.target.value)}
          />
        </label>
        <label className="flex flex-col text-xs" htmlFor="payroll-kind">
          {t('payroll.kind')}
          <select
            id="payroll-kind"
            className="border-line rounded px-2 py-1"
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          >
            {(['monthly', 'thr', 'adjustment', 'final'] as const).map((option) => (
              <option key={option} value={option}>
                {RUN_KIND_LABELS[option]}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" disabled={create.isPending}>
          {t('payroll.create')}
        </Button>
        {create.isError ? (
          <p role="alert" className="text-error text-xs">
            {t('payroll.createFailed')}
          </p>
        ) : null}
      </form>

      {list.length === 0 ? (
        <EmptyState title={t('payroll.boardEmpty')} />
      ) : (
        <ul className="flex flex-col gap-2">
          {list.map((run) => (
            <RunRow key={run.id} run={run} />
          ))}
        </ul>
      )}
    </section>
  )
}

function RunRow({ run }: { run: RunView }) {
  const { t } = useTranslation()
  return (
    <li className="border-line rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-ink-strong font-medium">
            {t('payroll.period', {
              month: run.period_month,
              year: run.period_year,
            })}
          </p>
          <p className="text-ink-muted text-sm">
            {RUN_KIND_LABELS[run.kind]} &middot;{' '}
            {t('payroll.people', { count: run.totals.employees })} &middot; {t('payroll.net')}{' '}
            {rupiah(run.totals.net)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {run.blocking_count > 0 ? <StatusBadge tone="error" labelKey="payroll.blocking" /> : null}
          <StatusBadge tone={toneForStatus(run.status)} labelKey={`payroll.status.${run.status}`} />
        </div>
      </div>
    </li>
  )
}

/**
 * Payroll queue: one run in detail, with the actions a named human may take.
 *
 * The order of the buttons is the order of the lifecycle, and each is shown only when the
 * run is actually in a state that allows it, so a refusal is not something a person has to
 * discover by clicking.
 */
export function PayrollQueue() {
  const { t } = useTranslation()
  const runs = usePayrollRuns()
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const list = runs.data ?? []
  const chosen = selectedId ?? list[0]?.id ?? null
  const run = usePayrollRun(chosen)

  if (runs.isLoading) {
    return <Skeleton className="h-40" />
  }
  if (list.length === 0) {
    return <EmptyState title={t('payroll.queueEmpty')} />
  }

  return (
    <section aria-labelledby="payroll-queue" className="flex flex-col gap-4">
      <h2 id="payroll-queue" className="text-ink-strong text-lg font-medium">
        {t('payroll.queueTitle')}
      </h2>

      <label className="flex flex-col text-xs" htmlFor="payroll-run">
        {t('payroll.run')}
        <select
          id="payroll-run"
          className="border-line rounded px-2 py-1"
          value={chosen ?? ''}
          onChange={(event) => setSelectedId(event.target.value)}
        >
          {list.map((option) => (
            <option key={option.id} value={option.id}>
              {t('payroll.period', {
                month: option.period_month,
                year: option.period_year,
              })}
              {' — '}
              {RUN_KIND_LABELS[option.kind]}
            </option>
          ))}
        </select>
      </label>

      {run.isLoading || run.data === undefined || run.data === null ? (
        <Skeleton className="h-40" />
      ) : (
        <RunDetail run={run.data} />
      )}
    </section>
  )
}

function RunDetail({ run }: { run: RunView }) {
  const { t } = useTranslation()
  const compute = useComputeRun()
  const submit = useSubmitRun()
  const cancel = useCancelRun()
  const blocking = blockingAnomalies(run)
  const advisory = advisoryAnomalies(run)
  const busy = compute.isPending || submit.isPending || cancel.isPending

  return (
    <div className="flex flex-col gap-4">
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Total label={t('payroll.gross')} value={run.totals.gross} />
        <Total label={t('payroll.deductions')} value={run.totals.total_deductions} />
        <Total label={t('payroll.net')} value={run.totals.net} />
        <Total label={t('payroll.employerCost')} value={run.totals.employer_cost} />
      </dl>

      {blocking.length > 0 ? (
        <section aria-labelledby="payroll-blocking" className="flex flex-col gap-2">
          <h3 id="payroll-blocking" className="text-ink-strong text-base font-medium">
            {t('payroll.blockingTitle', { count: run.blocking_count })}
          </h3>
          <ul className="flex flex-col gap-1">
            {blocking.map((anomaly) => (
              <li key={`${anomaly.code}-${anomaly.employee_id ?? 'run'}`} className="text-sm">
                <span className="text-error font-medium">{anomaly.code}</span>{' '}
                <span className="text-ink-muted">{anomaly.detail}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {advisory.length > 0 ? (
        <details className="text-ink-muted text-sm">
          <summary className="cursor-pointer">
            {t('payroll.advisoryTitle', { count: advisory.length })}
          </summary>
          <ul className="mt-1 flex flex-col gap-1">
            {advisory.map((anomaly) => (
              <li key={`${anomaly.code}-${anomaly.employee_id ?? 'run'}`}>
                <span className="font-medium">{anomaly.code}</span> {anomaly.detail}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {run.lines.length > 0 ? (
        <LineTable lines={run.lines} />
      ) : (
        <EmptyState title={t('payroll.noLines')} />
      )}

      <div className="flex flex-wrap items-center gap-2">
        {isComputable(run.status) ? (
          <Button disabled={busy} onClick={() => compute.mutate(run.id)}>
            {t('payroll.compute')}
          </Button>
        ) : null}

        {isSubmittable(run.status) ? (
          <Button
            disabled={busy || blocksSignoff(run)}
            title={blocksSignoff(run) ? t('payroll.signoffBlockedHint') : undefined}
            onClick={() => submit.mutate(run.id)}
          >
            {t('payroll.submit')}
          </Button>
        ) : null}

        {isExportable(run.status) ? (
          <a
            className="border-line rounded px-3 py-2 text-sm font-medium"
            href={packetUrl(run.id)}
            download
          >
            {t('payroll.download')}
          </a>
        ) : null}

        {isCancellable(run.status) ? (
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => cancel.mutate({ runId: run.id, reason: '' })}
          >
            {t('payroll.cancel')}
          </Button>
        ) : null}
      </div>

      {submit.isError ? (
        <p role="alert" className="text-error text-sm">
          {t('payroll.actionFailed')}
        </p>
      ) : null}

      <p className="text-ink-muted text-xs">{t('payroll.notice')}</p>
    </div>
  )
}

function Total({ label, value }: { label: string; value: number }) {
  return (
    <div className="border-line rounded-lg border p-2">
      <dt className="text-ink-muted text-xs">{label}</dt>
      <dd className="text-ink-strong tabular-nums">{rupiah(value)}</dd>
    </div>
  )
}

function LineTable({ lines }: { lines: LineView[] }) {
  const { t } = useTranslation()
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">{t('payroll.linesCaption')}</caption>
        <thead>
          <tr className="text-ink-muted border-line border-b text-left text-xs">
            <th scope="col">{t('payroll.colEmployee')}</th>
            <th scope="col" className="text-right">
              {t('payroll.colGross')}
            </th>
            <th scope="col" className="text-right">
              {t('payroll.colDeductions')}
            </th>
            <th scope="col" className="text-right">
              {t('payroll.colNet')}
            </th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <tr key={line.employee_id} className="border-line border-b">
              <td className="text-ink-strong">
                {line.employee_name || t('payroll.unnamedEmployee')}
              </td>
              <td className="text-right tabular-nums">{amount(line.gross)}</td>
              <td className="text-right tabular-nums">{amount(line.total_deductions)}</td>
              <td className="text-ink-strong text-right tabular-nums">{amount(line.net)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function toneForStatus(status: RunStatus): 'waiting' | 'error' | 'done' {
  if (status === 'approved' || status === 'exported') {
    return 'done'
  }
  if (status === 'rejected' || status === 'cancelled') {
    return 'error'
  }
  return 'waiting'
}
