import { useTranslation } from 'react-i18next'

import { LanguageSwitcher } from './LanguageSwitcher'
import { ThemeToggle } from './ThemeToggle'

export function Topbar() {
  const { t } = useTranslation()

  return (
    <header className="border-line bg-surface flex h-14 shrink-0 items-center justify-between gap-3 border-b px-4 md:px-8">
      <span className="text-ink-strong font-medium">{t('app.name')}</span>
      <div className="flex items-center gap-1">
        <LanguageSwitcher />
        <ThemeToggle />
      </div>
    </header>
  )
}
