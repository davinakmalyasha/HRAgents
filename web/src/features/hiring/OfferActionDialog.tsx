import { useQueryClient } from '@tanstack/react-query'
import { ChevronsUpDown } from 'lucide-react'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

import {
  decideOffer,
  queueOfferMessage,
  recordOfferAcceptance,
  submitOffer,
  type OfferResult,
} from './offerApi'
import type { OfferView } from './offer'

export type OfferActionKind = 'submit' | 'approve' | 'withdraw' | 'message' | 'accept' | 'decline'

const fieldClass = 'flex flex-col gap-1.5'
const labelClass = 'text-xs font-medium text-ink-strong'

/**
 * One dialog for the offer lifecycle: submit, approve, withdraw, queue the
 * candidate message, and record the candidate's acceptance or decline. Every
 * path is attributed to the authenticated principal server-side, so the user is
 * never asked to spell their name; nothing here decides on its own.
 */
export function OfferActionDialog({
  offer,
  action,
  open,
  onOpenChange,
}: {
  offer: OfferView
  action: OfferActionKind
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [language, setLanguage] = useState<'en' | 'id'>('en')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reasonRequired = action === 'withdraw' || action === 'decline'

  function close(next: boolean) {
    if (!next) {
      setProblem(null)
    }
    onOpenChange(next)
  }

  function errorFor(status: number, detail?: string): string {
    if (status === 409) {
      if (detail?.includes('reason is required')) {
        return t('offer.errors.reasonRequired')
      }
      if (detail?.includes('was rejected')) {
        return t('offer.errors.approvalRejected')
      }
      return t('offer.errors.conflict')
    }
    if (status === 403) {
      return t('offer.errors.forbidden')
    }
    if (status === 404) {
      return t('offer.errors.notFound')
    }
    return t('offer.errors.failed')
  }

  async function perform(): Promise<OfferResult> {
    switch (action) {
      case 'submit':
        return submitOffer(offer.id, {})
      case 'approve':
        return decideOffer(offer.id, {
          decision: 'approve',
          reason: reason.trim(),
        })
      case 'withdraw':
        return decideOffer(offer.id, {
          decision: 'withdraw',
          reason: reason.trim(),
        })
      case 'message':
        return queueOfferMessage(offer.id, {
          body: body.trim() === '' ? null : body,
          subject: subject.trim() === '' ? null : subject.trim(),
          language,
        })
      case 'accept':
        return recordOfferAcceptance(offer.id, {
          accepted: true,
          reason: '',
        })
      case 'decline':
        return recordOfferAcceptance(offer.id, {
          accepted: false,
          reason: reason.trim(),
        })
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (reasonRequired && reason.trim() === '') {
      setProblem(t('offer.errors.reasonRequired'))
      return
    }
    setProblem(null)
    setBusy(true)

    const result = await perform()

    setBusy(false)
    if (result.status === 200) {
      await queryClient.invalidateQueries({ queryKey: ['offers', offer.application_id] })
      await queryClient.invalidateQueries({ queryKey: ['communications', offer.candidate_id] })
      close(false)
      return
    }
    setProblem(errorFor(result.status, result.detail))
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(`offer.dialog.${action}Title`)}</DialogTitle>
          <DialogDescription>{t(`offer.dialog.${action}Hint`)}</DialogDescription>
        </DialogHeader>

        <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-4">
          {problem !== null ? (
            <p role="alert" className="text-error flex items-center gap-1 text-xs">
              <span aria-hidden="true">●</span>
              {problem}
            </p>
          ) : null}

          {reasonRequired || action === 'approve' ? (
            <div className={fieldClass}>
              <label htmlFor={`offer-action-reason-${action}`} className={labelClass}>
                {t('offer.fields.reason')}
              </label>
              <Textarea
                id={`offer-action-reason-${action}`}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder={t('offer.fields.reasonPlaceholder')}
                rows={2}
                className="min-h-9"
              />
            </div>
          ) : null}

          {action === 'message' ? (
            <>
              <div className={fieldClass}>
                <label htmlFor="offer-action-subject" className={labelClass}>
                  {t('offer.fields.subject')}
                </label>
                <Input
                  id="offer-action-subject"
                  value={subject}
                  onChange={(event) => setSubject(event.target.value)}
                  autoComplete="off"
                />
              </div>
              <div className={fieldClass}>
                <label htmlFor="offer-action-body" className={labelClass}>
                  {t('offer.fields.body')}
                </label>
                <Textarea
                  id="offer-action-body"
                  value={body}
                  onChange={(event) => setBody(event.target.value)}
                  placeholder={t('offer.fields.bodyPlaceholder')}
                  rows={4}
                  className="min-h-16"
                />
              </div>
              <div className={fieldClass}>
                <span id="offer-action-language" className={labelClass}>
                  {t('offer.fields.language')}
                </span>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      aria-labelledby="offer-action-language"
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
            </>
          ) : null}

          <DialogFooter>
            <Button type="submit" size="sm" disabled={busy}>
              {t(`offer.${action}`)}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
