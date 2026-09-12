import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { Button } from '@/components/ui/button'

export function NotFoundPage() {
  const { t } = useTranslation()

  return (
    <div className="flex flex-col items-start gap-4">
      <h1 className="text-ink-strong text-2xl font-semibold">{t('notFound.title')}</h1>
      <Button asChild variant="outline" size="sm">
        <Link to="/">{t('notFound.back')}</Link>
      </Button>
    </div>
  )
}
