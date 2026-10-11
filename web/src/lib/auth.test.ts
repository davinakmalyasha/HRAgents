import { afterEach, describe, expect, it } from 'vitest'

import {
  API_KEY_STORAGE_KEY,
  AuthRequiredError,
  credentialDisposition,
  forgetApiKey,
  isAuthRequired,
  notifyUnauthorized,
  onUnauthorized,
  rememberApiKey,
  storedApiKey,
} from './auth'

afterEach(() => {
  forgetApiKey()
  onUnauthorized(null)
  localStorage.clear()
  sessionStorage.clear()
})

describe('the key is kept for the tab, not for the browser', () => {
  it('round-trips a key through sessionStorage', () => {
    rememberApiKey('  rina-key  ')
    expect(storedApiKey()).toBe('rina-key')
    expect(sessionStorage.getItem(API_KEY_STORAGE_KEY)).toBe('rina-key')
  })

  it('treats a blank stored value as no key at all', () => {
    sessionStorage.setItem(API_KEY_STORAGE_KEY, '   ')
    expect(storedApiKey()).toBeNull()
  })

  it('forgets on sign-out', () => {
    rememberApiKey('rina-key')
    forgetApiKey()
    expect(storedApiKey()).toBeNull()
  })

  it('never writes the key to localStorage', () => {
    /**
     * localStorage survives the tab and is shared with every later visit on
     * this origin. The key is the whole credential, so it gets the shorter
     * lifetime: closing the tab ends the session.
     */
    rememberApiKey('rina-key')
    expect(localStorage.length).toBe(0)
    expect(JSON.stringify(localStorage)).not.toContain('rina-key')
  })
})

describe('what a refused response does to the credential', () => {
  it('forgets the key on either 401 code', () => {
    expect(credentialDisposition(401, 'auth_required')).toBe('forget')
    expect(credentialDisposition(401, 'auth_invalid')).toBe('forget')
  })

  it('forgets a 401 with no problem body at all', () => {
    /**A refused credential is refused whether or not the body parsed. Keeping a
     * key that produced a bare 401 sends it again on every retry.
     */
    expect(credentialDisposition(401, null)).toBe('forget')
  })

  it('keeps the key on a 403', () => {
    /**
     * A 403 means the credential works and the role lacks the permission. Signing
     * somebody out over that would ask them to fix, by signing in again, the one
     * thing signing in again cannot change.
     */
    expect(credentialDisposition(403, 'permission_denied')).toBe('keep')
  })

  it('keeps the key on everything that is not a 401', () => {
    for (const status of [200, 400, 404, 409, 422, 429, 500, 503]) {
      expect(credentialDisposition(status, null)).toBe('keep')
    }
  })
})

describe('a refused credential is distinguishable from a broken server', () => {
  it('is its own error type carrying the status and code', () => {
    const error = new AuthRequiredError(401, 'auth_invalid')
    expect(isAuthRequired(error)).toBe(true)
    expect(error.status).toBe(401)
    expect(error.code).toBe('auth_invalid')
    expect(error.name).toBe('AuthRequiredError')
  })

  it('does not swallow a network error', () => {
    /**The two need opposite responses: one sends the person to sign in, the
     * other tells them the server is unreachable. Collapsing them shows a
     * sign-in screen to somebody whose wifi dropped.
     */
    expect(isAuthRequired(new Error('network down'))).toBe(false)
    expect(isAuthRequired(undefined)).toBe(false)
  })
})

describe('the window can subscribe to refusals', () => {
  it('notifies the installed handler once per call', () => {
    let count = 0
    onUnauthorized(() => {
      count += 1
    })
    notifyUnauthorized()
    notifyUnauthorized()
    expect(count).toBe(2)
  })

  it('does nothing when no handler is installed', () => {
    expect(() => notifyUnauthorized()).not.toThrow()
  })

  it('can uninstall, so an unmounted screen stops navigating', () => {
    let count = 0
    onUnauthorized(() => {
      count += 1
    })
    onUnauthorized(null)
    notifyUnauthorized()
    expect(count).toBe(0)
  })
})
