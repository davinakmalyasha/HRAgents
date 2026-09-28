import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'
import type { components } from '@/api/schema'

type DocumentView = components['schemas']['DocumentView']
type EmployeeView = components['schemas']['EmployeeView']
type OrgUnitView = components['schemas']['OrgUnitView']
type ContractView = components['schemas']['ContractView']

const state = vi.hoisted(() => ({
  orgUnits: [] as unknown[],
  employees: [] as unknown[],
  contracts: [] as unknown[],
  documents: [] as unknown[],
  verify: vi.fn(),
}))

vi.mock('./useRecords', () => ({
  useOrgUnits: () => ({ isLoading: false, data: state.orgUnits }),
  useEmployees: () => ({ isLoading: false, data: state.employees }),
  useContracts: () => ({ isLoading: false, data: state.contracts }),
  useDocuments: () => ({ isLoading: false, data: state.documents }),
  useVerifyDocument: () => ({ mutate: state.verify }),
}))

vi.mock('./recordsApi', () => ({
  verifyDocument: vi.fn(),
  listOrgUnits: vi.fn(),
  listEmployees: vi.fn(),
  listContracts: vi.fn(),
  listDocuments: vi.fn(),
}))

const verifyMock = state.verify

import { RecordsBoard, RecordsQueue } from './RecordsWorkspace'

function orgUnit(overrides: Partial<OrgUnitView> = {}): OrgUnitView {
  return {
    id: 'unit-eng',
    name: 'Engineering',
    parent_id: null,
    cost_center: null,
    headcount: 2,
    children: [],
    ...overrides,
  }
}

function employee(overrides: Partial<EmployeeView> = {}): EmployeeView {
  return {
    id: 'emp-1',
    full_name: 'Budi Santoso',
    email: 'budi@example.test',
    job_title: 'Backend Engineer',
    status: 'active',
    hire_date: '2026-01-05',
    probation_end_date: '2026-04-05',
    offboarded_on: null,
    org_unit_id: 'unit-eng',
    manager_id: null,
    ...overrides,
  }
}

function document(overrides: Partial<DocumentView> = {}): DocumentView {
  return {
    id: 'doc-1',
    employee_id: 'emp-1',
    kind: 'ktp',
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

function contract(overrides: Partial<ContractView> = {}): ContractView {
  return {
    id: 'ctr-1',
    employee_id: 'emp-1',
    kind: 'fixed_term',
    status: 'active',
    start_date: '2026-01-05',
    end_date: '2027-01-05',
    ...overrides,
  } as ContractView
}

function renderWith(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>{ui}</QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('Records workspace', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
    verifyMock.mockReset()
    state.orgUnits = [
      orgUnit(),
      orgUnit({ id: 'unit-plat', name: 'Platform', parent_id: 'unit-eng', headcount: 0 }),
    ]
    state.employees = [
      employee(),
      employee({
        id: 'emp-2',
        full_name: 'Sinta Prabowo',
        org_unit_id: 'unit-plat',
        status: 'probation',
      }),
    ]
    state.contracts = [contract(), contract({ id: 'ctr-2', status: 'expired' })]
    state.documents = []
  })

  it('renders the org chart with rolled-up headcount and filters the directory', async () => {
    const user = userEvent.setup()
    renderWith(<RecordsBoard />)

    const org = screen.getByRole('region', { name: 'Org chart' })
    const platform = within(org).getByRole('button', { name: /Platform/ })
    // Engineering's headcount rolls up its child unit.
    expect(within(org).getByRole('button', { name: /Engineering/ })).toHaveTextContent('2 people')

    await user.click(platform)
    expect(screen.getAllByText('Sinta Prabowo')).toHaveLength(1)
    expect(screen.queryByText('Budi Santoso')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Show everyone' }))
    expect(screen.getByText('Budi Santoso')).toBeInTheDocument()
    expect(screen.getByText('Sinta Prabowo')).toBeInTheDocument()
  })

  it('summarises people, contracts, and the expiry queue', () => {
    state.documents = [document({ id: 'doc-1', days_to_expiry: 5 })]
    renderWith(<RecordsBoard />)

    expect(screen.getByText('2 in the directory')).toBeInTheDocument()
    const contractsTile = screen.getByText('Contracts').closest('div') as HTMLElement
    expect(within(contractsTile).getByText('1')).toBeInTheDocument()
    expect(within(contractsTile).getByText('active contracts')).toBeInTheDocument()
    expect(screen.getByText('Active: 1')).toBeInTheDocument()
    expect(screen.getByText('Probation: 1')).toBeInTheDocument()
    expect(screen.getByText(/0 expired · 1 within 60 days/)).toBeInTheDocument()
  })

  it('refuses to judge a document without a named human', async () => {
    const user = userEvent.setup()
    state.documents = [document({ days_to_expiry: 10 })]
    renderWith(<RecordsQueue />)

    await user.click(screen.getByRole('button', { name: 'Verify' }))

    expect(verifyMock).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('A named person is required')
  })

  it('verifies and rejects a document under the named verifier', async () => {
    const user = userEvent.setup()
    state.documents = [
      document({ id: 'doc-1', days_to_expiry: 30 }),
      document({ id: 'doc-2', status: 'failed', days_to_expiry: -2 }),
    ]
    renderWith(<RecordsQueue />)

    const [expiredRow, ktpRow] = screen.getAllByRole('listitem')
    await user.type(screen.getByLabelText('Verified by'), 'Sinta Prabowo')
    await user.click(within(ktpRow).getByRole('button', { name: 'Verify' }))
    await user.click(within(expiredRow).getByRole('button', { name: 'Reject' }))

    expect(verifyMock).toHaveBeenNthCalledWith(
      1,
      { documentId: 'doc-1', body: { verified_by: 'Sinta Prabowo', verified: true } },
      expect.anything(),
    )
    expect(verifyMock).toHaveBeenNthCalledWith(
      2,
      { documentId: 'doc-2', body: { verified_by: 'Sinta Prabowo', verified: false } },
      expect.anything(),
    )
  })

  it('reports a role that is not allowed to verify documents', async () => {
    const user = userEvent.setup()
    state.documents = [document({ days_to_expiry: 10 })]
    verifyMock.mockImplementation((_input, options) => {
      options.onSuccess({ status: 403, documentId: 'doc-1' })
    })
    renderWith(<RecordsQueue />)

    await user.type(screen.getByLabelText('Verified by'), 'agent:records_bot')
    await user.click(screen.getByRole('button', { name: 'Verify' }))

    expect(screen.getByRole('alert')).toHaveTextContent('Your role cannot verify documents')
  })

  it('reports a server failure and empties the queue when nothing expires', async () => {
    const user = userEvent.setup()
    state.documents = [document({ days_to_expiry: 10 })]
    verifyMock.mockImplementation((_input, options) => {
      options.onError(new Error('boom'))
    })
    renderWith(<RecordsQueue />)

    await user.type(screen.getByLabelText('Verified by'), 'Sinta')
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Could not save')

    state.documents = []
    renderWith(<RecordsQueue />)
    expect(screen.getByText(/Nothing expiring/)).toBeInTheDocument()
  })
})
