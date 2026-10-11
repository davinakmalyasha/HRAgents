import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from './api'

/**
 * Node's Request requires an absolute URL, unlike the browser's. Production uses
 * '/', which is same-origin; the tests give the client one it can parse.
 */
const ABSOLUTE = 'http://localhost/app'
import { forgetApiKey, onUnauthorized, rememberApiKey, storedApiKey } from './auth'

afterEach(() => {
  forgetApiKey()
  onUnauthorized(null)
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function problemResponse(status: number, code: string): Response {
  return new Response(JSON.stringify({ code, title: code, status }), {
    status,
    headers: { 'content-type': 'application/problem+json' },
  })
}

describe('the client carries the stored credential', () => {
  it('sends X-API-Key on every request once a key is stored', async () => {
    const seen: Request[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (request: Request) => {
        seen.push(request)
        return new Response(JSON.stringify({ actor_id: 'Rina', role: 'hr_admin' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }),
    )
    rememberApiKey('rina-key')

    await api.GET('/v1/session', { baseUrl: ABSOLUTE })

    expect(seen).toHaveLength(1)
    expect(seen[0]?.headers.get('X-API-Key')).toBe('rina-key')
  })

  it('sends no credential header when nothing is stored', async () => {
    const seen: Request[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (request: Request) => {
        seen.push(request)
        return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } })
      }),
    )

    await api.GET('/v1/session', { baseUrl: ABSOLUTE })

    expect(seen[0]?.headers.get('X-API-Key')).toBeNull()
  })

  it('reads the key per request, so signing out takes effect immediately', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{}', { status: 200 })),
    )
    rememberApiKey('first')
    await api.GET('/v1/session', { baseUrl: ABSOLUTE })
    forgetApiKey()
    const calls: Request[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (request: Request) => {
        calls.push(request)
        return new Response('{}', { status: 200 })
      }),
    )

    await api.GET('/v1/session', { baseUrl: ABSOLUTE })

    expect(calls[0]?.headers.get('X-API-Key')).toBeNull()
  })
})

describe('a refused credential is dropped and reported', () => {
  it('forgets the key and notifies on auth_invalid', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => problemResponse(401, 'auth_invalid')),
    )
    rememberApiKey('stale-key')
    let notified = 0
    onUnauthorized(() => {
      notified += 1
    })

    await api.GET('/v1/session', { baseUrl: ABSOLUTE })

    expect(storedApiKey()).toBeNull()
    expect(notified).toBe(1)
  })

  it('forgets the key and notifies on auth_required', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => problemResponse(401, 'auth_required')),
    )
    let notified = 0
    onUnauthorized(() => {
      notified += 1
    })

    await api.GET('/v1/session', { baseUrl: ABSOLUTE })

    expect(notified).toBe(1)
  })

  it('forgets a 401 even when the body is not a problem document', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('nope', { status: 401 })),
    )
    rememberApiKey('stale-key')

    await api.GET('/v1/session', { baseUrl: ABSOLUTE })

    expect(storedApiKey()).toBeNull()
  })

  it('keeps the key and stays quiet on a 403', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => problemResponse(403, 'permission_denied')),
    )
    rememberApiKey('valid-but-limited')
    let notified = 0
    onUnauthorized(() => {
      notified += 1
    })

    await api.GET('/v1/session', { baseUrl: ABSOLUTE })

    expect(storedApiKey()).toBe('valid-but-limited')
    expect(notified).toBe(0)
  })

  it('leaves a network failure alone', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('fetch failed')
      }),
    )
    rememberApiKey('good-key')
    let notified = 0
    onUnauthorized(() => {
      notified += 1
    })

    await expect(api.GET('/v1/session', { baseUrl: ABSOLUTE })).rejects.toThrow('fetch failed')

    expect(storedApiKey()).toBe('good-key')
    expect(notified).toBe(0)
  })
})
