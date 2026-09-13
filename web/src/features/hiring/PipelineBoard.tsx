import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { ScoreBar } from '@/components/status/ScoreBar'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

import { JobSelector } from './JobSelector'
import {
  groupIntoStages,
  shortId,
  waitingLabel,
  type ApplicationSummary,
  type PipelineColumn,
} from './pipeline'
import { useApplications, useJobs } from './useHiring'

function ApplicationCard({ application }: { application: ApplicationSummary }) {
  const { t } = useTranslation()

  return (
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
  )
}

function PipelineColumnView({ column }: { column: PipelineColumn }) {
  const { t } = useTranslation()

  return (
    <section
      aria-label={t(`hiring.stages.${column.stage}`)}
      className="bg-surface-subtle flex w-60 shrink-0 flex-col gap-2 rounded-lg p-2"
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
 * Read-only pipeline board.
 *
 * Stages are derived from deterministic statuses (`services/ingestion.py`);
 * cards link to the application detail. Manual stage moves wait for a designed
 * transition policy — dragging must never bypass the HITL gates.
 */
export function PipelineBoard() {
  const { t } = useTranslation()
  const [jobId, setJobId] = useState<string | null>(null)
  const jobs = useJobs()
  const applications = useApplications(jobId)

  if (applications.isLoading) {
    return <Skeleton className="h-64 w-full" />
  }

  const columns = groupIntoStages(applications.data ?? [])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <JobSelector jobs={jobs.data ?? []} value={jobId} onChange={setJobId} />
          <Button asChild variant="outline" size="sm">
            <Link to="/w/hiring/import">{t('import.open')}</Link>
          </Button>
        </div>
        <span className="text-2xs text-ink-muted">
          {t('hiring.inPipeline', { count: applications.data?.length ?? 0 })}
        </span>
      </div>

      <div className="flex gap-3 overflow-x-auto pb-2">
        {columns.map((column) => (
          <PipelineColumnView key={column.stage} column={column} />
        ))}
      </div>
    </div>
  )
}
