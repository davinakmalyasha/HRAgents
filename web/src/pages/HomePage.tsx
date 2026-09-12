import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { AttentionList } from '@/features/attention/AttentionList'
import { useAttention } from '@/features/attention/useAttention'

export function HomePage() {
  const { t } = useTranslation()
  const { needsYou, watching, isLoading } = useAttention()

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="needs-you" className="flex flex-col gap-3">
        <h1 id="needs-you" className="text-ink-strong text-2xl font-semibold">
          {t('home.needsYou')}
        </h1>
        {isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : needsYou.length === 0 ? (
          <EmptyState title={t('home.needsYouEmpty')} />
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
          <EmptyState title={t('home.watchingEmpty')} />
        ) : (
          <AttentionList items={watching} />
        )}
      </section>
    </div>
  )
}
