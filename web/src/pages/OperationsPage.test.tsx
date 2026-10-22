import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'
import type { components } from '@/api/schema'

import { OpsRequestError } from '@/features/ops/opsApi'
import { OperationsPage } from './OperationsPage'

type DeadLetterView = components['schemas']['DeadLetterView']

const state = vi.hoisted(() => ({
  letters: [] as unknown[],
  isLoading: false,
  isError: false,
  error: null as unknown,
  requeue: vi.fn(),
}))

const providers = vi.hoisted(() => ({
  data: [] as unknown[],
  isLoading: false,
  isError: false,
  error: null as unknown,
}))

vi.mock('@/features/providers/useProviders', () => ({
  useProviders: () => providers,
}))

vi.mock('@/features/ops/useOps', () => ({
  useDeadLetters: () => ({
    isLoading: state.isLoading,
    isError: state.isError,
    error: state.error,
    data: state.letters,
  }),
  useRequeueDeadLetter: () => ({ mutate: state.requeue, isPending: false, isError: false }),
}))

function letter(overrides: Partial<DeadLetterView> = {}): DeadLetterView {
  return {
    message_id: 'm-1',
    topic: 'evaluation.evaluate',
    created_at: '2026-10-18T09:00:00Z',
    attempts: 3,
    failed_reason: 'provider timeout',
    failed_at: null,
    payload_keys: ['application_id', 'resume_text'],
    application_id: '11111111-1111-1111-1111-111111111111',
    ...overrides,
  } as DeadLetterView
}

function renderWith(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>{ui}</QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('Operations page', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
    state.requeue.mockReset()
    state.isLoading = false
    state.isError = false
    state.error = null
    state.letters = [letter()]
  })

  it('shows the message metadata and gates the requeue behind a reason', async () => {
    const user = userEvent.setup()
    renderWith(<OperationsPage />)

    expect(screen.getByText('evaluation.evaluate')).toBeInTheDocument()
    expect(screen.getByText(/3 attempts/)).toBeInTheDocument()
    expect(screen.getByText(/Reason: provider timeout/)).toBeInTheDocument()
    expect(screen.getByText(/Payload keys: application_id, resume_text/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Requeue' }))
    const confirm = screen.getByRole('button', { name: 'Requeue message' })
    expect(confirm).toBeDisabled()

    await user.type(screen.getByLabelText('Why is this being retried?'), 'provider recovered')
    expect(confirm).toBeEnabled()
    await user.click(confirm)

    expect(state.requeue).toHaveBeenCalledWith(
      { messageId: 'm-1', reason: 'provider recovered' },
      expect.anything(),
    )
  })

  it('says the queue is forbidden instead of pretending it is empty', () => {
    state.isError = true
    state.error = new OpsRequestError(403)

    renderWith(<OperationsPage />)

    expect(
      screen.getByText('Only an HR administrator can see the operations queue.'),
    ).toBeInTheDocument()
  })

  it('celebrates an empty dead-letter list as the healthy state', () => {
    state.letters = []

    renderWith(<OperationsPage />)

    expect(
      screen.getByText('No dead-lettered messages. That is the healthy state.'),
    ).toBeInTheDocument()
  })
})
