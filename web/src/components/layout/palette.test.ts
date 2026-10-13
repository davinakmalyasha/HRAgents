import { describe, expect, it, vi } from 'vitest'

import { buildPaletteItems, matchesQuery, type PaletteLabels, type PaletteItem } from './palette'

const LABELS: PaletteLabels = {
  home: 'Home',
  navigation: 'Go to',
  actions: 'Actions',
  rooms: { board: 'Board', queue: 'Queue', chat: 'Chat' },
  toggleTheme: 'Toggle theme',
  switchToEnglish: 'Switch to English',
  switchToIndonesian: 'Ganti ke Bahasa Indonesia',
  signOut: 'Sign out',
}

const WORKSPACES = [
  { id: 'hiring' as const, name: 'Hiring' },
  { id: 'payroll' as const, name: 'Payroll' },
]

function build(overrides: {
  current?: 'hiring' | 'payroll' | null
  signedIn?: boolean
  language?: string
}): {
  items: PaletteItem[]
  navigate: ReturnType<typeof vi.fn>
  signOut: ReturnType<typeof vi.fn>
} {
  const navigate = vi.fn()
  const signOut = vi.fn()
  const items = buildPaletteItems(
    {
      workspaces: WORKSPACES,
      current: overrides.current ?? null,
      signedIn: overrides.signedIn ?? false,
      language: overrides.language ?? 'en',
    },
    {
      navigate,
      toggleTheme: vi.fn(),
      setLanguage: vi.fn(),
      signOut,
    },
    LABELS,
  )
  return { items, navigate, signOut }
}

function find(items: PaletteItem[], id: string): PaletteItem {
  const item = items.find((candidate) => candidate.id === id)
  expect(item).toBeDefined()
  return item as PaletteItem
}

describe('what the palette offers', () => {
  it('offers home and every workspace, as navigation', () => {
    const { items } = build({})

    const navigation = items.filter((item) => item.group === 'navigation')
    expect(navigation.map((item) => item.label)).toEqual(['Home', 'Hiring', 'Payroll'])
  })

  it('navigates to the workspace it names', () => {
    const { items, navigate } = build({})

    find(items, 'go-workspace-payroll').run()

    expect(navigate).toHaveBeenCalledWith('/w/payroll')
  })

  it('offers the three rooms only once inside a workspace', () => {
    /**The rooms belong to a workspace; outside one there is nothing to open. */
    const outside = build({ current: null }).items
    expect(outside.some((item) => item.id.startsWith('go-room-'))).toBe(false)

    const inside = build({ current: 'hiring' }).items
    expect(inside.filter((item) => item.id.startsWith('go-room-')).map((item) => item.id)).toEqual([
      'go-room-board',
      'go-room-queue',
      'go-room-chat',
    ])
  })

  it('opens a room as a query string on the current workspace', () => {
    const { items, navigate } = build({ current: 'hiring' })

    find(items, 'go-room-queue').run()

    expect(navigate).toHaveBeenCalledWith('/w/hiring?room=queue')
  })
})

describe('the language switch names the language it goes to', () => {
  it('points at Indonesian from English', () => {
    const { items } = build({ language: 'en' })

    expect(find(items, 'switch-language-id').label).toBe('Ganti ke Bahasa Indonesia')
  })

  it('points at English from Indonesian', () => {
    const { items } = build({ language: 'id' })

    expect(find(items, 'switch-language-en').label).toBe('Switch to English')
  })

  it('treats a regional tag as its base language', () => {
    const { items } = build({ language: 'id-ID' })

    expect(items.some((item) => item.id === 'switch-language-en')).toBe(true)
  })
})

describe('sign-out is offered only when there is a session to end', () => {
  it('hides it in the zero-config install', () => {
    /**With no keys configured the app runs as the local operator; an item that
     * leads to a sign-in screen which immediately waves you back in is worse
     * than no item.
     */
    const { items } = build({ signedIn: false })

    expect(items.some((item) => item.id === 'sign-out')).toBe(false)
  })

  it('offers it when a key is held, and runs the injected sign-out', () => {
    const { items, signOut } = build({ signedIn: true })

    find(items, 'sign-out').run()

    expect(signOut).toHaveBeenCalledTimes(1)
  })
})

describe('the palette carries no consequential writes', () => {
  it('has no item that creates, decides or deletes anything', () => {
    /**
     * A fuzzy match plus Enter is how the wrong thing gets run. Writes stay on
     * their workspace surfaces, where the state that gates them is on screen.
     */
    const { items } = build({ current: 'hiring', signedIn: true })

    const writeish = ['create', 'approve', 'reject', 'delete', 'cancel', 'hire', 'fire']
    for (const item of items) {
      const text = `${item.id} ${item.label} ${item.keywords.join(' ')}`.toLowerCase()
      for (const verb of writeish) {
        expect(text).not.toContain(verb)
      }
    }
  })
})

describe('search matches labels and keywords', () => {
  const item = find(build({}).items, 'go-workspace-payroll')

  it('matches on the visible label, case-insensitively', () => {
    expect(matchesQuery(item, 'payr')).toBe(true)
    expect(matchesQuery(item, 'PAYROLL')).toBe(true)
  })

  it('matches on a keyword the label does not contain', () => {
    expect(matchesQuery(item, 'ruang kerja')).toBe(true)
  })

  it('ignores surrounding whitespace and treats an empty query as everything', () => {
    expect(matchesQuery(item, '  payroll  ')).toBe(true)
    expect(matchesQuery(item, '')).toBe(true)
    expect(matchesQuery(item, '   ')).toBe(true)
  })

  it('does not match what it should not', () => {
    expect(matchesQuery(item, 'hiring')).toBe(false)
  })
})
