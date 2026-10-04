/**
 * One place that turns an HTTP status into a sentence a person can act on.
 *
 * This replaces nine per-dialog `errorFor()` copies that had drifted apart:
 * `CommunicationPanel` mapped 400 to "invalid phone" and 422 to "invalid
 * recipient" (inverted), `jobs` had no 404 string at all, and every copy had no
 * answer for the case that actually matters most on a phone -- the request
 * never reached the server.
 *
 * Two rules the copies broke:
 *
 * 1. A status of 0 means the request never completed (offline, DNS failure,
 *    the API container is down). It must never fall through to the generic
 *    "something went wrong", because that reads as "the server rejected my
 *    request" and invites the user to try again, forever.
 * 2. The API is the authority on *which* error this is. Anything derived from
 *    its prose lives in the `overrides` callback the caller passes, so the
 *    fragile contract is visible in one signature instead of nine bodies.
 *    `code` is the machine-readable replacement and is preferred the moment the
 *    server sends one -- see `matches()` below.
 */

/** HTTP status to the `*.errors.*` suffix every namespace uses. */
const STATUS_KEY: Readonly<Record<number, string>> = {
  400: 'invalid',
  403: 'forbidden',
  404: 'notFound',
  405: 'invalid',
  409: 'conflict',
  422: 'invalid',
  429: 'rateLimited',
}

/** The response never arrived. Not an HTTP status; `Response.status` is 0. */
export const NETWORK_FAILURE = 0

export interface ProblemDetail {
  title?: string
  detail?: string
  code?: string
}

export interface ProblemOptions {
  /**
   * Per-dialog escape hatch, tried before the shared status table. Return
   * `null` to fall through to the default mapping for that status.
   */
  overrides?: (status: number, detail: ProblemDetail | undefined) => string | null
}

/**
 * True when the server said `code: X`. Prefer this over prose matching: a
 * code is a contract, and reword the exception message on the server and this
 * keeps working while a substring match silently degrades.
 */
export function matches(detail: ProblemDetail | undefined, code: string): boolean {
  return detail?.code === code
}

/** The prose the server actually sent, for the rare case it must be shown. */
export function detailText(detail: ProblemDetail | undefined): string | undefined {
  if (!detail) {
    return undefined
  }
  return detail.title ?? (typeof detail.detail === 'string' ? detail.detail : undefined)
}

function resolve(t: (key: string) => string, key: string, fallback: string): string {
  const value = t(key)
  // i18next returns the key verbatim when it is missing, so this is the one
  // reliable way to tell "translated" from "absent".
  return value === key ? fallback : value
}

export function problemMessage(
  status: number,
  detail: ProblemDetail | undefined,
  t: (key: string) => string,
  namespace: string,
  options: ProblemOptions = {},
): string {
  if (status === NETWORK_FAILURE) {
    return resolve(t, 'common.errors.network', 'Could not reach the server.')
  }

  const override = options.overrides?.(status, detail)
  if (override !== null && override !== undefined) {
    return override
  }

  const genericFailed = resolve(
    t,
    `${namespace}.errors.failed`,
    resolve(t, 'common.errors.failed', 'Something went wrong.'),
  )
  const suffix = STATUS_KEY[status]
  if (suffix === undefined) {
    return genericFailed
  }
  return resolve(t, `${namespace}.errors.${suffix}`, genericFailed)
}
