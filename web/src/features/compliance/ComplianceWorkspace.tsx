import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge } from '@/components/status/StatusBadge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useEmployees } from '@/features/records/useRecords'
import { formatDateTime } from '@/lib/dates'

import {
  LAWFUL_BASES,
  PURGE_CONFIRMATION,
  consentState,
  consentTone,
  erasureTone,
  impactTone,
  isAwaitingDecision,
  isBreachTerminal,
  isExecutable,
  isRevocable,
  nextBreachStatuses,
  purgeConfirmed,
  purgeSummary,
  unverifiedTables,
  type BreachStatus,
  type BreachView,
  type ErasureView,
  type LawfulBasis,
  type PurgeReportView,
} from './complianceApi'
import {
  useAuditVerification,
  useBreaches,
  useCompleteBreachStep,
  useConsentStatus,
  useConsents,
  useErasures,
  useExecuteErasure,
  useOverdueBreachSteps,
  usePurge,
  useRateTables,
  useRecordConsent,
  useRetentionScan,
  useRevokeConsent,
  useSubmitErasure,
  useTransitionBreach,
  useUnverifiedRateTables,
  useVerifyErasureIdentity,
  useVerifyRateTable,
} from './useCompliance'

/**
 * Compliance board: what is unverified, what is late, and whether the log holds.
 *
 * Read-only. Deciding an erasure, purging a record or declaring a breach contained all
 * belong to a named human in the queue.
 */
