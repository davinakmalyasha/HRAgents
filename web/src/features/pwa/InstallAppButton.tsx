import { Download } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { useInstallPrompt } from './useInstallPrompt'

/**
 * Offered only when the browser says the app is installable.
 *
 * The icon is visible on a phone and the label appears from `sm` up; the
 * accessible name is always the full phrase.
 */
export function InstallAppButton() {
  const { t } = useTranslation()
  const { canInstall, install } = useInstallPrompt()

  if (!canInstall) {
    return null
  }

  return (
    <button
      type="button"
      className="border-line text-ink-muted hover:text-ink-strong flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs"
      aria-label={t('app.install')}
      onClick={() => void install()}
    >
      <Download aria-hidden="true" className="size-3.5" />
      <span className="hidden sm:inline">{t('app.install')}</span>
    </button>
  )
}
