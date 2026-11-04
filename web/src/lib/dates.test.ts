import { describe, expect, it } from 'vitest'

import i18n from '@/i18n'
import { formatDate, formatDateTime } from './dates'

describe('dates', () => {
  it('passes invalid input through unchanged', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date')
    expect(formatDateTime('not-a-date')).toBe('not-a-date')
  })

  it('follows the language switcher instead of the host default', async () => {
    await i18n.changeLanguage('en')
    const english = formatDate('2026-02-01T00:00:00Z')
    const englishTime = formatDateTime('2026-02-01T00:00:00Z')

    await i18n.changeLanguage('id')
    const indonesian = formatDate('2026-02-01T00:00:00Z')
    const indonesianTime = formatDateTime('2026-02-01T00:00:00Z')

    await i18n.changeLanguage('en')

    expect(english).not.toBe('2026-02-01T00:00:00Z')
    expect(indonesian).not.toBe('2026-02-01T00:00:00Z')
    expect(indonesian).not.toBe(english)
    expect(indonesianTime).not.toBe(englishTime)
  })
})
