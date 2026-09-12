import { cn } from 'cn'
import { useState, type FormEvent, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge } from '@/components/status/StatusBadge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import type { WorkspaceId } from '@/lib/workspaces'

import { HandoffButtons } from './HandoffButtons'
import type { ChatMessage } from './chatStore'
import { useChat } from './useChat'

interface ChatPanelProps {
  workspace?: WorkspaceId
}

function MessageRow({
  scope,
  workspace,
  message,
  requestText,
}: {
  scope: string
  workspace?: WorkspaceId
  message: ChatMessage
  requestText: string
}) {
  const { t } = useTranslation()

  if (message.role === 'system') {
    return <p className="text-2xs text-ink-muted text-center">{message.text}</p>
  }

  const isUser = message.role === 'user'
  return (
    <div className={cn('flex flex-col gap-1', isUser ? 'items-end' : 'items-start')}>
      <div
        className={cn(
          'border-line max-w-[85%] rounded-lg border px-3 py-2 text-sm whitespace-pre-wrap',
          isUser ? 'bg-surface-subtle' : 'bg-surface',
        )}
      >
        {message.text}
      </div>

      {!isUser && message.escalate ? (
        <StatusBadge tone="waiting" labelKey="chat.escalated" />
      ) : null}

      {!isUser && message.citations.length > 0 ? (
        <ul aria-label={t('chat.citations')} className="flex flex-wrap gap-1">
          {message.citations.map((citation) => (
            <li
              key={citation}
              className="border-line text-2xs text-ink-muted rounded-sm border px-1.5 py-0.5 font-mono"
            >
              {citation}
            </li>
          ))}
        </ul>
      ) : null}

      {!isUser && message.handoffOptions.length > 0 ? (
        <HandoffButtons
          scope={scope}
          workspace={workspace}
          message={message}
          requestText={requestText}
        />
      ) : null}
    </div>
  )
}

/** The user request a reply answered — what a handoff should carry. */
function precedingUserText(messages: ChatMessage[], index: number): string {
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    const candidate = messages[cursor]
    if (candidate?.role === 'user') {
      return candidate.text
    }
  }
  return ''
}

/** Workspace-bounded chat. Policy (Ask HR) uses the front door; others hint their workspace. */
export function ChatPanel({ workspace }: ChatPanelProps) {
  const { t } = useTranslation()
  const scope = workspace ?? 'policy'
  const { thread, send } = useChat(scope, workspace)
  const [draft, setDraft] = useState('')

  function submit() {
    const text = draft.trim()
    if (text === '' || thread.pending) {
      return
    }
    setDraft('')
    void send(text)
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    submit()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {thread.messages.length === 0 ? (
        <EmptyState title={t('chat.empty')} />
      ) : (
        <ol aria-live="polite" className="flex flex-col gap-4">
          {thread.messages.map((message, index) => (
            <li key={message.id}>
              <MessageRow
                scope={scope}
                workspace={workspace}
                message={message}
                requestText={precedingUserText(thread.messages, index)}
              />
            </li>
          ))}
        </ol>
      )}

      {thread.pending ? (
        <p role="status" className="text-2xs text-ink-muted">
          {t('chat.thinking')}
        </p>
      ) : null}

      {thread.error ? (
        <p role="alert" className="text-2xs text-error flex items-center gap-1">
          <span aria-hidden="true">●</span>
          {thread.error}
        </p>
      ) : null}

      <form onSubmit={handleSubmit} className="flex items-end gap-2">
        <Textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t('chat.placeholder')}
          aria-label={t('chat.placeholder')}
          rows={1}
          className="min-h-9 flex-1"
        />
        <Button type="submit" size="sm" disabled={thread.pending || draft.trim() === ''}>
          {t('chat.send')}
        </Button>
      </form>
    </div>
  )
}
