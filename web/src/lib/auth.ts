/**
 * The session credential, and what a 401 means for it.
 *
 * The server authenticates with role-bound API keys: the key decides who you
 * are and what you may do. So "signing in" here is entering a key, not a
 * password -- there are no passwords to reset, and pretending otherwise would
 * invent a flow the backend cannot honour.
 *
 * The key lives in `sessionStorage`, not `localStorage`: closing the tab ends
 * the session. That is a mitigation, not a defence -- any script on this origin
 * can read it -- so the deployment guidance of TLS plus network restriction in
 * front still stands.
 */

export const API_KEY_STORAGE_KEY = 'hragents.apiKey'

/** The stored key, or null when this browser holds none. */
export function storedApiKey(): string | null {
  if (typeof sessionStorage === 'undefined') {
    return null
  }
  const value = sessionStorage.getItem(API_KEY_STORAGE_KEY)
  return value === null || value.trim() === '' ? null : value
}

export function rememberApiKey(key: string): void {
  if (typeof sessionStorage !== 'undefined') {
    sessionStorage.setItem(API_KEY_STORAGE_KEY, key.trim())
  }
}

export function forgetApiKey(): void {
  if (typeof sessionStorage !== 'undefined') {
    sessionStorage.removeItem(API_KEY_STORAGE_KEY)
  }
}

/**
 * An error meaning "this request was refused for lack of a usable credential".
 *
 * Distinct from a network failure, because the two need opposite responses:
 * one sends the person to sign in, the other tells them the server is
 * unreachable. Collapsing them is how a dashboard shows a sign-in screen to
 * somebody whose wifi dropped.
 */
export class AuthRequiredError extends Error {
  readonly status: number
  readonly code: string | null

  constructor(status: number, code: string | null) {
    super(code === null ? 'authentication required' : code)
    this.name = 'AuthRequiredError'
    this.status = status
    this.code = code
  }
}

export function isAuthRequired(error: unknown): error is AuthRequiredError {
  return error instanceof AuthRequiredError
}

/**
 * What a refused response should do to the stored credential.
 *
 * `auth_required` and `auth_invalid` are the server's own codes for "nothing
 * was presented" and "what you presented was not accepted". Both mean the key
 * this browser holds is not usable, so it is dropped; any other status is
 * somebody else's problem and the credential is left alone. A 403 is
 * deliberately *not* here: the key is valid, the role just lacks the
 * permission, and forgetting it would sign the person out over a permission
 * they cannot change by signing in again.
 */
export function credentialDisposition(status: number, code: string | null): 'forget' | 'keep' {
  if (status !== 401) {
    return 'keep'
  }
  return code === null || code === 'auth_required' || code === 'auth_invalid' ? 'forget' : 'keep'
}

/**
 * A subscriber the response middleware can tell when a credential is refused.
 *
 * The middleware runs outside React, so it cannot navigate; it reports and the
 * app decides. Tests install their own handler rather than asserting on
 * `window.location`.
 */
export type UnauthorizedHandler = () => void

let handler: UnauthorizedHandler | null = null

export function onUnauthorized(next: UnauthorizedHandler | null): void {
  handler = next
}

export function notifyUnauthorized(): void {
  handler?.()
}
