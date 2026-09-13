import { describe, expect, it } from 'vitest'

import { parseImportCsv, toImportItems, validateImportRows } from './importCsv'

const VALID =
  'name,email,links,cv\nBudi Santoso,budi@example.com,github.com/budi,budi.pdf\nSinta,sinta@example.com,,\n'

describe('parseImportCsv', () => {
  it('parses rows with line numbers', () => {
    const { rows, issues } = parseImportCsv(VALID)

    expect(issues).toEqual([])
    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({
      name: 'Budi Santoso',
      email: 'budi@example.com',
      links: 'github.com/budi',
      cv: 'budi.pdf',
      line: 2,
    })
  })

  it('rejects a missing header', () => {
    const { rows, issues } = parseImportCsv('Budi,budi@example.com\n')

    expect(rows).toEqual([])
    expect(issues[0]?.messageKey).toBe('import.errors.badHeader')
  })

  it('handles uppercase headers and quoted commas', () => {
    const { rows } = parseImportCsv('Name,Email\n"Doe, John",john@example.com\n')

    expect(rows[0]?.name).toBe('Doe, John')
  })
})

describe('validateImportRows', () => {
  it('flags missing names, bad emails, and unknown CVs', () => {
    const { rows } = parseImportCsv('name,email,cv\n,not-an-email,missing.pdf\n')
    const issues = validateImportRows(rows, new Set(['budi.pdf']))

    expect(issues.map((issue) => issue.messageKey)).toEqual([
      'import.errors.missingName',
      'import.errors.badEmail',
      'import.errors.unknownCv',
    ])
  })

  it('flags empty input and oversized batches', () => {
    expect(validateImportRows([], new Set())[0]?.messageKey).toBe('import.errors.empty')

    const many = Array.from({ length: 501 }, (_, index) => ({
      name: `N${index}`,
      email: `n${index}@x.com`,
      links: '',
      cv: '',
      line: index + 2,
    }))
    expect(validateImportRows(many, new Set())[0]?.messageKey).toBe('import.errors.tooMany')
  })
})

describe('toImportItems', () => {
  it('links CV filenames to uploaded document ids', () => {
    const { rows } = parseImportCsv(VALID)
    const items = toImportItems(rows, new Map([['budi.pdf', 'doc-1']]))

    expect(items[0]).toEqual({
      full_name: 'Budi Santoso',
      emails: ['budi@example.com'],
      links: 'github.com/budi',
      document_id: 'doc-1',
    })
    expect(items[1]?.document_id).toBeNull()
  })
})
