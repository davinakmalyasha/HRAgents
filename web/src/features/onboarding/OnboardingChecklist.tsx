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

import { LinkDocumentDialog } from './LinkDocumentDialog'
import { StepActionDialog, type StepActionMode } from './StepActionDialog'
import {
  STEP_STATUS_TONES,
  boardOrder,
  checklistOrder,
  isOverdue,
  needsDocument,
  progressPercent,
  type OnboardingPlan,
  type OnboardingStep,
} from './onboarding'
import { useDocumentStatus, useEmployees, useOnboardingPlans } from './useOnboarding'

interface DialogTarget {
  mode: StepActionMode
  step: OnboardingStep
}

function PlanPicker({
  plans,
  selected,
}: {
  plans: OnboardingPlan[]
  selected: OnboardingPlan | undefined
}) {
  const { t } = useTranslation()
  const [, setSearchParams] = useSearchParams()

  return (
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor="onboarding-plan-picker" className="text-ink-strong text-xs font-medium">
        {t('onboarding.checklist.pickPlan')}
      </label>
      <select
        id="onboarding-plan-picker"
        value={selected?.id ?? ''}
        onChange={(event) => setSearchParams({ room: 'queue', plan: event.target.value })}
        className="border-line bg-surface text-ink h-9 rounded-md border px-2 text-sm"
      >
        <option value="">{t('onboarding.checklist.pickPlanPlaceholder')}</option>
        {plans.map((plan) => (
          <option key={plan.id} value={plan.id}>
            {plan.template_name} · {progressPercent(plan)}%
          </option>
        ))}
      </select>
    </div>
  )
}

function StepRow({
  planId,
  step,
  onAction,
  onLink,
}: {
  planId: string
  step: OnboardingStep
  onAction: (target: DialogTarget) => void
  onLink: (step: OnboardingStep) => void
}) {
  const { t } = useTranslation()
  const documentStatus = useDocumentStatus(planId)
  const finished = step.status === 'done' || step.status === 'waived'
  const status = documentStatus.data?.[step.key]
  const missingDocument = needsDocument(step) && step.linked_document_id === null

  return (
    <li className="flex flex-col gap-1.5 px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="text-ink-strong truncate text-xs font-medium">{step.title}</span>
          <StatusBadge
            tone={STEP_STATUS_TONES[step.status]}
            labelKey={`onboarding.stepStatuses.${step.status}`}
          />
          {isOverdue(step) ? <StatusBadge tone="error" labelKey="onboarding.overdue" /> : null}
          {step.requires_human_signoff ? (
            <Badge variant="outline" className="text-2xs">
              {t('onboarding.requiresSignoff')}
            </Badge>
          ) : null}
        </div>
        <span className="text-2xs text-ink-muted">
          {t(`onboarding.stepKinds.${step.kind}`)} · {t(`onboarding.roles.${step.assignee_role}`)}
        </span>
      </div>

      <div className="text-2xs text-ink-muted flex flex-wrap items-center gap-2">
        {step.due_on === null ? null : (
          <span>{t('onboarding.due', { date: formatDate(step.due_on) })}</span>
        )}
        {step.document_kind === null ? null : (
          <span>
            {t('onboarding.wantsDocument', {
              kind: t(`onboarding.documentKinds.${step.document_kind}`),
            })}
          </span>
        )}
        {status === undefined ? null : <span>{t(`onboarding.documentStatuses.${status}`)}</span>}
        {step.linked_document_id === null ? null : (
          <span className="font-mono">{step.linked_document_id.slice(0, 8)}</span>
        )}
      </div>

      {finished ? null : (
        <div className="flex flex-wrap items-center gap-2">
          {missingDocument ? (
            <Button size="xs" variant="outline" onClick={() => onLink(step)}>
              {t('onboarding.actions.linkDocument')}
            </Button>
          ) : null}
          <Button size="xs" onClick={() => onAction({ mode: 'complete', step })}>
            {t('onboarding.actions.complete')}
          </Button>
          {step.required ? null : (
            <Button size="xs" variant="outline" onClick={() => onAction({ mode: 'waive', step })}>
              {t('onboarding.actions.waive')}
            </Button>
          )}
        </div>
      )}
    </li>
  )
}

/**
 * The checklist room: one plan at a time, ordered by what needs a human now.
 * Completing, waiving, and linking a document all record a named human; a
 * required step cannot be waived here (and the server would refuse it anyway).
 */
export function OnboardingChecklist() {
  const { t } = useTranslation()
  const [searchParams] = useSearchParams()
  const plansQuery = useOnboardingPlans(true)
  const employees = useEmployees(false)
  const [action, setAction] = useState<DialogTarget | null>(null)
  const [linkTarget, setLinkTarget] = useState<OnboardingStep | null>(null)

  const planId = searchParams.get('plan') ?? ''
  const plans = boardOrder(plansQuery.data ?? [])
  const plan = plans.find((item) => item.id === planId)
  const names = new Map((employees.data ?? []).map((employee) => [employee.id, employee.full_name]))
  const steps = plan === undefined ? [] : checklistOrder(plan.steps)

  if (plansQuery.isLoading) {
    return <Skeleton className="h-32 w-full" />
  }

  return (
    <section aria-labelledby="onboarding-checklist" className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h2 id="onboarding-checklist" className="text-ink-strong text-lg font-medium">
          {t('onboarding.checklist.title')}
        </h2>
        <p className="text-2xs text-ink-muted">{t('onboarding.checklist.hint')}</p>
      </div>

      <PlanPicker plans={plans} selected={plan} />

      {plan === undefined ? (
        <EmptyState title={t('onboarding.checklist.empty')} />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-ink-strong text-sm font-medium">
                {names.get(plan.employee_id) ?? plan.employee_id}
              </span>
              <span className="text-2xs text-ink-muted font-mono tabular-nums">
                {progressPercent(plan)}%
              </span>
            </div>
            <Progress
              value={progressPercent(plan)}
              aria-label={t('onboarding.progressLabel')}
              className="h-1.5"
            />
          </div>

          {plan.blockers.length > 0 ? (
            <p className="text-error text-2xs flex items-center gap-1">
              <span aria-hidden="true">●</span>
              {t('onboarding.blockerNotice', { count: plan.blockers.length })}
            </p>
          ) : null}

          <ul className="divide-line border-line flex flex-col divide-y rounded-lg border">
            {steps.map((step) => (
              <StepRow
                key={step.key}
                planId={plan.id}
                step={step}
                onAction={setAction}
                onLink={setLinkTarget}
              />
            ))}
          </ul>
        </div>
      )}

      {plan !== undefined && action !== null ? (
        <StepActionDialog
          key={`${action.mode}-${action.step.key}`}
          planId={plan.id}
          step={action.step}
          mode={action.mode}
          open
          onOpenChange={(open) => {
            if (!open) {
              setAction(null)
            }
          }}
          onDone={() => setAction(null)}
        />
      ) : null}

      {plan !== undefined && linkTarget !== null ? (
        <LinkDocumentDialog
          key={`link-${linkTarget.key}`}
          planId={plan.id}
          employeeId={plan.employee_id}
          step={linkTarget}
          open
          onOpenChange={(open) => {
            if (!open) {
              setLinkTarget(null)
            }
          }}
          onDone={() => setLinkTarget(null)}
        />
      ) : null}
    </section>
  )
}
