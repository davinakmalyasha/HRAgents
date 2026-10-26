import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

import { ConnectionFormDialog } from './ConnectionFormDialog'
import { ConnectionList } from './ConnectionList'
import { ConnectionsRequestError } from './connectionsApi'
import { useConnections } from './useConnections'

/**
 * Operator-managed external MCP connections.
 *
 * The environment list and dashboard rows are merged by the API; environment
 * rows are marked and cannot be edited or removed here, and a dashboard row
 * may not shadow an environment name. Only listed tools are registered, and
 * destructive ones are refused because they have no preview contract.
 */
export function ConnectionsSection() {
  const { t } = useTranslation()
  const connections = useConnections()
  const [creating, setCreating] = useState(false)

  return (
    <section aria-labelledby="connections-heading" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 id="connections-heading" className="text-ink-strong text-lg font-medium">
            {t('connections.title')}
          </h2>
          <p className="text-ink-muted mt-1 max-w-prose text-sm">{t('connections.hint')}</p>
        </div>
        <Button type="button" size="sm" onClick={() => setCreating(true)}>
          {t('connections.add')}
        </Button>
      </div>

      {connections.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : connections.isError ? (
        <EmptyState
          title={
            connections.error instanceof ConnectionsRequestError && connections.error.status === 403
              ? t('connections.forbidden')
              : t('connections.unavailable')
          }
        />
      ) : (connections.data ?? []).length === 0 ? (
        <p className="text-ink-muted text-sm">{t('connections.empty')}</p>
      ) : (
        <ConnectionList servers={connections.data ?? []} />
      )}

      {creating ? (
        <ConnectionFormDialog
          server={null}
          open
          onOpenChange={(open) => {
            if (!open) setCreating(false)
          }}
        />
      ) : null}
    </section>
  )
}
