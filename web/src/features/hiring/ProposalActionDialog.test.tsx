import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

vi.mock('./schedulingApi', () => ({ decideProposal: vi.fn() }))

import { decideProposal } from './schedulingApi'
import { ProposalActionDialog } from './ProposalActionDialog'
import type { SchedulingProposal } from './scheduling'

const decideMock = vi.mocked(decideProposal)

function proposal(overrides: Partial<SchedulingProposal> = {}): SchedulingProposal {
  return {
    id: 'proposal-1',
    created_at: '2026-09-20T03:00:00Z',
    created_by: 'scheduling_service',
    status: 'pending_approval',
    decided_by: null,
    decided_at: null,
    supersedes_id: null,
    needs_human_reconciliation: false,
    requires_human_approval: true,
    payload: {
      candidate_id: 'cand-1',
      job_id: 'job-1',
      interviewer_ids: ['int-1'],
      slots: [
        { start_utc: '2026-09-21T02:00:00Z', end_utc: '2026-09-21T03:00:00Z', tentative: false },
      ],
      timezone: 'Asia/Jakarta',
      channel: 'email',
      auto_scheduled: false,
      policy: { decision: 'hitl_calendar' },
    },
    ...overrides,
  }
}

beforeEach(() => {
  decideMock.mockReset()
})

function renderDialog(action: 'confirm' | 'cancel' | 'reschedule') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onOpenChange = vi.fn()
  render(
    <QueryClientProvider client={client}>
      <ProposalActionDialog
        proposal={proposal()}
        action={action}
        open
        onOpenChange={onOpenChange}
      />
    </QueryClientProvider>,
  )
  return { onOpenChange }
}

describe('ProposalActionDialog', () => {
  it('requires a named human before deciding', async () => {
    renderDialog('confirm')

    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('scheduling.actions.confirm') }),
    )

    expect(decideMock).not.toHaveBeenCalled()
    expect(screen.getByText(i18n.t('scheduling.errors.byRequired'))).toBeInTheDocument()
  })

  it('requires a reason to cancel', async () => {
    renderDialog('cancel')

    await userEvent.type(screen.getByLabelText(i18n.t('scheduling.fields.by')), 'hr-admin')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('scheduling.actions.cancel') }))

    expect(decideMock).not.toHaveBeenCalled()
    expect(screen.getByText(i18n.t('scheduling.errors.reasonRequired'))).toBeInTheDocument()
  })

  it('confirms the proposal with the named actor', async () => {
    decideMock.mockResolvedValue({ status: 200 })
    const { onOpenChange } = renderDialog('confirm')

    await userEvent.type(screen.getByLabelText(i18n.t('scheduling.fields.by')), 'hr-admin')
    await userEvent.type(screen.getByLabelText(i18n.t('scheduling.fields.reason')), 'panel is free')
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('scheduling.actions.confirm') }),
    )

    expect(decideMock).toHaveBeenCalledWith('proposal-1', {
      by: 'hr-admin',
      decision: 'confirm',
      reason: 'panel is free',
    })
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('maps a rejected linked approval to its guidance', async () => {
    decideMock.mockResolvedValue({
      status: 409,
      detail: 'the linked scheduling approval was rejected; create a new proposal instead',
    })
    renderDialog('cancel')

    await userEvent.type(screen.getByLabelText(i18n.t('scheduling.fields.by')), 'hr-admin')
    await userEvent.type(screen.getByLabelText(i18n.t('scheduling.fields.reason')), 'try again')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('scheduling.actions.cancel') }))

    expect(screen.getByText(i18n.t('scheduling.errors.approvalRejected'))).toBeInTheDocument()
  })
})
