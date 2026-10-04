import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useState, type FormEvent } from 'react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { problemMessage } from '@/lib/problem'

import { completeStep, waiveStep, type PlanResult } from './onboardingApi'
import type { OnboardingStep } from './onboarding'

export type StepActionMode = 'complete' | 'waive'

function errorFor(status: number, t: (key: string) => string): string {
  return problemMessage(status, undefined, t, 'onboarding', {
    overrides: (code) => (code === 404 ? t('onboarding.errors.planNotFound') : null),
  })
}

/**
 * Complete or waive a checklist step. Both require a named human; a waiver
 * additionally requires a reason, so "we skipped this" is always attributable.
 */
export function StepActionDialog({
  planId,
  step,
  mode,
  open,
  onOpenChange,
  onDone,
}: {
  planId: string
  step: OnboardingStep
  mode: StepActionMode
  open: boolean
  onOpenChange: (open: boolean) => void
  onDone: (result: PlanResult) => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function close(next: boolean) {
    if (!next) {
      setProblem(null)
    }
    onOpenChange(next)
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (mode === 'waive' && reason.trim() === '') {
      setProblem(t('onboarding.errors.reasonRequired'))
      return
    }
    setProblem(null)
    setBusy(true)

    const result =
      mode === 'complete'
        ? await completeStep(planId, step.key, {
            note: note.trim() === '' ? null : note.trim(),
          })
        : await waiveStep(planId, step.key, { reason: reason.trim() })
    setBusy(false)

    if (result.status === 200 && result.plan !== undefined) {
      await queryClient.invalidateQueries({ queryKey: ['onboarding'] })
      close(false)
      onDone(result)
      return
    }
    setProblem(errorFor(result.status, t))
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {mode === 'complete'
              ? t('onboarding.actions.completeTitle')
              : t('onboarding.actions.waiveTitle')}
          </DialogTitle>
          <DialogDescription>
            {step.title} ·{' '}
            {mode === 'complete'
              ? t('onboarding.actions.completeHint')
              : t('onboarding.actions.waiveHint')}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-4">
          {problem !== null ? (
            <p role="alert" className="text-error flex items-center gap-1 text-xs">
              <span aria-hidden="true">●</span>
              {problem}
            </p>
          ) : null}

          {step.required ? (
            <p className="text-2xs text-ink-muted">{t('onboarding.actions.requiredStepNotice')}</p>
          ) : null}

          {mode === 'waive' ? (
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="onboarding-step-reason"
                className="text-ink-strong text-xs font-medium"
              >
                {t('onboarding.fields.reason')}
              </label>
              <Textarea
                id="onboarding-step-reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                rows={3}
              />
              <span className="text-2xs text-ink-muted">{t('onboarding.fields.reasonHint')}</span>
            </div>
          ) : (
            <div className="flex flex-col gap-1.5">
              <label htmlFor="onboarding-step-note" className="text-ink-strong text-xs font-medium">
                {t('onboarding.fields.note')}
              </label>
              <Textarea
                id="onboarding-step-note"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={3}
              />
            </div>
          )}

          <DialogFooter>
            <Button type="submit" size="sm" disabled={busy}>
              {mode === 'complete'
                ? t('onboarding.actions.confirmComplete')
                : t('onboarding.actions.confirmWaive')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
