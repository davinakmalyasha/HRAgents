import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { StatusBadge } from '@/components/status/StatusBadge'
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

import { toneForProvider } from './providerTone'
import type {
  ProviderField,
  ProviderOption,
  ProviderRequestError,
  ProviderStatusView,
} from './providersApi'
import {
  useClearProvider,
  useProviderOptions,
  useSaveProvider,
  useTestProvider,
} from './useProviders'

type FieldValue = string | boolean
type Values = Record<string, FieldValue>

/**
 * One capability's form, derived from the selected provider's own schema.
 *
 * Secrets are write-only: the API returns only the last four characters, so a
 * blank secret means "keep the stored one" rather than "clear it". The form
 * never pre-fills the mask, because posting it back would store the mask.
 */
export function ProviderSettingsDialog({
  provider,
  open,
  onOpenChange,
}: {
  provider: ProviderStatusView
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const options = useProviderOptions(open ? provider.capability : null)
  const save = useSaveProvider()
  const clear = useClearProvider()
  const test = useTestProvider()
  const [draft, setDraft] = useState<{ providerId: string; values: Values } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmingClear, setConfirmingClear] = useState(false)

  const selectedId =
    draft?.providerId ??
    options.data?.selected_provider_id ??
    options.data?.providers[0]?.provider_id ??
    null
  const current = options.data?.providers.find((item) => item.provider_id === selectedId) ?? null
  const values =
    draft !== null && draft.providerId === selectedId
      ? draft.values
      : defaultsFor(current, provider)

  function reset() {
    setDraft(null)
    setError(null)
    setConfirmingClear(false)
    test.reset()
  }

  function choose(providerId: string) {
    const next = options.data?.providers.find((item) => item.provider_id === providerId) ?? null
    setDraft({ providerId, values: defaultsFor(next, provider) })
    setError(null)
    test.reset()
  }

  function edit(name: string, value: FieldValue) {
    setDraft({ providerId: selectedId as string, values: { ...values, [name]: value } })
  }

  function payload(): Record<string, unknown> {
    if (current === null) return {}
    const config: Record<string, unknown> = {}
    for (const field of current.fields) {
      const value = values[field.name]
      if (field.type === 'boolean') {
        config[field.name] = Boolean(value)
      } else if (typeof value === 'string' && value !== '') {
        config[field.name] =
          field.type === 'integer' || field.type === 'number' ? Number(value) : value
      }
    }
    return config
  }

  function describe(cause: unknown): string {
    const detail = (cause as ProviderRequestError | undefined)?.detail
    return detail ?? t('providers.configure.failed')
  }

  function submit() {
    if (current === null) return
    setError(null)
    save.mutate(
      { capability: provider.capability, providerId: current.provider_id, config: payload() },
      {
        onSuccess: () => {
          toast.success(t('providers.configure.saved'))
          onOpenChange(false)
          reset()
        },
        onError: (cause) => setError(describe(cause)),
      },
    )
  }

  function runTest() {
    if (current === null) return
    setError(null)
    test.mutate(
      { capability: provider.capability, providerId: current.provider_id, config: payload() },
      { onError: (cause) => setError(describe(cause)) },
    )
  }

  function remove() {
    if (!confirmingClear) {
      setConfirmingClear(true)
      return
    }
    clear.mutate(provider.capability, {
      onSuccess: () => {
        toast.success(t('providers.configure.cleared'))
        onOpenChange(false)
        reset()
      },
      onError: (cause) => setError(describe(cause)),
    })
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next)
        if (!next) reset()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t('providers.configure.title', {
              capability: t(`providers.capability.${provider.capability}`),
            })}
          </DialogTitle>
          <DialogDescription>{t('providers.configure.hint')}</DialogDescription>
        </DialogHeader>

        {options.isLoading ? (
          <p className="text-ink-muted text-sm">{t('common.loading')}</p>
        ) : options.isError || current === null ? (
          <p role="alert" className="text-sm">
            {t('providers.configure.failed')}
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-ink-strong">{t('providers.configure.provider')}</span>
              <select
                className="border-line bg-surface rounded-md border px-3 py-2 text-sm"
                value={current.provider_id}
                onChange={(event) => choose(event.target.value)}
              >
                {options.data?.providers.map((item) => (
                  <option key={item.provider_id} value={item.provider_id}>
                    {item.display_name}
                  </option>
                ))}
              </select>
              {current.description !== '' ? (
                <span className="text-ink-muted text-2xs">{current.description}</span>
              ) : null}
            </label>

            {current.fields.map((field) => (
              <Field
                key={field.name}
                field={field}
                value={values[field.name] ?? ''}
                placeholder={secretPlaceholder(field, current, provider, t)}
                onChange={(value) => edit(field.name, value)}
              />
            ))}

            {test.data !== undefined ? (
              <div className="flex flex-col gap-1" role="status">
                <StatusBadge
                  tone={toneForProvider(test.data.status)}
                  labelKey={`providers.status.${test.data.status}`}
                />
                <span className="text-ink-muted text-xs">{test.data.detail}</span>
              </div>
            ) : null}

            {error !== null ? (
              <p role="alert" className="text-sm">
                {error}
              </p>
            ) : null}
          </div>
        )}

        <DialogFooter className="flex-wrap">
          {provider.source === 'settings' ? (
            <Button type="button" variant="outline" onClick={remove} disabled={clear.isPending}>
              {confirmingClear
                ? t('providers.configure.confirmClear')
                : t('providers.configure.clear')}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="outline"
            onClick={runTest}
            disabled={current === null || test.isPending}
          >
            {test.isPending ? t('providers.configure.testing') : t('providers.configure.test')}
          </Button>
          <Button type="button" onClick={submit} disabled={current === null || save.isPending}>
            {save.isPending ? t('providers.configure.saving') : t('providers.configure.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Field({
  field,
  value,
  placeholder,
  onChange,
}: {
  field: ProviderField
  value: FieldValue
  placeholder: string
  onChange: (value: FieldValue) => void
}) {
  if (field.type === 'boolean') {
    return (
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span className="text-ink-strong">{field.title}</span>
        {field.description !== '' ? (
          <span className="text-ink-muted text-2xs">{field.description}</span>
        ) : null}
      </label>
    )
  }
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-ink-strong">
        {field.title}
        {field.required ? ' *' : ''}
      </span>
      <Input
        type={
          field.secret
            ? 'password'
            : field.type === 'integer' || field.type === 'number'
              ? 'number'
              : 'text'
        }
        value={String(value)}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      {field.description !== '' ? (
        <span className="text-ink-muted text-2xs">{field.description}</span>
      ) : null}
    </label>
  )
}

/** Values for a provider's form: stored non-secrets, never the secret mask. */
function defaultsFor(spec: ProviderOption | null, provider: ProviderStatusView): Values {
  if (spec === null) return {}
  const same = spec.provider_id === provider.provider_id
  const config = same ? (provider.config ?? {}) : {}
  const values: Values = {}
  for (const field of spec.fields) {
    if (field.secret) {
      values[field.name] = ''
    } else if (field.type === 'boolean') {
      values[field.name] = Boolean(config[field.name] ?? field.default ?? false)
    } else {
      const stored = config[field.name]
      values[field.name] = stored === undefined || stored === null ? '' : String(stored)
    }
  }
  return values
}

function secretPlaceholder(
  field: ProviderField,
  spec: ProviderOption,
  provider: ProviderStatusView,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (!field.secret) return ''
  const stored = provider.config?.[field.name]
  if (spec.provider_id === provider.provider_id && stored !== undefined && stored !== null) {
    return t('providers.configure.secretKept', { mask: String(stored) })
  }
  return t('providers.configure.secretNew')
}
