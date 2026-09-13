import Papa from 'papaparse'

export const IMPORT_BATCH_LIMIT = 500

export interface CsvRow {
  name: string
  email: string
  links: string
  cv: string
  line: number
}

export interface CsvIssue {
  line: number
  messageKey: string
  count?: number
}

export interface ImportItem {
  full_name: string
  emails: string[]
  links: string
  document_id: string | null
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function cell(record: Record<string, string | undefined>, key: string): string {
  return (record[key] ?? '').trim()
}

/**
 * Parse the paste/upload text into candidate rows.
 *
 * Expected header (case-insensitive): name, email, links (optional), cv (optional).
 * A `cv` value must match an uploaded CV filename exactly.
 */
export function parseImportCsv(text: string): { rows: CsvRow[]; issues: CsvIssue[] } {
  const parsed = Papa.parse<Record<string, string>>(text, {
    header: true,
    skipEmptyLines: 'greedy',
    transformHeader: (header) => header.trim().toLowerCase(),
  })

  const issues: CsvIssue[] = parsed.errors.slice(0, 1).map(() => ({
    line: 0,
    messageKey: 'import.errors.badHeader',
  }))

  const fields = new Set(parsed.meta.fields ?? [])
  if (!fields.has('name') || !fields.has('email')) {
    return { rows: [], issues: [{ line: 0, messageKey: 'import.errors.badHeader' }] }
  }

  const rows: CsvRow[] = []
  parsed.data.forEach((record, index) => {
    const name = cell(record, 'name')
    const email = cell(record, 'email')
    if (name === '' && email === '') {
      return
    }
    rows.push({
      name,
      email,
      links: cell(record, 'links'),
      cv: cell(record, 'cv'),
      line: index + 2,
    })
  })
  return { rows, issues }
}

/** Validate rows against the batch limit, email shape, and uploaded CV names. */
export function validateImportRows(rows: CsvRow[], knownCvs: Set<string>): CsvIssue[] {
  const issues: CsvIssue[] = []
  if (rows.length === 0) {
    issues.push({ line: 0, messageKey: 'import.errors.empty' })
    return issues
  }
  if (rows.length > IMPORT_BATCH_LIMIT) {
    issues.push({ line: 0, messageKey: 'import.errors.tooMany', count: IMPORT_BATCH_LIMIT })
  }
  for (const row of rows) {
    if (row.name === '') {
      issues.push({ line: row.line, messageKey: 'import.errors.missingName' })
    }
    if (!EMAIL_PATTERN.test(row.email)) {
      issues.push({ line: row.line, messageKey: 'import.errors.badEmail' })
    }
    if (row.cv !== '' && !knownCvs.has(row.cv)) {
      issues.push({ line: row.line, messageKey: 'import.errors.unknownCv' })
    }
  }
  return issues
}

export function toImportItems(rows: CsvRow[], cvDocuments: Map<string, string>): ImportItem[] {
  return rows.map((row) => ({
    full_name: row.name,
    emails: [row.email],
    links: row.links,
    document_id: row.cv === '' ? null : (cvDocuments.get(row.cv) ?? null),
  }))
}
