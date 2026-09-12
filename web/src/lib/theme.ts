import { create } from 'zustand'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'hragents.theme'

function readTheme(): Theme {
  if (typeof localStorage === 'undefined') {
    return 'light'
  }
  return localStorage.getItem(STORAGE_KEY) === 'dark' ? 'dark' : 'light'
}

function applyTheme(theme: Theme) {
  if (typeof document === 'undefined') {
    return
  }
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

interface ThemeState {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggle: () => void
}

export const useTheme = create<ThemeState>((set, get) => ({
  theme: readTheme(),
  setTheme: (theme) => {
    applyTheme(theme)
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(STORAGE_KEY, theme)
    }
    set({ theme })
  },
  toggle: () => {
    get().setTheme(get().theme === 'light' ? 'dark' : 'light')
  },
}))

applyTheme(useTheme.getState().theme)
