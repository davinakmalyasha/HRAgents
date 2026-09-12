import { useTranslation } from 'react-i18next'
import { Navigate, useParams } from 'react-router'

import { EmptyState } from '@/components/feedback/EmptyState'
import { ThreeRooms } from '@/components/three-rooms/ThreeRooms'
import { isWorkspaceId, WORKSPACE_ICONS } from '@/lib/workspaces'

export function WorkspacePage() {
  const { t } = useTranslation()
  const { workspaceId } = useParams()

  if (!isWorkspaceId(workspaceId)) {
    return <Navigate to="/" replace />
  }

  const Icon = WORKSPACE_ICONS[workspaceId]
  const name = t(`workspaces.${workspaceId}.name`)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <Icon aria-hidden="true" className="text-ink-muted size-5" />
        <h1 className="text-ink-strong text-2xl font-semibold">{name}</h1>
      </div>

      <ThreeRooms
        board={<EmptyState title={t('workspace.boardPlaceholder', { name })} />}
        queue={<EmptyState title={t('workspace.queuePlaceholder')} />}
        chat={<EmptyState title={t('workspace.chatPlaceholder', { name })} />}
      />
    </div>
  )
}
