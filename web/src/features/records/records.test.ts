import { describe, expect, it } from 'vitest'

import type { components } from '@/api/schema'

import {
  DEFAULT_EXPIRY_WINDOW_DAYS,
  activeContracts,
  bucketByExpiry,
  documentNeedsAttention,
  headcountByStatus,
  orgTree,
  type RecordsContract,
  type RecordsDocument,
  type RecordsEmployee,
  type RecordsOrgUnit,
} from './records'

type DocumentKind = components['schemas']['DocumentKind']
type EmployeeStatus = components['schemas']['EmployeeStatus']
type ContractStatus = components['schemas']['ContractStatus']

function document(overrides: Partial<RecordsDocument> = {}): RecordsDocument {
  return {
    id: 'doc-1',
    employee_id: 'emp-1',
    kind: 'ktp' as DocumentKind,
    storage_key: 'employees/emp-1/ktp.pdf',
    filename: 'ktp.pdf',
    sha256: 'a'.repeat(64),
    issued_on: null,
    expires_on: null,
    status: 'claimed',
    days_to_expiry: null,
    ...overrides,
  }
}

function employee(overrides: Partial<RecordsEmployee> = {}): RecordsEmployee {
  return {
    id: 'emp-1',
    full_name: 'Budi Santoso',
    email: null,
    job_title: 'Backend Engineer',
    status: 'active' as EmployeeStatus,
    hire_date: '2026-01-05',
    probation_end_date: null,
    offboarded_on: null,
    org_unit_id: null,
    manager_id: null,
    ...overrides,
  }
}

function unit(overrides: Partial<RecordsOrgUnit> = {}): RecordsOrgUnit {
  return {
    id: 'unit-1',
    name: 'Engineering',
    parent_id: null,
    cost_center: null,
    headcount: 0,
    children: [],
    ...overrides,
  }
}

function contract(overrides: Partial<RecordsContract> = {}): RecordsContract {
  return {
    id: 'ctr-1',
    employee_id: 'emp-1',
    kind: 'fixed_term' as components['schemas']['ContractType'],
    status: 'active' as ContractStatus,
    start_date: '2026-01-05',
    end_date: null,
    ...overrides,
  } as RecordsContract
}

describe('records helpers', () => {
  it('orders the org tree parents-first with indented depth and roll-up headcount', () => {
    const units = [
      unit({ id: 'platform', name: 'Platform', parent_id: 'eng', headcount: 2 }),
      unit({ id: 'eng', name: 'Engineering', headcount: 5 }),
      unit({ id: 'ops', name: 'Operations', headcount: 1 }),
    ]

    const tree = orgTree(units)

    // Parents before children, alphabetical within a level.
    expect(tree.map((node) => node.name)).toEqual(['Engineering', 'Platform', 'Operations'])
    expect(tree.map((node) => node.depth)).toEqual([0, 1, 0])
    expect(tree.find((node) => node.name === 'Engineering')?.totalHeadcount).toBe(7)
    expect(tree.find((node) => node.name === 'Platform')?.totalHeadcount).toBe(2)
  })

  it('does not drop a unit whose parent is missing from the payload', () => {
    const tree = orgTree([unit({ id: 'child', name: 'Orphan', parent_id: 'missing' })])

    expect(tree).toHaveLength(1)
    expect(tree[0].name).toBe('Orphan')
  })

  it('buckets the vault by urgency, keeping already-expired documents first', () => {
    const bucket = bucketByExpiry([
      document({ id: 'later', days_to_expiry: 45 }),
      document({ id: 'soon', days_to_expiry: 10 }),
      document({ id: 'today', days_to_expiry: 0 }),
      document({ id: 'gone', days_to_expiry: -3 }),
      document({ id: 'none', days_to_expiry: null }),
    ])

    expect(bucket.documents.map((doc) => doc.id)).toEqual(['gone', 'today', 'soon', 'later'])
    expect(bucket.overdue).toBe(1)
    expect(bucket.expiringSoon).toBe(3)
    expect(bucketByExpiry([])).toEqual({ documents: [], overdue: 0, expiringSoon: 0 })
  })

  it('honours a custom expiry window', () => {
    const bucket = bucketByExpiry(
      [document({ id: 'a', days_to_expiry: 20 }), document({ id: 'b', days_to_expiry: 90 })],
      30,
    )

    expect(bucket.documents.map((doc) => doc.id)).toEqual(['a'])
  })

  it('flags only documents that still need a human verdict', () => {
    expect(documentNeedsAttention(document({ status: 'claimed' }))).toBe(true)
    expect(documentNeedsAttention(document({ status: 'failed' }))).toBe(true)
    expect(documentNeedsAttention(document({ status: 'verified' }))).toBe(false)
    expect(documentNeedsAttention(document({ status: 'expired' }))).toBe(false)
  })

  it('counts the directory by employment status and active contracts', () => {
    const counts = headcountByStatus([
      employee({ id: 'a', status: 'active' }),
      employee({ id: 'b', status: 'active' }),
      employee({ id: 'c', status: 'offboarded' }),
    ])

    expect(counts).toEqual({ active: 2, offboarded: 1 })
    expect(
      activeContracts([contract({ id: 'a' }), contract({ id: 'b', status: 'expired' })]).map(
        (item) => item.id,
      ),
    ).toEqual(['a'])
  })

  it('uses a sixty-day default expiry window', () => {
    expect(DEFAULT_EXPIRY_WINDOW_DAYS).toBe(60)
  })
})
