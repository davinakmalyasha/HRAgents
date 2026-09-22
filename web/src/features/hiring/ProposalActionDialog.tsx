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
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

import { decideProposal } from './schedulingApi'
import { shortId } from './pipeline'
import { type ProposalAction, type SchedulingProposal } from './scheduling'

const fieldClass = 'flex flex-col gap-1.5'
const labelClass = 'text-xs font-medium text-ink-strong'

/**
 * Confirm / cancel / reschedule a proposal as a named human. The server is the
 * single writer: confirmations decide the linked scheduling approval through
 * the shared approval engine; cancel and reschedule require a reason.
 */
export function ProposalActionDialog({
  proposal,
  action,
  open,
  onOpenChange,
}: {
  proposal: SchedulingProposal
  action: ProposalAction
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [by, setBy] = useState('')
  const [reason, setReason] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const candidateLabel = shortId(proposal.payload.candidate_id)
  const reasonRequired = action !== 'confirm'

  function close(next: boolean) {
    if (!next) {
      setProblem(null)
    }
    onOpenChange(next)
  }

  function errorFor(status: number, detail?: string): string {
    if (status === 409) {
      if (detail?.includes('reason is required')) {
        return t('scheduling.errors.reasonRequired')
      }
      if (detail?.includes('was rejected')) {
        return t('scheduling.errors.approvalRejected')
      }
      return t('scheduling.errors.conflict')
    }
    if (status === 403) {
      return t('scheduling.errors.forbidden')
    }
    if (status === 404) {
      return t('scheduling.errors.notFound')
    }
    return t('scheduling.errors.failed')
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (by.trim() === '') {
      setProblem(t('scheduling.errors.byRequired'))
      return
    }
    if (reasonRequired && reason.trim() === '') {
      setProblem(t('scheduling.errors.reasonRequired'))
      return
    }
    setProblem(null)
    setBusy(true)

    const result = await decideProposal(proposal.id, {
      by: by.trim(),
      decision: action,
      reason: reason.trim(),
    })

    setBusy(false)
    if (result.status === 200) {
      await queryClient.invalidateQueries({ queryKey: ['scheduling', 'proposals'] })
      close(false)
      return
    }
    setProblem(errorFor(result.status, result.detail))
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(`scheduling.dialog.${action}Title`)}</DialogTitle>
          <DialogDescription>
            {candidateLabel} · {t(`scheduling.dialog.${action}Hint`)}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-4">
          {problem !== null ? (
            <p role="alert" className="text-error flex items-center gap-1 text-xs">
              <span aria-hidden="true">●</span>
              {problem}
            </p>
          ) : null}

          <div className={fieldClass}>
            <label htmlFor={`proposal-by-${proposal.id}`} className={labelClass}>
              {t('scheduling.fields.by')}
            </label>
            <Input
              id={`proposal-by-${proposal.id}`}
              value={by}
              onChange={(event) => setBy(event.target.value)}
              placeholder={t('scheduling.fields.byPlaceholder')}
              autoComplete="off"
            />
          </div>

          <div className={fieldClass}>
            <label htmlFor={`proposal-reason-${proposal.id}`} className={labelClass}>
              {t('scheduling.fields.reason')}
            </label>
            <Textarea
              id={`proposal-reason-${proposal.id}`}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder={t('scheduling.fields.reasonPlaceholder')}
              rows={2}
              className="min-h-9"
            />
          </div>

          <DialogFooter>
            <Button type="submit" size="sm" disabled={busy}>
              {t(`scheduling.actions.${action}`)}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
