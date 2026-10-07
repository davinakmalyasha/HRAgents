import { describe, expect, it } from 'vitest'

import { detailText, matches, problemMessage } from './problem'

const t = (key: string) => key

describe('the problem detail is polymorphic and read safely', () => {
  it('reads a string detail', () => {
    expect(detailText({ detail: 'Reason code required' })).toBe('Reason code required')
  })

  it('falls back to the title when detail is a list', () => {
    /**
     * A validation problem sends a list of per-field errors in `detail`. Returning it
     * would put `[object Object]` in front of a person, and the server's own schema now
     * types it as a union so the guard is not merely defensive.
     */
    const validation = {
      title: 'The request could not be understood.',
      detail: [{ loc: ['body', 'reason'], msg: 'Field required' }],
    }
    expect(detailText(validation)).toBe('The request could not be understood.')
  })

  it('returns nothing when there is no string to show', () => {
    expect(detailText({ detail: [{ msg: 'Field required' }] })).toBeUndefined()
    expect(detailText(undefined)).toBeUndefined()
  })

  it('prefers the title over the detail', () => {
    expect(detailText({ title: 'Short', detail: 'Long explanation' })).toBe('Short')
  })
})

describe('codes are matched, not prose', () => {
  it('matches on the exact code', () => {
    expect(matches({ code: 'rate_table_unusable' }, 'rate_table_unusable')).toBe(true)
    expect(matches({ code: 'other' }, 'rate_table_unusable')).toBe(false)
    expect(matches(undefined, 'anything')).toBe(false)
  })
})

describe('the network failure never reads as a rejection', () => {
  it('says the server was unreachable, not that it refused', () => {
    const message = problemMessage(0, undefined, t, 'common')
    expect(message).toBe('Could not reach the server.')
  })
})
