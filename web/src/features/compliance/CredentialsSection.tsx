import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge } from '@/components/status/StatusBadge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { formatDateTime } from '@/lib/dates'

import {
  EntryParseError,
  entryToLine,
  parseEntries,
  type CredentialRegistryView,
} from './credentialsApi'
import {
  useCreateCredentialRegistry,
  useCredentialRegistries,
  useDeleteCredentialRegistry,
  useSetCredentialEntries,
  useVerifyCredentialRegistry,
} from './useCredentials'

/**
 * Credential registries: what the issuer confirmed, checked by a person.
 *
 * The import is a text format because the source is a person reading an issuer
 * page: each line is one credential, and the status is what the issuer said.
 * Nothing here is trusted until the registry is verified with a source note,
 * and editing rows invalidates that verification on the server.
 */
export function CredentialsSection() {
  const { t } = useTranslation()
  const registries = useCredentialRegistries()
  const create = useCreateCredentialRegistry()
  const [name, setName] = useState('')
  const [issuer, setIssuer] = useState('')

  if (registries.isLoading) {
    return <Skeleton className="h-32" />
  }

  const list = registries.data ?? []
  const canCreate = name.trim() !== '' && issuer.trim() !== '' && !create.isPending

  return (
    <section aria-labelledby="compliance-credentials" className="flex flex-col gap-3">
      <h2 id="compliance-credentials" className="text-ink-strong text-lg font-medium">
        {t('compliance.credentials.title', { count: list.length })}
      </h2>
      <p className="text-ink-muted max-w-prose text-sm">{t('compliance.credentials.hint')}</p>

      <div className="border-line flex flex-wrap items-end gap-2 rounded-lg border p-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-ink-strong">{t('compliance.credentials.newName')}</span>
          <Input className="w-64" value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-ink-strong">{t('compliance.credentials.newIssuer')}</span>
          <Input
            className="w-48"
            value={issuer}
            onChange={(event) => setIssuer(event.target.value)}
          />
        </label>
        <Button
          size="sm"
          disabled={!canCreate}
          onClick={() =>
            create.mutate(
              { name: name.trim(), issuer: issuer.trim() },
              {
                onSuccess: () => {
                  setName('')
                  setIssuer('')
                },
              },
            )
          }
        >
          {t('compliance.credentials.create')}
        </Button>
      </div>
      {create.isError ? (
        <p role="alert" className="text-error text-sm">
          {t('compliance.credentials.createFailed')}
        </p>
      ) : null}

      {list.length === 0 ? (
        <EmptyState title={t('compliance.credentials.empty')} />
      ) : (
        <ul className="flex flex-col gap-2">
          {list.map((registry) => (
            <CredentialRegistryCard key={registry.id} registry={registry} />
          ))}
        </ul>
      )}
    </section>
  )
}

function CredentialRegistryCard({ registry }: { registry: CredentialRegistryView }) {
  const { t } = useTranslation()
  const save = useSetCredentialEntries()
  const verify = useVerifyCredentialRegistry()
  const remove = useDeleteCredentialRegistry()
  const [rows, setRows] = useState(registry.entries.map(entryToLine).join('\n'))
  const [source, setSource] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const busy = save.isPending || verify.isPending || remove.isPending

  function saveRows() {
    setError(null)
    try {
      const entries = parseEntries(rows)
      save.mutate(
        { registryId: registry.id, entries },
        {
          onError: () => setError(t('compliance.credentials.saveFailed')),
        },
      )
    } catch (cause) {
      if (cause instanceof EntryParseError) {
        setError(t('compliance.credentials.parseError', { line: cause.line }))
      } else {
        setError(t('compliance.credentials.parseError', { line: 1 }))
      }
    }
  }

  function certify() {
    setError(null)
    verify.mutate(
      { registryId: registry.id, sourceNote: source.trim() },
      {
        onSuccess: () => setSource(''),
        onError: () => setError(t('compliance.credentials.verifyFailed')),
      },
    )
  }

  function erase() {
    if (!confirming) {
      setConfirming(true)
      return
    }
    remove.mutate(registry.id, {
      onError: () => setError(t('compliance.credentials.deleteFailed')),
    })
  }

  return (
    <li className="border-line flex flex-col gap-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-ink-strong text-sm font-medium">{registry.name}</p>
          <p className="text-ink-muted text-xs">
            {registry.issuer} ·{' '}
            {t('compliance.credentials.entryCount', { count: registry.entries.length })}
            {registry.verified_by
              ? ` · ${t('compliance.credentials.verifiedBy', { who: registry.verified_by })}`
              : ''}
          </p>
          {registry.verified_at ? (
            <p className="text-ink-muted text-2xs">
              {formatDateTime(registry.verified_at)}
              {registry.source_note ? ` · ${registry.source_note}` : ''}
            </p>
          ) : null}
        </div>
        <StatusBadge
          tone={registry.usable ? 'done' : 'waiting'}
          labelKey={
            registry.usable ? 'compliance.credentials.usable' : 'compliance.credentials.unverified'
          }
        />
      </div>

      {registry.entries.length > 0 ? (
        <ul className="text-ink-muted flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {registry.entries.map((entry) => (
            <li key={`${entry.name}-${entry.credential_id ?? ''}`}>
              <span className="text-ink-strong">{entry.name}</span> · {entry.status}
              {entry.expires_on ? ` · ${entry.expires_on}` : ''}
            </li>
          ))}
        </ul>
      ) : null}

      <label className="text-ink-strong text-sm" htmlFor={`rows-${registry.id}`}>
        {t('compliance.credentials.importLabel')}
      </label>
      <Textarea
        id={`rows-${registry.id}`}
        rows={Math.min(6, Math.max(3, rows.split('\n').length + 1))}
        value={rows}
        onChange={(event) => setRows(event.target.value)}
        placeholder={t('compliance.credentials.importHint')}
      />
      <span className="text-ink-muted text-2xs">{t('compliance.credentials.importHint')}</span>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" disabled={busy} onClick={saveRows}>
          {t('compliance.credentials.saveRows')}
        </Button>
        <label className="sr-only" htmlFor={`source-${registry.id}`}>
          {t('compliance.credentials.sourceLabel')}
        </label>
        <Input
          id={`source-${registry.id}`}
          className="w-64"
          placeholder={t('compliance.credentials.sourcePlaceholder')}
          value={source}
          onChange={(event) => setSource(event.target.value)}
        />
        <Button
          size="sm"
          disabled={busy || registry.entries.length === 0 || source.trim() === ''}
          onClick={certify}
        >
          {t('compliance.credentials.verify')}
        </Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={erase}>
          {confirming
            ? t('compliance.credentials.confirmDelete')
            : t('compliance.credentials.delete')}
        </Button>
      </div>

      {error !== null ? (
        <p role="alert" className="text-error text-sm">
          {error}
        </p>
      ) : null}
    </li>
  )
}
