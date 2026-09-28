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
  previewRejectionMessage: vi.fn(),
  queueOfferMessage: vi.fn(),
  markCommunicationSent: vi.fn(),
  listReplies: vi.fn(),
  composeDispatchLink: vi.fn(),
}))

import {
  composeDispatchLink,
  markCommunicationSent,
  previewRejectionMessage,
  queueOfferMessage,
  queueRejectionMessage,
  type CommunicationPreview,
} from './communicationApi'
import { CommunicationPanel } from './CommunicationPanel'

const queueRejectionMock = vi.mocked(queueRejectionMessage)
const previewMock = vi.mocked(previewRejectionMessage)
const queueOfferMock = vi.mocked(queueOfferMessage)
const markSentMock = vi.mocked(markCommunicationSent)
const composeLinkMock = vi.mocked(composeDispatchLink)

function preview(overrides: Partial<CommunicationPreview> = {}): CommunicationPreview {
  return {
    kind: 'rejection',
    can_queue: true,
    blockers: [],
    candidate_id: 'cand-1',
    application_id: 'app-1',
    evaluation_id: 'eval-1',
    language: 'en',
    subject: 'Your application for Backend Engineer',
    body: 'Where to strengthen:\n- more concrete evidence',
    recipient: null,
    recipient_phone: null,
    channel: 'email',
    ...overrides,
  }
}

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
    recipient_phone: null,
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
  previewMock.mockReset()
  queueOfferMock.mockReset()
  markSentMock.mockReset()
  composeLinkMock.mockReset()
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

  it('previews a rejection message before anything is queued', async () => {
    state.overrides = [override()]
    previewMock.mockResolvedValue({ status: 200, preview: preview() })
    queueRejectionMock.mockResolvedValue({ status: 201, communication: communication() })
    renderPanel('hitl_soft_rejection')

    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.queueRejection') }),
    )
    await userEvent.type(screen.getByLabelText(i18n.t('communication.fields.by')), 'lead-1')
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.previewAction') }),
    )

    // The preview rendered the body; the queue endpoint has not been touched.
    expect(previewMock).toHaveBeenCalledWith('cand-1', {
      by: 'lead-1',
      language: 'en',
      channel: 'email',
      to_email: null,
      to_phone: null,
    })
    expect(queueRejectionMock).not.toHaveBeenCalled()
    expect(screen.getByText(/Where to strengthen/)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: i18n.t('communication.queueAfterPreview') }),
    ).toBeInTheDocument()

    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.queueAfterPreview') }),
    )

    expect(queueRejectionMock).toHaveBeenCalledWith('cand-1', {
      by: 'lead-1',
      language: 'en',
      channel: 'email',
      to_email: null,
      to_phone: null,
    })
    expect(previewMock).toHaveBeenCalledTimes(1)
  })

  it('re-previews when a field that shapes the message changes', async () => {
    state.overrides = [override()]
    previewMock.mockResolvedValue({ status: 200, preview: preview() })
    queueRejectionMock.mockResolvedValue({ status: 201, communication: communication() })
    renderPanel('hitl_soft_rejection')

    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.queueRejection') }),
    )
    await userEvent.type(screen.getByLabelText(i18n.t('communication.fields.by')), 'lead-1')
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.previewAction') }),
    )
    expect(
      screen.getByRole('button', { name: i18n.t('communication.queueAfterPreview') }),
    ).toBeInTheDocument()

    await userEvent.click(screen.getByLabelText(i18n.t('communication.fields.toEmail')))
    await userEvent.type(
      screen.getByLabelText(i18n.t('communication.fields.toEmail')),
      'budi@example.com',
    )

    // A stale preview is never queueable: the button goes back to previewing.
    expect(
      screen.getByRole('button', { name: i18n.t('communication.previewAction') }),
    ).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.previewAction') }),
    )
    expect(previewMock).toHaveBeenLastCalledWith('cand-1', {
      by: 'lead-1',
      language: 'en',
      channel: 'email',
      to_email: 'budi@example.com',
      to_phone: null,
    })
  })

  it('shows the server blockers and refuses to queue behind them', async () => {
    state.overrides = [override()]
    previewMock.mockResolvedValue({
      status: 200,
      preview: preview({
        can_queue: false,
        blockers: ['an active rejection message already exists for this candidate'],
        body: null,
        subject: null,
      }),
    })
    renderPanel('hitl_soft_rejection')

    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.queueRejection') }),
    )
    await userEvent.type(screen.getByLabelText(i18n.t('communication.fields.by')), 'lead-1')
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.previewAction') }),
    )

    expect(
      screen.getByText('an active rejection message already exists for this candidate'),
    ).toBeInTheDocument()
    const queueButton = screen.getByRole('button', {
      name: i18n.t('communication.queueAfterPreview'),
    })
    expect(queueButton).toBeDisabled()
    queueRejectionMock.mockClear()
    await userEvent.click(queueButton)
    expect(queueRejectionMock).not.toHaveBeenCalled()
  })

  it('re-previews when the queue is refused after a good preview', async () => {
    state.overrides = [override()]
    previewMock.mockResolvedValueOnce({ status: 200, preview: preview() })
    previewMock.mockResolvedValueOnce({
      status: 200,
      preview: preview({
        can_queue: false,
        blockers: ['an active rejection message already exists for this candidate'],
        body: null,
        subject: null,
      }),
    })
    queueRejectionMock.mockResolvedValue({ status: 409 })
    renderPanel('hitl_soft_rejection')

    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.queueRejection') }),
    )
    await userEvent.type(screen.getByLabelText(i18n.t('communication.fields.by')), 'lead-1')
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.previewAction') }),
    )
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.queueAfterPreview') }),
    )

    // Someone else queued in between: the dialog re-previews instead of showing
    // a bare conflict, and the human sees the new blocker.
    expect(previewMock).toHaveBeenCalledTimes(2)
    expect(
      screen.getByText('an active rejection message already exists for this candidate'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: i18n.t('communication.queueAfterPreview') }),
    ).toBeDisabled()
    expect(queueRejectionMock).toHaveBeenCalledTimes(1)
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
    previewMock.mockResolvedValue({
      status: 200,
      preview: preview({ recipient: 'budi@example.com' }),
    })
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
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.previewAction') }),
    )
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.queueAfterPreview') }),
    )

    expect(queueRejectionMock).toHaveBeenCalledWith('cand-1', {
      by: 'lead-1',
      language: 'en',
      channel: 'email',
      to_email: 'budi@example.com',
      to_phone: null,
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

  it('composes a WhatsApp link and still leaves the message queued until recorded', async () => {
    state.communications = [
      communication({ kind: 'offer', channel: 'whatsapp', recipient_phone: '0812-3456-7890' }),
    ]
    composeLinkMock.mockResolvedValue({
      status: 200,
      link: {
        communication_id: 'comm-1',
        provider: 'whatsapp.manual_links',
        phone: '6281234567890',
        url: 'https://wa.me/6281234567890?text=Offer',
        body: 'We would like to offer you the role.',
      },
    })
    markSentMock.mockResolvedValue({ status: 200, communication: communication() })
    renderPanel()

    await userEvent.click(screen.getByRole('button', { name: i18n.t('communication.composeLink') }))
    await userEvent.click(screen.getByRole('button', { name: i18n.t('communication.composeLink') }))

    expect(composeLinkMock).not.toHaveBeenCalled()
    expect(screen.getByText(i18n.t('communication.errors.byRequired'))).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText(i18n.t('communication.fields.by')), 'Sinta Prabowo')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('communication.composeLink') }))

    expect(composeLinkMock).toHaveBeenCalledWith('comm-1', 'Sinta Prabowo', undefined)
    expect(
      await screen.findByRole('link', { name: i18n.t('communication.openWhatsapp') }),
    ).toHaveAttribute('href', 'https://wa.me/6281234567890?text=Offer')

    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('communication.recordAfterLink') }),
    )

    expect(markSentMock).toHaveBeenCalledWith('comm-1', 'Sinta Prabowo')
  })

  it('offers a WhatsApp link action only on WhatsApp messages', () => {
    state.communications = [communication()]
    renderPanel()

    expect(
      screen.queryByRole('button', { name: i18n.t('communication.composeLink') }),
    ).not.toBeInTheDocument()
  })
})
