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
import { problemMessage } from '@/lib/problem'

import {
  composeDispatchLink,
  markCommunicationSent,
  queueOfferMessage,
  queueRejectionMessage,
  previewRejectionMessage,
  type CommunicationPreview,
} from './communicationApi'
import {
  COMMUNICATION_CHANNELS,
  canQueueRejection,
  dispatchEvidence,
  newestFirstCommunications,
  newestFirstReplies,
  type Channel,
  type CommunicationView,
  type PolicyDecision,
  type ReplyView,
  type WhatsappDispatchLinkView,
} from './communication'
import { useCommunications, useEvaluationOverrides, useReplies } from './useCommunications'

const STATUS_TONES: Partial<Record<CommunicationView['status'], StatusTone>> = {
  queued: 'waiting',
  sent: 'done',
}

type DialogMode = 'rejection' | 'offer' | 'sent' | 'link'

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
  const [language, setLanguage] = useState<'en' | 'id'>('en')
  const [channel, setChannel] = useState<Channel>('email')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [toEmail, setToEmail] = useState('')
  const [toPhone, setToPhone] = useState('')
  const [link, setLink] = useState<WhatsappDispatchLinkView | null>(null)
  const [preview, setPreview] = useState<CommunicationPreview | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const recipient = toEmail.trim() === '' ? null : toEmail.trim()
  const phone = toPhone.trim() === '' ? null : toPhone.trim()

  /** Any change to what shapes the message invalidates a stale preview. */
  function invalidatePreview() {
    setPreview(null)
  }

  function close(next: boolean) {
    if (!next) {
      setProblem(null)
    }
    onOpenChange(next)
  }

  function errorFor(status: number): string {
    return problemMessage(status, undefined, t, 'communication', {
      overrides: (code) => {
        // 400 is a malformed phone number; 422 is a schema problem with the
        // recipient. These two branches used to be swapped, so the most common
        // form error produced the wrong message.
        if (code === 400) {
          return t('communication.errors.invalidPhone')
        }
        if (code === 422) {
          return t('communication.errors.invalidRecipient')
        }
        return null
      },
    })
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (mode === 'offer' && body.trim() === '') {
      setProblem(t('communication.errors.bodyRequired'))
      return
    }
    setProblem(null)
    setBusy(true)

    if (mode === 'link') {
      const result = await composeDispatchLink(communicationId ?? '', phone ?? undefined)
      setBusy(false)
      if (result.status === 200 && result.link !== undefined) {
        setLink(result.link)
        return
      }
      setProblem(errorFor(result.status))
      return
    }

    // A rejection is previewed first: the human reads the exact message before
    // anything is queued.
    if (mode === 'rejection' && preview === null) {
      setBusy(false)
      await runPreview()
      return
    }
    if (mode === 'rejection' && preview?.can_queue === false) {
      setBusy(false)
      return
    }

    const result =
      mode === 'rejection'
        ? await queueRejectionMessage(candidateId, {
            language,
            channel,
            to_email: recipient,
            to_phone: phone,
          })
        : mode === 'offer'
          ? await queueOfferMessage(candidateId, {
              body,
              subject: subject.trim() === '' ? null : subject.trim(),
              language,
              channel,
              to_email: recipient,
              to_phone: phone,
            })
          : await markCommunicationSent(communicationId ?? '')

    setBusy(false)
    if (result.status === 200 || result.status === 201) {
      await queryClient.invalidateQueries({ queryKey: ['communications', candidateId] })
      close(false)
      return
    }
    if (mode === 'rejection') {
      // A refusal at queue time: fall back to a fresh preview so the human sees
      // what changed instead of a bare error code.
      invalidatePreview()
      await runPreview()
      return
    }
    setProblem(errorFor(result.status))
  }

  /**
   * Render what queueing would store, without storing it. The dialog only offers
   * the queue button after a preview the human has read.
   */
  async function runPreview() {
    setBusy(true)
    const result = await previewRejectionMessage(candidateId, {
      language,
      channel,
      to_email: recipient,
      to_phone: phone,
    })
    setBusy(false)
    if (result.status === 200 && result.preview !== undefined) {
      setPreview(result.preview)
      setProblem(null)
      return
    }
    setPreview(null)
    setProblem(errorFor(result.status))
  }

  async function recordAfterLink() {
    setBusy(true)
    const result = await markCommunicationSent(communicationId ?? '')
    setBusy(false)
    if (result.status === 200) {
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
        : mode === 'link'
          ? 'communication.dialogs.linkTitle'
          : 'communication.dialogs.sentTitle'
  const hintKey =
    mode === 'rejection'
      ? 'communication.dialogs.rejectionHint'
      : mode === 'offer'
        ? 'communication.dialogs.offerHint'
        : mode === 'link'
          ? 'communication.dialogs.linkHint'
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
                      onValueChange={(value) => {
                        setLanguage(value as 'en' | 'id')
                        invalidatePreview()
                      }}
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
                      onValueChange={(value) => {
                        setChannel(value as Channel)
                        invalidatePreview()
                      }}
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

          {mode !== 'sent' && mode !== 'link' && channel === 'email' ? (
            <div className={fieldClass}>
              <label htmlFor={`communication-to-${mode}`} className={labelClass}>
                {t('communication.fields.toEmail')}
              </label>
              <Input
                id={`communication-to-${mode}`}
                type="email"
                value={toEmail}
                onChange={(event) => {
                  setToEmail(event.target.value)
                  invalidatePreview()
                }}
                placeholder={t('communication.fields.toEmailPlaceholder')}
                autoComplete="off"
              />
              <span className="text-2xs text-ink-muted">
                {t('communication.fields.toEmailHint')}
              </span>
            </div>
          ) : null}

          {mode === 'link' || (mode !== 'sent' && channel === 'whatsapp') ? (
            <div className={fieldClass}>
              <label htmlFor={`communication-phone-${mode}`} className={labelClass}>
                {t('communication.fields.toPhone')}
              </label>
              <Input
                id={`communication-phone-${mode}`}
                type="tel"
                value={toPhone}
                onChange={(event) => {
                  setToPhone(event.target.value)
                  invalidatePreview()
                }}
                placeholder={t('communication.fields.toPhonePlaceholder')}
                autoComplete="off"
              />
              <span className="text-2xs text-ink-muted">
                {t('communication.fields.toPhoneHint')}
              </span>
            </div>
          ) : null}

          {preview === null ? null : (
            <div className="border-line bg-surface-subtle flex flex-col gap-2 rounded-md border p-3">
              <span className="text-ink-strong text-xs font-medium">
                {preview.can_queue
                  ? t('communication.previewTitle')
                  : t('communication.previewBlockedTitle')}
              </span>
              {preview.can_queue ? (
                <>
                  {preview.subject === null ? null : (
                    <span className="text-2xs text-ink-muted">{preview.subject}</span>
                  )}
                  <pre className="text-ink-strong text-2xs whitespace-pre-wrap">{preview.body}</pre>
                </>
              ) : (
                <ul className="text-error text-2xs flex flex-col gap-1">
                  {preview.blockers.map((blocker) => (
                    <li key={blocker} className="flex items-start gap-1">
                      <span aria-hidden="true">●</span>
                      <span>{blocker}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {link === null ? null : (
            <div className="border-line bg-surface-subtle flex flex-col gap-2 rounded-md border p-3">
              <span className="text-ink-strong text-xs font-medium">
                {t('communication.linkReady', { phone: link.phone })}
              </span>
              <a
                className="text-primary text-xs underline"
                href={link.url}
                target="_blank"
                rel="noreferrer"
              >
                {t('communication.openWhatsapp')}
              </a>
              <code className="text-ink-muted text-2xs break-all">{link.url}</code>
              <Button
                type="button"
                size="sm"
                disabled={busy}
                onClick={() => void recordAfterLink()}
              >
                {t('communication.recordAfterLink')}
              </Button>
            </div>
          )}

          <DialogFooter>
            {link !== null ? null : (
              <Button
                type="submit"
                size="sm"
                disabled={busy || (mode === 'rejection' && preview?.can_queue === false)}
              >
                {mode === 'sent'
                  ? t('communication.confirmSent')
                  : mode === 'link'
                    ? t('communication.composeLink')
                    : mode === 'rejection' && preview === null
                      ? t('communication.previewAction')
                      : mode === 'rejection'
                        ? t('communication.queueAfterPreview')
                        : t('communication.confirm')}
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function CommunicationItem({
  item,
  onMarkSent,
  onComposeLink,
}: {
  item: CommunicationView
  onMarkSent: () => void
  onComposeLink: () => void
}) {
  const { t } = useTranslation()
  const tone = STATUS_TONES[item.status]
  const evidence = dispatchEvidence(item)

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
          <div className="flex items-center gap-2">
            {item.channel === 'whatsapp' ? (
              <Button variant="outline" size="xs" onClick={onComposeLink}>
                {t('communication.composeLink')}
              </Button>
            ) : null}
            <Button variant="outline" size="xs" onClick={onMarkSent}>
              {t('communication.markSent')}
            </Button>
          </div>
        ) : null}
      </div>

      {item.subject !== null ? (
        <span className="text-ink-strong text-xs font-medium">{item.subject}</span>
      ) : null}

      {item.recipient !== null ? (
        <span className="text-2xs text-ink-muted">
          {t('communication.toAddress', { address: item.recipient })}
        </span>
      ) : item.recipient_phone !== null ? (
        <span className="text-2xs text-ink-muted">
          {t('communication.toPhone', { phone: item.recipient_phone })}
        </span>
      ) : null}

      <pre className="border-line bg-surface-subtle text-ink max-h-48 overflow-y-auto rounded-md border p-2 text-xs whitespace-pre-wrap">
        {item.body}
      </pre>

      {evidence.error !== null ? (
        <p role="status" className="text-error text-2xs flex items-center gap-1">
          <span aria-hidden="true">●</span>
          {t('communication.dispatchFailed', {
            provider: evidence.provider ?? t('communication.transport'),
            error: evidence.error,
          })}
        </p>
      ) : evidence.provider !== null ? (
        <span className="text-2xs text-ink-muted">
          {t('communication.dispatchedVia', {
            provider: evidence.provider,
            attempts: evidence.attempts,
          })}
        </span>
      ) : null}

      <span className="text-2xs text-ink-muted">
        {t('communication.queuedBy', { name: item.approved_by })} ·{' '}
        {formatDateTime(item.created_at)}
        {item.sent_by === null ? '' : ` · ${t('communication.sentBy', { name: item.sent_by })}`}
      </span>
    </li>
  )
}

function ReplyItem({ reply }: { reply: ReplyView }) {
  const { t } = useTranslation()

  return (
    <li className="flex flex-col gap-1 px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-ink-strong text-xs font-medium">
          {reply.subject === '' ? t('communication.replyNoSubject') : reply.subject}
        </span>
        <span className="text-2xs text-ink-muted">{formatDateTime(reply.received_at)}</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-2xs text-ink-muted">
          {t('communication.replyFrom', { address: reply.sender })}
        </span>
        <span className="text-2xs text-ink-muted">
          {t('communication.replyVia', { provider: reply.provider })}
        </span>
      </div>
      <pre className="border-line bg-surface-subtle text-ink max-h-48 overflow-y-auto rounded-md border p-2 text-xs whitespace-pre-wrap">
        {reply.body}
      </pre>
    </li>
  )
}

/**
 * Candidate-facing messages: queueing is gated (a recorded rejection decision,
 * a named approver) and nothing is sent before that approval. Dispatch is
 * either recorded manually here or carried by the configured email transport,
 * which writes its own evidence (provider, attempts, last error) back onto the
 * message. Bodies stay visible until an outcome is recorded, and replies the
 * transport captured are shown below as evidence, never as decisions.
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
  const replies = useReplies(candidateId)
  const overrides = useEvaluationOverrides(evaluationId)
  const [dialog, setDialog] = useState<DialogState | null>(null)

  const items = newestFirstCommunications(communications.data ?? [])
  const replyItems = newestFirstReplies(replies.data ?? [])
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
              onComposeLink={() => setDialog({ mode: 'link', communicationId: item.id })}
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

      <section aria-labelledby="replies" className="flex flex-col gap-3">
        <h3 id="replies" className="text-ink-strong text-sm font-medium">
          {t('communication.repliesTitle')}
        </h3>
        <p className="text-2xs text-ink-muted">{t('communication.repliesHint')}</p>
        {replies.isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : replyItems.length === 0 ? (
          <EmptyState title={t('communication.repliesEmpty')} />
        ) : (
          <ul className="divide-line border-line flex flex-col divide-y rounded-lg border">
            {replyItems.map((reply) => (
              <ReplyItem key={reply.id} reply={reply} />
            ))}
          </ul>
        )}
      </section>
    </section>
  )
}
