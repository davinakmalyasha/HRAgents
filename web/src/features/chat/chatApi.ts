import { api } from '@/lib/api'
import { storedApiKey } from '@/lib/auth'
import type { WorkspaceId } from '@/lib/workspaces'
import type { components } from '@/api/schema'

export type ChatReply = components['schemas']['ChatReplyView']

export interface AskResult {
  status: number
  reply?: ChatReply
}

export interface ChatRouting {
  workspace: WorkspaceId
  reason: string
  matched_keywords: string[]
  handoff_options: WorkspaceId[]
}

export interface StreamCallbacks {
  onRouting?: (routing: ChatRouting) => void
  onReply?: (reply: ChatReply) => void
}

export async function askHr(input: {
  message: string
  workspace?: WorkspaceId
  conversationId?: string | null
}): Promise<AskResult> {
  const { data, response } = await api.POST('/v1/chat', {
    body: {
      message: input.message,
      workspace: input.workspace,
      conversation_id: input.conversationId ?? undefined,
    },
  })
  return { status: response.status, reply: data }
}

export async function requestHandoff(input: {
  message: string
  source: WorkspaceId
  target: WorkspaceId
}): Promise<boolean> {
  const { response } = await api.POST('/v1/chat/handoffs', {
    body: {
      message: input.message,
      source_workspace: input.source,
      target_workspace: input.target,
    },
  })
  return response.ok
}

/**
 * Ask HR over the SSE route, so the routed workspace can be named before the
 * answer. Uses `fetch` rather than EventSource because the credential is a
 * header, and parses the stream by hand for the same reason.
 */
export async function streamHr(
  input: {
    message: string
    workspace?: WorkspaceId
    conversationId?: string | null
  },
  callbacks: StreamCallbacks,
): Promise<AskResult> {
  const params = new URLSearchParams({ message: input.message })
  if (input.workspace !== undefined) params.set('workspace', input.workspace)
  if (input.conversationId) params.set('conversation_id', input.conversationId)
  const key = storedApiKey()
  const headers: Record<string, string> = { Accept: 'text/event-stream' }
  if (key !== null) headers['X-API-Key'] = key

  const response = await fetch(`/v1/chat/stream?${params.toString()}`, { headers })
  if (!response.ok || response.body === null) {
    return { status: response.status }
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let reply: ChatReply | undefined
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf('\n\n')
      const event = /^event: (.+)$/m.exec(frame)?.[1]
      const data = /^data: (.+)$/m.exec(frame)?.[1]
      if (event === undefined || data === undefined) continue
      if (event === 'routing') {
        callbacks.onRouting?.(JSON.parse(data) as ChatRouting)
      } else if (event === 'reply') {
        reply = JSON.parse(data) as ChatReply
        callbacks.onReply?.(reply)
      } else if (event === 'error') {
        return { status: 502 }
      }
    }
  }
  return { status: response.status, reply }
}
