import { useTranslation } from 'react-i18next'
import { useMemo, useState, type ReactNode } from 'react'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge } from '@/components/status/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

import {
  DEFAULT_EXPIRY_WINDOW_DAYS,
  activeContracts,
  bucketByExpiry,
  documentNeedsAttention,
  headcountByStatus,
  orgTree,
  type RecordsDocument,
  type RecordsEmployee,
} from './records'
import {
  useContracts,
  useDocuments,
  useEmployees,
  useOrgUnits,
  useVerifyDocument,
} from './useRecords'

/**
 * Records board: the org chart on the left, the people directory on the right.
 * Read-only by design — the queue room is where a human changes a document.
 */
export function RecordsBoard() {
  const { t } = useTranslation()
  const orgUnits = useOrgUnits()
  const employees = useEmployees()
  const [selectedUnit, setSelectedUnit] = useState<string | null>(null)

  const tree = useMemo(() => orgTree(orgUnits.data ?? []), [orgUnits.data])
  const directory = useMemo(() => {
    const all = employees.data ?? []
    return selectedUnit === null
      ? all
      : all.filter((employee) => employee.org_unit_id === selectedUnit)
  }, [employees.data, selectedUnit])

  return (
    <section aria-labelledby="records-board" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="records-board" className="text-ink-strong text-lg font-medium">
          {t('records.orgTitle')}
        </h2>
        <span className="text-2xs text-ink-muted">
          {t('records.headcountTotal', {
            count: (employees.data ?? []).length,
          })}
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section aria-labelledby="records-org" className="border-line rounded-lg border p-3">
          <h3 id="records-org" className="text-ink-strong text-sm font-medium">
            {t('records.orgChart')}
          </h3>
          {orgUnits.isLoading ? (
            <Skeleton className="mt-3 h-20 w-full" />
          ) : tree.length === 0 ? (
            <p className="text-2xs text-ink-muted mt-3">{t('records.noOrgUnits')}</p>
          ) : (
            <ul className="mt-3 flex flex-col gap-1">
              {tree.map((unit) => (
                <li key={unit.id}>
                  <button
                    type="button"
                    aria-pressed={selectedUnit === unit.id}
                    onClick={() => setSelectedUnit(selectedUnit === unit.id ? null : unit.id)}
                    className="border-line hover:border-accent flex w-full items-center justify-between gap-2 rounded-md border px-2 py-1.5 text-left"
                    style={{ paddingInlineStart: `${0.5 + unit.depth * 0.75}rem` }}
                  >
                    <span className="text-ink-strong truncate text-sm">{unit.name}</span>
                    <span className="text-2xs text-ink-muted font-mono tabular-nums">
                      {t('records.headcount', { count: unit.totalHeadcount })}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="records-directory" className="border-line rounded-lg border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id="records-directory" className="text-ink-strong text-sm font-medium">
              {t('records.directory')}
            </h3>
            {selectedUnit !== null ? (
              <Button size="xs" variant="ghost" onClick={() => setSelectedUnit(null)}>
                {t('records.clearFilter')}
              </Button>
            ) : null}
          </div>
          {employees.isLoading ? (
            <Skeleton className="mt-3 h-20 w-full" />
          ) : directory.length === 0 ? (
            <p className="text-2xs text-ink-muted mt-3">{t('records.noEmployees')}</p>
          ) : (
            <ul className="mt-3 flex flex-col gap-2">
              {directory.map((employee) => (
                <EmployeeRow key={employee.id} employee={employee} />
              ))}
            </ul>
          )}
        </section>
      </div>

      <RecordsSummary employees={employees.data ?? []} />
    </section>
  )
}

function EmployeeRow({ employee }: { employee: RecordsEmployee }) {
  const { t } = useTranslation()
  return (
    <li className="border-line flex items-center justify-between gap-2 border-b pb-2 last:border-b-0">
      <div className="flex min-w-0 flex-col">
        <span className="text-ink-strong truncate text-sm">{employee.full_name}</span>
        <span className="text-2xs text-ink-muted truncate">
          {employee.job_title ?? t('records.noJobTitle')}
        </span>
      </div>
      <div className="flex items-center gap-2">
        {employee.probation_end_date ? (
          <Badge variant="outline" className="text-2xs">
            {t('records.probation', { date: employee.probation_end_date })}
          </Badge>
        ) : null}
        <StatusBadge
          tone={employee.status === 'offboarded' ? 'error' : 'done'}
          labelKey={`records.status.${employee.status}`}
        />
      </div>
    </li>
  )
}

function RecordsSummary({ employees }: { employees: RecordsEmployee[] }) {
  const { t } = useTranslation()
  const contracts = useContracts()
  const documents = useDocuments()
  const counts = headcountByStatus(employees)
  const bucket = bucketByExpiry(documents.data ?? [])
  const contractsActive = activeContracts(contracts.data ?? []).length

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <SummaryTile
        label={t('records.summaryPeople')}
        value={t('records.headcount', { count: employees.length })}
        detail={Object.entries(counts).map(([status, count]) => (
          <span key={status}>
            {t(`records.status.${status}`)}: {count}
          </span>
        ))}
      />
      <SummaryTile
        label={t('records.summaryContracts')}
        value={String(contractsActive)}
        detail={t('records.contractsActive')}
      />
      <SummaryTile
        label={t('records.summaryDocuments')}
        value={String(bucket.documents.length)}
        detail={t('records.expirySummary', {
          overdue: bucket.overdue,
          soon: bucket.expiringSoon,
          days: DEFAULT_EXPIRY_WINDOW_DAYS,
        })}
      />
    </div>
  )
}

function SummaryTile({
  label,
  value,
  detail,
}: {
  label: string
  value: string
  detail: ReactNode
}) {
  return (
    <div className="border-line bg-surface flex flex-col gap-1 rounded-lg border p-3">
      <span className="text-2xs text-ink-muted">{label}</span>
      <span className="text-ink-strong font-mono text-lg tabular-nums">{value}</span>
      <span className="text-2xs text-ink-muted flex flex-wrap gap-x-2">{detail}</span>
    </div>
  )
}

export interface DocumentVaultProps {
  documents: RecordsDocument[]
  isLoading: boolean
}

/**
 * The expiry queue: documents that are expired, expiring soon, or waiting for a
 * human verdict. Verification is the only write, and it always names a person.
 */
export function DocumentVault({ documents, isLoading }: DocumentVaultProps) {
  const { t } = useTranslation()
  const verify = useVerifyDocument()
  const [verifier, setVerifier] = useState('')
  const [error, setError] = useState<string | null>(null)
  const bucket = bucketByExpiry(documents)

  function decide(documentId: string, approved: boolean) {
    if (verifier.trim() === '') {
      setError(t('records.errors.byRequired'))
      return
    }
    setError(null)
    void verify.mutate(
      { documentId, body: { verified_by: verifier.trim(), verified: approved } },
      {
        onError: () => setError(t('records.errors.failed')),
        onSuccess: (result) => {
          if (result.status === 403) {
            setError(t('records.errors.forbidden'))
          } else if (result.status >= 400) {
            setError(t('records.errors.failed'))
          }
        },
      },
    )
  }

  if (isLoading) {
    return <Skeleton className="h-24 w-full" />
  }

  if (bucket.documents.length === 0) {
    return <EmptyState title={t('records.noDocuments')} />
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {bucket.overdue > 0 ? <StatusBadge tone="error" labelKey="records.expiredCount" /> : null}
        {bucket.expiringSoon > 0 ? (
          <StatusBadge tone="waiting" labelKey="records.expiringSoon" />
        ) : null}
        <span className="text-2xs text-ink-muted">
          {t('records.expirySummary', {
            overdue: bucket.overdue,
            soon: bucket.expiringSoon,
            days: DEFAULT_EXPIRY_WINDOW_DAYS,
          })}
        </span>
      </div>

      <div className="flex flex-col gap-2">
        <label className="text-2xs text-ink-muted flex flex-col gap-1" htmlFor="records-verifier">
          {t('records.verifier')}
          <input
            id="records-verifier"
            className="border-line bg-surface text-ink-strong rounded-md border px-2 py-1 text-sm"
            value={verifier}
            placeholder={t('records.verifierPlaceholder')}
            onChange={(event) => setVerifier(event.target.value)}
          />
        </label>
        {error !== null ? (
          <p role="alert" className="text-2xs text-error">
            {error}
          </p>
        ) : null}
      </div>

      <ul className="flex flex-col gap-2">
        {bucket.documents.map((document) => (
          <li key={document.id} className="border-line bg-surface rounded-lg border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex min-w-0 flex-col">
                <span className="text-ink-strong truncate text-sm">
                  {t(`records.documentKinds.${document.kind}`)}
                </span>
                <span className="text-2xs text-ink-muted truncate">
                  {document.filename ?? document.storage_key}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-2xs text-ink-muted font-mono tabular-nums">
                  {expiryLabel(t, document)}
                </span>
                <StatusBadge
                  tone={
                    document.status === 'verified'
                      ? 'done'
                      : document.status === 'expired' || document.status === 'failed'
                        ? 'error'
                        : 'waiting'
                  }
                  labelKey={`records.documentStatuses.${document.status}`}
                />
              </div>
            </div>
            {documentNeedsAttention(document) ? (
              <div className="mt-2 flex gap-2">
                <Button size="xs" onClick={() => decide(document.id, true)}>
                  {t('records.verify')}
                </Button>
                <Button size="xs" variant="outline" onClick={() => decide(document.id, false)}>
                  {t('records.reject')}
                </Button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  )
}

type Translate = (key: string, options?: Record<string, string | number>) => string

function expiryLabel(t: Translate, document: RecordsDocument): string {
  const days = document.days_to_expiry
  if (days === null) {
    return t('records.noExpiry')
  }
  if (days < 0) {
    return t('records.expiredDays', { count: Math.abs(days) })
  }
  return t('records.expiresInDays', { count: days })
}

/** The Records queue room: the expiry queue the operator works through. */
export function RecordsQueue() {
  const { t } = useTranslation()
  const documents = useDocuments({ expiringWithinDays: DEFAULT_EXPIRY_WINDOW_DAYS })

  return (
    <section aria-labelledby="records-vault" className="flex flex-col gap-3">
      <h2 id="records-vault" className="text-ink-strong text-lg font-medium">
        {t('records.vaultTitle')}
      </h2>
      <p className="text-2xs text-ink-muted">{t('records.vaultHint')}</p>
      <DocumentVault documents={documents.data ?? []} isLoading={documents.isLoading} />
    </section>
  )
}
