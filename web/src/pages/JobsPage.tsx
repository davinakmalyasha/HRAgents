import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { Button } from '@/components/ui/button'
import { JobManager } from '@/features/hiring/JobManager'

export function JobsPage() {
  const { t } = useTranslation()

  return (
    <div className="flex max-w-4xl flex-col gap-8">
      <div className="flex flex-col gap-3">
        <Button asChild variant="ghost" size="xs" className="self-start">
          <Link to="/w/hiring?room=board">{t('jobs.back')}</Link>
        </Button>
        <h1 className="text-ink-strong text-2xl font-semibold">{t('jobs.title')}</h1>
      </div>

      <JobManager />
    </div>
  )
}
