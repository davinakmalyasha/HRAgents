import { create } from 'zustand'

import type { WorkspaceId } from '@/lib/workspaces'

import type { ChatReply } from './chatApi'

export type ChatRole = 'user' | 'assistant' | 'system'

export interface ChatMessage {
  id: string
  role: ChatRole
  text: string
  citations: string[]
  escalate: boolean
  workspace?: WorkspaceId
  handoffOptions: WorkspaceId[]
  handedOffTo: WorkspaceId[]
}

export interface ChatThread {
  conversationId: string | null
  messages: ChatMessage[]
  pending: boolean
  error: string | null
}

export const EMPTY_THREAD: ChatThread = {
  conversationId: null,
  messages: [],
  pending: false,
  error: null,
}

interface ChatState {
  threads: Record<string, ChatThread>
}

export const useChatStore = create<ChatState>(() => ({ threads: {} }))

export function useChatThread(scope: string): ChatThread {
  return useChatStore((state) => state.threads[scope] ?? EMPTY_THREAD)
}

export function getChatThread(scope: string): ChatThread {
  return useChatStore.getState().threads[scope] ?? EMPTY_THREAD
}

function updateThread(scope: string, update: (thread: ChatThread) => ChatThread): void {
  useChatStore.setState((state) => ({
    threads: {
      ...state.threads,
      [scope]: update(state.threads[scope] ?? EMPTY_THREAD),
    },
  }))
}

function messageId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `m-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export const chatThreadActions = {
  appendUser(scope: string, text: string): void {
    updateThread(scope, (thread) => ({
      ...thread,
      error: null,
      messages: [
        ...thread.messages,
        {
          id: messageId(),
          role: 'user',
          text,
          citations: [],
          escalate: false,
          handoffOptions: [],
          handedOffTo: [],
        },
      ],
    }))
  },

  begin(scope: string): void {
    updateThread(scope, (thread) => ({ ...thread, pending: true, error: null }))
  },

  resolve(scope: string, reply: ChatReply): void {
    updateThread(scope, (thread) => ({
      ...thread,
      conversationId: reply.conversation_id,
      pending: false,
      error: null,
      messages: [
        ...thread.messages,
        {
          id: messageId(),
          role: 'assistant',
          text: reply.answer,
          citations: reply.citations,
          escalate: reply.escalate,
          workspace: reply.workspace,
          handoffOptions: reply.handoff_options,
          handedOffTo: [],
        },
      ],
    }))
  },

  fail(scope: string, detail: string): void {
    updateThread(scope, (thread) => ({ ...thread, pending: false, error: detail }))
  },

  restart(scope: string, notice: string): void {
    updateThread(scope, (thread) => ({
      ...thread,
      conversationId: null,
      messages: [
        ...thread.messages,
        {
          id: messageId(),
          role: 'system',
          text: notice,
          citations: [],
          escalate: false,
          handoffOptions: [],
          handedOffTo: [],
        },
      ],
    }))
  },

  markHandedOff(scope: string, messageIdToMark: string, target: WorkspaceId): void {
    updateThread(scope, (thread) => ({
      ...thread,
      messages: thread.messages.map((message) =>
        message.id === messageIdToMark
          ? { ...message, handedOffTo: [...message.handedOffTo, target] }
          : message,
      ),
    }))
  },

  clear(scope: string): void {
    useChatStore.setState((state) => {
      const threads = { ...state.threads }
      delete threads[scope]
      return { threads }
    })
  },
}
