import { describe, expect, it } from 'vitest'

import type { components } from '@/api/schema'

import {
  impactTone,
  isAwaitingDecision,
  isBreachTerminal,
  isExecutable,
  isSubmittable,
  nextBreachStatuses,
  purgeSummary,
  purgedOutcomes,
  sparedOutcomes,
  unverifiedTables,
} from './complianceApi'

type Table = components['schemas']['RateTableView']
type Report = components['schemas']['PurgeReportView']

function table(overrides: Partial<Table> = {}): Table {
  return {
    id: 'tbl-1',
    name: 'PPH21 TER 2026',
    kind: 'pph21_ter',
    jurisdiction: 'ID',
    source_note: null,
    verified: false,
    verified_by: null,
    entry_count: 4,
    usable: true,
    effective_from: '2026-01-01',
    effective_to: null,
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('a breach only moves forward along its own ladder', () => {
  it('offers exactly the next status', () => {
    /**`ComplianceService` refuses anything but open → contained → notified → closed.
     * Offering `closed` on a breach nobody contained would be refused every time.
     */
    expect(nextBreachStatuses('open')).toEqual(['contained'])
    expect(nextBreachStatuses('contained')).toEqual(['notified'])
    expect(nextBreachStatuses('notified')).toEqual(['closed'])
  })

  it('offers nothing once closed', () => {
    expect(nextBreachStatuses('closed')).toEqual([])
    expect(isBreachTerminal('closed')).toBe(true)
    expect(isBreachTerminal('notified')).toBe(false)
  })
})

describe('impact drives the tone but never the tone alone', () => {
  it('treats high and critical as urgent', () => {
    expect(impactTone('critical')).toBe('error')
    expect(impactTone('high')).toBe('error')
  })

  it('treats low and medium as ordinary', () => {
    /**The badge still renders a label; this only chooses the colour, and colour is
     * never the only signal.
     */
    expect(impactTone('low')).toBe('waiting')
    expect(impactTone('medium')).toBe('waiting')
  })
})

describe('an erasure is submitted once and executed once', () => {
  it('submits only while received', () => {
    /**`pending_approval` belongs to the approval engine. Offering submit again would
     * raise a second approval for one request.
     */
    expect(isSubmittable('received')).toBe(true)
    expect(isSubmittable('pending_approval')).toBe(false)
    expect(isSubmittable('approved')).toBe(false)
  })

  it('executes only what a human approved and nobody has run', () => {
    /**Execution destroys records. `partial` has already run once, so re-running it
     * would be a second purge of the same subject.
     */
    expect(isExecutable('approved')).toBe(true)
    expect(isExecutable('partial')).toBe(true)
    expect(isExecutable('executed')).toBe(false)
    expect(isExecutable('received')).toBe(false)
  })

  it('counts a received and a pending request as awaiting a decision', () => {
    expect(isAwaitingDecision('received')).toBe(true)
    expect(isAwaitingDecision('pending_approval')).toBe(true)
    expect(isAwaitingDecision('executed')).toBe(false)
    expect(isAwaitingDecision('denied')).toBe(false)
  })
})

describe('an unverified rate table is a guess about a statutory figure', () => {
  it('lists only the unverified ones', () => {
    const list = [table({ id: 'a' }), table({ id: 'b', verified: true })]
    expect(unverifiedTables(list).map((item) => item.id)).toEqual(['a'])
  })

  it('lists none when every table has a source behind it', () => {
    expect(unverifiedTables([table({ verified: true })])).toHaveLength(0)
  })
})

describe('a purge report says what it did and what it did not', () => {
  const report: Report = {
    by: 'local-operator',
    dry_run: true,
    executed_at: '2026-01-01T00:00:00Z',
    purged: [
      {
        record_id: 'rec-1',
        entity: 'employee',
        subject_kind: 'employee',
        subject_id: 'emp-1',
        action: 'delete',
        purged: true,
        detail: 'deleted',
        status: 'purged',
      },
    ],
    held: ['rec-3'],
    uncovered: ['rec-4'],
    skipped: [
      {
        record_id: 'rec-2',
        entity: 'application',
        subject_kind: 'candidate',
        subject_id: 'cand-1',
        action: 'anonymize',
        purged: false,
        detail: 'no handler',
        status: 'skipped',
      },
    ],
  }

  /**purged holds only what went; anything the server could not touch is reported
   * separately, which is why a reader can tell the difference without parsing prose.
   */
  const allOutcomes = [...report.purged, ...(report.skipped ?? [])]

  it('separates destroyed from spared', () => {
    /**A report reading "purged: 1" with nothing about the records left on disk is how
     * a retention obligation gets quietly unmet.
     */
    const summary = purgeSummary(report)
    expect(summary.destroyed).toBe(1)
    expect(summary.spared).toBe(1)
    expect(summary.stillPresent).toEqual(['rec-3', 'rec-4'])
  })

  it('keeps held and skipped records visible in the outcome lists', () => {
    expect(purgedOutcomes(allOutcomes).map((item) => item.record_id)).toEqual(['rec-1'])
    expect(sparedOutcomes(allOutcomes).map((item) => item.record_id)).toEqual(['rec-2'])
  })

  it('reports nothing purged for a dry run without inventing any', () => {
    const dry = { ...report, dry_run: true, purged: [], skipped: report.skipped }
    expect(purgeSummary(dry).destroyed).toBe(0)
    expect(purgeSummary(dry).spared).toBe(1)
  })
})
