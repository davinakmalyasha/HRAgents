import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'

import { ExportRequestError, fetchTenantExport, saveExport } from './exportApi'

/**
 * The operator's copy of the record.
 *
 * Admin-only on the server; a refusal names the role or the missing durable
 * backend instead of failing silently. The response is streamed by the API, so
 * the browser shows one "preparing" state rather than a progress bar it cannot
 * compute honestly.
 */
export function ExportSection() {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  async function run() {
    setError(null)
    setSaved(null)
    setBusy(true)
    try {
      const archive = await fetchTenantExport()
      saveExport(archive)
      setSaved(archive.filename)
    } catch (cause) {
      if (cause instanceof ExportRequestError && cause.status === 403) {
        setError(t('compliance.export.forbidden'))
      } else if (cause instanceof ExportRequestError && cause.status === 409) {
        setError(cause.detail ?? t('compliance.export.noBackend'))
      } else {
        setError(t('compliance.export.failed'))
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-labelledby="compliance-export" className="flex flex-col gap-3">
      <h2 id="compliance-export" className="text-ink-strong text-lg font-medium">
        {t('compliance.export.title')}
      </h2>
      <p className="text-ink-muted max-w-prose text-sm">{t('compliance.export.hint')}</p>
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" variant="outline" disabled={busy} onClick={() => void run()}>
          {busy ? t('compliance.export.preparing') : t('compliance.export.download')}
        </Button>
        {saved !== null ? (
          <p role="status" className="text-ink-muted text-xs">
            {t('compliance.export.saved', { name: saved })}
          </p>
        ) : null}
      </div>
      {error !== null ? (
        <p role="alert" className="text-error text-sm">
          {error}
        </p>
      ) : null}
    </section>
  )
}
