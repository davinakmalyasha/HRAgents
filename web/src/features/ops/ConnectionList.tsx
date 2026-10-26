import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { StatusBadge } from '@/components/status/StatusBadge'
import { Button } from '@/components/ui/button'

import { ConnectionsRequestError, type McpProbeResult, type McpServerView } from './connectionsApi'
import { ConnectionFormDialog } from './ConnectionFormDialog'
import { useRemoveConnection, useTestConnection } from './useConnections'

function ConnectionRow({
  server,
  onEdit,
}: {
  server: McpServerView
  onEdit: (s: McpServerView) => void
}) {
  const { t } = useTranslation()
  const remove = useRemoveConnection()
  const test = useTestConnection()
  const [testing, setTesting] = useState(false)
  const [probe, setProbe] = useState<McpProbeResult | null>(null)
  const [probeError, setProbeError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  const connected = server.status?.connected === true
  const tone = server.status === null ? 'waiting' : connected ? 'done' : 'error'
  const labelKey =
    server.status === null
      ? 'connections.pending'
      : connected
        ? 'connections.connected'
        : 'connections.unreachable'

  async function runTest() {
    setTesting(true)
    setProbe(null)
    setProbeError(null)
    try {
      setProbe(await test.mutateAsync(server.name))
    } catch (cause) {
      setProbeError(
        cause instanceof ConnectionsRequestError && cause.status === 403
          ? t('connections.forbidden')
          : t('connections.testFailed'),
      )
    } finally {
      setTesting(false)
    }
  }

  function removeServer() {
    if (!confirming) {
      setConfirming(true)
      return
    }
    remove.mutate(server.name, {
      onSuccess: () => toast.success(t('connections.deleted')),
      onError: () => setProbeError(t('connections.saveFailed')),
    })
  }

  return (
    <li className="border-line flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <p className="text-ink-strong text-sm font-medium">{server.name}</p>
          <span className="text-ink-muted text-2xs border-line rounded-full border px-2 py-0.5">
            {server.source === 'environment'
              ? t('connections.environment')
              : t('connections.dashboard')}
          </span>
          <StatusBadge tone={tone} labelKey={labelKey} />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Button type="button" size="sm" variant="outline" disabled={testing} onClick={runTest}>
            {testing ? t('connections.testing') : t('connections.test')}
          </Button>
          {server.source === 'dashboard' ? (
            <>
              <Button type="button" size="sm" variant="ghost" onClick={() => onEdit(server)}>
                {t('connections.edit')}
              </Button>
              <Button
                type="button"
                size="sm"
                variant={confirming ? 'destructive' : 'ghost'}
                disabled={remove.isPending}
                onClick={removeServer}
                onBlur={() => setConfirming(false)}
              >
                {confirming ? t('connections.confirmDelete') : t('connections.delete')}
              </Button>
            </>
          ) : null}
        </div>
      </div>

      <p className="text-ink-muted text-xs break-all">{server.url}</p>
      {server.status?.detail && !connected ? (
        <p className="text-error text-xs">{server.status.detail}</p>
      ) : null}
      {server.tools && Object.keys(server.tools).length > 0 ? (
        <ul className="flex flex-wrap gap-x-3 gap-y-1">
          {Object.entries(server.tools).map(([remote, impact]) => (
            <li key={remote} className="text-ink-muted text-xs">
              <code className="text-ink">{remote}</code> · {impact}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-ink-muted text-xs">{t('connections.noTools')}</p>
      )}
      {server.source === 'environment' ? (
        <p className="text-ink-muted text-xs">{t('connections.managedByEnv')}</p>
      ) : null}
      {probe !== null ? (
        <p className="text-ink-muted text-xs" role="status">
          {probe.connected
            ? (probe.tools ?? []).length > 0
              ? t('connections.offered', { tools: (probe.tools ?? []).join(', ') })
              : t('connections.offeredNone')
            : probe.detail}
        </p>
      ) : null}
      {probeError !== null ? (
        <p className="text-error text-xs" role="alert">
          {probeError}
        </p>
      ) : null}
    </li>
  )
}

/**
 * The configured connections, with their live status.
 *
 * The Test button probes the saved configuration; it does not register tools or
 * write anything. Removing a dashboard connection takes two clicks because it
 * revokes an agent's tools immediately.
 */
export function ConnectionList({ servers }: { servers: McpServerView[] }) {
  const [editing, setEditing] = useState<McpServerView | null>(null)

  return (
    <>
      <ul className="flex flex-col gap-2">
        {servers.map((server) => (
          <ConnectionRow key={server.name} server={server} onEdit={setEditing} />
        ))}
      </ul>
      {editing === null ? null : (
        <ConnectionFormDialog
          server={editing}
          open
          onOpenChange={(open) => {
            if (!open) setEditing(null)
          }}
        />
      )}
    </>
  )
}
