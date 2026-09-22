import { Fragment, useState } from 'react'
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

import { CommunicationPanel } from '@/features/hiring/CommunicationPanel'
import { shortId } from '@/features/hiring/pipeline'
import { useApplication, useEvaluation } from '@/features/hiring/useHiring'

type EvaluationView = components['schemas']['EvaluationView']

/**
 * No hidden ranking: every number opens its formula, weight, and evidence.
 * The breakdown stays inspectable per dimension — same input, same score.
 */
function EvaluationCard({ evaluation }: { evaluation: EvaluationView }) {
  const { t } = useTranslation()
  const [formulaOpen, setFormulaOpen] = useState(false)
  const [evidenceRow, setEvidenceRow] = useState<string | null>(null)

  return (
    <div className="border-line flex flex-col gap-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-3">
        <Badge>{evaluation.recommendation}</Badge>
        <Badge variant="secondary">{evaluation.policy.decision}</Badge>
        <ScoreBar value={evaluation.s_tech} label={t('hiring.score')} />
        <span className="text-2xs text-ink-muted font-mono">σ {evaluation.sigma.toFixed(2)}</span>
        <Button
          variant="ghost"
          size="xs"
          aria-expanded={formulaOpen}
          onClick={() => setFormulaOpen((open) => !open)}
        >
          {t('hiring.computed')}
        </Button>
      </div>

      {formulaOpen ? (
        <div className="border-line bg-surface-subtle flex flex-col gap-2 rounded-md border p-3">
          <p className="text-2xs text-ink-muted">{t('hiring.computedNote')}</p>
          <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">
            {evaluation.breakdown.map((item) => (
              <div key={item.dimension} className="flex items-center justify-between gap-2">
                <dt className="text-ink-muted text-2xs">
                  {t(`hiring.dimensions.${item.dimension}`)}
                </dt>
                <dd className="text-ink-strong text-2xs font-mono tabular-nums">
                  {item.weight.toFixed(2)} × {item.score.toFixed(2)} ={' '}
                  {(item.weight * item.score).toFixed(3)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}

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
            <TableHead>
              <span className="sr-only">{t('hiring.evidence')}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {evaluation.breakdown.map((item) => {
            const evidence = item.evidence ?? []
            const open = evidenceRow === item.dimension
            const dimensionLabel = t(`hiring.dimensions.${item.dimension}`)
            return (
              <Fragment key={item.dimension}>
                <TableRow>
                  <TableCell className="font-medium">{dimensionLabel}</TableCell>
                  <TableCell>
                    <ScoreBar value={item.score} label={dimensionLabel} />
                  </TableCell>
                  <TableCell className="text-2xs font-mono">{item.weight.toFixed(2)}</TableCell>
                  <TableCell className="text-ink-muted max-w-96 text-xs">
                    {item.rationale}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="xs"
                      aria-expanded={open}
                      aria-label={t(open ? 'hiring.hideDetails' : 'hiring.showDetails', {
                        dimension: dimensionLabel,
                      })}
                      onClick={() => setEvidenceRow(open ? null : item.dimension)}
                    >
                      {t('hiring.evidence')} · {evidence.length}
                    </Button>
                  </TableCell>
                </TableRow>
                {open ? (
                  <TableRow>
                    <TableCell colSpan={5} className="bg-surface-subtle">
                      {evidence.length === 0 ? (
                        <p className="text-2xs text-ink-muted">{t('hiring.noEvidence')}</p>
                      ) : (
                        <ul className="flex flex-col gap-2">
                          {evidence.map((ref, index) => (
                            <li key={`${ref.locator}-${index}`} className="flex flex-col gap-0.5">
                              <span className="text-ink-strong text-2xs font-mono">
                                {ref.locator}
                              </span>
                              {ref.excerpt === null || ref.excerpt === undefined ? null : (
                                <span className="text-ink text-2xs">{ref.excerpt}</span>
                              )}
                              <span className="text-2xs text-ink-muted">
                                {t('hiring.source')}: {ref.source_type} ·{' '}
                                {t('hiring.confidenceShort', { value: ref.confidence.toFixed(2) })}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </TableCell>
                  </TableRow>
                ) : null}
              </Fragment>
            )
          })}
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

      <CommunicationPanel
        candidateId={record.candidate_id}
        evaluationId={evaluation.data?.id}
        policyDecision={evaluation.data?.policy.decision}
      />

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
