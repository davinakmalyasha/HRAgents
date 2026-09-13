import { useQueryClient } from '@tanstack/react-query'
import { ChevronsUpDown } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

import { recordOverride, type AuditReceipt, type PolicyDecision } from './hiringApi'
import { DECISIONS, REVIEWER_ROLES, type ReviewerRole } from './review'

interface OverrideDialogProps {
  evaluationId: string
  candidateLabel: string
  contextLine: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

type Phase =
  | { name: 'form' }
  | { name: 'submitting' }
  | { name: 'done'; receipt: AuditReceipt; decision: PolicyDecision; reviewer: string }
  | { name: 'error'; detail: string }

const fieldClass = 'flex flex-col gap-1.5'
const labelClass = 'text-xs font-medium text-ink-strong'

/**
 * Named-human sign-off. Client validation mirrors the server gates
 * (named reviewer, permitted role, non-blank reason code); the API stays
 * authoritative and every outcome is audited with a receipt.
 */
export function OverrideDialog({
  evaluationId,
  candidateLabel,
  contextLine,
  open,
  onOpenChange,
}: OverrideDialogProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [reviewer, setReviewer] = useState('')
  const [role, setRole] = useState<ReviewerRole | ''>('')
  const [decision, setDecision] = useState<PolicyDecision | ''>('')
  const [reason, setReason] = useState('')
  const [notes, setNotes] = useState('')
  const [phase, setPhase] = useState<Phase>({ name: 'form' })
  const [fieldErrors, setFieldErrors] = useState<string[]>([])

  function close(next: boolean) {
    if (!next) {
      setPhase({ name: 'form' })
      setFieldErrors([])
    }
    onOpenChange(next)
  }

  function validate(): string[] {
    const problems: string[] = []
    if (reviewer.trim() === '') {
      problems.push(t('review.errors.reviewerRequired'))
    } else if (reviewer.trim().toLowerCase().startsWith('agent:')) {
      problems.push(t('review.errors.agentBlocked'))
    }
    if (role === '') {
      problems.push(t('review.errors.roleRequired'))
    }
    if (decision === '') {
      problems.push(t('review.errors.decisionRequired'))
    }
    if (reason.trim() === '') {
      problems.push(t('review.errors.reasonRequired'))
    }
    return problems
  }

  function errorFor(status: number): string {
    if (status === 403) {
      return t('review.errors.forbidden')
    }
    if (status === 404) {
      return t('review.errors.notFound')
    }
    if (status === 409) {
      return t('review.errors.conflict')
    }
    return t('review.errors.failed')
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const problems = validate()
    if (problems.length > 0 || role === '' || decision === '') {
      setFieldErrors(problems)
      return
    }
    setFieldErrors([])
    setPhase({ name: 'submitting' })

    const result = await recordOverride(evaluationId, {
      reviewer_id: reviewer.trim(),
      reviewer_role: role,
      override_decision: decision,
      reason_code: reason.trim(),
      notes: notes.trim() === '' ? null : notes.trim(),
    })

    if (result.status === 201 && result.receipt !== undefined) {
      await queryClient.invalidateQueries({ queryKey: ['applications'] })
      setPhase({
        name: 'done',
        receipt: result.receipt,
        decision,
        reviewer: reviewer.trim(),
      })
      return
    }
    setPhase({ name: 'error', detail: errorFor(result.status) })
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('review.title')}</DialogTitle>
          <DialogDescription>
            {candidateLabel} · {contextLine}
          </DialogDescription>
        </DialogHeader>

        {phase.name === 'done' ? (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge>{t(`review.decisions.${phase.decision}`)}</Badge>
              <span className="text-ink-muted text-xs">
                {t('review.decidedBy', { reviewer: phase.reviewer })}
              </span>
            </div>
            <dl className="border-line bg-surface-subtle flex flex-col gap-1 rounded-md border p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <dt className="text-ink-muted">{t('review.receiptSeq')}</dt>
                <dd className="text-ink-strong font-mono">{phase.receipt.seq}</dd>
              </div>
              <div className="flex flex-col gap-1">
                <dt className="text-ink-muted">{t('review.receiptHash')}</dt>
                <dd className="text-ink-strong font-mono break-all">{phase.receipt.entry_hash}</dd>
              </div>
            </dl>
            <p className="text-2xs text-ink-muted">{t('review.receiptNote')}</p>
            <DialogFooter>
              <Button type="button" size="sm" onClick={() => close(false)}>
                {t('review.done')}
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-4">
            {phase.name === 'error' ? (
              <p role="alert" className="text-error flex items-center gap-1 text-xs">
                <span aria-hidden="true">●</span>
                {phase.detail}
              </p>
            ) : null}

            {fieldErrors.length > 0 ? (
              <ul role="alert" className="text-error flex flex-col gap-1 text-xs">
                {fieldErrors.map((problem) => (
                  <li key={problem} className="flex items-center gap-1">
                    <span aria-hidden="true">●</span>
                    {problem}
                  </li>
                ))}
              </ul>
            ) : null}

            <div className={fieldClass}>
              <label htmlFor="override-reviewer" className={labelClass}>
                {t('review.reviewer')}
              </label>
              <Input
                id="override-reviewer"
                value={reviewer}
                onChange={(event) => setReviewer(event.target.value)}
                placeholder={t('review.reviewerPlaceholder')}
                autoComplete="off"
              />
            </div>

            <div className={fieldClass}>
              <span id="override-role-label" className={labelClass}>
                {t('review.role')}
              </span>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    aria-labelledby="override-role-label"
                    className="justify-between"
                  >
                    <span>{role === '' ? t('review.choose') : t(`review.roles.${role}`)}</span>
                    <ChevronsUpDown aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuRadioGroup
                    value={role}
                    onValueChange={(value) => setRole(value as ReviewerRole)}
                  >
                    {REVIEWER_ROLES.map((option) => (
                      <DropdownMenuRadioItem key={option} value={option}>
                        {t(`review.roles.${option}`)}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            <div className={fieldClass}>
              <span id="override-decision-label" className={labelClass}>
                {t('review.decision')}
              </span>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    aria-labelledby="override-decision-label"
                    className="justify-between"
                  >
                    <span>
                      {decision === '' ? t('review.choose') : t(`review.decisions.${decision}`)}
                    </span>
                    <ChevronsUpDown aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuRadioGroup
                    value={decision}
                    onValueChange={(value) => setDecision(value as PolicyDecision)}
                  >
                    {DECISIONS.map((option) => (
                      <DropdownMenuRadioItem key={option} value={option}>
                        {t(`review.decisions.${option}`)}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            <div className={fieldClass}>
              <label htmlFor="override-reason" className={labelClass}>
                {t('review.reason')}
              </label>
              <Input
                id="override-reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder={t('review.reasonPlaceholder')}
                autoComplete="off"
              />
            </div>

            <div className={fieldClass}>
              <label htmlFor="override-notes" className={labelClass}>
                {t('review.notes')}
              </label>
              <Textarea
                id="override-notes"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                placeholder={t('review.notesPlaceholder')}
                rows={2}
                className="min-h-9"
              />
            </div>

            <DialogFooter>
              <Button type="submit" size="sm" disabled={phase.name === 'submitting'}>
                {t('review.submit')}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
