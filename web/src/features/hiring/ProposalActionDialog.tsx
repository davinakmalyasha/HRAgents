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
import { detailText, problemMessage, type ProblemDetail } from '@/lib/problem'

import { decideProposal } from './schedulingApi'
import { shortId } from './pipeline'
import {
  formatSlot,
  type ProposalAction,
  type SchedulingProposal,
  type TimeSlot,
} from './scheduling'

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
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const slots = proposal.payload.slots
  const [slot, setSlot] = useState<TimeSlot | null>(slots.length === 1 ? slots[0] : null)

  const candidateLabel = shortId(proposal.payload.candidate_id)
  const reasonRequired = action !== 'confirm'
  const slotRequired = action === 'confirm' && slots.length > 1

  function close(next: boolean) {
    if (!next) {
      setProblem(null)
    }
    onOpenChange(next)
  }

  function errorFor(status: number, detail?: ProblemDetail): string {
    return problemMessage(status, detail, t, 'scheduling', {
      // The server's own refusal text, matched in one place per dialog rather
      // than duplicated in nine. Prefers a machine `code` when the API sends
      // one -- see `lib/problem.ts`.
      overrides: (code, body) => {
        if (code !== 409) {
          return null
        }
        const prose = detailText(body) ?? ''
        if (prose.includes('reason is required')) {
          return t('scheduling.errors.reasonRequired')
        }
        if (prose.includes('was rejected')) {
          return t('scheduling.errors.approvalRejected')
        }
        return null
      },
    })
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (reasonRequired && reason.trim() === '') {
      setProblem(t('scheduling.errors.reasonRequired'))
      return
    }
    if (slotRequired && slot === null) {
      setProblem(t('scheduling.errors.slotRequired'))
      return
    }
    setProblem(null)
    setBusy(true)

    const result = await decideProposal(proposal.id, {
      decision: action,
      reason: reason.trim(),
      ...(action === 'confirm' && slot !== null ? { slot } : {}),
    })

    setBusy(false)
    if (result.status === 200) {
      await queryClient.invalidateQueries({ queryKey: ['scheduling', 'proposals'] })
      close(false)
      return
    }
    setProblem(errorFor(result.status, result.problem))
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

          {slotRequired ? (
            <fieldset className={fieldClass}>
              <legend className={labelClass}>{t('scheduling.fields.confirmedSlot')}</legend>
              <p className="text-ink-muted text-2xs">{t('scheduling.fields.confirmedSlotHint')}</p>
              {slots.map((option) => (
                <label key={option.start_utc} className="flex items-center gap-2 text-xs">
                  <input
                    type="radio"
                    name={`proposal-slot-${proposal.id}`}
                    checked={slot?.start_utc === option.start_utc}
                    onChange={() => setSlot(option)}
                  />
                  {formatSlot(option, proposal.payload.timezone, i18n.language)}
                </label>
              ))}
            </fieldset>
          ) : null}

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
