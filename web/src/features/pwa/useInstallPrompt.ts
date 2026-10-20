import { useEffect, useState } from 'react'

/**
 * The browser's install affordance, when it offers one.
 *
 * Chromium fires `beforeinstallprompt` once the manifest, icons and service
 * worker qualify; Safari has no such event, so the button simply never appears
 * there instead of pretending. The event is kept until the person acts because
 * it can only be prompted once.
 */
interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

export function useInstallPrompt() {
  const [deferred, setDeferred] = useState<InstallPromptEvent | null>(null)
  const [installed, setInstalled] = useState(false)

  useEffect(() => {
    function onBeforeInstall(event: Event) {
      // Suppress the browser's own mini-infobar; the topbar button is the offer.
      event.preventDefault()
      setDeferred(event as InstallPromptEvent)
    }
    function onInstalled() {
      setInstalled(true)
      setDeferred(null)
    }
    window.addEventListener('beforeinstallprompt', onBeforeInstall)
    window.addEventListener('appinstalled', onInstalled)
    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall)
      window.removeEventListener('appinstalled', onInstalled)
    }
  }, [])

  async function install() {
    if (deferred === null) {
      return
    }
    await deferred.prompt()
    await deferred.userChoice
    // The event is single-use; offering the button again would do nothing.
    setDeferred(null)
  }

  return { canInstall: deferred !== null && !installed, install, installed }
}
