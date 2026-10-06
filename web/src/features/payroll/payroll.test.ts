import { describe, expect, it } from 'vitest'

import type { components } from '@/api/schema'

import {
  RUN_KIND_LABELS,
  RUN_STATUS_LABELS,
  advisoryAnomalies,
  amount,
  blockingAnomalies,
  blocksSignoff,
  deductionBreakdown,
  isCancellable,
  isComputable,
  isExportable,
  isSubmittable,
  rupiah,
  type AnomalyView,
  type LineView,
  type RunStatus,
  type RunView,
} from './payrollApi'

function run(overrides: Partial<RunView> = {}): RunView {
  return {
    id: 'run-1',
    period_year: 2026,
    period_month: 3,
    kind: 'monthly',
    status: 'draft',
    approval_id: null,
    signed_off_by: null,
    blocking_count: 0,
    anomalies: [],
    lines: [],
    totals: {
      employees: 0,
      gross: 0,
      total_deductions: 0,
      net: 0,
      employer_cost: 0,
    },
    ...overrides,
  }
}

function anomaly(overrides: Partial<AnomalyView> = {}): AnomalyView {
  return {
    code: 'negative_net',
    detail: 'Computed net pay is negative',
    employee_id: 'emp-1',
    severity: 'error',
    ...overrides,
  }
}

function line(overrides: Partial<LineView> = {}): LineView {
  return {
    employee_id: 'emp-1',
    employee_name: 'Sari Dewi',
    base_salary: 10_000_000,
    allowances: 0,
    overtime_pay: 0,
    bonus: 0,
    gross: 10_000_000,
    bpjs_kesehatan_employee: 100_000,
    bpjs_jht_employee: 200_000,
    bpjs_jp_employee: 100_000,
    pph21: 500_000,
    other_deductions: 0,
    total_deductions: 900_000,
    net: 9_100_000,
    employer_cost: 500_000,
    notes: [],
    ...overrides,
  }
}

describe('lifecycle actions follow the server state machine', () => {
  /**Each predicate mirrors the server's own guard.

    Offering a button the server will refuse turns a clear "this run is approved; it
    cannot be cancelled" into a dead end with an error toast. These are the guards in
    `services/payroll.py`: `_require_editable`, `submit_for_signoff`, `build_review_packet_xlsx`
    and `cancel_run`.
  */

  it('computes only from a draft or an assembling run', () => {
    expect(isComputable('draft')).toBe(true)
    expect(isComputable('assembling')).toBe(true)
    for (const status of [
      'ready_for_review',
      'pending_signoff',
      'approved',
      'exported',
      'cancelled',
      'rejected',
    ] as RunStatus[]) {
      expect(isComputable(status)).toBe(false)
    }
  })

  it('submits only a run that has been computed and reviewed', () => {
    expect(isSubmittable('ready_for_review')).toBe(true)
    for (const status of [
      'draft',
      'assembling',
      'pending_signoff',
      'approved',
      'exported',
      'cancelled',
      'rejected',
    ] as RunStatus[]) {
      expect(isSubmittable(status)).toBe(false)
    }
  })

  it('exports only after a named human signed off', () => {
    /**The packet is the review artefact. Before sign-off it would invite disbursing
    figures nobody approved, which is the thing the whole approval chain exists to stop.
    */
    expect(isExportable('approved')).toBe(true)
    for (const status of [
      'draft',
      'ready_for_review',
      'pending_signoff',
      'exported',
      'cancelled',
    ] as RunStatus[]) {
      expect(isExportable(status)).toBe(false)
    }
  })

  it('never cancels a run that is already approved or exported', () => {
    expect(isCancellable('approved')).toBe(false)
    expect(isCancellable('exported')).toBe(false)
    expect(isCancellable('cancelled')).toBe(false)
    expect(isCancellable('draft')).toBe(true)
    expect(isCancellable('ready_for_review')).toBe(true)
  })
})

describe('sign-off is gated on the server blocking count', () => {
  it('blocks while any ERROR anomaly remains', () => {
    const blocked = run({ blocking_count: 2, anomalies: [anomaly(), anomaly()] })
    expect(blocksSignoff(blocked)).toBe(true)
  })

  it('does not block on advisories alone', () => {
    /**A warning is exactly what the severity split means: worth seeing, not worth
    stopping for. Blocking on it would make the severity column meaningless.
    */
    const warned = run({
      blocking_count: 0,
      anomalies: [anomaly({ severity: 'warning', code: 'overtime_excessive' })],
    })
    expect(blocksSignoff(warned)).toBe(false)
  })

  it('separates blocking anomalies from advisories', () => {
    const withBoth = run({
      blocking_count: 1,
      anomalies: [
        anomaly({ code: 'negative_net', severity: 'error' }),
        anomaly({ code: 'overtime_excessive', severity: 'warning' }),
        anomaly({ code: 'net_deviation', severity: 'info' }),
      ],
    })

    expect(blockingAnomalies(withBoth).map((a) => a.code)).toEqual(['negative_net'])
    expect(advisoryAnomalies(withBoth).map((a) => a.code)).toEqual([
      'overtime_excessive',
      'net_deviation',
    ])
  })
})

describe('money display', () => {
  it('formats rupiah with grouping', () => {
    /**A seven-figure figure is unreadable without separators, and the reviewer is
    checking it against a bank transfer.
    */
    expect(rupiah(12_345_678)).toContain('12')
    expect(amount(12_345_678)).toBe('12.345.678')
  })

  it('shows whole rupiah, because that is what is paid', () => {
    /**The server computes exact two-place decimals. Rupiah has no sub-unit in
    practice, so the displayed figure should be the one that leaves the account.
    */
    expect(amount(10_000_000.4)).toBe('10.000.000')
  })
})

describe('deduction breakdown', () => {
  it('groups the three BPJS employee shares separately from tax and other', () => {
    const breakdown = deductionBreakdown(line())

    expect(breakdown.bpjs).toBe(400_000)
    expect(breakdown.tax).toBe(500_000)
    expect(breakdown.other).toBe(0)
  })

  it('sums to the line total, so the breakdown cannot disagree with the payslip', () => {
    const subject = line({
      bpjs_kesehatan_employee: 100_000,
      bpjs_jht_employee: 200_000,
      bpjs_jp_employee: 100_000,
      pph21: 500_000,
      other_deductions: 50_000,
      total_deductions: 950_000,
    })
    const breakdown = deductionBreakdown(subject)

    expect(breakdown.bpjs + breakdown.tax + breakdown.other).toBe(subject.total_deductions)
  })
})

describe('labels cover every value the API can return', () => {
  it('has a label for every run status', () => {
    /**A missing label renders the raw key, which reads as a bug in the product.

    The types are exhaustive so the compiler enforces this; the test names the gap if a
    status is ever added without one.
    */
    const everyStatus: RunStatus[] = [
      'draft',
      'assembling',
      'ready_for_review',
      'pending_signoff',
      'approved',
      'rejected',
      'exported',
      'cancelled',
    ]
    for (const status of everyStatus) {
      expect(RUN_STATUS_LABELS[status]).toBeTruthy()
    }
  })

  it('has a label for every run kind', () => {
    const everyKind: components['schemas']['PayrollRunKind'][] = [
      'monthly',
      'thr',
      'adjustment',
      'final',
    ]
    for (const kind of everyKind) {
      expect(RUN_KIND_LABELS[kind]).toBeTruthy()
    }
  })
})
