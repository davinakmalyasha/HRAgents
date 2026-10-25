import { describe, expect, it } from 'vitest'

import { EntryParseError, entryToLine, parseEntries } from './credentialsApi'

describe('parseEntries', () => {
  it('reads a name-only row as a verified credential', () => {
    expect(parseEntries('AWS Solutions Architect')).toEqual([
      {
        name: 'AWS Solutions Architect',
        status: 'verified',
        credential_id: null,
        expires_on: null,
        notes: null,
      },
    ])
  })

  it('reads the full row and keeps notes containing a pipe', () => {
    const [entry] = parseEntries('CKA | failed | CKA-1 | 2026-01-31 | checked: re-exam | pending')
    expect(entry).toEqual({
      name: 'CKA',
      status: 'failed',
      credential_id: 'CKA-1',
      expires_on: '2026-01-31',
      notes: 'checked: re-exam | pending',
    })
  })

  it('skips blank lines and refuses an empty import', () => {
    expect(parseEntries('\n  \nIFRS\n')).toHaveLength(1)
    expect(() => parseEntries(' \n')).toThrow(EntryParseError)
  })

  it('refuses an unknown status or a malformed date, naming the line', () => {
    expect(() => parseEntries('IFRS\nCKA | maybe')).toThrowError(/line 2/)
    expect(() => parseEntries('IFRS\nCKA | verified | | 31-01-2026')).toThrowError(/line 2/)
  })

  it('round-trips an entry back to its line', () => {
    expect(
      entryToLine({
        name: 'CKA',
        status: 'verified',
        credential_id: 'CKA-1',
        expires_on: '2027-01-01',
        notes: null,
      }),
    ).toBe('CKA | verified | CKA-1 | 2027-01-01')
  })
})
