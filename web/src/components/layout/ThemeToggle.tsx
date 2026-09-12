import { Moon, Sun } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { useTheme } from '@/lib/theme'

export function ThemeToggle() {
  const { t } = useTranslation()
  const theme = useTheme((state) => state.theme)
  const toggle = useTheme((state) => state.toggle)

  return (
    <Button variant="ghost" size="icon-sm" aria-label={t('common.toggleTheme')} onClick={toggle}>
      {theme === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
    </Button>
  )
}
