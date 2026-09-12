import '@fontsource-variable/inter'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import '@fontsource/jetbrains-mono/600.css'
import '@/styles/globals.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import '@/i18n'
import { App } from '@/App'

const container = document.getElementById('root')
if (container === null) {
  throw new Error('root element is missing')
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
