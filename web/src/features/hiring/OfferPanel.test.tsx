import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

const offersState = vi.hoisted(() => ({ offers: [] as unknown[] }))

vi.mock('./useOffers', () => ({
  useOffers: () => ({ isLoading: false, data: offersState.offers }),
}))

import { OfferPanel } from './OfferPanel'
import type { OfferView } from './offer'

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
    revisions: [
      {
        id: 'revision-1',
        offer_id: 'offer-1',
        revision_index: 1,
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
        changed_by: 'hr-admin',
        changed_at: '2026-09-20T03:00:00Z',
        note: 'initial',
      },
    ],
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

beforeEach(() => {
  offersState.offers = []
})

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <OfferPanel applicationId="app-1" />
    </QueryClientProvider>,
  )
}

describe('OfferPanel', () => {
  it('shows the empty state and opens the create form', async () => {
    renderPanel()

    expect(screen.getByText(i18n.t('offer.empty'))).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: i18n.t('offer.create') }))

    expect(
      screen.getByRole('heading', { name: i18n.t('offer.form.createTitle') }),
    ).toBeInTheDocument()
    expect(screen.getByLabelText(i18n.t('offer.form.by'))).toBeInTheDocument()
  })

  it('offers revise and submit for a draft, prefilled for revision', async () => {
    offersState.offers = [offer()]
    renderPanel()

    expect(screen.getByRole('button', { name: i18n.t('offer.submit') })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: i18n.t('offer.revise') }))

    expect(screen.getByText(i18n.t('offer.form.reviseTitle'))).toBeInTheDocument()
    expect(screen.getByLabelText(i18n.t('offer.terms.position'))).toHaveValue('Backend Engineer')
  })

  it('offers approval actions while pending and opens the dialog', async () => {
    offersState.offers = [offer({ status: 'pending_approval' })]
    renderPanel()

    expect(screen.getByText(i18n.t('offer.status.pending_approval'))).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: i18n.t('offer.approve') }))

    expect(screen.getByText(i18n.t('offer.dialog.approveTitle'))).toBeInTheDocument()
  })

  it('shows the revision history and no actions for terminal offers', () => {
    offersState.offers = [offer({ status: 'withdrawn' })]
    renderPanel()

    expect(screen.getByText(i18n.t('offer.status.withdrawn'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('offer.history', { count: 1 }))).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: i18n.t('offer.submit') })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: i18n.t('offer.approve') })).not.toBeInTheDocument()
  })
})
