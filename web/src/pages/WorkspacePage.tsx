import { useTranslation } from 'react-i18next'
import { Navigate, useParams, useSearchParams } from 'react-router'

import { EmptyState } from '@/components/feedback/EmptyState'
import { ThreeRooms, type RoomId } from '@/components/three-rooms/ThreeRooms'
import { ChatPanel } from '@/features/chat/ChatPanel'
import { GrowthBoard, GrowthQueue } from '@/features/growth/GrowthWorkspace'
import { LeaveBoard, LeaveQueue } from '@/features/leave/LeaveWorkspace'
import { OffboardingBoard, OffboardingQueue } from '@/features/offboarding/OffboardingWorkspace'
import { PayrollBoard, PayrollQueue } from '@/features/payroll/PayrollWorkspace'
import { PipelineBoard } from '@/features/hiring/PipelineBoard'
import { ReviewQueue } from '@/features/hiring/ReviewQueue'
import { SchedulingView } from '@/features/hiring/SchedulingView'
import { OnboardingBoard } from '@/features/onboarding/OnboardingBoard'
import { OnboardingChecklist } from '@/features/onboarding/OnboardingChecklist'
import { RecordsBoard, RecordsQueue } from '@/features/records/RecordsWorkspace'
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
        board={
          workspaceId === 'hiring' ? (
            <PipelineBoard />
          ) : workspaceId === 'onboarding' ? (
            <OnboardingBoard />
          ) : workspaceId === 'records' ? (
            <RecordsBoard />
          ) : workspaceId === 'leave' ? (
            <LeaveBoard />
          ) : workspaceId === 'payroll' ? (
            <PayrollBoard />
          ) : workspaceId === 'offboarding' ? (
            <OffboardingBoard />
          ) : workspaceId === 'growth' ? (
            <GrowthBoard />
          ) : (
            <EmptyState title={t('workspace.boardPlaceholder', { name })} />
          )
        }
        queue={
          workspaceId === 'hiring' ? (
            <div className="flex flex-col gap-6">
              <section aria-labelledby="hiring-signoff" className="flex flex-col gap-3">
                <h2 id="hiring-signoff" className="text-ink-strong text-lg font-medium">
                  {t('review.title')}
                </h2>
                <ReviewQueue />
              </section>
              <SchedulingView />
            </div>
          ) : workspaceId === 'onboarding' ? (
            <OnboardingChecklist />
          ) : workspaceId === 'records' ? (
            <RecordsQueue />
          ) : workspaceId === 'leave' ? (
            <LeaveQueue />
          ) : workspaceId === 'payroll' ? (
            <PayrollQueue />
          ) : workspaceId === 'offboarding' ? (
            <OffboardingQueue />
          ) : workspaceId === 'growth' ? (
            <GrowthQueue />
          ) : (
            <EmptyState title={t('workspace.queuePlaceholder')} />
          )
        }
        chat={workspaceId === 'policy' ? <ChatPanel /> : <ChatPanel workspace={workspaceId} />}
      />
    </div>
  )
}
