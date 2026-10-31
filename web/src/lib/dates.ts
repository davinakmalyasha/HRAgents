import i18n from '@/i18n'

function activeLocale(): string {
  const language = typeof i18n.language === 'string' ? i18n.language : 'en'
  return language.toLowerCase().startsWith('id') ? 'id-ID' : 'en-US'
}

export function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString(activeLocale(), { dateStyle: 'medium', timeStyle: 'short' })
}

export function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleDateString(activeLocale(), { dateStyle: 'medium' })
}
