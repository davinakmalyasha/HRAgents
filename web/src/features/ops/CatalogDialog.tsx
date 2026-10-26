import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'

import type { ConnectionPreset } from './connectionsApi'
import { useMcpCatalog } from './useConnections'

/**
 * The connector catalog: templates, not connections.
 *
 * Nothing in this list is enabled. Choosing one fills the form with the shape
 * of the connection — tools, impacts, agents and the token variable — and the
 * operator still supplies the gateway endpoint, saves it and runs Test.
 */
export function CatalogDialog({
  open,
  onOpenChange,
  onUse,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onUse: (preset: ConnectionPreset) => void
}) {
  const { t } = useTranslation()
  const catalog = useMcpCatalog()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('connections.catalogTitle')}</DialogTitle>
          <DialogDescription>{t('connections.catalogHint')}</DialogDescription>
        </DialogHeader>
        {catalog.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : catalog.isError ? (
          <p className="text-error text-sm" role="alert">
            {t('connections.catalogUnavailable')}
          </p>
        ) : (catalog.data ?? []).length === 0 ? (
          <p className="text-ink-muted text-sm">{t('connections.catalogEmpty')}</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {(catalog.data ?? []).map((entry) => (
              <li key={entry.id} className="border-line flex flex-col gap-2 rounded-lg border p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="text-ink-strong text-sm font-medium">{entry.title}</p>
                    <p className="text-ink-muted mt-1 text-sm">{entry.summary}</p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    onClick={() =>
                      onUse({
                        name: entry.id,
                        auth_env: entry.auth_env ?? '',
                        tools: entry.tools as ConnectionPreset['tools'],
                        allowed_agents: entry.allowed_agents ?? [],
                      })
                    }
                  >
                    {t('connections.useTemplate')}
                  </Button>
                </div>
                <p className="text-ink-muted text-xs">
                  <span className="text-ink-strong">{t('connections.dataFlow')}: </span>
                  {entry.data_flow}
                </p>
                <p className="text-ink-muted text-xs">
                  <span className="text-ink-strong">{t('connections.scopes')}: </span>
                  {(entry.scopes ?? []).join(' · ')}
                </p>
                <details className="text-ink-muted text-xs">
                  <summary className="text-ink-strong cursor-pointer">
                    {t('connections.enableSteps')}
                  </summary>
                  <ol className="mt-1 list-decimal ps-4">
                    {(entry.enable_steps ?? []).map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ol>
                </details>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  )
}
