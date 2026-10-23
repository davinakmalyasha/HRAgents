import { Bell, BellOff, BellRing } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { usePushNotifications } from './usePushNotifications'

/**
 * The notification toggle.
 *
 * Every visible state pairs an icon with words: "on" is a bell with a label,
 * "blocked" is a crossed bell with a label. The button is absent -- not
 * disabled-looking -- when the deployment has no VAPID keys, because there is
 * nothing an operator action here could fix. It is also absent while the
 * browser cannot receive pushes at all.
 */
export function NotificationsButton() {
  const { t } = useTranslation()
  const { status, error, toggle } = usePushNotifications()

  if (status === 'loading' || status === 'unsupported' || status === 'unconfigured') {
    return null
  }

  const blocked = status === 'blocked'
  const on = status === 'enabled'
  const label = blocked ? t('push.blocked') : on ? t('push.on') : t('push.turnOn')

  return (
    <span className="flex items-center gap-1">
      <button
        type="button"
        className="border-line text-ink-muted hover:text-ink-strong flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-60"
        aria-label={label}
        aria-pressed={on}
        title={blocked ? t('push.blockedHint') : label}
        disabled={blocked || status === 'working'}
        onClick={() => void toggle()}
      >
        {blocked ? (
          <BellOff aria-hidden="true" className="size-3.5" />
        ) : on ? (
          <BellRing aria-hidden="true" className="size-3.5" />
        ) : (
          <Bell aria-hidden="true" className="size-3.5" />
        )}
        <span className="hidden sm:inline">{label}</span>
      </button>
      {error !== null ? (
        <span role="status" className="text-ink-muted hidden text-xs md:inline">
          {t(`push.error.${error}`)}
        </span>
      ) : null}
    </span>
  )
}
