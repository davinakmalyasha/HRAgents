import type { WorkspaceId } from '@/lib/workspaces'

/**
 * One runnable command.
 *
 * Grouped only by what the palette shows: places to go, and things to do. A
 * third group would be a taxonomy nobody reads.
 */
export type PaletteGroup = 'navigation' | 'actions'

export interface PaletteItem {
  id: string
  group: PaletteGroup
  label: string
  /** Extra words that should match a search for this item. */
  keywords: string[]
  run: () => void
}

export interface PaletteSources {
  /** Workspace ids paired with the name to display for the current language. */
  workspaces: { id: WorkspaceId; name: string }[]
  /** The workspace the palette was opened from, if any. */
  current: WorkspaceId | null
  /** Whether this browser holds a credential, i.e. whether there is a session to end. */
  signedIn: boolean
  /** The active language, so the switch can name the one it goes to. */
  language: string
}

export interface PaletteActions {
  navigate: (to: string) => void
  toggleTheme: () => void
  setLanguage: (language: 'en' | 'id') => void
  /**
   * The session-holding action, injected rather than imported so the builder
   * stays pure and the component owns the cache-clearing.
   */
  signOut: () => void
}

export interface PaletteLabels {
  home: string
  navigation: string
  actions: string
  rooms: Record<'board' | 'queue' | 'chat', string>
  toggleTheme: string
  switchToEnglish: string
  switchToIndonesian: string
  signOut: string
}

const OTHER_LANGUAGE: Record<string, 'en' | 'id'> = { en: 'id', id: 'en' }

/**
 * The commands the shell can honestly offer.
 *
 * Everything here is navigation or a display preference. There are deliberately
 * no "create employee" or "approve leave" entries: a palette is a fast way to
 * reach an action, and burying a consequential write behind a keystroke and a
 * fuzzy match is how one gets run by accident. Writes stay on their workspace
 * surfaces, where the state that gates them is on screen.
 *
 * The sign-out item appears only when a key is held, because in the
 * zero-config install there is nothing to sign out of and an item that leads
 * to a screen which immediately waves you back in is worse than no item.
 */
export function buildPaletteItems(
  sources: PaletteSources,
  actions: PaletteActions,
  labels: PaletteLabels,
): PaletteItem[] {
  const items: PaletteItem[] = [
    {
      id: 'go-home',
      group: 'navigation',
      label: labels.home,
      keywords: ['home', 'beranda', 'attention'],
      run: () => actions.navigate('/'),
    },
  ]

  for (const workspace of sources.workspaces) {
    items.push({
      id: `go-workspace-${workspace.id}`,
      group: 'navigation',
      label: workspace.name,
      keywords: [workspace.id, 'workspace', 'ruang kerja'],
      run: () => actions.navigate(`/w/${workspace.id}`),
    })
  }

  if (sources.current !== null) {
    for (const room of ['board', 'queue', 'chat'] as const) {
      items.push({
        id: `go-room-${room}`,
        group: 'navigation',
        label: labels.rooms[room],
        keywords: [room, 'room', 'ruang'],
        run: () => actions.navigate(`/w/${sources.current}?room=${room}`),
      })
    }
  }

  items.push({
    id: 'toggle-theme',
    group: 'actions',
    label: labels.toggleTheme,
    keywords: ['theme', 'dark', 'light', 'tema', 'gelap', 'terang'],
    run: actions.toggleTheme,
  })

  const other = OTHER_LANGUAGE[languageKey(sources.language)]
  items.push({
    id: `switch-language-${other}`,
    group: 'actions',
    label: other === 'id' ? labels.switchToIndonesian : labels.switchToEnglish,
    keywords: ['language', 'bahasa', 'locale'],
    run: () => actions.setLanguage(other),
  })

  if (sources.signedIn) {
    items.push({
      id: 'sign-out',
      group: 'actions',
      label: labels.signOut,
      keywords: ['sign out', 'log out', 'keluar'],
      run: actions.signOut,
    })
  }

  return items
}

function languageKey(language: string): string {
  return language.startsWith('id') ? 'id' : 'en'
}

/** Case-insensitive match over the label and its keywords. */
export function matchesQuery(item: PaletteItem, query: string): boolean {
  const needle = query.trim().toLowerCase()
  if (needle === '') {
    return true
  }
  return (
    item.label.toLowerCase().includes(needle) ||
    item.keywords.some((keyword) => keyword.toLowerCase().includes(needle))
  )
}