export function ComplianceBoard() {
  const { t } = useTranslation()
  const breaches = useBreaches()
  const overdue = useOverdueBreachSteps()
  const tables = useRateTables()
  const unverified = useUnverifiedRateTables()
  const [checking, setChecking] = useState(false)
  const audit = useAuditVerification(checking)

  if (breaches.isLoading || tables.isLoading) {
    return <Skeleton className="h-40" />
  }

  const openBreaches = (breaches.data ?? []).filter((item) => !isBreachTerminal(item.status))
  const unverifiedList = unverified.data ?? unverifiedTables(tables.data ?? [])

  return (
    <section aria-labelledby="compliance-board" className="flex flex-col gap-5">
      <h2 id="compliance-board" className="text-ink-strong text-lg font-medium">
        {t('compliance.boardTitle')}
      </h2>

      <section aria-labelledby="compliance-rate-tables">
        <h3 id="compliance-rate-tables" className="text-ink-strong text-base font-medium">
          {t('compliance.unverifiedTablesTitle', { count: unverifiedList.length })}
        </h3>
        {unverifiedList.length === 0 ? (
          <EmptyState title={t('compliance.allTablesVerified')} />
        ) : (
          <ul className="mt-2 flex flex-col gap-2">
            {unverifiedList.map((table) => (
              <li key={table.id} className="border-line rounded-lg border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-ink-strong text-sm font-medium">{table.name}</p>
                    <p className="text-ink-muted text-xs">
                      {table.kind} · {table.jurisdiction} ·{' '}
                      {t('compliance.entryCount', {
                        count: table.entry_count,
                      })}
                    </p>
                  </div>
                  <StatusBadge
                    tone={table.usable ? 'waiting' : 'error'}
                    labelKey={table.usable ? 'compliance.unverified' : 'compliance.notUsable'}
                  />
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="compliance-breaches">
        <h3 id="compliance-breaches" className="text-ink-strong text-base font-medium">
          {t('compliance.openBreachesTitle', { count: openBreaches.length })}
        </h3>
        {openBreaches.length === 0 ? (
          <EmptyState title={t('compliance.noOpenBreaches')} />
        ) : (
          <ul className="mt-2 flex flex-col gap-2">
            {openBreaches.map((breach) => (
              <li key={breach.id} className="border-line rounded-lg border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-ink-strong text-sm font-medium">{breach.title}</p>
                    <p className="text-ink-muted text-xs">
                      {t('compliance.discoveredAt', {
                        date: formatDateTime(breach.discovered_at),
                      })}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge
                      tone={impactTone(breach.impact)}
                      labelKey={`compliance.impact.${breach.impact}`}
                    />
                    <StatusBadge
                      tone={breach.status === 'closed' ? 'done' : 'waiting'}
                      labelKey={`compliance.breachStatus.${breach.status}`}
                    />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="compliance-overdue">
        <h3 id="compliance-overdue" className="text-ink-strong text-base font-medium">
          {t('compliance.overdueStepsTitle', { count: (overdue.data ?? []).length })}
        </h3>
        {(overdue.data ?? []).length === 0 ? (
          <EmptyState title={t('compliance.noOverdueSteps')} />
        ) : (
          <ul className="mt-2 flex flex-col gap-2">
            {(overdue.data ?? []).map((row) => (
              <li
                key={`${row.incident_id}-${row.step.key}`}
                className="border-line rounded-lg border p-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-ink-strong text-sm font-medium">{row.incident_title}</p>
                    <p className="text-ink-muted text-xs">
                      {row.step.title} ·{' '}
                      {t('compliance.dueAt', {
                        date: formatDateTime(row.step.due_at),
                      })}
                    </p>
                  </div>
                  <StatusBadge tone="error" labelKey="compliance.overdue" />
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="compliance-audit">
        <h3 id="compliance-audit" className="text-ink-strong text-base font-medium">
          {t('compliance.auditTitle')}
        </h3>
        <p className="text-ink-muted mt-1 text-xs">{t('compliance.auditHint')}</p>
        <Button
          className="mt-2"
          size="sm"
          disabled={checking && audit.isFetching}
          onClick={() => setChecking(true)}
        >
          {audit.isFetching ? t('compliance.verifying') : t('compliance.verify')}
        </Button>
        {audit.data ? <AuditVerdict verdict={audit.data} /> : null}
        {audit.isError ? (
          <p role="alert" className="text-error mt-2 text-sm">
            {t('compliance.verifyFailed')}
          </p>
        ) : null}
      </section>
    </section>
  )
}

function AuditVerdict({
  verdict,
}: {
  verdict: {
    intact: boolean
    entry_count: number
    checked_by: string
    checked_at: string
    head_hash: string | null
    first_invalid_seq: number | null
  }
}) {
  const { t } = useTranslation()
  return (
    <div className="border-line mt-2 rounded-lg border p-3">
      <div className="flex items-center gap-2">
        <StatusBadge
          tone={verdict.intact ? 'done' : 'error'}
          labelKey={verdict.intact ? 'compliance.auditIntact' : 'compliance.auditBroken'}
        />
        <span className="text-ink-muted text-xs tabular-nums">
          {t('compliance.auditEntries', { count: verdict.entry_count })}
        </span>
      </div>
      <p className="text-ink-muted mt-1 text-xs">
        {t('compliance.auditCheckedBy', {
          who: verdict.checked_by,
          when: formatDateTime(verdict.checked_at),
        })}
      </p>
      {!verdict.intact && verdict.first_invalid_seq !== null ? (
        <p role="alert" className="text-error mt-1 text-xs">
          {t('compliance.firstInvalid', { seq: verdict.first_invalid_seq })}
        </p>
      ) : null}
    </div>
  )
}

/**
 * Compliance queue: breach containment steps, erasure requests, and rate-table
 * verification.
 *
 * An erasure decision is never made here. Submitting raises an approval; a named human
 * decides it in the approvals inbox, and only an approved request offers Execute.
 */
export function ComplianceQueue() {
  return (
    <div className="flex flex-col gap-6">
      <ConsentSection />
      <ErasureSection />
      <BreachSection />
      <RetentionSection />
    </div>
  )
}

function ErasureSection() {
  const { t } = useTranslation()
  const requests = useErasures()
  const submit = useSubmitErasure()
  const execute = useExecuteErasure()
  const verifyIdentity = useVerifyErasureIdentity()

  if (requests.isLoading) {
    return <Skeleton className="h-40" />
  }

  const list = requests.data ?? []
  const pending = list.filter((item) => isAwaitingDecision(item.status))
  const readyToExecute = list.filter((item) => isExecutable(item.status))

  return (
    <section aria-labelledby="compliance-erasures" className="flex flex-col gap-3">
      <h2 id="compliance-erasures" className="text-ink-strong text-lg font-medium">
        {t('compliance.erasuresTitle', { count: pending.length })}
      </h2>
      {pending.length === 0 ? (
        <EmptyState title={t('compliance.noPendingErasures')} />
      ) : (
        <ul className="flex flex-col gap-2">
          {pending.map((request) => (
            <ErasureRow
              key={request.id}
              request={request}
              onVerify={() => verifyIdentity.mutate({ requestId: request.id, method: 'documents' })}
              onSubmit={() => submit.mutate(request.id)}
              busy={submit.isPending || execute.isPending || verifyIdentity.isPending}
            />
          ))}
        </ul>
      )}

      {readyToExecute.length > 0 ? (
        <>
          <h3 className="text-ink-strong text-base font-medium">
            {t('compliance.approvedErasuresTitle', { count: readyToExecute.length })}
          </h3>
          <p className="text-ink-muted text-xs">{t('compliance.executeWarning')}</p>
          <ul className="flex flex-col gap-2">
            {readyToExecute.map((request) => (
              <ErasureRow
                key={request.id}
                request={request}
                onExecute={() => execute.mutate(request.id)}
                busy={execute.isPending}
              />
            ))}
          </ul>
        </>
      ) : null}

      {submit.isError || execute.isError || verifyIdentity.isError ? (
        <p role="alert" className="text-error text-sm">
          {t('compliance.erasureActionFailed')}
        </p>
      ) : null}
    </section>
  )
}

function ErasureRow({
  request,
  onVerify,
  onSubmit,
  onExecute,
  busy,
}: {
  request: ErasureView
  onVerify?: () => void
  onSubmit?: () => void
  onExecute?: () => void
  busy: boolean
}) {
  const { t } = useTranslation()
  return (
    <li className="border-line rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-ink-strong text-sm font-medium">{request.subject_kind}</p>
          <p className="text-ink-muted text-xs">
            {t('compliance.receivedAt', { date: formatDateTime(request.received_at) })}
          </p>
          <p className="text-ink-muted text-xs">{request.reason}</p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge
            tone={erasureTone(request.status)}
            labelKey={`compliance.erasureStatus.${request.status}`}
          />
          {onVerify ? (
            <Button size="sm" disabled={busy} onClick={onVerify}>
              {t('compliance.verifyIdentity')}
            </Button>
          ) : null}
          {onSubmit ? (
            <Button size="sm" disabled={busy} onClick={onSubmit}>
              {t('compliance.submitForApproval')}
            </Button>
          ) : null}
          {onExecute ? (
            <Button size="sm" variant="destructive" disabled={busy} onClick={onExecute}>
              {t('compliance.execute')}
            </Button>
          ) : null}
        </div>
      </div>
    </li>
  )
}

function BreachSection() {
  const { t } = useTranslation()
  const breaches = useBreaches()
  const transition = useTransitionBreach()
  const completeStep = useCompleteBreachStep()

  if (breaches.isLoading) {
    return <Skeleton className="h-40" />
  }

  const open = (breaches.data ?? []).filter((item) => !isBreachTerminal(item.status))
  if (open.length === 0) {
    return (
      <section aria-labelledby="compliance-breach-queue" className="flex flex-col gap-3">
        <h2 id="compliance-breach-queue" className="text-ink-strong text-lg font-medium">
          {t('compliance.breachQueueTitle')}
        </h2>
        <EmptyState title={t('compliance.noOpenBreaches')} />
      </section>
    )
  }

  return (
    <section aria-labelledby="compliance-breach-queue" className="flex flex-col gap-3">
      <h2 id="compliance-breach-queue" className="text-ink-strong text-lg font-medium">
        {t('compliance.breachQueueTitle', { count: open.length })}
      </h2>
      <ul className="flex flex-col gap-2">
        {open.map((breach) => (
          <BreachRow
            key={breach.id}
            breach={breach}
            busy={transition.isPending || completeStep.isPending}
            onTransition={(status) =>
              transition.mutate({ incidentId: breach.id, body: { status } })
            }
            onStep={(stepKey) =>
              completeStep.mutate({ incidentId: breach.id, stepKey, note: null })
            }
          />
        ))}
      </ul>
      {transition.isError || completeStep.isError ? (
        <p role="alert" className="text-error text-sm">
          {t('compliance.breachActionFailed')}
        </p>
      ) : null}
    </section>
  )
}

function BreachRow({
  breach,
  busy,
  onTransition,
  onStep,
}: {
  breach: BreachView
  busy: boolean
  onTransition: (status: BreachStatus) => void
  onStep: (stepKey: string) => void
}) {
  const { t } = useTranslation()
  const allowed = useMemo(() => nextBreachStatuses(breach.status), [breach.status])
  const outstanding = breach.steps.filter((step) => step.required && !step.completed)

  return (
    <li className="border-line rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-ink-strong text-sm font-medium">{breach.title}</p>
          <p className="text-ink-muted text-xs">{breach.template_name}</p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge
            tone={impactTone(breach.impact)}
            labelKey={`compliance.impact.${breach.impact}`}
          />
          <StatusBadge
            tone={breach.status === 'closed' ? 'done' : 'waiting'}
            labelKey={`compliance.breachStatus.${breach.status}`}
          />
          {allowed.map((status) => (
            <Button
              key={status}
              size="sm"
              disabled={busy}
              /**
               * Closing needs every required step done. The button is disabled with the
               * reason attached rather than offered and refused, because "close failed"
               * is not something an operator can act on.
               */
              title={
                status === 'closed' && outstanding.length > 0
                  ? t('compliance.closeBlockedBy', { count: outstanding.length })
                  : undefined
              }
              onClick={() => onTransition(status)}
            >
              {t(`compliance.moveTo.${status}`)}
            </Button>
          ))}
        </div>
      </div>

      {breach.steps.length > 0 ? (
        <ul className="mt-2 flex flex-col gap-1">
          {breach.steps.map((step) => (
            <li key={step.key} className="flex items-center justify-between gap-2">
              <span className="text-ink-muted text-xs">
                {step.title}
                {step.required ? '' : ` · ${t('compliance.optional')}`}
              </span>
              <span className="flex items-center gap-2">
                <StatusBadge
                  tone={step.completed ? 'done' : 'waiting'}
                  labelKey={step.completed ? 'compliance.stepDone' : 'compliance.stepPending'}
                />
                {!step.completed && step.required ? (
                  <Button size="sm" disabled={busy} onClick={() => onStep(step.key)}>
                    {t('compliance.completeStep')}
                  </Button>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  )
}

function RetentionSection() {
  const { t } = useTranslation()
  const [ran, setRan] = useState(false)
  const scan = useRetentionScan(ran)
  const tables = useRateTables()
  const verifyTable = useVerifyRateTable()
  const [sourceNote, setSourceNote] = useState<Record<string, string>>({})

  const unverified = unverifiedTables(tables.data ?? [])

  return (
    <section aria-labelledby="compliance-retention" className="flex flex-col gap-3">
      <h2 id="compliance-retention" className="text-ink-strong text-lg font-medium">
        {t('compliance.retentionTitle')}
      </h2>

      <div>
        <Button size="sm" disabled={scan.isFetching} onClick={() => setRan(true)}>
          {t('compliance.scanRetention')}
        </Button>
        <p className="text-ink-muted mt-1 text-xs">{t('compliance.scanHint')}</p>
        {scan.data ? (
          <ul className="text-ink-muted mt-2 flex flex-wrap gap-3 text-xs">
            <li>{t('compliance.tracked', { count: scan.data.tracked_count })}</li>
            <li>{t('compliance.due', { count: scan.data.due })}</li>
            <li>{t('compliance.held', { count: scan.data.held })}</li>
            <li>{t('compliance.uncovered', { count: scan.data.uncovered })}</li>
          </ul>
        ) : null}
      </div>

      <PurgePanel />
      <div>
        <h3 className="text-ink-strong text-base font-medium">
          {t('compliance.rateTableVerifyTitle', { count: unverified.length })}
        </h3>
        {unverified.length === 0 ? (
          <EmptyState title={t('compliance.allTablesVerified')} />
        ) : (
          <ul className="mt-2 flex flex-col gap-2">
            {unverified.map((table) => (
              <li key={table.id} className="border-line rounded-lg border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-ink-strong text-sm font-medium">{table.name}</p>
                  <span className="flex items-center gap-2">
                    <label className="sr-only" htmlFor={`source-${table.id}`}>
                      {t('compliance.sourceNoteLabel')}
                    </label>
                    <Input
                      id={`source-${table.id}`}
                      className="w-64"
                      placeholder={t('compliance.sourceNotePlaceholder')}
                      value={sourceNote[table.id] ?? ''}
                      onChange={(event) =>
                        setSourceNote((current) => ({
                          ...current,
                          [table.id]: event.target.value,
                        }))
                      }
                    />
                    <Button
                      size="sm"
                      disabled={verifyTable.isPending || (sourceNote[table.id] ?? '').trim() === ''}
                      /**
                       * Verifying without a source is how an unverified figure becomes a
                       * verified one on paper only, so the button stays disabled until
                       * the note names where the number came from.
                       */
                      onClick={() =>
                        verifyTable.mutate({
                          tableId: table.id,
                          body: { source_note: (sourceNote[table.id] ?? '').trim() },
                        })
                      }
                    >
                      {t('compliance.verifyTable')}
                    </Button>
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
        {verifyTable.isError ? (
          <p role="alert" className="text-error mt-2 text-xs">
            {t('compliance.verifyTableFailed')}
          </p>
        ) : null}
      </div>
    </section>
  )
}

/**
 * Purge: preview, then type the word, then run.
 *
 * The dry run and the real run are the same server path, so the report the operator reads
 * is produced by the code that deletes. A purge destroys records, so the real run is
 * gated on an explicit confirmation phrase rather than a second click on the same button
 * -- and the report stays on screen after it runs, because the outcome is the record of
 * what happened.
 */
function PurgePanel() {
  const { t } = useTranslation()
  const purge = usePurge()
  const [report, setReport] = useState<PurgeReportView | null>(null)
  const [confirmText, setConfirmText] = useState('')

  const summary = report ? purgeSummary(report) : null
  const ran = report !== null && !report.dry_run

  function run(dryRun: boolean) {
    purge.mutate(
      { dry_run: dryRun },
      {
        onSuccess: (data) => {
          setReport(data)
          if (!dryRun) {
            setConfirmText('')
          }
        },
      },
    )
  }

  return (
    <div className="border-line flex flex-col gap-2 rounded-lg border p-3">
      <h3 className="text-ink-strong text-base font-medium">{t('compliance.purgeTitle')}</h3>
      <p className="text-ink-muted text-xs">{t('compliance.purgeWarning')}</p>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" disabled={purge.isPending} onClick={() => run(true)}>
          {t('compliance.previewPurge')}
        </Button>
      </div>

      {summary && report ? (
        <div className="border-line rounded border p-2">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge
              tone={report.dry_run ? 'waiting' : 'done'}
              labelKey={report.dry_run ? 'compliance.dryRun' : 'compliance.realRun'}
            />
            <span className="text-ink-muted text-xs tabular-nums">
              {t('compliance.purgeCounts', {
                destroyed: summary.destroyed,
                spared: summary.spared,
                untouched: summary.stillPresent.length,
              })}
            </span>
          </div>
          {summary.stillPresent.length > 0 ? (
            <p className="text-ink-muted mt-1 text-xs">
              {t('compliance.stillPresent', { count: summary.stillPresent.length })}
            </p>
          ) : null}
        </div>
      ) : null}

      {report?.dry_run ? (
        <div className="flex flex-col gap-2">
          <label className="text-ink-muted text-xs" htmlFor="purge-confirm">
            {t('compliance.purgeConfirmLabel', { phrase: PURGE_CONFIRMATION })}
          </label>
          <Input
            id="purge-confirm"
            className="w-48"
            value={confirmText}
            onChange={(event) => setConfirmText(event.target.value)}
          />
          <Button
            className="self-start"
            size="sm"
            variant="destructive"
            disabled={purge.isPending || !purgeConfirmed(confirmText)}
            onClick={() => run(false)}
          >
            {t('compliance.runPurge')}
          </Button>
        </div>
      ) : null}

      {ran ? <p className="text-ink-muted text-xs">{t('compliance.purgeDone')}</p> : null}

      {purge.isError ? (
        <p role="alert" className="text-error text-sm">
          {t('compliance.purgeFailed')}
        </p>
      ) : null}
    </div>
  )
}

/**
 * Consent registry: what each person agreed to, what they refused, and what they
 * withdrew.
 *
 * A refusal is recorded, not merely absent -- `granted: false` is evidence too, and the
 * registry is what an audit reads. Recording is open to a person or an agent capturing a
 * form; withdrawing is human-only in the service and needs a reason.
 */
export function ConsentSection() {
  const { t } = useTranslation()
  const employees = useEmployees()
  const [subjectId, setSubjectId] = useState('')
  const consents = useConsents(subjectId === '' ? null : subjectId)
  const status = useConsentStatus(subjectId === '' ? null : subjectId, 'employee')
  const record = useRecordConsent()
  const revoke = useRevokeConsent()

  const [purpose, setPurpose] = useState('')
  const [basis, setBasis] = useState<LawfulBasis>('consent')
  const [granting, setGranting] = useState(true)
  const [revokingId, setRevokingId] = useState<string | null>(null)
  const [revokeReason, setRevokeReason] = useState('')

  const rows = consents.data ?? []
  const blankPurpose = purpose.trim() === ''

  return (
    <section aria-labelledby="compliance-consents" className="flex flex-col gap-3">
      <h2 id="compliance-consents" className="text-ink-strong text-lg font-medium">
        {t('compliance.consentsTitle')}
      </h2>
      <p className="text-ink-muted text-xs">{t('compliance.consentsHint')}</p>

      <label className="text-ink-muted text-xs" htmlFor="consent-subject">
        {t('compliance.subjectField')}
      </label>
      <select
        id="consent-subject"
        className="border-line w-full max-w-sm rounded border p-2 text-sm"
        value={subjectId}
        onChange={(event) => setSubjectId(event.target.value)}
      >
        <option value="">{t('compliance.subjectPlaceholder')}</option>
        {(employees.data ?? []).map((employee) => (
          <option key={employee.id} value={employee.id}>
            {employee.full_name}
          </option>
        ))}
      </select>

      {subjectId === '' ? null : (
        <>
          {status.data ? (
            <p className="text-ink-muted text-xs">
              {t('compliance.consentCounts', {
                active: status.data.active_purposes.length,
                total: status.data.records.length,
              })}
            </p>
          ) : null}

          {consents.isLoading ? (
            <Skeleton className="h-24" />
          ) : rows.length === 0 ? (
            <EmptyState title={t('compliance.noConsents')} />
          ) : (
            <ul className="flex flex-col gap-2">
              {rows.map((consent) => {
                const state = consentState(consent)
                return (
                  <li key={consent.id} className="border-line rounded-lg border p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <p className="text-ink-strong text-sm font-medium">{consent.purpose}</p>
                        <p className="text-ink-muted text-xs">
                          {t(`compliance.lawfulBasis.${consent.lawful_basis}`, {
                            defaultValue: consent.lawful_basis,
                          })}
                          {' · '}
                          {t('compliance.capturedBy', { who: consent.captured_by })}
                          {consent.policy_version ? ` · v${consent.policy_version}` : ''}
                        </p>
                        {consent.revoked_reason ? (
                          <p className="text-ink-muted mt-1 text-xs italic">
                            {t('compliance.revokedBecause', { reason: consent.revoked_reason })}
                          </p>
                        ) : null}
                      </div>
                      <div className="flex items-center gap-2">
                        <StatusBadge
                          tone={consentTone(state)}
                          labelKey={`compliance.consentState.${state}`}
                        />
                        {isRevocable(consent) && revokingId !== consent.id ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              setRevokingId(consent.id)
                              setRevokeReason('')
                            }}
                          >
                            {t('compliance.revoke')}
                          </Button>
                        ) : null}
                      </div>
                    </div>

                    {revokingId === consent.id ? (
                      <div className="mt-2 flex flex-col gap-2">
                        <label className="text-ink-muted text-xs" htmlFor={`revoke-${consent.id}`}>
                          {t('compliance.revokeReasonLabel')}
                        </label>
                        <textarea
                          id={`revoke-${consent.id}`}
                          className="border-line w-full rounded border p-2 text-sm"
                          rows={2}
                          value={revokeReason}
                          onChange={(event) => setRevokeReason(event.target.value)}
                        />
                        <div className="flex flex-wrap items-center gap-2">
                          <Button
                            size="sm"
                            variant="destructive"
                            disabled={revoke.isPending || revokeReason.trim() === ''}
                            /**
                             * Withdrawal is human-only on the server and the reason is
                             * mandatory: the record outlives the tool, and "revoked" with
                             * no why is not a record anybody can rely on.
                             */
                            onClick={() =>
                              revoke.mutate(
                                { consentId: consent.id, reason: revokeReason.trim() },
                                { onSuccess: () => setRevokingId(null) },
                              )
                            }
                          >
                            {t('compliance.confirmRevoke')}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setRevokingId(null)}>
                            {t('compliance.cancel')}
                          </Button>
                        </div>
                      </div>
                    ) : null}
                  </li>
                )
              })}
            </ul>
          )}

          <div className="border-line flex flex-col gap-2 rounded-lg border p-3">
            <h3 className="text-ink-strong text-sm font-medium">
              {t('compliance.recordConsentTitle')}
            </h3>
            <label className="text-ink-muted text-xs" htmlFor="consent-purpose">
              {t('compliance.purposeLabel')}
            </label>
            <Input
              id="consent-purpose"
              placeholder={t('compliance.purposePlaceholder')}
              value={purpose}
              onChange={(event) => setPurpose(event.target.value)}
            />
            <label className="text-ink-muted text-xs" htmlFor="consent-basis">
              {t('compliance.basisLabel')}
            </label>
            <select
              id="consent-basis"
              className="border-line w-full max-w-sm rounded border p-2 text-sm"
              value={basis}
              onChange={(event) => setBasis(event.target.value as LawfulBasis)}
            >
              {LAWFUL_BASES.map((item) => (
                <option key={item} value={item}>
                  {t(`compliance.lawfulBasis.${item}`, { defaultValue: item })}
                </option>
              ))}
            </select>
            <fieldset className="flex items-center gap-4">
              <legend className="text-ink-muted text-xs">{t('compliance.outcomeLabel')}</legend>
              <label className="flex items-center gap-1 text-sm">
                <input
                  type="radio"
                  name="consent-outcome"
                  checked={granting}
                  onChange={() => setGranting(true)}
                />
                {t('compliance.granted')}
              </label>
              <label className="flex items-center gap-1 text-sm">
                <input
                  type="radio"
                  name="consent-outcome"
                  checked={!granting}
                  onChange={() => setGranting(false)}
                />
                {t('compliance.refused')}
              </label>
            </fieldset>
            <p className="text-ink-muted text-xs">{t('compliance.refusalIsEvidence')}</p>
            <Button
              className="self-start"
              size="sm"
              disabled={record.isPending || blankPurpose}
              onClick={() =>
                record.mutate(
                  {
                    subject_kind: 'employee',
                    subject_id: subjectId,
                    purpose: purpose.trim(),
                    lawful_basis: basis,
                    granted: granting,
                    capture_method: 'manual',
                    policy_version: '1.0',
                  },
                  {
                    onSuccess: () => {
                      setPurpose('')
                      setGranting(true)
                    },
                  },
                )
              }
            >
              {t('compliance.recordConsent')}
            </Button>
          </div>
        </>
      )}

      {record.isError || revoke.isError ? (
        <p role="alert" className="text-error text-sm">
          {t('compliance.consentActionFailed')}
        </p>
      ) : null}
    </section>
  )
}
