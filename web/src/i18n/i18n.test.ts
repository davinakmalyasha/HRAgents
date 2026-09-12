import { beforeEach, describe, expect, it } from 'vitest'

import i18n from './index'
import en from './locales/en.json'
import id from './locales/id.json'

function flatten(value: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(value).flatMap(([key, entry]) => {
    const path = prefix === '' ? key : `${prefix}.${key}`
    if (typeof entry === 'object' && entry !== null) {
      return flatten(entry as Record<string, unknown>, path)
    }
    return [path]
  })
}

describe('i18n', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('keeps English and Bahasa Indonesia complete and in sync', () => {
    expect(flatten(id).sort()).toEqual(flatten(en).sort())
  })

  it('switches the active language', async () => {
    await i18n.changeLanguage('id')
    expect(i18n.t('home.watching')).toBe('Dipantau')

    await i18n.changeLanguage('en')
    expect(i18n.t('home.watching')).toBe('Watching')
  })

  it('falls back to English for unknown languages', async () => {
    await i18n.changeLanguage('fr')
    expect(i18n.t('home.watching')).toBe('Watching')
  })
})
