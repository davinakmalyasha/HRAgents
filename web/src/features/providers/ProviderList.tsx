import { Lock } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { StatusBadge } from '@/components/status/StatusBadge'

import type { ProviderStatusView } from './providersApi'

/**
 * The provider panel: one row per capability.
 *
 * A provider that answers says so, one that does not says why, and an
 * environment lock is marked with a padlock, because "the UI says one
 * provider and the environment says another" is the bug this screen exists to
 * prevent. Secrets come back masked; only the last four characters are shown.
 */
export function ProviderList({ providers }: { providers: ProviderStatusView[] }) {
  const { t } = useTranslation()

  return (
    <ul className="flex flex-col gap-2">
      {providers.map((provider) => (
        <li key={provider.capability} className="border-line rounded-lg border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <p className="text-ink-strong text-sm">{provider.display_name}</p>
              {provider.locked ? (
                <span className="text-ink-muted text-2xs flex items-center gap-1">
                  <Lock aria-hidden="true" className="size-3" />
                  {t('providers.locked')}
                </span>
              ) : null}
            </div>
            <StatusBadge
              tone={toneFor(provider.status)}
              labelKey={`providers.status.${provider.status}`}
            />
          </div>
          <p className="text-ink-muted mt-1 text-xs">{provider.detail}</p>
          <p className="text-ink-muted text-2xs mt-0.5 font-mono">
            {provider.provider_id} · {t(`providers.capability.${provider.capability}`)}
          </p>
          {Object.keys(provider.config ?? {}).length > 0 ? (
            <dl className="text-ink-muted text-2xs mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono">
              {Object.entries(provider.config ?? {}).map(([key, value]) => (
                <div key={key} className="flex gap-1">
                  <dt>{key}=</dt>
                  <dd>{String(value)}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </li>
      ))}
    </ul>
  )
}

function toneFor(status: ProviderStatusView['status']): 'waiting' | 'error' | 'done' {
  if (status === 'ok') {
    return 'done'
  }
  if (status === 'degraded') {
    return 'waiting'
  }
  return 'error'
}
