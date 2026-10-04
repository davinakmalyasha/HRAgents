import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

vi.mock('./offerApi', () => ({
  createOffer: vi.fn(),
  reviseOffer: vi.fn(),
  submitOffer: vi.fn(),
  decideOffer: vi.fn(),
  queueOfferMessage: vi.fn(),
  recordOfferAcceptance: vi.fn(),
}))

import { decideOffer, queueOfferMessage, recordOfferAcceptance } from './offerApi'
import { OfferActionDialog } from './OfferActionDialog'
import type { OfferView } from './offer'

const decideMock = vi.mocked(decideOffer)
const messageMock = vi.mocked(queueOfferMessage)
const acceptMock = vi.mocked(recordOfferAcceptance)

function offer(overrides: Partial<OfferView> = {}): OfferView {
  return {
    id: 'offer-1',
    application_id: 'app-1',
    candidate_id: 'cand-1',
    job_id: 'job-1',
    status: 'pending_approval',
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

beforeEach(() => {
  decideMock.mockReset()
  messageMock.mockReset()
  acceptMock.mockReset()
})

function renderDialog(action: 'approve' | 'withdraw' | 'message' | 'accept' | 'decline') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onOpenChange = vi.fn()
  render(
    <QueryClientProvider client={client}>
      <OfferActionDialog offer={offer()} action={action} open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  )
  return { onOpenChange }
}

describe('OfferActionDialog', () => {
  it('never asks the user to name themselves', async () => {
    renderDialog('approve')

    // The server takes the actor from the API key. A name field here would be
    // the worst outcome: the user would believe the record was theirs.
    expect(screen.queryByLabelText(i18n.t('offer.fields.by'))).not.toBeInTheDocument()
  })

  it('requires a reason to withdraw', async () => {
    renderDialog('withdraw')

    await userEvent.click(screen.getByRole('button', { name: i18n.t('offer.withdraw') }))

    expect(decideMock).not.toHaveBeenCalled()
    expect(screen.getByText(i18n.t('offer.errors.reasonRequired'))).toBeInTheDocument()
  })

  it('approves with an optional reason and no actor field', async () => {
    decideMock.mockResolvedValue({ status: 200 })
    const { onOpenChange } = renderDialog('approve')

    await userEvent.click(screen.getByRole('button', { name: i18n.t('offer.approve') }))

    expect(decideMock).toHaveBeenCalledWith('offer-1', {
      decision: 'approve',
      reason: '',
    })
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('queues the message with a server-composed body when left blank', async () => {
    messageMock.mockResolvedValue({ status: 200 })
    renderDialog('message')

    await userEvent.click(screen.getByRole('button', { name: i18n.t('offer.message') }))

    expect(messageMock).toHaveBeenCalledWith('offer-1', {
      body: null,
      subject: null,
      language: 'en',
    })
  })

  it('records acceptance without any reason', async () => {
    acceptMock.mockResolvedValue({ status: 200 })
    renderDialog('accept')

    await userEvent.click(screen.getByRole('button', { name: i18n.t('offer.accept') }))

    expect(acceptMock).toHaveBeenCalledWith('offer-1', {
      accepted: true,
      reason: '',
    })
  })

  it('maps a rejected linked approval to its guidance', async () => {
    decideMock.mockResolvedValue({
      status: 409,
      problem: { title: 'the linked offer approval was rejected; create a new offer instead' },
    })
    renderDialog('approve')

    await userEvent.click(screen.getByRole('button', { name: i18n.t('offer.approve') }))

    expect(screen.getByText(i18n.t('offer.errors.approvalRejected'))).toBeInTheDocument()
  })
})
