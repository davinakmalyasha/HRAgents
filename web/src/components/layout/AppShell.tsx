import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router'

import { useSession } from '@/features/auth/session'
import { isAuthRequired, onUnauthorized } from '@/lib/auth'

import { CommandPalette } from './CommandPalette'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

export function AppShell() {
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
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenPalette={() => setPaletteOpen(true)} />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-8">
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
