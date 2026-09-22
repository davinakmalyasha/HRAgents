import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge } from '@/components/status/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDateTime } from '@/lib/dates'

import { OfferActionDialog, type OfferActionKind } from './OfferActionDialog'
import { OfferFormDialog } from './OfferFormDialog'
import {
  OFFER_STATUS_TONES,
  actionsForOffer,
  formatMoney,
  newestFirstOffers,
  type OfferAction,
  type OfferView,
} from './offer'
import { useOffers } from './useOffers'

type Dialog =
  | { kind: 'form'; offer: OfferView | null }
  | { kind: 'action'; offer: OfferView; action: OfferActionKind }

function isFormAction(action: OfferAction): action is 'revise' {
  return action === 'revise'
}

function OfferItem({
  offer,
  onAction,
}: {
  offer: OfferView
  onAction: (action: OfferAction) => void
}) {
  const { t, i18n } = useTranslation()
  const tone = OFFER_STATUS_TONES[offer.status]
  const actions = actionsForOffer(offer.status)
  const terms = offer.terms

  const timeline: string[] = [t('offer.createdBy', { name: offer.created_by })]
  if (offer.decided_by !== null && offer.decided_by !== undefined) {
    timeline.push(t('offer.decidedBy', { name: offer.decided_by }))
  }
  if (offer.queued_at !== null && offer.queued_at !== undefined) {
    timeline.push(`${t('offer.queuedAt')} · ${formatDateTime(offer.queued_at)}`)
  }
  if (offer.accepted_at !== null && offer.accepted_at !== undefined) {
    timeline.push(`${t('offer.acceptedAt')} · ${formatDateTime(offer.accepted_at)}`)
  }
  if (offer.decline_reason !== null && offer.decline_reason !== undefined) {
    timeline.push(t('offer.declinedReason', { reason: offer.decline_reason }))
  }

  return (
    <li className="flex flex-col gap-3 px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {tone === undefined ? (
            <Badge variant="outline">{t(`offer.status.${offer.status}`)}</Badge>
          ) : (
            <StatusBadge tone={tone} labelKey={`offer.status.${offer.status}`} />
          )}
          <span className="text-ink-strong text-xs font-medium">{terms.position_title}</span>
          <span className="text-2xs text-ink-muted">
            {t(`offer.types.${terms.employment_type}`)}
          </span>
        </div>
        <span className="text-2xs text-ink-muted font-mono">
          {formatMoney(terms.salary_amount, terms.salary_currency, i18n.language)}
        </span>
      </div>

      <dl className="text-2xs grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
        <div className="flex items-center justify-between gap-2">
          <dt className="text-ink-muted">{t('offer.terms.start')}</dt>
          <dd className="text-ink-strong font-mono">{terms.start_date}</dd>
        </div>
        {terms.end_date === null || terms.end_date === undefined ? null : (
          <div className="flex items-center justify-between gap-2">
            <dt className="text-ink-muted">{t('offer.terms.end')}</dt>
            <dd className="text-ink-strong font-mono">{terms.end_date}</dd>
          </div>
        )}
        {terms.probation_months === null || terms.probation_months === undefined ? null : (
          <div className="flex items-center justify-between gap-2">
            <dt className="text-ink-muted">{t('offer.terms.probation')}</dt>
            <dd className="text-ink-strong font-mono">{terms.probation_months}</dd>
          </div>
        )}
        {terms.expires_at === null || terms.expires_at === undefined ? null : (
          <div className="flex items-center justify-between gap-2">
            <dt className="text-ink-muted">{t('offer.terms.validUntil')}</dt>
            <dd className="text-ink-strong font-mono">{terms.expires_at.slice(0, 10)}</dd>
          </div>
        )}
      </dl>

      <span className="text-2xs text-ink-muted">
        {timeline.join(' · ')} · {formatDateTime(offer.created_at)}
      </span>

      <details className="border-line rounded-md border px-2 py-1.5">
        <summary className="text-ink-muted text-2xs cursor-pointer">
          {t('offer.history', { count: offer.revisions.length })}
        </summary>
        <ul className="mt-1.5 flex flex-col gap-1">
          {offer.revisions.map((revision) => (
            <li key={revision.id} className="text-2xs flex flex-wrap items-center gap-2">
              <span className="text-ink-strong font-mono">
                {t('offer.revision', { index: revision.revision_index })}
              </span>
              <span className="text-ink-muted">
                {formatMoney(
                  revision.terms.salary_amount,
                  revision.terms.salary_currency,
                  i18n.language,
                )}
              </span>
              <span className="text-ink-muted">
                {revision.changed_by} · {formatDateTime(revision.changed_at)}
              </span>
              {revision.note === '' ? null : (
                <span className="text-ink-muted italic">{revision.note}</span>
              )}
            </li>
          ))}
        </ul>
      </details>

      {actions.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {actions.map((action) => (
            <Button
              key={action}
              variant={action === 'approve' || action === 'accept' ? 'default' : 'outline'}
              size="xs"
              onClick={() => onAction(action)}
            >
              {t(`offer.${action}`)}
            </Button>
          ))}
        </div>
      ) : null}
    </li>
  )
}

/**
 * Offer records for an application: terms, approval trail, acceptance, and
 * append-only revisions. Every action is a named-human act — the system never
 * approves, sends, or accepts on its own.
 */
export function OfferPanel({ applicationId }: { applicationId: string }) {
  const { t } = useTranslation()
  const offers = useOffers(applicationId)
  const [dialog, setDialog] = useState<Dialog | null>(null)

  const items = newestFirstOffers(offers.data ?? [])

  return (
    <section aria-labelledby="offer" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="offer" className="text-ink-strong text-xl font-medium">
          {t('offer.title')}
        </h2>
        <Button size="sm" onClick={() => setDialog({ kind: 'form', offer: null })}>
          {t('offer.create')}
        </Button>
      </div>

      {offers.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : items.length === 0 ? (
        <EmptyState title={t('offer.empty')} />
      ) : (
        <ul className="divide-line border-line flex flex-col divide-y rounded-lg border">
          {items.map((offer) => (
            <OfferItem
              key={offer.id}
              offer={offer}
              onAction={(action) => {
                if (isFormAction(action)) {
                  setDialog({ kind: 'form', offer })
                } else {
                  setDialog({ kind: 'action', offer, action })
                }
              }}
            />
          ))}
        </ul>
      )}

      {dialog !== null && dialog.kind === 'form' ? (
        <OfferFormDialog
          key={dialog.offer?.id ?? 'new'}
          applicationId={applicationId}
          offer={dialog.offer}
          open
          onOpenChange={(next) => {
            if (!next) {
              setDialog(null)
            }
          }}
        />
      ) : null}
      {dialog !== null && dialog.kind === 'action' ? (
        <OfferActionDialog
          key={`${dialog.offer.id}-${dialog.action}`}
          offer={dialog.offer}
          action={dialog.action}
          open
          onOpenChange={(next) => {
            if (!next) {
              setDialog(null)
            }
          }}
        />
      ) : null}
    </section>
  )
}
