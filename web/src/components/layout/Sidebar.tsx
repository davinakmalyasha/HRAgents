import { cn } from 'cn'
import { Home } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { NavLink } from 'react-router'

import { WORKSPACE_ICONS, WORKSPACE_IDS } from '@/lib/workspaces'

const itemClass =
  'flex items-center gap-3 rounded-md px-2 py-2 text-xs font-medium text-ink-muted transition-colors hover:bg-background hover:text-ink md:px-3'

function linkClass({ isActive }: { isActive: boolean }) {
  return cn(itemClass, isActive && 'bg-background text-primary hover:text-primary')
}

export function Sidebar() {
  const { t } = useTranslation()

  return (
    <nav
      aria-label={t('nav.workspaces')}
      className="border-line bg-surface-subtle flex w-14 shrink-0 flex-col gap-1 border-r px-2 py-3 md:w-60"
    >
      <NavLink to="/" end className={linkClass}>
        <Home aria-hidden="true" className="size-4" />
        <span className="hidden md:inline">{t('nav.home')}</span>
      </NavLink>

      <p className="text-2xs text-ink-muted mt-3 hidden px-3 font-medium tracking-wide uppercase md:block">
        {t('nav.workspaces')}
      </p>

      {WORKSPACE_IDS.map((id) => {
        const Icon = WORKSPACE_ICONS[id]
        return (
          <NavLink key={id} to={`/w/${id}`} className={linkClass}>
            <Icon aria-hidden="true" className="size-4" />
            <span className="hidden md:inline">{t(`workspaces.${id}.name`)}</span>
          </NavLink>
        )
      })}
    </nav>
  )
}
