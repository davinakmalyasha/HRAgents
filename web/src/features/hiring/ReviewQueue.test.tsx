import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

const queueState = vi.hoisted(() => ({
  apps: [
    {
      application_id: 'app-1',
      candidate_id: 'cand-1',
      job_id: 'job-1',
      status: 'gated',
      priority_score: 0.7,
      s_tech: 0.62,
      hours_waiting: 30,
    },
  ],
}))

vi.mock('./useHiring', () => ({
  useGatedApplications: () => ({ isLoading: false, data: queueState.apps }),
  useEvaluation: () => ({
    isLoading: false,
    data: {
      id: 'eval-1',
      s_tech: 0.62,
      flags: ['low_confidence_extraction'],
      policy: { decision: 'hitl_soft_rejection' },
    },
  }),
}))

vi.mock('./hiringApi', () => ({ recordOverride: vi.fn() }))

import { ReviewQueue } from './ReviewQueue'

beforeEach(() => {
  queueState.apps = [
    {
      application_id: 'app-1',
      candidate_id: 'cand-1',
      job_id: 'job-1',
      status: 'gated',
      priority_score: 0.7,
      s_tech: 0.62,
      hours_waiting: 30,
    },
  ]
})

function renderQueue() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ReviewQueue />
    </QueryClientProvider>,
  )
}

describe('ReviewQueue', () => {
  it('lists gated applications with their evaluation context', () => {
    renderQueue()

    expect(screen.getByText('cand-1')).toBeInTheDocument()
    expect(screen.getByText(i18n.t('review.flagsCount', { count: 1 }))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: i18n.t('review.review') })).toBeInTheDocument()
  })

  it('opens the sign-off dialog for an item', async () => {
    renderQueue()

    await userEvent.click(screen.getByRole('button', { name: i18n.t('review.review') }))

    expect(screen.getByText(i18n.t('review.title'))).toBeInTheDocument()
    expect(screen.getByLabelText(i18n.t('review.reviewer'))).toBeInTheDocument()
  })

  it('celebrates an empty queue', () => {
    queueState.apps = []
    renderQueue()

    expect(screen.getByText(i18n.t('review.empty'))).toBeInTheDocument()
  })
})
