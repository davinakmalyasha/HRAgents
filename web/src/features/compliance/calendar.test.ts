import { describe, expect, it } from 'vitest'

import type { CalendarItemView } from './complianceApi'

import { groupByDay, monthWindow, shiftMonth } from './calendar'

function item(overrides: Partial<CalendarItemView> = {}): CalendarItemView {
  return {
    source: 'deadline',
    kind: 'probation_end',
    due_on: '2026-10-10',
    overdue: false,
    subject_id: 'emp-1',
    subject_name: 'Sari Dewi',
    detail: '',
    entry_id: null,
    title: null,
    category: null,
    source_note: null,
    notes: null,
    ...overrides,
  } as CalendarItemView
}

describe('monthWindow', () => {
  it('covers the whole month inclusively', () => {
    expect(monthWindow(2026, 10)).toEqual({ start: '2026-10-01', end: '2026-10-31' })
  })

  it('knows February in a leap year', () => {
    expect(monthWindow(2028, 2)).toEqual({ start: '2028-02-01', end: '2028-02-29' })
    expect(monthWindow(2026, 2)).toEqual({ start: '2026-02-01', end: '2026-02-28' })
  })
})

describe('shiftMonth', () => {
  it('carries the year forward in December', () => {
    expect(shiftMonth(2026, 12, 1)).toEqual({ year: 2027, month: 1 })
  })

  it('carries the year backward in January', () => {
    expect(shiftMonth(2026, 1, -1)).toEqual({ year: 2025, month: 12 })
  })

  it('is its own inverse across a year boundary', () => {
    const forward = shiftMonth(2026, 11, 3)
    expect(forward).toEqual({ year: 2027, month: 2 })
    expect(shiftMonth(forward.year, forward.month, -3)).toEqual({ year: 2026, month: 11 })
  })
})

describe('groupByDay', () => {
  it('buckets by due date, days ascending, keeping API order within a day', () => {
    const first = item({ due_on: '2026-10-05' })
    const second = item({ due_on: '2026-10-01', kind: 'document_expiry' })
    const sameDay = item({ due_on: '2026-10-05', kind: 'contract_expiry' })

    const grouped = groupByDay([first, second, sameDay])

    expect(grouped.map((group) => group.dueOn)).toEqual(['2026-10-01', '2026-10-05'])
    expect(grouped[1].items.map((entry) => entry.kind)).toEqual([
      'probation_end',
      'contract_expiry',
    ])
  })

  it('returns nothing for an empty window', () => {
    expect(groupByDay([])).toEqual([])
  })
})
