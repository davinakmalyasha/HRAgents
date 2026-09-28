import { useTranslation } from 'react-i18next'
import { useState } from 'react'
import { useSearchParams } from 'react-router'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge } from '@/components/status/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate } from '@/lib/dates'

import { boardOrder, progressPercent, type OnboardingPlan } from './onboarding'
import { StartPlanDialog } from './StartPlanDialog'
import { useEmployees, useOnboardingPlans } from './useOnboarding'

function PlanCard({
  plan,
  hireName,
  onOpen,
}: {
  plan: OnboardingPlan
  hireName: string
  onOpen: () => void
}) {
  const { t } = useTranslation()
  const percent = progressPercent(plan)
  const openSteps = plan.steps.filter(
    (step) => step.status !== 'done' && step.status !== 'waived',
  ).length
  const overdue = plan.steps.filter((step) => step.is_overdue).length

  return (
    <li className="border-line bg-surface flex flex-col gap-2.5 rounded-lg border p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col">
          <span className="text-ink-strong truncate text-sm font-medium">{hireName}</span>
          <span className="text-ink-muted text-2xs truncate">{plan.template_name}</span>
        </div>
        {plan.is_complete ? (
          <StatusBadge tone="done" labelKey="onboarding.planComplete" />
        ) : plan.blockers.length > 0 ? (
          <StatusBadge tone="error" labelKey="onboarding.blocked" />
        ) : overdue > 0 ? (
          <StatusBadge tone="error" labelKey="onboarding.overdue" />
        ) : (
          <StatusBadge tone="waiting" labelKey="onboarding.inProgress" />
        )}
      </div>

      <div className="flex flex-col gap-1">
        <Progress value={percent} aria-label={t('onboarding.progressLabel')} className="h-1.5" />
        <div className="text-2xs text-ink-muted flex items-center justify-between">
          <span className="font-mono tabular-nums">{percent}%</span>
          <span>{t('onboarding.openSteps', { count: openSteps })}</span>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {plan.blockers.length > 0 ? (
          <Badge variant="outline" className="text-2xs">
            {t('onboarding.blockerCount', { count: plan.blockers.length })}
          </Badge>
        ) : null}
        <span className="text-2xs text-ink-muted">
          {t('onboarding.startedAt', { date: formatDate(plan.started_at) })}
        </span>
        <Button size="xs" variant="outline" onClick={onOpen}>
          {t('onboarding.openChecklist')}
        </Button>
      </div>
    </li>
  )
}

/**
 * Active onboardings as a board: blocked and overdue plans first, complete ones
 * last. Starting a plan is a human action (a named creator, a template, and
 * optionally a hire created in the same flow).
 */
export function OnboardingBoard() {
  const { t } = useTranslation()
  const [, setSearchParams] = useSearchParams()
  const plans = useOnboardingPlans(true)
  const employees = useEmployees(false)
  const [starting, setStarting] = useState(false)

  const items = boardOrder(plans.data ?? [])
  const names = new Map((employees.data ?? []).map((employee) => [employee.id, employee.full_name]))

  function openChecklist(planId: string) {
    setSearchParams({ room: 'queue', plan: planId })
  }

  return (
    <section aria-labelledby="onboarding-board" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="onboarding-board" className="text-ink-strong text-lg font-medium">
          {t('onboarding.plansTitle')}
        </h2>
        <Button size="sm" onClick={() => setStarting(true)}>
          {t('onboarding.startPlan')}
        </Button>
      </div>
      <p className="text-2xs text-ink-muted">{t('onboarding.boardHint')}</p>

      {plans.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : items.length === 0 ? (
        <EmptyState title={t('onboarding.emptyPlans')} />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {items.map((plan) => (
            <PlanCard
              key={plan.id}
              plan={plan}
              hireName={names.get(plan.employee_id) ?? plan.employee_id.slice(0, 8)}
              onOpen={() => openChecklist(plan.id)}
            />
          ))}
        </ul>
      )}

      <StartPlanDialog
        open={starting}
        onOpenChange={(open) => {
          if (!open) {
            setStarting(false)
          }
        }}
      />
    </section>
  )
}
