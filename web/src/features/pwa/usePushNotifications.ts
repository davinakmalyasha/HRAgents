import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'

import {
  fetchPushConfig,
  registerPushSubscription,
  removeSubscriptionByEndpoint,
  sendPushTest,
} from './pushApi'
import {
  PushPermissionError,
  PushUnsupportedError,
  currentSubscription,
  pushSupported,
  subscribeBrowser,
  subscriptionPayload,
} from './push'

export type PushStatus =
  'loading' | 'unsupported' | 'unconfigured' | 'blocked' | 'disabled' | 'working' | 'enabled'

export type PushError = 'permission' | 'subscribe' | 'save' | 'deliver' | null

/**
 * The notification toggle's state machine.
 *
 * "On" means the browser holds a subscription *and* the server has the same
 * endpoint: a browser-only subscription would show a promise nothing can keep.
 * Enabling sends one test notification, because a permission prompt that ends
 * in silence is indistinguishable from a failure.
 */
export function usePushNotifications() {
  const config = useQuery({
    queryKey: ['push-config'],
    queryFn: fetchPushConfig,
    staleTime: 60_000,
    retry: false,
  })
  const [status, setStatus] = useState<PushStatus>('loading')
  const [error, setError] = useState<PushError>(null)
  const enabled = config.data?.enabled === true
  const publicKey = config.data?.public_key ?? null

  useEffect(() => {
    if (!config.isSuccess) return
    let cancelled = false
    void (async () => {
      if (!pushSupported()) {
        if (!cancelled) setStatus('unsupported')
        return
      }
      if (!enabled || publicKey === null) {
        if (!cancelled) setStatus('unconfigured')
        return
      }
      if (window.Notification.permission === 'denied') {
        if (!cancelled) setStatus('blocked')
        return
      }
      try {
        const existing = await currentSubscription()
        if (existing !== null) {
          // A browser can hold a subscription the server has forgotten (a
          // restore, a rebuilt database). Registering is idempotent by
          // endpoint, so the pair is repaired instead of shown as broken.
          await registerPushSubscription(subscriptionPayload(existing))
          if (!cancelled) setStatus('enabled')
          return
        }
      } catch {
        // Not subscribed on the server is a normal state; the toggle retries.
      }
      if (!cancelled) setStatus('disabled')
    })()
    return () => {
      cancelled = true
    }
  }, [config.isSuccess, enabled, publicKey])

  const enable = useCallback(async () => {
    if (publicKey === null) return
    setError(null)
    setStatus('working')
    try {
      const subscription = await subscribeBrowser(publicKey)
      await registerPushSubscription(subscriptionPayload(subscription))
    } catch (cause) {
      setError(
        cause instanceof PushPermissionError
          ? 'permission'
          : cause instanceof PushUnsupportedError
            ? 'subscribe'
            : 'save',
      )
      setStatus('disabled')
      return
    }
    try {
      const report = await sendPushTest()
      if (report.delivered === 0) setError('deliver')
    } catch {
      setError('deliver')
    }
    setStatus('enabled')
  }, [publicKey])

  const disable = useCallback(async () => {
    setError(null)
    setStatus('working')
    try {
      const existing = await currentSubscription()
      if (existing !== null) {
        const { endpoint } = existing
        await existing.unsubscribe()
        await removeSubscriptionByEndpoint(endpoint)
      }
    } catch {
      setError('save')
    }
    setStatus('disabled')
  }, [])

  const toggle = status === 'enabled' ? disable : enable
  return { status, error, toggle }
}
