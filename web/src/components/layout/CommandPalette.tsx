import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router'

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { useSignOut } from '@/features/auth/session'
import { useWorkspaces, workspaceName } from '@/features/workspaces/useWorkspaces'
import { storedApiKey } from '@/lib/auth'
import { useTheme } from '@/lib/theme'
import { isWorkspaceId, WORKSPACE_IDS } from '@/lib/workspaces'

import { buildPaletteItems, type PaletteItem } from './palette'

/**
 * The keyboard way around the app: `Ctrl`/`Cmd`+`K`.
 *
 * Only navigation, the two display preferences and sign-out. Nothing here writes
 * data -- a consequential action behind a fuzzy match is one Enter away from
 * being run by accident, and the surfaces that gate them also show the state a
 * person needs in order to decide.
 */
export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const workspaces = useWorkspaces()
  const toggleTheme = useTheme((state) => state.toggle)
  const signOut = useSignOut()

  const current = useMemo(() => workspaceFromPath(location.pathname), [location.pathname])

  const items = useMemo(
    () =>
      buildPaletteItems(
        {
          workspaces: WORKSPACE_IDS.map((id) => ({
            id,
            name: workspaceName(workspaces.data, id, i18n.language, t(`workspaces.${id}.name`)),
          })),
          current,
          signedIn: storedApiKey() !== null,
          language: i18n.language,
        },
        {
          navigate: (to) => {
            void navigate(to)
          },
          toggleTheme,
          setLanguage: (language) => {
            void i18n.changeLanguage(language)
          },
          signOut: () => {
            signOut()
            void navigate('/login', { replace: true })
          },
        },
        {
          home: t('palette.home'),
          navigation: t('palette.navigation'),
          actions: t('palette.actions'),
          rooms: {
            board: t('rooms.board'),
            queue: t('rooms.queue'),
            chat: t('rooms.chat'),
          },
          toggleTheme: t('common.toggleTheme'),
          switchToEnglish: t('palette.switchToEnglish'),
          switchToIndonesian: t('palette.switchToIndonesian'),
          signOut: t('auth.signOut'),
        },
      ),
    [current, i18n, navigate, signOut, t, toggleTheme, workspaces.data],
  )

  const navigation = items.filter((item) => item.group === 'navigation')
  const actions = items.filter((item) => item.group === 'actions')

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('palette.title')}
      description={t('palette.description')}
    >
      <CommandInput placeholder={t('palette.placeholder')} />
      <CommandList>
        <CommandEmpty>{t('palette.empty')}</CommandEmpty>
        <CommandGroup heading={t('palette.navigation')}>
          {navigation.map((item) => (
            <PaletteOption key={item.id} item={item} onOpenChange={onOpenChange} />
          ))}
        </CommandGroup>
        <CommandGroup heading={t('palette.actions')}>
          {actions.map((item) => (
            <PaletteOption key={item.id} item={item} onOpenChange={onOpenChange} />
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  )
}

function PaletteOption({
  item,
  onOpenChange,
}: {
  item: PaletteItem
  onOpenChange: (open: boolean) => void
}) {
  return (
    <CommandItem
      value={`${item.label} ${item.keywords.join(' ')}`}
      onSelect={() => {
        /**
         * Close first, then run: an action that navigates or signs out must not
         * leave a dialog mounted over the screen it navigates to.
         */
        onOpenChange(false)
        item.run()
      }}
    >
      {item.label}
    </CommandItem>
  )
}

/** The workspace id in the path, or null anywhere else. */
function workspaceFromPath(pathname: string): ReturnType<typeof workspaceIdOrNull> {
  const match = /\/w\/([^/?]+)/.exec(pathname)
  return match ? workspaceIdOrNull(match[1]) : null
}

function workspaceIdOrNull(value: string | undefined) {
  return value !== undefined && isWorkspaceId(value) ? value : null
}
