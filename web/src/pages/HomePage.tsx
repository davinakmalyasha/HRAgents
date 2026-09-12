import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'

export function HomePage() {
  const { t } = useTranslation()

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="needs-you" className="flex flex-col gap-3">
        <h1 id="needs-you" className="text-ink-strong text-2xl font-semibold">
          {t('home.needsYou')}
        </h1>
        <EmptyState title={t('home.needsYouEmpty')} />
      </section>

      <section aria-labelledby="watching" className="flex flex-col gap-3">
        <h2 id="watching" className="text-ink-strong text-xl font-medium">
          {t('home.watching')}
        </h2>
        <EmptyState title={t('home.watchingEmpty')} />
      </section>
    </div>
  )
}
