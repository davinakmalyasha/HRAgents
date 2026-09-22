import { useQueryClient } from '@tanstack/react-query'
import { ChevronsUpDown } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge, type StatusTone } from '@/components/status/StatusBadge'
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
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { formatDateTime } from '@/lib/dates'

import { markCommunicationSent, queueOfferMessage, queueRejectionMessage } from './communicationApi'
import {
  COMMUNICATION_CHANNELS,
  canQueueRejection,
  newestFirstCommunications,
  type Channel,
  type CommunicationView,
  type PolicyDecision,
} from './communication'
import { useCommunications, useEvaluationOverrides } from './useCommunications'

const STATUS_TONES: Partial<Record<CommunicationView['status'], StatusTone>> = {
  queued: 'waiting',
  sent: 'done',
}

type DialogMode = 'rejection' | 'offer' | 'sent'

interface DialogState {
  mode: DialogMode
  communicationId?: string
}

const fieldClass = 'flex flex-col gap-1.5'
const labelClass = 'text-xs font-medium text-ink-strong'

function CommunicationDialog({
  mode,
  candidateId,
  communicationId,
  open,
  onOpenChange,
}: {
  mode: DialogMode
  candidateId: string
  communicationId?: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [by, setBy] = useState('')
  const [language, setLanguage] = useState<'en' | 'id'>('en')
  const [channel, setChannel] = useState<Channel>('email')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function close(next: boolean) {
    if (!next) {
      setProblem(null)
    }
    onOpenChange(next)
  }

  function errorFor(status: number): string {
    if (status === 403) {
      return t('communication.errors.forbidden')
    }
    if (status === 404) {
      return t('communication.errors.notFound')
    }
    if (status === 409) {
      return t('communication.errors.conflict')
    }
    return t('communication.errors.failed')
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (by.trim() === '') {
      setProblem(t('communication.errors.byRequired'))
      return
    }
    if (mode === 'offer' && body.trim() === '') {
      setProblem(t('communication.errors.bodyRequired'))
      return
    }
    setProblem(null)
    setBusy(true)

    const result =
      mode === 'rejection'
        ? await queueRejectionMessage(candidateId, { by: by.trim(), language, channel })
        : mode === 'offer'
          ? await queueOfferMessage(candidateId, {
              by: by.trim(),
              body,
              subject: subject.trim() === '' ? null : subject.trim(),
              language,
              channel,
            })
          : await markCommunicationSent(communicationId ?? '', by.trim())

    setBusy(false)
    if (result.status === 200 || result.status === 201) {
      await queryClient.invalidateQueries({ queryKey: ['communications', candidateId] })
      close(false)
      return
    }
    setProblem(errorFor(result.status))
  }

  const titleKey =
    mode === 'rejection'
      ? 'communication.dialogs.rejectionTitle'
      : mode === 'offer'
        ? 'communication.dialogs.offerTitle'
        : 'communication.dialogs.sentTitle'
  const hintKey =
    mode === 'rejection'
      ? 'communication.dialogs.rejectionHint'
      : mode === 'offer'
        ? 'communication.dialogs.offerHint'
        : 'communication.dialogs.sentHint'

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t(titleKey)}</DialogTitle>
          <DialogDescription>{t(hintKey)}</DialogDescription>
        </DialogHeader>

        <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-4">
          {problem !== null ? (
            <p role="alert" className="text-error flex items-center gap-1 text-xs">
              <span aria-hidden="true">●</span>
              {problem}
            </p>
          ) : null}

          <div className={fieldClass}>
            <label htmlFor={`communication-by-${mode}`} className={labelClass}>
              {t('communication.fields.by')}
            </label>
            <Input
              id={`communication-by-${mode}`}
              value={by}
              onChange={(event) => setBy(event.target.value)}
              placeholder={t('communication.fields.byPlaceholder')}
              autoComplete="off"
            />
          </div>

          {mode === 'sent' ? null : (
            <>
              <div className={fieldClass}>
                <span id={`communication-language-${mode}`} className={labelClass}>
                  {t('communication.fields.language')}
                </span>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      aria-labelledby={`communication-language-${mode}`}
                      className="justify-between"
                    >
                      <span>{t(`communication.languages.${language}`)}</span>
                      <ChevronsUpDown aria-hidden="true" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start">
                    <DropdownMenuRadioGroup
                      value={language}
                      onValueChange={(value) => setLanguage(value as 'en' | 'id')}
                    >
                      <DropdownMenuRadioItem value="en">
                        {t('communication.languages.en')}
                      </DropdownMenuRadioItem>
                      <DropdownMenuRadioItem value="id">
                        {t('communication.languages.id')}
                      </DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>

              <div className={fieldClass}>
                <span id={`communication-channel-${mode}`} className={labelClass}>
                  {t('communication.fields.channel')}
                </span>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      aria-labelledby={`communication-channel-${mode}`}
                      className="justify-between"
                    >
                      <span>{t(`communication.channels.${channel}`)}</span>
                      <ChevronsUpDown aria-hidden="true" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start">
                    <DropdownMenuRadioGroup
                      value={channel}
                      onValueChange={(value) => setChannel(value as Channel)}
                    >
                      {COMMUNICATION_CHANNELS.map((option) => (
                        <DropdownMenuRadioItem key={option} value={option}>
                          {t(`communication.channels.${option}`)}
                        </DropdownMenuRadioItem>
                      ))}
                    </DropdownMenuRadioGroup>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </>
          )}

          {mode === 'offer' ? (
            <>
              <div className={fieldClass}>
                <label htmlFor="communication-subject" className={labelClass}>
                  {t('communication.fields.subject')}
                </label>
                <Input
                  id="communication-subject"
                  value={subject}
                  onChange={(event) => setSubject(event.target.value)}
                  placeholder={t('communication.fields.subjectPlaceholder')}
                  autoComplete="off"
                />
              </div>
              <div className={fieldClass}>
                <label htmlFor="communication-body" className={labelClass}>
                  {t('communication.fields.body')}
                </label>
                <Textarea
                  id="communication-body"
                  value={body}
                  onChange={(event) => setBody(event.target.value)}
                  rows={6}
                />
              </div>
            </>
          ) : null}

          <DialogFooter>
            <Button type="submit" size="sm" disabled={busy}>
              {mode === 'sent' ? t('communication.confirmSent') : t('communication.confirm')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function CommunicationItem({
  item,
  onMarkSent,
}: {
  item: CommunicationView
  onMarkSent: () => void
}) {
  const { t } = useTranslation()
  const tone = STATUS_TONES[item.status]

  return (
    <li className="flex flex-col gap-2 px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{t(`communication.kinds.${item.kind}`)}</Badge>
          {tone === undefined ? (
            <Badge variant="outline">{t(`communication.statuses.${item.status}`)}</Badge>
          ) : (
            <StatusBadge tone={tone} labelKey={`communication.statuses.${item.status}`} />
          )}
          <span className="text-2xs text-ink-muted">
            {t(`communication.languages.${item.language}`)}
          </span>
          <span className="text-2xs text-ink-muted">
            {t(`communication.channels.${item.channel}`)}
          </span>
        </div>
        {item.status === 'queued' ? (
          <Button variant="outline" size="xs" onClick={onMarkSent}>
            {t('communication.markSent')}
          </Button>
        ) : null}
      </div>

      {item.subject !== null ? (
        <span className="text-ink-strong text-xs font-medium">{item.subject}</span>
      ) : null}

      <pre className="border-line bg-surface-subtle text-ink max-h-48 overflow-y-auto rounded-md border p-2 text-xs whitespace-pre-wrap">
        {item.body}
      </pre>

      <span className="text-2xs text-ink-muted">
        {t('communication.queuedBy', { name: item.approved_by })} ·{' '}
        {formatDateTime(item.created_at)}
        {item.sent_by === null ? '' : ` · ${t('communication.sentBy', { name: item.sent_by })}`}
      </span>
    </li>
  )
}

/**
 * Candidate-facing messages: queueing is gated (a recorded rejection decision,
 * a named approver) and the system never dispatches — ``mark sent`` records
 * manual dispatch evidence. Bodies stay visible until an outcome is recorded.
 */
export function CommunicationPanel({
  candidateId,
  evaluationId,
  policyDecision,
}: {
  candidateId: string
  evaluationId: string | undefined
  policyDecision: PolicyDecision | undefined
}) {
  const { t } = useTranslation()
  const communications = useCommunications(candidateId)
  const overrides = useEvaluationOverrides(evaluationId)
  const [dialog, setDialog] = useState<DialogState | null>(null)

  const items = newestFirstCommunications(communications.data ?? [])
  const rejectionAllowed = canQueueRejection(policyDecision, overrides.data ?? [])
  const activeRejection = items.some(
    (item) => item.kind === 'rejection' && item.status !== 'cancelled',
  )

  return (
    <section aria-labelledby="communication" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="communication" className="text-ink-strong text-xl font-medium">
          {t('communication.title')}
        </h2>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={evaluationId === undefined || !rejectionAllowed || activeRejection}
            onClick={() => setDialog({ mode: 'rejection' })}
          >
            {t('communication.queueRejection')}
          </Button>
          <Button
            size="sm"
            disabled={evaluationId === undefined}
            onClick={() => setDialog({ mode: 'offer' })}
          >
            {t('communication.composeOffer')}
          </Button>
        </div>
      </div>

      {evaluationId === undefined ? (
        <p className="text-2xs text-ink-muted">{t('communication.needsEvaluation')}</p>
      ) : !rejectionAllowed ? (
        <p className="text-2xs text-ink-muted">{t('communication.rejectionLocked')}</p>
      ) : activeRejection ? (
        <p className="text-2xs text-ink-muted">{t('communication.rejectionExists')}</p>
      ) : null}

      {communications.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : items.length === 0 ? (
        <EmptyState title={t('communication.empty')} />
      ) : (
        <ul className="divide-line border-line flex flex-col divide-y rounded-lg border">
          {items.map((item) => (
            <CommunicationItem
              key={item.id}
              item={item}
              onMarkSent={() => setDialog({ mode: 'sent', communicationId: item.id })}
            />
          ))}
        </ul>
      )}

      {dialog !== null ? (
        <CommunicationDialog
          key={`${dialog.mode}-${dialog.communicationId ?? ''}`}
          mode={dialog.mode}
          candidateId={candidateId}
          communicationId={dialog.communicationId}
          open
          onOpenChange={(open) => {
            if (!open) {
              setDialog(null)
            }
          }}
        />
      ) : null}
    </section>
  )
}
