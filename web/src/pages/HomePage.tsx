import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge } from '@/components/status/StatusBadge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { AttentionList } from '@/features/attention/AttentionList'
import type { AttentionFailure } from '@/features/attention/attention'
import { useAttention } from '@/features/attention/useAttention'
import { SetupCard } from '@/features/setup/SetupCard'
import { useSetup } from '@/features/setup/useSetup'

export function HomePage() {
  const { t } = useTranslation()
  const { needsYou, watching, isLoading, failures, retry, limitedQueues } = useAttention()
  const setup = useSetup()
  const restricted = failures.filter((failure) => failure.kind === 'forbidden')
  const failed = failures.filter((failure) => failure.kind === 'failed')
  const queueNames = (items: AttentionFailure[]) =>
    items.map((item) => t(`home.sources.${item.queue}`)).join(', ')

  return (
    <div className="flex flex-col gap-8">
      {setup.data && setup.data.counts?.employees === 0 ? <SetupCard status={setup.data} /> : null}

      {failed.length > 0 ? (
        <div
          role="alert"
          className="border-line bg-surface-subtle flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3"
        >
          <span className="text-ink text-sm">{t('home.loadFailed')}</span>
          <Button variant="outline" size="xs" onClick={retry}>
            {t('home.retry')}
          </Button>
        </div>
      ) : null}

      {restricted.length > 0 ? (
        <p className="text-ink-muted flex flex-wrap items-center gap-2 text-sm">
          <StatusBadge tone="waiting" labelKey="home.roleRestricted" />
          {t('home.roleRestrictedDetail', { sources: queueNames(restricted) })}
        </p>
      ) : null}

      {limitedQueues.length > 0 ? (
        <ul className="text-ink-muted flex flex-col gap-1 text-xs">
          {limitedQueues.map((queue) => (
            <li key={queue.queue} className="flex flex-wrap items-center gap-2">
              <span>
                {t('home.queueLimited', {
                  queue: t(`home.sources.${queue.queue}`),
                  shown: queue.shown,
                  total: queue.total,
                })}
              </span>
              {queue.workspace ? (
                <Link className="font-medium underline" to={`/w/${queue.workspace}?room=queue`}>
                  {t('home.viewAll')}
                </Link>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      <section aria-labelledby="needs-you" className="flex flex-col gap-3">
        <h1 id="needs-you" className="text-ink-strong text-2xl font-semibold">
          {t('home.needsYou')}
        </h1>
        {isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : needsYou.length === 0 ? (
          failures.length === 0 ? (
            <EmptyState title={t('home.needsYouEmpty')} />
          ) : null
        ) : (
          <AttentionList items={needsYou} />
        )}
      </section>

      <section aria-labelledby="watching" className="flex flex-col gap-3">
        <h2 id="watching" className="text-ink-strong text-xl font-medium">
          {t('home.watching')}
        </h2>
        {isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : watching.length === 0 ? (
          failures.length === 0 ? (
            <EmptyState title={t('home.watchingEmpty')} />
          ) : null
        ) : (
          <AttentionList items={watching} />
        )}
      </section>
    </div>
  )
}
