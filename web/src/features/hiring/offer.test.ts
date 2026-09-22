import { describe, expect, it } from 'vitest'

import {
  actionsForOffer,
  activeOffer,
  formatMoney,
  newestFirstOffers,
  type OfferView,
} from './offer'

function offer(overrides: Partial<OfferView> = {}): OfferView {
  return {
    id: 'offer-1',
    application_id: 'app-1',
    candidate_id: 'cand-1',
    job_id: 'job-1',
    status: 'draft',
    terms: {
      position_title: 'Backend Engineer',
      employment_type: 'pkwtt',
      start_date: '2026-11-01',
      end_date: null,
      probation_months: 3,
      salary_amount: 25_000_000,
      salary_currency: 'IDR',
      notes: '',
      expires_at: null,
    },
    revisions: [],
    created_by: 'hr-admin',
    created_at: '2026-09-20T03:00:00Z',
    updated_at: '2026-09-20T03:00:00Z',
    decided_by: null,
    decided_at: null,
    queued_at: null,
    accepted_at: null,
    declined_at: null,
    decline_reason: null,
    ...overrides,
  }
}

describe('actionsForOffer', () => {
  it('offers revise and submit for drafts', () => {
    expect(actionsForOffer('draft')).toEqual(['revise', 'submit'])
  })

  it('offers approve and withdraw while pending', () => {
    expect(actionsForOffer('pending_approval')).toEqual(['approve', 'withdraw'])
  })

  it('offers message, acceptance, and withdrawal once approved', () => {
    expect(actionsForOffer('approved')).toEqual(['message', 'accept', 'decline', 'withdraw'])
  })

  it('only records acceptance outcomes once the message is queued', () => {
    expect(actionsForOffer('queued')).toEqual(['accept', 'decline'])
  })

  it('offers nothing for terminal statuses', () => {
    for (const status of ['accepted', 'declined', 'expired', 'withdrawn'] as const) {
      expect(actionsForOffer(status)).toEqual([])
    }
  })
})

describe('formatMoney', () => {
  it('renders the amount with its currency and no decimals', () => {
    expect(formatMoney(25_000_000, 'IDR', 'en-US')).toMatch(/25,000,000/)
  })
})

describe('offer ordering', () => {
  it('orders newest first', () => {
    const older = offer({ id: 'older', created_at: '2026-09-18T03:00:00Z' })
    const newer = offer({ id: 'newer', created_at: '2026-09-20T03:00:00Z' })

    expect(newestFirstOffers([older, newer]).map((item) => item.id)).toEqual(['newer', 'older'])
  })

  it('prefers the newest offer that still has actions', () => {
    const terminal = offer({ id: 'done', status: 'withdrawn', created_at: '2026-09-21T03:00:00Z' })
    const draft = offer({ id: 'draft-2', status: 'draft', created_at: '2026-09-20T03:00:00Z' })

    expect(activeOffer([terminal, draft])?.id).toBe('draft-2')
  })

  it('falls back to the newest offer when everything is terminal', () => {
    const terminal = offer({ id: 'done', status: 'accepted' })
    expect(activeOffer([terminal])?.id).toBe('done')
    expect(activeOffer([])).toBeNull()
  })
})
