import { render, screen } from '@testing-library/react'
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
  return render(
    <MemoryRouter>
      <SchedulingView />
    </MemoryRouter>,
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
    schedulingState.proposals = [proposal({ requires_human_approval: true })]
    renderView()

    expect(screen.getByText(i18n.t('scheduling.status.needs_approval'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('scheduling.approvalHint'))).toBeInTheDocument()
  })

  it('flags proposals with no mutual slots for coordination', () => {
    schedulingState.proposals = [proposal({ needs_human_reconciliation: true })]
    renderView()

    expect(screen.getByText(i18n.t('scheduling.status.reconciliation'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('scheduling.reconciliationHint'))).toBeInTheDocument()
  })

  it('celebrates an empty proposal list', () => {
    renderView()

    expect(screen.getByText(i18n.t('scheduling.empty'))).toBeInTheDocument()
  })
})
