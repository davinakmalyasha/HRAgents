import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

import { OverrideDialog } from './OverrideDialog'
import { shortId, type ApplicationSummary } from './pipeline'
import { useEvaluation, useGatedApplications } from './useHiring'

function ReviewQueueItem({ application }: { application: ApplicationSummary }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const evaluation = useEvaluation(application.application_id)
  const candidateLabel = shortId(application.candidate_id)

  const contextLine =
    evaluation.data === null || evaluation.data === undefined
      ? ''
      : `${t('hiring.score')}: ${evaluation.data.s_tech.toFixed(2)} · ${evaluation.data.policy.decision}`

  return (
    <li className="flex items-center justify-between gap-3 px-3 py-2.5">
      <div className="flex min-w-0 flex-col gap-0.5">
        <div className="flex items-center gap-2">
          <span className="text-ink-strong font-mono text-xs">{candidateLabel}</span>
          {evaluation.data !== null && evaluation.data !== undefined ? (
            <Badge variant="outline" className="text-2xs font-mono">
              {t('review.flagsCount', { count: evaluation.data.flags.length })}
            </Badge>
          ) : null}
        </div>
        <span className="text-ink-muted truncate text-xs">
          {evaluation.isLoading
            ? t('chat.thinking')
            : evaluation.data === null || evaluation.data === undefined
              ? t('review.awaitingEvaluation')
              : contextLine}
        </span>
      </div>

      <Button
        size="xs"
        disabled={evaluation.data === null || evaluation.data === undefined}
        onClick={() => setOpen(true)}
      >
        {t('review.review')}
      </Button>

      {evaluation.data !== null && evaluation.data !== undefined ? (
        <OverrideDialog
          evaluationId={evaluation.data.id}
          candidateLabel={candidateLabel}
          contextLine={contextLine}
          open={open}
          onOpenChange={setOpen}
        />
      ) : null}
    </li>
  )
}

/**
 * Decisions waiting on a named human. Every gated application carries its
 * evaluation (sign-off targets the evaluation); the override endpoint stays
 * the only writer, and the dialog shows the audit receipt afterwards.
 */
export function ReviewQueue() {
  const { t } = useTranslation()
  const gated = useGatedApplications()

  if (gated.isLoading) {
    return <Skeleton className="h-32 w-full" />
  }

  const items = gated.data ?? []
  if (items.length === 0) {
    return <EmptyState title={t('review.empty')} />
  }

  return (
    <ul className="divide-line border-line flex flex-col divide-y rounded-lg border">
      {items.map((application) => (
        <ReviewQueueItem key={application.application_id} application={application} />
      ))}
    </ul>
  )
}
