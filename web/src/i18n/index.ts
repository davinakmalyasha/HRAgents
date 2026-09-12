import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import en from './locales/en.json'
import id from './locales/id.json'

export const LANGUAGE_STORAGE_KEY = 'hragents.language'
export const SUPPORTED_LANGUAGES = ['en', 'id'] as const
export type Language = (typeof SUPPORTED_LANGUAGES)[number]

function readLanguage(): Language {
  if (typeof localStorage === 'undefined') {
    return 'en'
  }
  const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY)
  return stored === 'id' ? 'id' : 'en'
}

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    id: { translation: id },
  },
  lng: readLanguage(),
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
})

i18n.on('languageChanged', (language) => {
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, language)
  }
  if (typeof document !== 'undefined') {
    document.documentElement.lang = language
  }
})

export default i18n
