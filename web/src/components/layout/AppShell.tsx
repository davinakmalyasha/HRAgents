import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router'

import { useSession } from '@/features/auth/session'
import { isAuthRequired, onUnauthorized } from '@/lib/auth'

import { CommandPalette } from './CommandPalette'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

export function AppShell() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const session = useSession()

  /**
   * A credential that is refused anywhere -- a query, a mutation, a background
   * refetch -- ends the same way: the key is gone (the client drops it on 401)
   * and the person is sent to sign in, remembering where they were.
   */
  useEffect(() => {
    onUnauthorized(() => navigate('/login', { state: { from: location.pathname } }))
    return () => onUnauthorized(null)
  }, [location.pathname, navigate])

  const [paletteOpen, setPaletteOpen] = useState(false)
  /**
   * The one keyboard shortcut the shell claims: Cmd/Ctrl+K toggles the palette.
   * The state lives here and both the key and the topbar button drive it --
   * two ways into one piece of state, not two components that each think they
   * own it.
   */
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key.toLowerCase() !== 'k' || !(event.metaKey || event.ctrlKey)) {
        return
      }
      event.preventDefault()
      setPaletteOpen((current) => !current)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  /**
   * The session resolves before anything else mounts.
   *
   * The sidebar and every workspace read the API on mount, so rendering them
   * while the session is still unknown fires half a dozen requests that are all
   * going to be refused -- a burst of 401s in the console and a flash of error
   * states on the way to the sign-in screen. One request first, then the app.
   */
  if (session.isPending) {
    return <SessionCheck />
  }

  /**
   * A refused session is not an error state to render; it means this app has
   * nobody to act as.
   */
  if (session.isError && isAuthRequired(session.error)) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return (
    <div className="bg-surface text-ink flex min-h-dvh">
      {/*
        Keyboard users land here first. The sidebar renders every workspace and
        three rooms, so without this the only way into the page is through
        fourteen links that are not the content.
      */}
      <a
        href="#main-content"
        className="bg-surface text-ink-strong border-line sr-only rounded-md border px-3 py-2 text-sm focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50"
      >
        {t('common.skipToContent')}
      </a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenPalette={() => setPaletteOpen(true)} />
        <main
          id="main-content"
          tabIndex={-1}
          className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 focus:outline-none md:px-8"
        >
          <Outlet />
        </main>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  )
}

function SessionCheck() {
  const { t } = useTranslation()
  return (
    <main className="bg-surface text-ink flex min-h-dvh items-center justify-center">
      <p className="text-ink-muted text-sm">{t('auth.checking')}</p>
    </main>
  )
}
