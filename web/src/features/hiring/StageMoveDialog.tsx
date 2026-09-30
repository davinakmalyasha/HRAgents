import { useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'

import { OverrideDialog } from './OverrideDialog'
import { moveStage } from './hiringApi'
import {
  shortId,
  type ApplicationStatus,
  type ApplicationSummary,
  type PipelineStage,
} from './pipeline'
import { useEvaluation } from './useHiring'

type Mode = 'move' | 'choice'
type Phase = Mode | 'withdraw'

const fieldClass = 'flex flex-col gap-1.5'
const labelClass = 'text-xs font-medium text-ink-strong'

/**
 * One dialog for every board drop the server allows a human to request:
 *
 * - `move` — a gated/status move needs a reason; the actor is the
 *   authenticated principal, so the user is never asked to spell their name.
 * - `choice` — closing is two different acts: withdraw (reason) or record the
 *   rejection sign-off through the existing override flow — the stage endpoint
 *   never writes `rejected` itself.
 *
 * Mounted fresh per drop (parent keys it), so state starts clean.
 */
export function StageMoveDialog({
  application,
  mode,
  target,
  targetStage,
  open,
  onOpenChange,
}: {
  application: ApplicationSummary
  mode: Mode
  target: ApplicationStatus | null
  targetStage: PipelineStage
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [phase, setPhase] = useState<Phase>(mode)
  const [overrideOpen, setOverrideOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const evaluation = useEvaluation(
    mode === 'choice' && open ? application.application_id : undefined,
  )

  const candidateLabel = shortId(application.candidate_id)

  function close(next: boolean) {
    if (!next) {
      setProblem(null)
    }
    onOpenChange(next)
  }

  function errorFor(status: number, detail?: string): string {
    if (status === 409) {
      if (detail?.includes('rejection sign-off')) {
        return t('board.errors.needSignoff')
      }
      if (detail?.includes('scheduling is gated')) {
        return t('board.errors.needScheduling')
      }
      if (detail?.includes('worker') || detail?.includes('system-owned')) {
        return t('board.systemOwned')
      }
      if (detail?.includes('already')) {
        return t('board.errors.noop')
      }
      return t('board.errors.conflict')
    }
    if (status === 403) {
      return t('board.errors.forbidden')
    }
    if (status === 404) {
      return t('board.errors.notFound')
    }
    return t('board.errors.failed')
  }

  function validate(): boolean {
    const problems: string[] = []
    if (reason.trim() === '') {
      problems.push(t('board.errors.reasonRequired'))
    }
    if (problems.length > 0) {
      setProblem(problems[0])
      return false
    }
    return true
  }

  async function submitMove(nextTarget: ApplicationStatus) {
    if (!validate()) {
      return
    }
    setProblem(null)
    setBusy(true)
    const result = await moveStage(application.application_id, {
      target: nextTarget,
      reason: reason.trim(),
    })
    setBusy(false)
    if (result.status === 200) {
      await queryClient.invalidateQueries({ queryKey: ['applications'] })
      close(false)
      return
    }
    setProblem(errorFor(result.status, result.detail))
  }

  function startSignoff() {
    if (evaluation.isLoading) {
      return
    }
    if (evaluation.data === null || evaluation.data === undefined) {
      setProblem(t('board.errors.notEvaluated'))
      return
    }
    setOverrideOpen(true)
  }

  // The sign-off is the existing override flow: one modal at a time.
  if (phase === 'choice' && overrideOpen && evaluation.data != null) {
    const contextLine = `${t('hiring.score')}: ${evaluation.data.s_tech.toFixed(2)} · ${evaluation.data.policy.decision}`
    return (
      <OverrideDialog
        evaluationId={evaluation.data.id}
        candidateLabel={candidateLabel}
        contextLine={contextLine}
        open
        onOpenChange={(next) => {
          if (!next) {
            setOverrideOpen(false)
            onOpenChange(false)
          }
        }}
      />
    )
  }

  if (phase === 'choice') {
    return (
      <Dialog open={open} onOpenChange={close}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('board.choiceTitle', { candidate: candidateLabel })}</DialogTitle>
            <DialogDescription>{t('board.choiceHint')}</DialogDescription>
          </DialogHeader>

          {problem !== null ? (
            <p role="alert" className="text-error flex items-center gap-1 text-xs">
              <span aria-hidden="true">●</span>
              {problem}
            </p>
          ) : null}

          <div className="flex flex-col gap-2">
            <Button size="sm" disabled={evaluation.isLoading} onClick={startSignoff}>
              {t('board.rejectAction')}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setPhase('withdraw')}>
              {t('board.withdrawAction')}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    )
  }

  const withdraw = phase === 'withdraw'
  const actionTarget: ApplicationStatus = withdraw ? 'withdrawn' : (target ?? 'gated')

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {withdraw
              ? t('board.withdrawTitle', { candidate: candidateLabel })
              : t('board.moveTitle', { stage: t(`hiring.stages.${targetStage}`) })}
          </DialogTitle>
          <DialogDescription>
            {withdraw ? t('board.withdrawHint') : t('board.reasonPlaceholder')}
          </DialogDescription>
        </DialogHeader>

        <form
          onSubmit={(event: FormEvent) => {
            event.preventDefault()
            void submitMove(actionTarget)
          }}
          className="flex flex-col gap-4"
        >
          {problem !== null ? (
            <p role="alert" className="text-error flex items-center gap-1 text-xs">
              <span aria-hidden="true">●</span>
              {problem}
            </p>
          ) : null}

          <div className={fieldClass}>
            <label htmlFor={`stage-reason-${application.application_id}`} className={labelClass}>
              {t('board.reason')}
            </label>
            <Textarea
              id={`stage-reason-${application.application_id}`}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              className="min-h-16"
            />
          </div>

          <DialogFooter>
            <Button type="submit" size="sm" disabled={busy}>
              {withdraw ? t('board.confirmWithdraw') : t('board.confirm')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
