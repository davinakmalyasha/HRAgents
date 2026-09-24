import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'
import type { components } from '@/api/schema'

type CommunicationView = components['schemas']['CommunicationView']
type OverrideView = components['schemas']['OverrideView']
type PolicyDecision = components['schemas']['PolicyDecision']
type ReplyView = components['schemas']['ReplyView']

const state = vi.hoisted(() => ({
  communications: [] as unknown[],
  overrides: [] as unknown[],
  replies: [] as unknown[],
}))

vi.mock('./useCommunications', () => ({
  useCommunications: () => ({ isLoading: false, data: state.communications }),
  useEvaluationOverrides: () => ({ isLoading: false, data: state.overrides }),
  useReplies: () => ({ isLoading: false, data: state.replies }),
}))

vi.mock('./communicationApi', () => ({
  queueRejectionMessage: vi.fn(),
  queueOfferMessage: vi.fn(),
  markCommunicationSent: vi.fn(),
  listReplies: vi.fn(),
}))

import { markCommunicationSent, queueOfferMessage, queueRejectionMessage } from './communicationApi'
import { CommunicationPanel } from './CommunicationPanel'

const queueRejectionMock = vi.mocked(queueRejectionMessage)
const queueOfferMock = vi.mocked(queueOfferMessage)
const markSentMock = vi.mocked(markCommunicationSent)

function communication(overrides: Partial<CommunicationView> = {}): CommunicationView {
  return {
    id: 'comm-1',
    candidate_id: 'cand-1',
    application_id: 'app-1',
    evaluation_id: 'eval-1',
    kind: 'rejection',
    channel: 'email',
    language: 'en',
    subject: 'Your application for Backend Engineer',
    body: 'Where to strengthen:\n- more concrete evidence',
    status: 'queued',
    approved_by: 'hr-admin',
    approved_at: '2026-09-20T03:00:00Z',
    sent_by: null,
    sent_at: null,
    recipient: null,
    provider: null,
    provider_message_id: null,
    send_attempts: 0,
    last_error: null,
    created_at: '2026-09-20T03:00:00Z',
    ...overrides,
  }
}

function reply(overrides: Partial<ReplyView> = {}): ReplyView {
  return {
    id: 'reply-1',
    candidate_id: 'cand-1',
    communication_id: 'comm-1',
    channel: 'email',
    sender: 'budi@example.com',
    subject: 'Re: Your offer',
    body: 'Saya tertarik, terima kasih.',
    provider: 'email.imap_poll',
    provider_message_id: '<reply-1@example.com>',
    received_at: '2026-09-22T02:15:00Z',
    ...overrides,
  }
}

function override(overrides: Partial<OverrideView> = {}): OverrideView {
  return {
    id: 'override-1',
    evaluation_id: 'eval-1',
    reviewer_id: 'lead-1',
    reviewer_role: 'engineering_lead',
    override_decision: 'hitl_soft_rejection',
    reason_code: 'below_bar',
    notes: null,
    decided_at: '2026-09-10T10:00:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  state.communications = []
  state.overrides = []
  state.replies = []
  queueRejectionMock.mockReset()
  queueOfferMock.mockReset()
  markSentMock.mockReset()
})

function renderPanel(policyDecision: PolicyDecision = 'reject_auto') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CommunicationPanel
        candidateId="cand-1"
        evaluationId="eval-1"
        policyDecision={policyDecision}
      />
    </QueryClientProvider>,
  )
}

