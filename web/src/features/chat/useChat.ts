import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { WorkspaceId } from '@/lib/workspaces'

import { requestHandoff, streamHr } from './chatApi'
import { chatThreadActions, getChatThread, useChatThread } from './chatStore'

export function useChat(scope: string, workspace?: WorkspaceId) {
  const { t } = useTranslation()
  const thread = useChatThread(scope)
  const [routing, setRouting] = useState<WorkspaceId | null>(null)

  async function send(text: string): Promise<void> {
    const message = text.trim()
    const current = getChatThread(scope)
    if (message === '' || current.pending) {
      return
    }

    chatThreadActions.appendUser(scope, message)
    chatThreadActions.begin(scope)
    setRouting(null)

    const callbacks = {
      onRouting: (decision: { workspace: WorkspaceId }) => setRouting(decision.workspace),
    }
    let result = await streamHr(
      { message, workspace, conversationId: current.conversationId },
      callbacks,
    )

    // A conversation is pinned to its workspace server-side. When routing moves
    // to another department, we visibly restart the context instead of leaking
    // one workspace's history into another (chat is read-only, so retry is safe).
    if (result.status === 409) {
      chatThreadActions.restart(scope, t('chat.newSubject'))
      setRouting(null)
      result = await streamHr({ message, workspace }, callbacks)
    }

    setRouting(null)
    if (result.status !== 200 || result.reply === undefined) {
      chatThreadActions.fail(scope, t('chat.error'))
      return
    }
    chatThreadActions.resolve(scope, result.reply)
  }

  async function handOff(
    input: { text: string; source?: WorkspaceId; messageId: string },
    target: WorkspaceId,
  ): Promise<boolean> {
    const ok = await requestHandoff({
      message: input.text,
      source: input.source ?? workspace ?? 'policy',
      target,
    })
    if (ok) {
      chatThreadActions.markHandedOff(scope, input.messageId, target)
    }
    return ok
  }

  return { thread, send, handOff, routing }
}
