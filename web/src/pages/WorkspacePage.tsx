import { useTranslation } from 'react-i18next'
import { Navigate, useParams, useSearchParams } from 'react-router'

import { EmptyState } from '@/components/feedback/EmptyState'
import { ThreeRooms, type RoomId } from '@/components/three-rooms/ThreeRooms'
import { ChatPanel } from '@/features/chat/ChatPanel'
import { useWorkspaces, workspaceName } from '@/features/workspaces/useWorkspaces'
import { isWorkspaceId, WORKSPACE_ICONS } from '@/lib/workspaces'

const ROOMS: RoomId[] = ['board', 'queue', 'chat']

function isRoom(value: string | null): value is RoomId {
  return value !== null && (ROOMS as string[]).includes(value)
}

export function WorkspacePage() {
  const { t, i18n } = useTranslation()
  const { workspaceId } = useParams()
  const [searchParams] = useSearchParams()
  const { data: workspaces } = useWorkspaces()

  if (!isWorkspaceId(workspaceId)) {
    return <Navigate to="/" replace />
  }

  const requestedRoom = searchParams.get('room')
  const defaultRoom: RoomId = isRoom(requestedRoom) ? requestedRoom : 'board'
  const Icon = WORKSPACE_ICONS[workspaceId]
  const name = workspaceName(
    workspaces,
    workspaceId,
    i18n.language,
    t(`workspaces.${workspaceId}.name`),
  )

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <Icon aria-hidden="true" className="text-ink-muted size-5" />
        <h1 className="text-ink-strong text-2xl font-semibold">{name}</h1>
      </div>

      <ThreeRooms
        key={defaultRoom}
        defaultRoom={defaultRoom}
        board={<EmptyState title={t('workspace.boardPlaceholder', { name })} />}
        queue={<EmptyState title={t('workspace.queuePlaceholder')} />}
        chat={workspaceId === 'policy' ? <ChatPanel /> : <ChatPanel workspace={workspaceId} />}
      />
    </div>
  )
}
