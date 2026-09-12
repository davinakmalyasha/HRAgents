import { api } from '@/lib/api'
import type { WorkspaceId } from '@/lib/workspaces'
import type { components } from '@/api/schema'

export type ChatReply = components['schemas']['ChatReplyView']

export interface AskResult {
  status: number
  reply?: ChatReply
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
