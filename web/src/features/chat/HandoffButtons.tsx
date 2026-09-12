import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { StatusBadge } from '@/components/status/StatusBadge'
import { Button } from '@/components/ui/button'
import type { WorkspaceId } from '@/lib/workspaces'

import type { ChatMessage } from './chatStore'
import { useChat } from './useChat'

interface HandoffButtonsProps {
  scope: string
  workspace?: WorkspaceId
  message: ChatMessage
  requestText: string
}

export function HandoffButtons({ scope, workspace, message, requestText }: HandoffButtonsProps) {
  const { t } = useTranslation()
  const { handOff } = useChat(scope, workspace)

  const pending = message.handoffOptions.filter((option) => !message.handedOffTo.includes(option))
  if (pending.length === 0 || requestText === '') {
    return null
  }

  async function handleHandOff(target: WorkspaceId) {
    const ok = await handOff(
      { text: requestText, source: message.workspace, messageId: message.id },
      target,
    )
    if (ok) {
      toast.success(t('chat.handoff.queued', { workspace: t(`workspaces.${target}.name`) }))
    } else {
      toast.error(t('chat.handoff.failed'))
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <StatusBadge tone="waiting" labelKey="chat.handoff.title" />
      {pending.map((target) => (
        <Button
          key={target}
          variant="outline"
          size="xs"
          onClick={() => {
            void handleHandOff(target)
          }}
        >
          {t('chat.handoff.action', { workspace: t(`workspaces.${target}.name`) })}
        </Button>
      ))}
    </div>
  )
}
