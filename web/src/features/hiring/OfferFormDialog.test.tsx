import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

vi.mock('./offerApi', () => ({
  createOffer: vi.fn(),
  reviseOffer: vi.fn(),
}))

import { createOffer } from './offerApi'
import { OfferFormDialog } from './OfferFormDialog'
import type { OfferView } from './offer'

const createMock = vi.mocked(createOffer)

beforeEach(() => {
  createMock.mockReset()
})

function renderForm(offer: OfferView | null = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onOpenChange = vi.fn()
  render(
    <QueryClientProvider client={client}>
      <OfferFormDialog applicationId="app-1" offer={offer} open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  )
  return { onOpenChange }
}

async function fillMinimum() {
  await userEvent.type(screen.getByLabelText(i18n.t('offer.terms.position')), 'Backend Engineer')
  await userEvent.type(screen.getByLabelText(i18n.t('offer.terms.start')), '2026-11-01')
  await userEvent.type(screen.getByLabelText(i18n.t('offer.form.salary')), '25000000')
}

describe('OfferFormDialog', () => {
  it('requires position, start date, and a valid salary -- and no actor', async () => {
    renderForm()

    // No "by" field: the server attributes the offer to the API key holder, so
    // asking for a name here would collect a value nothing reads.
    expect(screen.queryByLabelText(i18n.t('offer.form.by'))).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: i18n.t('offer.form.save') }))

    expect(createMock).not.toHaveBeenCalled()
    expect(screen.getByText(i18n.t('offer.errors.positionRequired'))).toBeInTheDocument()
  })

  it('blocks a PKWT offer without an end date', async () => {
    renderForm()
    await fillMinimum()

    await userEvent.click(screen.getByRole('button', { name: i18n.t('offer.terms.type') }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: i18n.t('offer.types.pkwt') }))
    await userEvent.click(screen.getByRole('button', { name: i18n.t('offer.form.save') }))

    expect(createMock).not.toHaveBeenCalled()
    expect(await screen.findByText(i18n.t('offer.errors.pkwtNeedsEnd'))).toBeInTheDocument()
  })

  it('creates the offer with the entered terms', async () => {
    createMock.mockResolvedValue({ status: 201 })
    const { onOpenChange } = renderForm()
    await fillMinimum()

    await userEvent.type(screen.getByLabelText(i18n.t('offer.form.probation')), '3')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('offer.form.save') }))

    expect(createMock).toHaveBeenCalledWith({
      application_id: 'app-1',
      note: '',
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
    })
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
