import createClient from 'openapi-fetch'

import type { paths } from '@/api/schema'
import { credentialDisposition, forgetApiKey, notifyUnauthorized, storedApiKey } from '@/lib/auth'

/**
 * The API client, with the credential attached and refused credentials handled.
 *
 * The key is read per request rather than captured at import time, so signing in
 * or out takes effect on the next call without rebuilding the client.
 *
 * A 401 drops the stored key -- it can never start working again, and leaving
 * it in place would send it on every retry -- and notifies the app, which is
 * what sends the person to the sign-in screen. Anything else, including a 403,
 * leaves the credential alone.
 */
export const api = createClient<paths>({
  baseUrl: '/',
  /**
   * Resolved at call time, not captured when the client is built. Capturing
   * `globalThis.fetch` at import time would freeze whatever was installed then,
   * so tests could not substitute it and a polyfill loaded later would be
   * ignored.
   */
  fetch: (input) => globalThis.fetch(input),
})

api.use({
  onRequest({ request }) {
    const key = storedApiKey()
    if (key !== null) {
      request.headers.set('X-API-Key', key)
    }
    return request
  },
  async onResponse({ response }) {
    if (response.status !== 401) {
      return response
    }
    const code = await problemCode(response.clone())
    if (credentialDisposition(response.status, code) === 'forget') {
      forgetApiKey()
      notifyUnauthorized()
    }
    return response
  },
})

/** The `code` from a problem body, or null when the body is not one. */
async function problemCode(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json()
    if (body !== null && typeof body === 'object' && 'code' in body) {
      const code = (body as { code?: unknown }).code
      return typeof code === 'string' ? code : null
    }
  } catch {
    // A 401 with no JSON body is still a refused credential; the status is
    // enough to forget it.
  }
  return null
}
