import type { components } from '@/api/schema'
import type { StatusTone } from '@/components/status/StatusBadge'

export type OfferView = components['schemas']['OfferView']
export type OfferStatus = components['schemas']['OfferStatus']
export type OfferTerms = components['schemas']['OfferTerms']
export type OfferRevisionView = components['schemas']['OfferRevisionView']

export type OfferAction =
  'revise' | 'submit' | 'approve' | 'withdraw' | 'message' | 'accept' | 'decline'

export const OFFER_STATUS_TONES: Partial<Record<OfferStatus, StatusTone>> = {
  pending_approval: 'waiting',
  accepted: 'done',
}

/**
 * Which actions a status offers. Mirrors the server's lifecycle: only drafts
 * are revised or submitted; approved offers can be messaged; acceptance is
 * recorded on approved/queued offers; terminal states offer nothing.
 */
export function actionsForOffer(status: OfferStatus): OfferAction[] {
  switch (status) {
    case 'draft':
      return ['revise', 'submit']
    case 'pending_approval':
      return ['approve', 'withdraw']
    case 'approved':
      return ['message', 'accept', 'decline', 'withdraw']
    case 'queued':
      return ['accept', 'decline']
    case 'accepted':
    case 'declined':
    case 'expired':
    case 'withdrawn':
      return []
  }
}

export function formatMoney(amount: number, currency: string, locale: string): string {
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  }).format(amount)
}

export function newestFirstOffers(offers: OfferView[]): OfferView[] {
  return [...offers].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
}

export function activeOffer(offers: OfferView[]): OfferView | null {
  const ordered = newestFirstOffers(offers)
  return ordered.find((offer) => actionsForOffer(offer.status).length > 0) ?? ordered[0] ?? null
}