describe('CommunicationPanel', () => {
  it('shows queued messages with their status and dispatch action', () => {
    state.communications = [communication()]
    renderPanel()

    expect(screen.getByText(i18n.t('communication.kinds.rejection'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('communication.statuses.queued'))).toBeInTheDocument()
    expect(screen.getByText(/more concrete evidence/)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: i18n.t('communication.markSent') }),
    ).toBeInTheDocument()
  })

  it('records dispatch evidence with a named actor', async () => {
    state.communications = [communication()]
    markSentMock.mockResolvedValue({
      status: 200,
      communication: communication({ status: 'sent' }),
    })
    renderPanel()

    await userEvent.click(screen.getByRole('button', { name: i18n.t('communication.markSent') }))
    await userEvent.click(screen.getByRole('button', { name: i18n.t('communication.confirmSent') }))

    expect(markSentMock).not.toHaveBeenCalled()
    expect(screen.getByText(i18n.t('communication.errors.byRequired'))).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText(i18n.t('communication.fields.by')), 'Sinta Prabowo')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('communication.confirmSent') }))

    expect(markSentMock).toHaveBeenCalledWith('comm-1', 'Sinta Prabowo')
  })

  it('locks rejection queueing until a decision is recorded', () => {
    renderPanel('hitl_soft_rejection')

    expect(
      screen.getByRole('button', { name: i18n.t('communication.queueRejection') }),
    ).toBeDisabled()
    expect(screen.getByText(i18n.t('communication.rejectionLocked'))).toBeInTheDocument()
  })

  it('queues a rejection message once the decision is recorded', async () => {
    state.overrides = [override()]
    queueRejectionMock.mockResolvedValue({ status: 201, communication: communication() })
    renderPanel('hitl_soft_rejection')

    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.queueRejection') }),
    )
    await userEvent.type(screen.getByLabelText(i18n.t('communication.fields.by')), 'lead-1')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('communication.confirm') }))

    expect(queueRejectionMock).toHaveBeenCalledWith('cand-1', {
      by: 'lead-1',
      language: 'en',
      channel: 'email',
      to_email: null,
    })
  })

  it('requires a body before queueing an offer and submits the authored message', async () => {
    queueOfferMock.mockResolvedValue({
      status: 201,
      communication: communication({ kind: 'offer', subject: null }),
    })
    renderPanel()

    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.composeOffer') }),
    )
    await userEvent.type(screen.getByLabelText(i18n.t('communication.fields.by')), 'hr-admin')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('communication.confirm') }))

    expect(queueOfferMock).not.toHaveBeenCalled()
    expect(screen.getByText(i18n.t('communication.errors.bodyRequired'))).toBeInTheDocument()

    await userEvent.type(
      screen.getByLabelText(i18n.t('communication.fields.body')),
      'We would like to offer you the role.',
    )
    await userEvent.click(screen.getByRole('button', { name: i18n.t('communication.confirm') }))

    expect(queueOfferMock).toHaveBeenCalledWith(
      'cand-1',
      expect.objectContaining({
        by: 'hr-admin',
        body: 'We would like to offer you the role.',
        subject: null,
        language: 'en',
        channel: 'email',
      }),
    )
  })

  it('captures the recipient address so a transport can deliver the message', async () => {
    state.overrides = [override()]
    queueRejectionMock.mockResolvedValue({ status: 201, communication: communication() })
    renderPanel('hitl_soft_rejection')

    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.queueRejection') }),
    )
    await userEvent.type(screen.getByLabelText(i18n.t('communication.fields.by')), 'lead-1')
    await userEvent.type(
      screen.getByLabelText(i18n.t('communication.fields.toEmail')),
      'budi@example.com',
    )
    await userEvent.click(screen.getByRole('button', { name: i18n.t('communication.confirm') }))

    expect(queueRejectionMock).toHaveBeenCalledWith('cand-1', {
      by: 'lead-1',
      language: 'en',
      channel: 'email',
      to_email: 'budi@example.com',
    })
  })

  it('shows a failed dispatch with the transport and the error, keeping it queued', () => {
    state.communications = [
      communication({
        recipient: 'budi@example.com',
        provider: 'email.smtp',
        send_attempts: 2,
        last_error: 'mailbox unavailable',
      }),
    ]
    renderPanel()

    expect(
      screen.getByText(
        i18n.t('communication.dispatchFailed', {
          provider: 'email.smtp',
          error: 'mailbox unavailable',
        }),
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: i18n.t('communication.markSent') })).toBeEnabled()
  })

  it('shows the provider evidence on a sent message', () => {
    state.communications = [
      communication({
        status: 'sent',
        sent_by: 'transport:email.smtp',
        sent_at: '2026-09-21T04:00:00Z',
        recipient: 'budi@example.com',
        provider: 'email.smtp',
        send_attempts: 1,
      }),
    ]
    renderPanel()

    expect(
      screen.getByText(
        i18n.t('communication.dispatchedVia', { provider: 'email.smtp', attempts: 1 }),
      ),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: i18n.t('communication.markSent') }),
    ).not.toBeInTheDocument()
  })

  it('lists captured replies as evidence', () => {
    state.replies = [reply()]
    renderPanel()

    expect(screen.getByText('Re: Your offer')).toBeInTheDocument()
    expect(screen.getByText(/Saya tertarik/)).toBeInTheDocument()
    expect(
      screen.getByText(i18n.t('communication.replyFrom', { address: 'budi@example.com' })),
    ).toBeInTheDocument()
    expect(
      screen.getByText(i18n.t('communication.replyVia', { provider: 'email.imap_poll' })),
    ).toBeInTheDocument()
  })

  it('shows an empty state when no replies were captured', () => {
    renderPanel()

    expect(screen.getByText(i18n.t('communication.repliesEmpty'))).toBeInTheDocument()
  })
})
