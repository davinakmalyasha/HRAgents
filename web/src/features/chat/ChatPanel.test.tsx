import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

import type { ChatReply } from './chatApi'
import { ChatPanel } from './ChatPanel'
import { chatThreadActions, useChatStore } from './chatStore'

vi.mock('./chatApi', () => ({
  streamHr: vi.fn(),
  requestHandoff: vi.fn(),
}))

import { requestHandoff, streamHr } from './chatApi'

const streamMock = vi.mocked(streamHr)
const requestHandoffMock = vi.mocked(requestHandoff)

function answering(reply: ChatReply) {
  streamMock.mockImplementation(async (_input, callbacks) => {
    callbacks.onRouting?.({
      workspace: reply.workspace,
      reason: 'keyword',
      matched_keywords: [],
      handoff_options: [],
    })
    callbacks.onReply?.(reply)
    return { status: 200, reply }
  })
}

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
  streamMock.mockReset()
  requestHandoffMock.mockReset()
})

describe('ChatPanel', () => {
  it('sends a message and renders the grounded answer with citations', async () => {
    answering(REPLY)
    render(<ChatPanel />)

    await userEvent.type(screen.getByRole('textbox', { name: i18n.t('chat.placeholder') }), 'cuti?')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('chat.send') }))

    expect(await screen.findByText(REPLY.answer)).toBeInTheDocument()
    expect(screen.getByRole('list', { name: i18n.t('chat.citations') })).toHaveTextContent(
      'leave-policy.md#saldo',
    )
    expect(streamMock).toHaveBeenCalledWith(
      { message: 'cuti?', workspace: undefined, conversationId: null },
      expect.objectContaining({ onRouting: expect.any(Function) }),
    )
  })

  it('restarts the conversation visibly when routing crosses workspaces (409)', async () => {
    streamMock
      .mockResolvedValueOnce({ status: 409 })
      .mockResolvedValueOnce({ status: 200, reply: { ...REPLY, workspace: 'payroll' } })

    render(<ChatPanel />)
    await userEvent.type(screen.getByRole('textbox', { name: i18n.t('chat.placeholder') }), 'gaji?')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('chat.send') }))

    expect(await screen.findByText(i18n.t('chat.newSubject'))).toBeInTheDocument()
    expect(await screen.findByText(REPLY.answer)).toBeInTheDocument()
    expect(streamMock).toHaveBeenCalledTimes(2)
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

  it('names the routed workspace while the answer is pending', async () => {
    let finish: (result: { status: number; reply: ChatReply }) => void = () => {}
    streamMock.mockImplementation(async (_input, callbacks) => {
      callbacks.onRouting?.({
        workspace: 'leave',
        reason: 'keyword',
        matched_keywords: ['cuti'],
        handoff_options: [],
      })
      return new Promise((resolve) => {
        finish = resolve
      })
    })
    render(<ChatPanel />)

    await userEvent.type(screen.getByRole('textbox', { name: i18n.t('chat.placeholder') }), 'cuti?')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('chat.send') }))

    expect(
      await screen.findByText(
        i18n.t('chat.routing', { workspace: i18n.t('workspaces.leave.name') }),
      ),
    ).toBeInTheDocument()

    await act(async () => {
      finish({ status: 200, reply: REPLY })
    })
    expect(await screen.findByText(REPLY.answer)).toBeInTheDocument()
  })
})
