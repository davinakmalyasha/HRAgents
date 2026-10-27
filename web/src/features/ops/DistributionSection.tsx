import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'

import { OpsRequestError } from './opsApi'
import { useFairness } from './useOps'

const WINDOW_DAYS = 90

/**
 * Per-job score distributions from evaluations the pipeline actually made.
 *
 * This is not a demographic fairness metric and does not pretend to be one:
 * protected attributes are never collected or scored, so the report monitors
 * drift, routing and flags by job. The note under the table says so on screen,
 * not only in the docs.
 */
export function DistributionSection() {
  const { t } = useTranslation()
  const report = useFairness(WINDOW_DAYS)

  return (
    <section aria-labelledby="distribution-heading" className="flex flex-col gap-2">
      <div>
        <h2 id="distribution-heading" className="text-ink-strong text-lg font-medium">
          {t('distribution.title')}
        </h2>
        <p className="text-ink-muted mt-1 max-w-prose text-sm">
          {t('distribution.hint', { days: WINDOW_DAYS })}
        </p>
      </div>

      {report.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : report.isError ? (
        <EmptyState
          title={
            report.error instanceof OpsRequestError && report.error.status === 403
              ? t('distribution.forbidden')
              : t('distribution.unavailable')
          }
        />
      ) : (report.data?.jobs ?? []).length === 0 ? (
        <p className="text-ink-muted text-sm">{t('distribution.empty')}</p>
      ) : (
        <div className="border-line overflow-x-auto rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="border-line text-ink-muted border-b text-xs">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('distribution.job')}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('distribution.evaluated')}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('distribution.mean')}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('distribution.range')}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('distribution.needsHuman')}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('distribution.flagged')}
                </th>
              </tr>
            </thead>
            <tbody>
              {(report.data?.jobs ?? []).map((job) => (
                <tr key={job.job_id ?? job.job_title} className="border-line border-t">
                  <td className="text-ink px-3 py-2">{job.job_title}</td>
                  <td className="text-ink-muted px-3 py-2">{job.evaluations}</td>
                  <td className="text-ink-muted px-3 py-2">{job.mean.toFixed(2)}</td>
                  <td className="text-ink-muted px-3 py-2">
                    {job.minimum.toFixed(2)}–{job.maximum.toFixed(2)}
                  </td>
                  <td className="text-ink-muted px-3 py-2">{job.requires_human}</td>
                  <td className="text-ink-muted px-3 py-2">{job.flagged}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {report.data ? <p className="text-ink-muted text-xs">{report.data.note}</p> : null}
    </section>
  )
}
