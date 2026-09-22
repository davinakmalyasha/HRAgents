import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

import type { SchedulingProposal } from './scheduling'

const schedulingState = vi.hoisted(() => ({
  proposals: [] as unknown[],
}))

vi.mock('./useScheduling', () => ({
  useSchedulingProposals: () => ({ isLoading: false, data: schedulingState.proposals }),
}))

vi.mock('./useHiring', () => ({
  useApplications: () => ({
    data: [
      {
        application_id: 'app-1',
        candidate_id: 'cand-1',
        job_id: 'job-1',
        status: 'scheduled',
        priority_score: 0.9,
        s_tech: 0.9,
        hours_waiting: 4,
      },
    ],
  }),
}))

import { SchedulingView } from './SchedulingView'

function proposal(overrides: Partial<SchedulingProposal>): SchedulingProposal {
  return {
    id: 'proposal-1',
    created_at: '2026-09-20T03:00:00Z',
    created_by: 'scheduling_service',
    status: 'auto_scheduled',
    decided_by: null,
    decided_at: null,
    supersedes_id: null,
    needs_human_reconciliation: false,
    requires_human_approval: false,
    payload: {
      candidate_id: 'cand-1',
      job_id: 'job-1',
      interviewer_ids: ['int-1'],
      slots: [
        { start_utc: '2026-09-21T02:00:00Z', end_utc: '2026-09-21T03:00:00Z', tentative: false },
      ],
      timezone: 'Asia/Jakarta',
      channel: 'email',
      auto_scheduled: true,
      policy: {
        decision: 'auto_schedule',
        reasons: ['s_tech 0.900 ≥ 0.85 and σ 0.0200 ≤ 0.05; auto-scheduling is within bounds'],
      },
    },
    ...overrides,
  }
}

beforeEach(() => {
  schedulingState.proposals = []
})

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SchedulingView />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SchedulingView', () => {
  it('shows an auto-scheduled proposal with its slots and policy decision', () => {
    schedulingState.proposals = [proposal({})]
    renderView()

    expect(screen.getByText(i18n.t('scheduling.status.auto'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('review.decisions.auto_schedule'))).toBeInTheDocument()
    expect(screen.getByText(/Slots: 1/)).toBeInTheDocument()
    expect(screen.getByText(/09:00–10:00/)).toBeInTheDocument()
    expect(screen.getByText(/auto-scheduling is within bounds/)).toBeInTheDocument()
  })

  it('links the candidate to the application when it is in view', () => {
    schedulingState.proposals = [proposal({})]
    renderView()

    expect(screen.getByRole('link', { name: 'cand-1' })).toHaveAttribute(
      'href',
      '/w/hiring/applications/app-1',
    )
  })

  it('flags proposals waiting on a human decision', () => {
    schedulingState.proposals = [
      proposal({ status: 'pending_approval', requires_human_approval: true }),
    ]
    renderView()

    expect(screen.getByText(i18n.t('scheduling.status.needs_approval'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('scheduling.approvalHint'))).toBeInTheDocument()
  })

  it('flags proposals with no mutual slots for coordination', () => {
    schedulingState.proposals = [
      proposal({
        status: 'pending_approval',
        requires_human_approval: true,
        needs_human_reconciliation: true,
      }),
    ]
    renderView()

    expect(screen.getByText(i18n.t('scheduling.status.reconciliation'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('scheduling.reconciliationHint'))).toBeInTheDocument()
  })

  it('offers the decision actions while a proposal is open', () => {
    schedulingState.proposals = [proposal({ status: 'pending_approval' })]
    renderView()

    expect(
      screen.getByRole('button', { name: i18n.t('scheduling.actions.confirm') }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: i18n.t('scheduling.actions.cancel') }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: i18n.t('scheduling.actions.reschedule') }),
    ).toBeInTheDocument()
  })

  it('opens the decision dialog from an action', async () => {
    schedulingState.proposals = [proposal({ status: 'pending_approval' })]
    renderView()

    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('scheduling.actions.confirm') }),
    )

    expect(screen.getByText(i18n.t('scheduling.dialog.confirmTitle'))).toBeInTheDocument()
    expect(screen.getByLabelText(i18n.t('scheduling.fields.by'))).toBeInTheDocument()
  })

  it('shows terminal states without actions, with the deciding human', () => {
    schedulingState.proposals = [
      proposal({ status: 'confirmed', decided_by: 'hr-admin' }),
      proposal({ id: 'proposal-2', status: 'cancelled', decided_by: 'lead-1' }),
    ]
    renderView()

    expect(screen.getByText(i18n.t('scheduling.status.confirmed'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('scheduling.status.cancelled'))).toBeInTheDocument()
    expect(screen.getByText(/Decided by lead-1/)).toBeInTheDocument()
    // Confirmed rows keep cancel/reschedule; cancelled rows are terminal.
    expect(
      screen.getAllByRole('button', { name: i18n.t('scheduling.actions.cancel') }),
    ).toHaveLength(1)
    expect(
      screen.queryByRole('button', { name: i18n.t('scheduling.actions.confirm') }),
    ).not.toBeInTheDocument()
  })

  it('notes when a proposal replaces an earlier one', () => {
    schedulingState.proposals = [
      proposal({
        status: 'pending_approval',
        supersedes_id: 'proposal-0',
      }),
    ]
    renderView()

    expect(screen.getByText(i18n.t('scheduling.replacesEarlier'))).toBeInTheDocument()
  })

  it('celebrates an empty proposal list', () => {
    renderView()

    expect(screen.getByText(i18n.t('scheduling.empty'))).toBeInTheDocument()
  })
})
