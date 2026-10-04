import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

const evaluationState = vi.hoisted(() => ({
  data: null as Record<string, unknown> | null,
}))

vi.mock('./hiringApi', () => ({
  recordOverride: vi.fn(),
  moveStage: vi.fn(),
}))

vi.mock('./useHiring', () => ({
  useEvaluation: () => ({ isLoading: false, data: evaluationState.data }),
}))

import { moveStage } from './hiringApi'
import { StageMoveDialog } from './StageMoveDialog'
import type { ApplicationStatus, ApplicationSummary } from './pipeline'

const moveStageMock = vi.mocked(moveStage)

function application(overrides: Partial<ApplicationSummary> = {}): ApplicationSummary {
  return {
    application_id: 'app-1',
    candidate_id: '00000000-0000-0000-0000-0000000000bb',
    job_id: 'job-1',
    status: 'evaluated',
    priority_score: 0.7,
    s_tech: 0.62,
    hours_waiting: 12,
    ...overrides,
  }
}

beforeEach(() => {
  evaluationState.data = null
  moveStageMock.mockReset()
  // A default so every test satisfies the mock's return contract. Without it a
  // test that reaches `moveStage` but does not stub it resolves `undefined`,
  // which threw a TypeError inside the async handler and escaped as an
  // unhandled rejection -- vitest reported 192 passing tests and still exited 1.
  moveStageMock.mockResolvedValue({ status: 200 })
})

function renderDialog(
  overrides: {
    mode?: 'move' | 'choice'
    target?: ApplicationStatus | null
    targetStage?: 'decision' | 'closed' | 'interview'
    onOpenChange?: (open: boolean) => void
  } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onOpenChange = overrides.onOpenChange ?? vi.fn()
  render(
    <QueryClientProvider client={client}>
      <StageMoveDialog
        application={application()}
        mode={overrides.mode ?? 'move'}
        target={'target' in overrides ? (overrides.target ?? null) : 'gated'}
        targetStage={overrides.targetStage ?? 'decision'}
        open
        onOpenChange={onOpenChange}
      />
    </QueryClientProvider>,
  )
  return { onOpenChange }
}

describe('StageMoveDialog', () => {
  it('requires a reason before moving, and never asks for a name', async () => {
    renderDialog()

    // No "moved by" field: the server attributes the move to the key holder.
    expect(screen.queryByLabelText(i18n.t('board.by'))).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: i18n.t('board.confirm') }))

    expect(moveStageMock).not.toHaveBeenCalled()
    expect(screen.getByText(i18n.t('board.errors.reasonRequired'))).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText(i18n.t('board.reason')), 'pulled for review')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('board.confirm') }))

    expect(moveStageMock).toHaveBeenCalledWith('app-1', {
      target: 'gated',
      reason: 'pulled for review',
    })
  })

  it('submits the gated move with a reason', async () => {
    moveStageMock.mockResolvedValue({ status: 200 })
    const { onOpenChange } = renderDialog()

    await userEvent.type(screen.getByLabelText(i18n.t('board.reason')), 'pulled for review')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('board.confirm') }))

    expect(moveStageMock).toHaveBeenCalledWith('app-1', {
      target: 'gated',
      reason: 'pulled for review',
    })
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('maps a scheduling refusal to its hint', async () => {
    moveStageMock.mockResolvedValue({
      status: 409,
      problem: { title: 'scheduling is gated: create a proposal or record an approved override' },
    })
    renderDialog({ target: 'scheduled', targetStage: 'interview' })

    await userEvent.type(screen.getByLabelText(i18n.t('board.reason')), 'want to book it')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('board.confirm') }))

    expect(screen.getByText(i18n.t('board.errors.needScheduling'))).toBeInTheDocument()
  })

  it('says the server was unreachable instead of "conflict" when the request never lands', async () => {
    // A dropped connection used to reject out of the async handler: the
    // dialog stayed disabled forever, `setBusy(false)` never ran, and the
    // promise became an unhandled rejection.
    moveStageMock.mockRejectedValue(new TypeError('Failed to fetch'))
    const { onOpenChange } = renderDialog()

    await userEvent.type(screen.getByLabelText(i18n.t('board.reason')), 'pulled for review')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('board.confirm') }))

    expect(await screen.findByText(i18n.t('common.errors.network'))).toBeInTheDocument()
    // The dialog must stay usable: the retry button is enabled again.
    expect(screen.getByRole('button', { name: i18n.t('board.confirm') })).toBeEnabled()
    expect(onOpenChange).not.toHaveBeenCalled()
  })

  it('withdraws the candidate from the close choice with a reason', async () => {
    moveStageMock.mockResolvedValue({ status: 200 })
    renderDialog({ mode: 'choice', target: null, targetStage: 'closed' })

    await userEvent.click(screen.getByRole('button', { name: i18n.t('board.withdrawAction') }))
    await userEvent.type(screen.getByLabelText(i18n.t('board.reason')), 'candidate left')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('board.confirmWithdraw') }))

    expect(moveStageMock).toHaveBeenCalledWith('app-1', {
      target: 'withdrawn',
      reason: 'candidate left',
    })
  })

  it('opens the override flow from the close choice', async () => {
    evaluationState.data = {
      id: 'eval-1',
      s_tech: 0.62,
      policy: { decision: 'hitl_soft_rejection' },
    }
    renderDialog({ mode: 'choice', target: null, targetStage: 'closed' })

    await userEvent.click(screen.getByRole('button', { name: i18n.t('board.rejectAction') }))

    expect(screen.getByText(i18n.t('review.title'))).toBeInTheDocument()
  })

  it('refuses the sign-off when the application has no evaluation', async () => {
    evaluationState.data = null
    renderDialog({ mode: 'choice', target: null, targetStage: 'closed' })

    await userEvent.click(screen.getByRole('button', { name: i18n.t('board.rejectAction') }))

    expect(screen.getByText(i18n.t('board.errors.notEvaluated'))).toBeInTheDocument()
    expect(screen.queryByText(i18n.t('review.title'))).not.toBeInTheDocument()
  })
})
