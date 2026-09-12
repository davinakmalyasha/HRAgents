import { Globe } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { SUPPORTED_LANGUAGES, type Language } from '@/i18n'

const LANGUAGE_LABELS: Record<Language, string> = {
  en: 'English',
  id: 'Bahasa Indonesia',
}

export function LanguageSwitcher() {
  const { i18n, t } = useTranslation()
  const current: Language = i18n.language.startsWith('id') ? 'id' : 'en'

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" aria-label={t('common.changeLanguage')}>
          <Globe aria-hidden="true" />
          <span className="text-2xs font-mono uppercase">{current}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {SUPPORTED_LANGUAGES.map((language) => (
          <DropdownMenuItem
            key={language}
            onSelect={() => {
              void i18n.changeLanguage(language)
            }}
          >
            {LANGUAGE_LABELS[language]}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
