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

function flattenValues(
  value: Record<string, unknown>,
  prefix = '',
  into = new Map<string, string>(),
): Map<string, string> {
  for (const [key, entry] of Object.entries(value)) {
    const path = prefix === '' ? key : `${prefix}.${key}`
    if (typeof entry === 'object' && entry !== null) {
      flattenValues(entry as Record<string, unknown>, path, into)
    } else if (typeof entry === 'string') {
      into.set(path, entry)
    }
  }
  return into
}

function placeholders(value: string): string[] {
  return [
    ...new Set([...value.matchAll(/\{\{\s*([\w.]+)\s*\}\}/g)].map((match) => match[1])),
  ].sort()
}

describe('i18n', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('keeps English and Bahasa Indonesia complete and in sync', () => {
    expect(flatten(id).sort()).toEqual(flatten(en).sort())
  })

  it('keeps every translation non-empty with matching placeholders', () => {
    const english = flattenValues(en)
    const indonesian = flattenValues(id)
    const problems: string[] = []

    for (const [path, value] of english) {
      const translation = indonesian.get(path)
      if (translation === undefined) {
        continue
      }
      if (value.trim() === '' || translation.trim() === '') {
        problems.push(`${path}: empty translation`)
      }
      if (placeholders(value).join(',') !== placeholders(translation).join(',')) {
        problems.push(`${path}: placeholders differ`)
      }
    }

    expect(problems).toEqual([])
  })

  it('switches the active language', async () => {
    await i18n.changeLanguage('id')
    expect(i18n.t('home.watching')).toBe('Dipantau')
    expect(document.documentElement.lang).toBe('id')

    await i18n.changeLanguage('en')
    expect(i18n.t('home.watching')).toBe('Watching')
    expect(document.documentElement.lang).toBe('en')
  })

  it('falls back to English for unknown languages', async () => {
    await i18n.changeLanguage('fr')
    expect(i18n.t('home.watching')).toBe('Watching')
  })
})
