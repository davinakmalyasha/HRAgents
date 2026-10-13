import { Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { useSession, useSignOut } from '@/features/auth/session'
import { storedApiKey } from '@/lib/auth'

import { LanguageSwitcher } from './LanguageSwitcher'
import { ThemeToggle } from './ThemeToggle'

export function Topbar({ onOpenPalette }: { onOpenPalette: () => void }) {
  const { t } = useTranslation()
  return (
    <header className="border-line bg-surface flex h-14 shrink-0 items-center justify-between gap-3 border-b px-4 md:px-8">
      <span className="text-ink-strong font-medium">{t('app.name')}</span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          className="border-line text-ink-muted hover:text-ink-strong hidden items-center gap-2 rounded-md border px-3 py-1.5 text-xs sm:flex"
          onClick={onOpenPalette}
        >
          <Search aria-hidden="true" className="size-3.5" />
          {t('palette.open')}
          {/*
            The hint shows the key that works on this platform. A Mac user
            pressing Ctrl+K is not wrong, but showing the chord they will reach
            for is the difference between a shortcut and a rumour.
          */}
          <kbd className="border-line text-2xs rounded border px-1 font-mono">
            {isApplePlatform() ? '⌘K' : 'Ctrl K'}
          </kbd>
        </button>
        <Identity />
        <LanguageSwitcher />
        <ThemeToggle />
      </div>
    </header>
  )
}

function isApplePlatform(): boolean {
  if (typeof navigator === 'undefined') {
    return false
  }
  return /Mac|iPhone|iPad/.test(navigator.platform ?? '')
}

/**
 * Who this browser is acting as, and the way out.
 *
 * The role comes from the server's answer, not from anything local: it is the
 * same claim every permission check uses, and showing a locally-guessed role
 * would eventually disagree with what the API allows.
 */
function Identity() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const session = useSession()
  const signOut = useSignOut()

  if (session.data === undefined) {
    return null
  }

  const signedIn = storedApiKey() !== null
  return (
    <span className="text-ink-muted flex items-center gap-2 text-xs">
      <span className="truncate" title={`${session.data.actor_id} (${session.data.role})`}>
        {t('auth.signedInAs', {
          who: session.data.actor_id,
          role: t(`approvals.role.${session.data.role}`, { defaultValue: session.data.role }),
        })}
      </span>
      {/*
        Only offered when a key is actually held. In the zero-config local
        install there is nothing to sign out of -- a "sign out" that leads to a
        login screen which immediately waves you back in would be worse than
        no button.
      */}
      {signedIn ? (
        <button
          type="button"
          className="hover:text-ink-strong underline"
          onClick={() => {
            signOut()
            navigate('/login', { replace: true })
          }}
        >
          {t('auth.signOut')}
        </button>
      ) : null}
    </span>
  )
}
