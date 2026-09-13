import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

vi.mock('./hiringApi', () => ({ recordOverride: vi.fn() }))

import { recordOverride } from './hiringApi'
import { OverrideDialog } from './OverrideDialog'

const recordOverrideMock = vi.mocked(recordOverride)

const RECEIPT = {
  entry_id: '00000000-0000-0000-0000-0000000000ee',
  seq: 12,
  entry_hash: 'a'.repeat(64),
  prev_hash: null,
  created_at: '2026-09-12T00:00:00Z',
}

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onOpenChange = vi.fn()
  render(
    <QueryClientProvider client={client}>
      <OverrideDialog
        evaluationId="eval-1"
        candidateLabel="cand-1"
        contextLine="s_tech: 0.62"
        open
        onOpenChange={onOpenChange}
      />
    </QueryClientProvider>,
  )
  return { onOpenChange }
}

async function chooseOption(field: 'role' | 'decision', optionName: string) {
  await userEvent.click(
    screen.getByRole('button', {
      name: field === 'role' ? i18n.t('review.role') : i18n.t('review.decision'),
    }),
  )
  await userEvent.click(screen.getByRole('menuitemradio', { name: optionName }))
}

beforeEach(() => {
  recordOverrideMock.mockReset()
})

describe('OverrideDialog', () => {
  it('requires a named reviewer, a role, a decision, and a reason', async () => {
    renderDialog()

    await userEvent.click(screen.getByRole('button', { name: i18n.t('review.submit') }))

    expect(recordOverrideMock).not.toHaveBeenCalled()
    expect(screen.getByText(i18n.t('review.errors.reviewerRequired'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('review.errors.roleRequired'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('review.errors.decisionRequired'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('review.errors.reasonRequired'))).toBeInTheDocument()
  })

  it('blocks agent-prefixed reviewers', async () => {
    renderDialog()

    await userEvent.type(screen.getByLabelText(i18n.t('review.reviewer')), 'agent:screening')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('review.submit') }))

    expect(recordOverrideMock).not.toHaveBeenCalled()
    expect(screen.getByText(i18n.t('review.errors.agentBlocked'))).toBeInTheDocument()
  })

  it('records the decision and shows the audit receipt', async () => {
    recordOverrideMock.mockResolvedValue({ status: 201, receipt: RECEIPT })
    renderDialog()

    await userEvent.type(screen.getByLabelText(i18n.t('review.reviewer')), 'Sinta Prabowo')
    await chooseOption('role', i18n.t('review.roles.recruiter_lead'))
    await chooseOption('decision', i18n.t('review.decisions.hitl_soft_rejection'))
    await userEvent.type(screen.getByLabelText(i18n.t('review.reason')), 'below_bar_after_review')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('review.submit') }))

    expect(recordOverrideMock).toHaveBeenCalledWith('eval-1', {
      reviewer_id: 'Sinta Prabowo',
      reviewer_role: 'recruiter_lead',
      override_decision: 'hitl_soft_rejection',
      reason_code: 'below_bar_after_review',
      notes: null,
    })
    expect(
      await screen.findByText(i18n.t('review.decisions.hitl_soft_rejection')),
    ).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText(RECEIPT.entry_hash)).toBeInTheDocument()
  })

  it('maps a 403 to the forbidden message', async () => {
    recordOverrideMock.mockResolvedValue({ status: 403 })
    renderDialog()

    await userEvent.type(screen.getByLabelText(i18n.t('review.reviewer')), 'Sinta Prabowo')
    await chooseOption('role', i18n.t('review.roles.engineering_lead'))
    await chooseOption('decision', i18n.t('review.decisions.auto_schedule'))
    await userEvent.type(screen.getByLabelText(i18n.t('review.reason')), 'reconsider')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('review.submit') }))

    expect(await screen.findByText(i18n.t('review.errors.forbidden'))).toBeInTheDocument()
  })
})
