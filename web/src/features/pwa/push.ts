import type { PushSubscriptionPayload } from './pushApi'

/**
 * Browser-side Web Push, kept separate from React so it can be exercised
 * without a component. Everything here is feature-detected: an unsupported
 * browser gets an honest absence, never a button that cannot work.
 */

export class PushUnsupportedError extends Error {
  constructor() {
    super('this browser cannot receive push notifications')
    this.name = 'PushUnsupportedError'
  }
}

export class PushPermissionError extends Error {
  constructor() {
    super('notification permission was not granted')
    this.name = 'PushPermissionError'
  }
}

export function pushSupported(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  )
}

/** The manifest scope's registration, or null before one exists. */
async function registration(): Promise<ServiceWorkerRegistration | null> {
  const found = await navigator.serviceWorker.getRegistration('/app/')
  return found ?? null
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  const found = await registration()
  if (found === null) return null
  return found.pushManager.getSubscription()
}

export async function subscribeBrowser(publicKey: string): Promise<PushSubscription> {
  if (!pushSupported()) throw new PushUnsupportedError()
  const permission = await window.Notification.requestPermission()
  if (permission !== 'granted') throw new PushPermissionError()
  const found = await navigator.serviceWorker.ready
  return found.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(publicKey),
  })
}

export async function unsubscribeBrowser(): Promise<boolean> {
  const existing = await currentSubscription()
  if (existing === null) return false
  return existing.unsubscribe()
}

export function subscriptionPayload(subscription: PushSubscription): PushSubscriptionPayload {
  const json = subscription.toJSON()
  const p256dh = json.keys?.p256dh
  const auth = json.keys?.auth
  if (json.endpoint === undefined || p256dh === undefined || auth === undefined) {
    throw new PushUnsupportedError()
  }
  return {
    endpoint: json.endpoint,
    keys: { p256dh, auth },
    user_agent: typeof navigator === 'undefined' ? null : navigator.userAgent,
  }
}

/**
 * The application server key is base64url; PushManager wants raw bytes.
 *
 * Padding is restored before atob because base64url drops it, and a payload
 * whose length is not a multiple of four would otherwise decode to garbage.
 */
export function urlBase64ToUint8Array(base64Url: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64Url.length % 4)) % 4)
  const base64 = (base64Url + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = window.atob(base64)
  const bytes = new Uint8Array(raw.length)
  for (let index = 0; index < raw.length; index += 1) {
    bytes[index] = raw.charCodeAt(index)
  }
  return bytes
}
