import { beforeEach, describe, expect, it } from 'vitest'

import type { ChatReply } from './chatApi'
import { chatThreadActions, getChatThread, useChatStore } from './chatStore'

const REPLY: ChatReply = {
  conversation_id: 'c-1',
  workspace: 'leave',
  route_reason: 'keyword',
  matched_keywords: ['cuti'],
  handoff_options: ['payroll'],
  answer: 'Saldo cuti Anda 12 hari.',
  citations: ['leave-policy.md#saldo'],
  escalate: false,
}

beforeEach(() => {
  useChatStore.setState({ threads: {} })
})

describe('chatThreadActions', () => {
  it('keeps separate scopes isolated', () => {
    chatThreadActions.appendUser('policy', 'halo')
    chatThreadActions.appendUser('hiring', 'hiring question')

    expect(getChatThread('policy').messages).toHaveLength(1)
    expect(getChatThread('hiring').messages[0]?.text).toBe('hiring question')
  })

  it('resolves a reply with conversation, citations, and handoff options', () => {
    chatThreadActions.appendUser('policy', 'berapa saldo cuti saya?')
    chatThreadActions.begin('policy')
    chatThreadActions.resolve('policy', REPLY)

    const thread = getChatThread('policy')
    expect(thread.pending).toBe(false)
    expect(thread.conversationId).toBe('c-1')
    const answer = thread.messages[1]
    expect(answer?.role).toBe('assistant')
    expect(answer?.citations).toEqual(['leave-policy.md#saldo'])
    expect(answer?.handoffOptions).toEqual(['payroll'])
  })

  it('renders deltas into one placeholder and lets the final reply replace it', () => {
    chatThreadActions.appendUser('policy', 'cuti?')
    chatThreadActions.begin('policy')
    chatThreadActions.appendDelta('policy', 'Saldo ')
    chatThreadActions.appendDelta('policy', 'cuti Anda 12 hari.')

    const streaming = getChatThread('policy').messages.at(-1)
    expect(streaming?.text).toBe('Saldo cuti Anda 12 hari.')
    expect(streaming?.streaming).toBe(true)

    chatThreadActions.resolve('policy', REPLY)

    const thread = getChatThread('policy')
    // The grounded answer replaces the streamed guess; it is not appended after it.
    expect(thread.messages).toHaveLength(2)
    expect(thread.messages.at(-1)?.streaming).toBe(false)
    expect(thread.messages.at(-1)?.text).toBe(REPLY.answer)
  })

  it('records failures without dropping the thread', () => {
    chatThreadActions.appendUser('policy', 'hai')
    chatThreadActions.begin('policy')
    chatThreadActions.fail('policy', 'boom')

    const thread = getChatThread('policy')
    expect(thread.pending).toBe(false)
    expect(thread.error).toBe('boom')
    expect(thread.messages).toHaveLength(1)
  })

  it('restarts the conversation with a visible notice', () => {
    chatThreadActions.appendUser('policy', 'hai')
    chatThreadActions.begin('policy')
    chatThreadActions.resolve('policy', REPLY)
    chatThreadActions.restart('policy', 'New subject')

    const thread = getChatThread('policy')
    expect(thread.conversationId).toBeNull()
    expect(thread.messages.at(-1)?.role).toBe('system')
  })

  it('marks a handoff target once queued', () => {
    chatThreadActions.appendUser('policy', 'hai')
    chatThreadActions.begin('policy')
    chatThreadActions.resolve('policy', REPLY)

    const answer = getChatThread('policy').messages[1]
    expect(answer).toBeDefined()
    chatThreadActions.markHandedOff('policy', answer!.id, 'payroll')

    expect(getChatThread('policy').messages[1]?.handedOffTo).toEqual(['payroll'])
  })
})
