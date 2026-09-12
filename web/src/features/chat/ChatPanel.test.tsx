import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

import type { ChatReply } from './chatApi'
import { ChatPanel } from './ChatPanel'
import { chatThreadActions, useChatStore } from './chatStore'

vi.mock('./chatApi', () => ({
  askHr: vi.fn(),
  requestHandoff: vi.fn(),
}))

import { askHr, requestHandoff } from './chatApi'

const askHrMock = vi.mocked(askHr)
const requestHandoffMock = vi.mocked(requestHandoff)

const REPLY: ChatReply = {
  conversation_id: 'c-1',
  workspace: 'leave',
  route_reason: 'keyword',
  matched_keywords: ['cuti'],
  handoff_options: [],
  answer: 'Saldo cuti Anda 12 hari.',
  citations: ['leave-policy.md#saldo'],
  escalate: false,
}

beforeEach(() => {
  useChatStore.setState({ threads: {} })
  askHrMock.mockReset()
  requestHandoffMock.mockReset()
})

describe('ChatPanel', () => {
  it('sends a message and renders the grounded answer with citations', async () => {
    askHrMock.mockResolvedValue({ status: 200, reply: REPLY })
    render(<ChatPanel />)

    await userEvent.type(screen.getByRole('textbox', { name: i18n.t('chat.placeholder') }), 'cuti?')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('chat.send') }))

    expect(await screen.findByText(REPLY.answer)).toBeInTheDocument()
    expect(screen.getByRole('list', { name: i18n.t('chat.citations') })).toHaveTextContent(
      'leave-policy.md#saldo',
    )
    expect(askHrMock).toHaveBeenCalledWith({
      message: 'cuti?',
      workspace: undefined,
      conversationId: null,
    })
  })

  it('restarts the conversation visibly when routing crosses workspaces (409)', async () => {
    askHrMock
      .mockResolvedValueOnce({ status: 409 })
      .mockResolvedValueOnce({ status: 200, reply: { ...REPLY, workspace: 'payroll' } })

    render(<ChatPanel />)
    await userEvent.type(screen.getByRole('textbox', { name: i18n.t('chat.placeholder') }), 'gaji?')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('chat.send') }))

    expect(await screen.findByText(i18n.t('chat.newSubject'))).toBeInTheDocument()
    expect(await screen.findByText(REPLY.answer)).toBeInTheDocument()
    expect(askHrMock).toHaveBeenCalledTimes(2)
  })

  it('shows escalations with icon and label', () => {
    chatThreadActions.appendUser('policy', 'hai')
    chatThreadActions.resolve('policy', {
      ...REPLY,
      escalate: true,
      citations: [],
    })
    render(<ChatPanel />)

    const status = screen.getByText(i18n.t('chat.escalated'))
    expect(status).toBeInTheDocument()
    expect(status.parentElement?.textContent).toContain('▲')
  })

  it('queues a handoff and hides the used action', async () => {
    requestHandoffMock.mockResolvedValue(true)
    chatThreadActions.appendUser('policy', 'tolong siapkan onboarding Budi')
    chatThreadActions.resolve('policy', {
      ...REPLY,
      handoff_options: ['onboarding'],
    })
    render(<ChatPanel />)

    const action = screen.getByRole('button', {
      name: i18n.t('chat.handoff.action', { workspace: i18n.t('workspaces.onboarding.name') }),
    })
    await userEvent.click(action)

    expect(requestHandoffMock).toHaveBeenCalledWith({
      message: 'tolong siapkan onboarding Budi',
      source: 'leave',
      target: 'onboarding',
    })
    expect(
      screen.queryByRole('button', {
        name: i18n.t('chat.handoff.action', { workspace: i18n.t('workspaces.onboarding.name') }),
      }),
    ).not.toBeInTheDocument()
  })

  it('shows a thinking state and disables sending while pending', () => {
    chatThreadActions.appendUser('policy', 'hai')
    chatThreadActions.begin('policy')
    render(<ChatPanel />)

    expect(screen.getByText(i18n.t('chat.thinking'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: i18n.t('chat.send') })).toBeDisabled()
  })
})
