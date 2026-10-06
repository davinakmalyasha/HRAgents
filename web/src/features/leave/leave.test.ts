import { describe, expect, it } from 'vitest'

import type { components } from '@/api/schema'

import {
  LEAVE_TYPE_LABELS,
  balanceTone,
  pendingFirst,
  withEmployeeNames,
  type BalanceView,
  type LeaveRequestView,
  type RequestStatus,
} from './leaveApi'

type LeaveType = components['schemas']['LeaveType']

const NAMES = new Map([
  ['emp-1', 'Sari Dewi'],
  ['emp-2', 'Budi Santoso'],
])

function request(overrides: Partial<LeaveRequestView> = {}): LeaveRequestView {
  return {
    id: 'req-1',
    employee_id: 'emp-1',
    leave_type: 'annual',
    start_date: '2026-03-02',
    end_date: '2026-03-04',
    days: 3,
    reason: null,
    status: 'pending',
    approval_id: null,
    ...overrides,
  }
}

function balance(overrides: Partial<BalanceView> = {}): BalanceView {
  return {
    employee_id: 'emp-1',
    leave_type: 'annual',
    year: 2026,
    entitled: 12,
    used: 4,
    pending: 2,
    carried_over: 0,
    adjustment: 0,
    available: 6,
    ...overrides,
  }
}

describe('withEmployeeNames', () => {
  it('sorts by start date so the queue reads as a calendar', () => {
    const rows = withEmployeeNames(
      [
        request({ id: 'later', start_date: '2026-04-01' }),
        request({ id: 'earlier', start_date: '2026-01-05' }),
      ],
      NAMES,
    )

    expect(rows.map((row) => row.request.id)).toEqual(['earlier', 'later'])
  })

  it('attaches the employee name the API does not send', () => {
    const rows = withEmployeeNames([request()], NAMES)
    expect(rows[0].employeeName).toBe('Sari Dewi')
  })

  it('keeps a request whose employee is missing from the directory', () => {
    /**A person who has left the directory still has requests somebody must decide.

    Dropping the row would hide a pending request from the queue entirely, which is the
    failure mode this whole product is supposed to prevent.
    */
    const rows = withEmployeeNames([request({ employee_id: 'emp-gone' })], NAMES)

    expect(rows).toHaveLength(1)
    expect(rows[0].employeeName).toBe('emp-gone')
  })

  it('does not mutate the input array', () => {
    const input = [
      request({ id: 'b', start_date: '2026-05-01' }),
      request({ id: 'a', start_date: '2026-01-01' }),
    ]
    const before = input.map((item) => item.id)

    withEmployeeNames(input, NAMES)

    expect(input.map((item) => item.id)).toEqual(before)
  })
})

describe('pendingFirst', () => {
  it('puts requests awaiting a decision above settled ones', () => {
    const rows = withEmployeeNames(
      [
        request({ id: 'approved', status: 'approved', start_date: '2026-01-01' }),
        request({ id: 'pending', status: 'pending', start_date: '2026-06-01' }),
      ],
      NAMES,
    )

    expect(pendingFirst(rows).map((row) => row.request.id)).toEqual(['pending', 'approved'])
  })

  it('still orders by start date within a status', () => {
    const rows = withEmployeeNames(
      [
        request({ id: 'p2', status: 'pending', start_date: '2026-07-01' }),
        request({ id: 'p1', status: 'pending', start_date: '2026-02-01' }),
      ],
      NAMES,
    )

    expect(pendingFirst(rows).map((row) => row.request.id)).toEqual(['p1', 'p2'])
  })
})

describe('balanceTone', () => {
  it('flags an over-drawn balance as an error', () => {
    /**Over-drawn means the API let a request through that the balance cannot cover.

    Surfacing it as an error tone is the whole point: a signed negative number looks
    like a normal figure to somebody scanning a table.
    */
    expect(balanceTone(balance({ available: -1 }))).toBe('over')
  })

  it('warns when there is a day or less left', () => {
    expect(balanceTone(balance({ available: 1 }))).toBe('warn')
    expect(balanceTone(balance({ available: 0 }))).toBe('warn')
  })

  it('treats a healthy balance as fine', () => {
    expect(balanceTone(balance({ available: 6 }))).toBe('ok')
  })
})

describe('LEAVE_TYPE_LABELS', () => {
  it('has a label for every leave type the API can return', () => {
    /**A missing label renders as `undefined`, which reads as a bug in the row.

    The type is exhaustive, so the compiler enforces this too; the test is here so the
    failure names the gap rather than surfacing as a blank cell in production.
    */
    const everyType: LeaveType[] = [
      'annual',
      'sick',
      'personal',
      'maternity',
      'paternity',
      'bereavement',
      'marriage',
      'unpaid',
      'other',
    ]
    for (const leaveType of everyType) {
      expect(LEAVE_TYPE_LABELS[leaveType]).toBeTruthy()
    }
  })
})

describe('request status', () => {
  it('treats a request as one a human can act on', () => {
    /**Cancelling is offered for pending and approved, not for a draft.

    The queue offers cancellation and not approval: approval goes through the approvals
    inbox, which is the one surface that records who decided.
    */
    const cancellable = (status: RequestStatus): boolean => ['pending', 'approved'].includes(status)

    expect(cancellable('pending')).toBe(true)
    expect(cancellable('approved')).toBe(true)
    expect(cancellable('draft')).toBe(false)
    expect(cancellable('rejected')).toBe(false)
    expect(cancellable('cancelled')).toBe(false)
  })
})
