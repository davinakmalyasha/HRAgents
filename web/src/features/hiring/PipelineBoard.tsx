import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { ScoreBar } from '@/components/status/ScoreBar'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from 'cn'

import { JobSelector } from './JobSelector'
import { StageMoveDialog } from './StageMoveDialog'
import {
  groupIntoStages,
  intentForDrop,
  shortId,
  waitingLabel,
  type ApplicationStatus,
  type ApplicationSummary,
  type PipelineColumn,
  type PipelineStage,
} from './pipeline'
import { useApplications, useJobs } from './useHiring'

interface StageMove {
  application: ApplicationSummary
  mode: 'move' | 'choice'
  target: ApplicationStatus | null
  targetStage: PipelineStage
}

function ApplicationCard({ application }: { application: ApplicationSummary }) {
  const { t } = useTranslation()
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: application.application_id,
  })

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      aria-label={t('board.dragLabel', { candidate: shortId(application.candidate_id) })}
      style={{ transform: CSS.Transform.toString(transform) }}
      className={isDragging ? 'opacity-60' : undefined}
    >
      <Link
        to={`/w/hiring/applications/${application.application_id}`}
        className="border-line bg-surface hover:border-line-strong flex flex-col gap-2 rounded-md border p-2.5 transition-colors"
      >
        <div className="flex items-center justify-between gap-2">
          <span className="text-2xs text-ink-strong font-mono">
            {shortId(application.candidate_id)}
          </span>
          <span className="text-2xs text-ink-muted">
            {t('hiring.waiting', { duration: waitingLabel(application.hours_waiting) })}
          </span>
        </div>

        {application.s_tech == null ? (
          <span className="text-2xs text-ink-muted">{t('hiring.notScored')}</span>
        ) : (
          <ScoreBar value={application.s_tech} label={t('hiring.score')} />
        )}

        <div className="text-2xs text-ink-muted flex items-center justify-between">
          <span>{t('hiring.priority')}</span>
          <span className="font-mono tabular-nums">{application.priority_score.toFixed(2)}</span>
        </div>
      </Link>
    </div>
  )
}

function PipelineColumnView({ column }: { column: PipelineColumn }) {
  const { t } = useTranslation()
  const { setNodeRef, isOver } = useDroppable({ id: column.stage })

  return (
    <section
      ref={setNodeRef}
      aria-label={t(`hiring.stages.${column.stage}`)}
      className={cn(
        'flex w-60 shrink-0 flex-col gap-2 rounded-lg p-2',
        isOver ? 'bg-background ring-ring ring-1' : 'bg-surface-subtle',
      )}
    >
      <header className="flex items-center justify-between px-1">
        <h3 className="text-ink-strong text-xs font-medium">
          {t(`hiring.stages.${column.stage}`)}
        </h3>
        <span className="text-2xs text-ink-muted font-mono">{column.items.length}</span>
      </header>

      {column.items.length === 0 ? (
        <p className="border-line text-2xs text-ink-muted rounded-md border border-dashed px-2 py-6 text-center">
          {t('hiring.emptyColumn')}
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {column.items.map((application) => (
            <ApplicationCard key={application.application_id} application={application} />
          ))}
        </div>
      )}
    </section>
  )
}

/**
 * Pipeline board with gated manual moves.
 *
 * Stages derive from deterministic statuses; a drop only *requests* a move —
 * `intentForDrop` routes it (reason dialog, close choice, or refusal) and the
 * stage endpoint validates the designed transition table, so dragging can
 * never bypass a HITL gate (docs/architecture/board-transitions.md).
 */
export function PipelineBoard() {
  const { t } = useTranslation()
  const [jobId, setJobId] = useState<string | null>(null)
  const [stageMove, setStageMove] = useState<StageMove | null>(null)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  )
  const jobs = useJobs()
  const applications = useApplications(jobId)

  if (applications.isLoading) {
    return <Skeleton className="h-64 w-full" />
  }

  const columns = groupIntoStages(applications.data ?? [])

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (over === null) {
      return
    }
    const application = (applications.data ?? []).find((item) => item.application_id === active.id)
    if (application === undefined) {
      return
    }
    const targetStage = over.id as PipelineStage
    const intent = intentForDrop(application.status, targetStage)
    if (intent.kind === 'noop') {
      return
    }
    if (intent.kind === 'system') {
      toast.error(t('board.systemOwned'))
      return
    }
    setStageMove({
      application,
      mode: intent.kind === 'choice' ? 'choice' : 'move',
      target: intent.kind === 'move' ? intent.status : null,
      targetStage,
    })
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <JobSelector jobs={jobs.data ?? []} value={jobId} onChange={setJobId} />
          <Button asChild variant="outline" size="sm">
            <Link to="/w/hiring/jobs">{t('jobs.manage')}</Link>
          </Button>
          <Button asChild variant="outline" size="sm">
            <Link to="/w/hiring/import">{t('import.open')}</Link>
          </Button>
        </div>
        <span className="text-2xs text-ink-muted">
          {t('hiring.inPipeline', { count: applications.data?.length ?? 0 })}
        </span>
      </div>

      <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
        <div className="flex gap-3 overflow-x-auto pb-2">
          {columns.map((column) => (
            <PipelineColumnView key={column.stage} column={column} />
          ))}
        </div>
      </DndContext>

      {stageMove !== null ? (
        <StageMoveDialog
          key={`${stageMove.application.application_id}-${stageMove.targetStage}`}
          application={stageMove.application}
          mode={stageMove.mode}
          target={stageMove.target}
          targetStage={stageMove.targetStage}
          open
          onOpenChange={(next) => {
            if (!next) {
              setStageMove(null)
            }
          }}
        />
      ) : null}
    </div>
  )
}
