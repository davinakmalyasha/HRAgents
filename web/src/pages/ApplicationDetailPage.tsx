import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'

import type { components } from '@/api/schema'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ScoreBar } from '@/components/status/ScoreBar'
import { StatusBadge } from '@/components/status/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDateTime } from '@/lib/dates'

import { shortId } from '@/features/hiring/pipeline'
import { useApplication, useEvaluation } from '@/features/hiring/useHiring'

type EvaluationView = components['schemas']['EvaluationView']

function EvaluationCard({ evaluation }: { evaluation: EvaluationView }) {
  const { t } = useTranslation()

  return (
    <div className="border-line flex flex-col gap-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-3">
        <Badge>{evaluation.recommendation}</Badge>
        <Badge variant="secondary">{evaluation.policy.decision}</Badge>
        <ScoreBar value={evaluation.s_tech} label={t('hiring.score')} />
        <span className="text-2xs text-ink-muted font-mono">σ {evaluation.sigma.toFixed(2)}</span>
      </div>

      {evaluation.flags.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone="waiting" labelKey="hiring.flags" />
          {evaluation.flags.map((flag) => (
            <Badge key={flag} variant="outline" className="text-2xs font-mono">
              {flag}
            </Badge>
          ))}
        </div>
      ) : null}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('hiring.dimension')}</TableHead>
            <TableHead>{t('hiring.score')}</TableHead>
            <TableHead>{t('hiring.weight')}</TableHead>
            <TableHead>{t('hiring.rationale')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {evaluation.breakdown.map((item) => (
            <TableRow key={item.dimension}>
              <TableCell className="font-medium">{item.dimension}</TableCell>
              <TableCell>
                <ScoreBar value={item.score} label={item.dimension} />
              </TableCell>
              <TableCell className="text-2xs font-mono">{item.weight.toFixed(2)}</TableCell>
              <TableCell className="text-ink-muted max-w-96 text-xs">{item.rationale}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

export function ApplicationDetailPage() {
  const { t } = useTranslation()
  const { applicationId } = useParams()
  const application = useApplication(applicationId)
  const evaluation = useEvaluation(applicationId)

  if (application.isLoading) {
    return <Skeleton className="h-64 w-full" />
  }

  if (application.data === null || application.data === undefined) {
    return <EmptyState title={t('hiring.notFound')} />
  }

  const record = application.data

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Button asChild variant="ghost" size="xs" className="self-start">
          <Link to="/w/hiring?room=board">{t('hiring.back')}</Link>
        </Button>

        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-ink-strong text-2xl font-semibold">{t('hiring.application')}</h1>
          <Badge variant="secondary" className="font-mono">
            {record.status}
          </Badge>
        </div>

        <dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
          <div className="flex flex-col gap-0.5">
            <dt className="text-ink-muted">{t('hiring.candidate')}</dt>
            <dd className="text-ink-strong font-mono">{shortId(record.candidate_id)}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-ink-muted">{t('hiring.received')}</dt>
            <dd className="text-ink-strong font-mono">{formatDateTime(record.received_at)}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-ink-muted">{t('hiring.priority')}</dt>
            <dd className="text-ink-strong font-mono">{record.priority_score.toFixed(2)}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-ink-muted">{t('hiring.score')}</dt>
            <dd className="text-ink-strong font-mono">
              {record.s_tech == null ? '—' : record.s_tech.toFixed(2)}
            </dd>
          </div>
        </dl>
      </div>

      <section aria-labelledby="evaluation" className="flex flex-col gap-3">
        <h2 id="evaluation" className="text-ink-strong text-xl font-medium">
          {t('hiring.evaluation')}
        </h2>
        {evaluation.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : evaluation.data === null || evaluation.data === undefined ? (
          <EmptyState title={t('hiring.notEvaluated')} />
        ) : (
          <EvaluationCard evaluation={evaluation.data} />
        )}
      </section>

      <section aria-labelledby="timeline" className="flex flex-col gap-3">
        <h2 id="timeline" className="text-ink-strong text-xl font-medium">
          {t('hiring.timeline')}
        </h2>
        <ol className="border-line flex flex-col gap-1.5 rounded-lg border p-3">
          {(record.timeline ?? []).map((event, index) => (
            <li key={`${event.at}-${index}`} className="flex items-baseline gap-3 text-xs">
              <span className="text-2xs text-ink-muted shrink-0 font-mono">
                {formatDateTime(event.at)}
              </span>
              <span className="text-ink">{event.event}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
