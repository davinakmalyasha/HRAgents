import { describe, expect, it } from 'vitest'

import {
  PushPermissionError,
  PushUnsupportedError,
  pushSupported,
  subscribeBrowser,
  subscriptionPayload,
  urlBase64ToUint8Array,
} from './push'

describe('urlBase64ToUint8Array', () => {
  it('decodes an unpadded base64url key into the same bytes as base64', () => {
    // "hello" is aGVsbG8= in base64 and aGVsbG8 in base64url.
    expect(Array.from(urlBase64ToUint8Array('aGVsbG8'))).toEqual([104, 101, 108, 108, 111])
  })

  it('maps the url-safe characters back', () => {
    expect(Array.from(urlBase64ToUint8Array('-_8'))).toEqual([251, 255])
  })
})

describe('push support', () => {
  it('reports unsupported in a browser without the APIs', () => {
    expect(pushSupported()).toBe(false)
  })

  it('refuses to subscribe instead of pretending', async () => {
    await expect(subscribeBrowser('key')).rejects.toBeInstanceOf(PushUnsupportedError)
  })
})

describe('subscriptionPayload', () => {
  it('sends the endpoint and both keys, never the raw JSON', () => {
    const subscription = {
      toJSON: () => ({
        endpoint: 'https://fcm.googleapis.com/fcm/send/abc',
        keys: { p256dh: 'p'.repeat(20), auth: 'a'.repeat(12) },
      }),
    } as unknown as PushSubscription

    const payload = subscriptionPayload(subscription)

    expect(payload.endpoint).toContain('fcm.googleapis.com')
    expect(payload.keys).toEqual({ p256dh: 'p'.repeat(20), auth: 'a'.repeat(12) })
  })

  it('refuses a subscription the browser described incompletely', () => {
    const subscription = {
      toJSON: () => ({ endpoint: 'https://example.com/push', keys: {} }),
    } as unknown as PushSubscription

    expect(() => subscriptionPayload(subscription)).toThrow(PushUnsupportedError)
  })
})

describe('errors', () => {
  it('carry names the toggle can distinguish', () => {
    expect(new PushPermissionError().name).toBe('PushPermissionError')
    expect(new PushUnsupportedError().name).toBe('PushUnsupportedError')
  })
})
