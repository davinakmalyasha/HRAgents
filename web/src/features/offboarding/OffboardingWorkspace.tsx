import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge } from '@/components/status/StatusBadge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate } from '@/lib/dates'
import { useEmployees } from '@/features/records/useRecords'

import {
  blockingAssets,
  canFinalise,
  finalisationBlockers,
  outstandingRequiredSteps,
  type AssetView,
  type PlanView,
  type StepView,
} from './offboardingApi'
import {
  useCompleteOffboardingStep,
  useDefaultOffboardingTemplate,
  useFinaliseOffboarding,
  useMarkAssetMissing,
  useOffboardingAssets,
  useOffboardingPlans,
  useReturnAsset,
  useStartOffboarding,
  useWaiveOffboardingStep,
} from './useOffboarding'

/**
 * Offboarding board: who is leaving, when, and what is left to clear.
 *
 * Read-only. Completion, waivers and asset returns are in the queue, because each of them
 * is a consequential act that needs a named human and, for a waiver, a recorded reason.
 */
export function OffboardingBoard() {
  const { t } = useTranslation()
  const plans = useOffboardingPlans()
  const employees = useEmployees()

  const names = useMemo(() => {
    const map = new Map<string, string>()
    for (const employee of employees.data ?? []) {
      map.set(employee.id, employee.full_name)
    }
    return map
  }, [employees.data])

  if (plans.isLoading) {
    return <Skeleton className="h-40" />
  }

  const list = plans.data ?? []
  if (list.length === 0) {
    return <EmptyState title={t('offboarding.boardEmpty')} />
  }

  return (
    <section aria-labelledby="offboarding-board" className="flex flex-col gap-4">
      <h2 id="offboarding-board" className="text-ink-strong text-lg font-medium">
        {t('offboarding.boardTitle')}
      </h2>
      <ul className="flex flex-col gap-2">
        {list.map((plan) => (
          <li key={plan.id} className="border-line rounded-lg border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-ink-strong font-medium">
                  {names.get(plan.employee_id) ?? plan.employee_id}
                </p>
                <p className="text-ink-muted text-sm">
                  {plan.reason} &middot;{' '}
                  {t('offboarding.lastDay', { date: formatDate(plan.last_working_day) })}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-ink-muted text-xs tabular-nums">
                  {t('offboarding.progress', {
                    percent: Math.round(plan.progress * 100),
                  })}
                </span>
                <StatusBadge
                  tone={plan.is_complete ? 'done' : 'waiting'}
                  labelKey={
                    plan.is_complete ? 'offboarding.statusComplete' : 'offboarding.statusOpen'
                  }
                />
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

/**
 * Offboarding queue: one departing employee's checklist, their assets, and the actions.
 *
 * Waiving is offered with an explicit confirmation, because it is the only action here
 * that can skip something the law requires -- and the server demands a reason for it, so
 * a waiver that skips a required step is always attributable to a named human.
 */
export function OffboardingQueue() {
  const { t } = useTranslation()
  const plans = useOffboardingPlans()
  const employees = useEmployees()
  const [selected, setSelected] = useState<string | null>(null)

  const list = plans.data ?? []
  const chosen = selected ?? list[0]?.id ?? null
  const plan = list.find((item) => item.id === chosen) ?? null

  const names = useMemo(() => {
    const map = new Map<string, string>()
    for (const employee of employees.data ?? []) {
      map.set(employee.id, employee.full_name)
    }
    return map
  }, [employees.data])

  if (plans.isLoading) {
    return <Skeleton className="h-40" />
  }
  if (list.length === 0) {
    return (
      <section aria-labelledby="offboarding-queue" className="flex flex-col gap-3">
        <h2 id="offboarding-queue" className="text-ink-strong text-lg font-medium">
          {t('offboarding.queueTitle')}
        </h2>
        <EmptyState title={t('offboarding.queueEmpty')} />
        <StartOffboardingForm />
      </section>
    )
  }

  return (
    <section aria-labelledby="offboarding-queue" className="flex flex-col gap-4">
      <h2 id="offboarding-queue" className="text-ink-strong text-lg font-medium">
        {t('offboarding.queueTitle')}
      </h2>

      <label className="flex flex-col text-xs" htmlFor="offboarding-plan">
        {t('offboarding.employee')}
        <select
          id="offboarding-plan"
          className="border-line rounded px-2 py-1"
          value={chosen ?? ''}
          onChange={(event) => setSelected(event.target.value)}
        >
          {list.map((option) => (
            <option key={option.id} value={option.id}>
              {names.get(option.employee_id) ?? option.employee_id} —{' '}
              {formatDate(option.last_working_day)}
            </option>
          ))}
        </select>
      </label>

      {plan ? (
        <PlanDetail plan={plan} employeeName={names.get(plan.employee_id) ?? plan.employee_id} />
      ) : null}
    </section>
  )
}

function PlanDetail({ plan, employeeName }: { plan: PlanView; employeeName: string }) {
  const { t } = useTranslation()
  const assets = useOffboardingAssets(plan.employee_id)
  const complete = useCompleteOffboardingStep()
  const waive = useWaiveOffboardingStep()
  const finalise = useFinaliseOffboarding()
  const outstanding = outstandingRequiredSteps(plan)
  const blockers = finalisationBlockers(plan, assets.data ?? [])
  const busy = complete.isPending || waive.isPending || finalise.isPending

  return (
    <div className="flex flex-col gap-4">
      <h3 className="text-ink-strong text-base font-medium">{employeeName}</h3>

      <StepList
        steps={plan.steps}
        busy={busy}
        onComplete={(step) => complete.mutate({ planId: plan.id, stepKey: step.key })}
        onWaive={(step) =>
          waive.mutate({
            planId: plan.id,
            stepKey: step.key,
            reason: t('offboarding.defaultWaiveReason'),
          })
        }
      />

      <AssetPanel employeeId={plan.employee_id} assets={assets.data ?? []} />

      <div className="flex flex-wrap items-center gap-2">
        <Button
          disabled={busy || !canFinalise(plan, assets.data ?? [])}
          title={
            blockers.length > 0
              ? t('offboarding.blockedBy', { reasons: blockers.join(' + ') })
              : undefined
          }
          onClick={() => finalise.mutate(plan.id)}
        >
          {t('offboarding.finalise')}
        </Button>
        {outstanding.length > 0 ? (
          <span className="text-ink-muted text-xs">
            {t('offboarding.outstanding', { count: outstanding.length })}
          </span>
        ) : null}
      </div>

      {waive.isError || finalise.isError ? (
        <p role="alert" className="text-error text-sm">
          {t('offboarding.actionFailed')}
        </p>
      ) : null}
    </div>
  )
}

function StepList({
  steps,
  busy,
  onComplete,
  onWaive,
}: {
  steps: StepView[]
  busy: boolean
  onComplete: (step: StepView) => void
  onWaive: (step: StepView) => void
}) {
  const { t } = useTranslation()
  return (
    <ul className="flex flex-col gap-2">
      {steps.map((step) => (
        <li key={step.key} className="border-line rounded-lg border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-ink-strong text-sm font-medium">{step.title}</p>
              <p className="text-ink-muted text-xs">
                {step.required ? t('offboarding.required') : t('offboarding.optional')}
                {step.due_on ? ` · ${t('offboarding.due', { date: formatDate(step.due_on) })}` : ''}
              </p>
              {step.note ? <p className="text-ink-muted mt-1 text-xs italic">{step.note}</p> : null}
            </div>
            <div className="flex items-center gap-2">
              <StatusBadge tone={toneForStep(step)} labelKey={`offboarding.step.${step.status}`} />
              {step.status !== 'done' && step.status !== 'waived' ? (
                <>
                  <Button size="sm" disabled={busy} onClick={() => onComplete(step)}>
                    {t('offboarding.complete')}
                  </Button>
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => onWaive(step)}>
                    {t('offboarding.waive')}
                  </Button>
                </>
              ) : null}
            </div>
          </div>
        </li>
      ))}
    </ul>
  )
}

/**
 * Assets, and which ones still block clearance.
 *
 * `blocks_clearance` is read from the server rather than derived, because "returned",
 * "missing" and "written off" clear an asset by different routes and only the server knows
 * which applies to which.
 */
function AssetPanel({ employeeId, assets }: { employeeId: string; assets: AssetView[] }) {
  const { t } = useTranslation()
  const returnAsset = useReturnAsset()
  const markMissing = useMarkAssetMissing()
  const outstanding = blockingAssets(assets)

  return (
    <section aria-labelledby="offboarding-assets" className="flex flex-col gap-2">
      <h4 id="offboarding-assets" className="text-ink-strong text-base font-medium">
        {t('offboarding.assetsTitle')}
        {outstanding.length > 0 ? (
          <span className="text-ink-muted text-sm"> ({outstanding.length})</span>
        ) : null}
      </h4>

      {assets.length === 0 ? (
        <EmptyState title={t('offboarding.assetsEmpty')} />
      ) : (
        <ul className="flex flex-col gap-2">
          {assets.map((asset) => (
            <li key={asset.id} className="border-line rounded-lg border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-ink-strong text-sm font-medium">{asset.name}</p>
                  <p className="text-ink-muted text-xs">
                    {asset.category}
                    {asset.asset_code ? ` · ${asset.asset_code}` : ''}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge
                    tone={asset.blocks_clearance ? 'error' : 'done'}
                    labelKey={
                      asset.blocks_clearance
                        ? 'offboarding.assetOutstanding'
                        : 'offboarding.assetCleared'
                    }
                  />
                  {asset.blocks_clearance ? (
                    <>
                      <Button
                        size="sm"
                        disabled={returnAsset.isPending}
                        onClick={() => returnAsset.mutate(asset.id)}
                      >
                        {t('offboarding.assetReturn')}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={markMissing.isPending}
                        onClick={() =>
                          markMissing.mutate({
                            assetId: asset.id,
                            note: t('offboarding.missingNote'),
                          })
                        }
                      >
                        {t('offboarding.assetMissing')}
                      </Button>
                    </>
                  ) : null}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="sr-only">{employeeId}</p>
    </section>
  )
}

function StartOffboardingForm() {
  const { t } = useTranslation()
  const employees = useEmployees()
  const templates = useDefaultOffboardingTemplate()
  const start = useStartOffboarding()
  const [employeeId, setEmployeeId] = useState('')
  const [lastDay, setLastDay] = useState('')

  return (
    <form
      className="border-line flex flex-wrap items-end gap-2 rounded-lg border p-3"
      onSubmit={(event) => {
        event.preventDefault()
        start.mutate({
          employee_id: employeeId,
          last_working_day: lastDay,
          reason: 'resignation',
          template_id: templates.data?.id ?? null,
        })
      }}
    >
      <label className="flex flex-col text-xs" htmlFor="offboarding-employee">
        {t('offboarding.employee')}
        <select
          id="offboarding-employee"
          className="border-line rounded px-2 py-1"
          value={employeeId}
          onChange={(event) => setEmployeeId(event.target.value)}
          required
        >
          <option value="">—</option>
          {(employees.data ?? []).map((employee) => (
            <option key={employee.id} value={employee.id}>
              {employee.full_name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col text-xs" htmlFor="offboarding-lastday">
        {t('offboarding.lastDayField')}
        <input
          id="offboarding-lastday"
          className="border-line rounded px-2 py-1"
          type="date"
          value={lastDay}
          onChange={(event) => setLastDay(event.target.value)}
          required
        />
      </label>
      <Button type="submit" disabled={start.isPending || employeeId === '' || lastDay === ''}>
        {t('offboarding.start')}
      </Button>
    </form>
  )
}

function toneForStep(step: StepView): 'waiting' | 'error' | 'done' {
  if (step.status === 'done') return 'done'
  if (step.status === 'blocked') return 'error'
  if (step.status === 'waived') return 'error'
  return 'waiting'
}
