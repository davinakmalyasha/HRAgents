import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

import {
  ConnectionsRequestError,
  type ConnectionPreset,
  type McpServerConfig,
  type McpServerView,
} from './connectionsApi'
import { useSaveConnection } from './useConnections'

const IMPACTS = ['read', 'write', 'destructive'] as const
type Impact = (typeof IMPACTS)[number]
type ToolRow = { remote: string; impact: Impact }

/**
 * The connection form. The name is fixed once saved: it is part of every tool
 * name the agents already see, so renaming would silently break their grants.
 *
 * Tools are listed explicitly, one row each. A remote tool that is not in this
 * list is never registered, which is what keeps a server from widening its own
 * reach after the operator approved it.
 */
export function ConnectionFormDialog({
  server,
  preset = null,
  open,
  onOpenChange,
}: {
  server: McpServerView | null
  preset?: ConnectionPreset | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const save = useSaveConnection()
  const editing = server !== null
  const [name, setName] = useState(server?.name ?? preset?.name ?? '')
  const [url, setUrl] = useState(server?.url ?? '')
  const [authEnv, setAuthEnv] = useState(server?.auth_env ?? preset?.auth_env ?? '')
  const [timeoutSeconds, setTimeoutSeconds] = useState(String(server?.timeout_seconds ?? 10))
  const [agents, setAgents] = useState(
    (server?.allowed_agents ?? preset?.allowed_agents ?? []).join(', '),
  )
  const [tools, setTools] = useState<ToolRow[]>(
    Object.entries(server?.tools ?? preset?.tools ?? {}).map(([remote, impact]) => ({
      remote,
      impact: impact as Impact,
    })),
  )
  const [error, setError] = useState<string | null>(null)

  function editTool(index: number, patch: Partial<ToolRow>) {
    setTools((current) =>
      current.map((row, position) => (position === index ? { ...row, ...patch } : row)),
    )
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (name.trim() === '') {
      setError(t('connections.nameRequired'))
      return
    }
    const config: McpServerConfig = {
      name: name.trim(),
      url: url.trim(),
      auth_env: authEnv.trim() === '' ? null : authEnv.trim(),
      timeout_seconds: Number(timeoutSeconds) || 10,
      allowed_agents: agents
        .split(',')
        .map((agent) => agent.trim())
        .filter((agent) => agent !== ''),
      tools: Object.fromEntries(
        tools
          .filter((row) => row.remote.trim() !== '')
          .map((row) => [row.remote.trim(), row.impact]),
      ),
    }
    save.mutate(config, {
      onSuccess: () => {
        toast.success(t('connections.saved'))
        onOpenChange(false)
      },
      onError: (cause) =>
        setError(
          cause instanceof ConnectionsRequestError ? cause.message : t('connections.saveFailed'),
        ),
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {editing ? t('connections.editTitle') : t('connections.addTitle')}
          </DialogTitle>
          <DialogDescription>{t('connections.formHint')}</DialogDescription>
        </DialogHeader>
        <form className="flex flex-col gap-3" onSubmit={submit}>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="connection-name" className="text-ink-strong text-sm">
              {t('connections.name')}
            </label>
            <Input
              id="connection-name"
              value={name}
              maxLength={40}
              disabled={editing}
              onChange={(event) => setName(event.target.value)}
            />
            <p className="text-ink-muted text-xs">{t('connections.nameHint')}</p>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="connection-url" className="text-ink-strong text-sm">
              {t('connections.url')}
            </label>
            <Input
              id="connection-url"
              value={url}
              required
              onChange={(event) => setUrl(event.target.value)}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="connection-auth" className="text-ink-strong text-sm">
                {t('connections.authEnv')}
              </label>
              <Input
                id="connection-auth"
                value={authEnv}
                onChange={(event) => setAuthEnv(event.target.value)}
              />
              <p className="text-ink-muted text-xs">{t('connections.authEnvHint')}</p>
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="connection-timeout" className="text-ink-strong text-sm">
                {t('connections.timeout')}
              </label>
              <Input
                id="connection-timeout"
                type="number"
                min={1}
                max={120}
                value={timeoutSeconds}
                onChange={(event) => setTimeoutSeconds(event.target.value)}
              />
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="connection-agents" className="text-ink-strong text-sm">
              {t('connections.agents')}
            </label>
            <Input
              id="connection-agents"
              value={agents}
              onChange={(event) => setAgents(event.target.value)}
            />
            <p className="text-ink-muted text-xs">{t('connections.agentsHint')}</p>
          </div>
          <fieldset className="flex flex-col gap-2">
            <legend className="text-ink-strong text-sm">{t('connections.tools')}</legend>
            <p className="text-ink-muted text-xs">{t('connections.toolsHint')}</p>
            {tools.map((row, index) => (
              <div key={index} className="flex flex-wrap items-end gap-2">
                <div className="flex min-w-40 flex-1 flex-col gap-1">
                  <label className="text-ink-muted text-xs" htmlFor={`tool-name-${index}`}>
                    {t('connections.toolName')}
                  </label>
                  <Input
                    id={`tool-name-${index}`}
                    value={row.remote}
                    onChange={(event) => editTool(index, { remote: event.target.value })}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-ink-muted text-xs" htmlFor={`tool-impact-${index}`}>
                    {t('connections.impact')}
                  </label>
                  <select
                    id={`tool-impact-${index}`}
                    className="border-line bg-surface rounded-md border px-3 py-2 text-sm"
                    value={row.impact}
                    onChange={(event) => editTool(index, { impact: event.target.value as Impact })}
                  >
                    {IMPACTS.map((impact) => (
                      <option key={impact} value={impact}>
                        {impact}
                      </option>
                    ))}
                  </select>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    setTools((current) => current.filter((_, position) => position !== index))
                  }
                >
                  {t('connections.removeTool')}
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="self-start"
              onClick={() => setTools((current) => [...current, { remote: '', impact: 'read' }])}
            >
              {t('connections.addTool')}
            </Button>
          </fieldset>
          {error === null ? null : (
            <p className="text-error text-sm" role="alert">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('connections.cancel')}
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? t('connections.saving') : t('connections.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
