import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'
import type { components } from '@/api/schema'

type PlanView = components['schemas']['hr_agents__api__onboarding_schemas__PlanView']
type StepView = components['schemas']['hr_agents__api__onboarding_schemas__StepView']
type EmployeeView = components['schemas']['EmployeeView']

const state = vi.hoisted(() => ({
  plans: [] as unknown[],
  employees: [] as unknown[],
  documents: [] as unknown[],
  documentStatus: {} as Record<string, string>,
}))

vi.mock('./useOnboarding', () => ({
  useOnboardingPlans: () => ({ isLoading: false, data: state.plans }),
  useOnboardingTemplates: () => ({
    isLoading: false,
    data: [{ id: 'tpl-1', name: 'Engineering onboarding', step_count: 6 }],
  }),
  useEmployees: () => ({ isLoading: false, data: state.employees }),
  useEmployeeDocuments: () => ({ isLoading: false, data: state.documents }),
  useDocumentStatus: () => ({ isLoading: false, data: state.documentStatus }),
}))

vi.mock('./onboardingApi', () => ({
  startPlan: vi.fn(),
  createEmployee: vi.fn(),
  completeStep: vi.fn(),
  waiveStep: vi.fn(),
  linkDocument: vi.fn(),
}))

import { completeStep, createEmployee, startPlan, waiveStep } from './onboardingApi'
import { OnboardingBoard } from './OnboardingBoard'
import { OnboardingChecklist } from './OnboardingChecklist'

const startPlanMock = vi.mocked(startPlan)
const createEmployeeMock = vi.mocked(createEmployee)
const completeStepMock = vi.mocked(completeStep)
const waiveStepMock = vi.mocked(waiveStep)

function step(overrides: Partial<StepView> = {}): StepView {
  return {
    key: 'ktp',
    title: 'Collect KTP',
    kind: 'document',
    required: true,
    requires_human_signoff: false,
    assignee_role: 'hr_admin',
    status: 'pending',
    document_kind: 'ktp',
    due_on: null,
    is_overdue: false,
    linked_document_id: null,
    linked_task_id: null,
    ...overrides,
  }
}

function plan(overrides: Partial<PlanView> = {}): PlanView {
  return {
    id: 'plan-1',
    employee_id: 'emp-1',
    template_id: 'tpl-1',
    template_name: 'Engineering onboarding',
    template_version_hash: 'abc',
    progress: 0.5,
    is_complete: false,
    started_at: '2026-09-20T03:00:00Z',
    completed_at: null,
    steps: [step()],
    blockers: [],
    ...overrides,
  }
}

function employee(overrides: Partial<EmployeeView> = {}): EmployeeView {
  return {
    id: 'emp-1',
    full_name: 'Rina Wulandari',
    email: 'rina@example.com',
    job_title: 'Backend Engineer',
    status: 'active',
    hire_date: '2026-09-20',
    probation_end_date: null,
    offboarded_on: null,
    org_unit_id: null,
    manager_id: null,
    ...overrides,
  }
}

function renderWithRouter(node: React.ReactElement, route = '/w/onboarding') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/w/onboarding" element={node} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  state.plans = []
  state.employees = []
  state.documents = []
  state.documentStatus = {}
  startPlanMock.mockReset()
  createEmployeeMock.mockReset()
  completeStepMock.mockReset()
  waiveStepMock.mockReset()
})

describe('OnboardingBoard', () => {
  it('lists active plans with progress and blockers', () => {
    state.plans = [
      plan({ blockers: ['contract'] }),
      plan({
        id: 'plan-2',
        employee_id: 'emp-2',
        progress: 1,
        is_complete: true,
        steps: [step({ status: 'done' })],
      }),
    ]
    state.employees = [employee(), employee({ id: 'emp-2', full_name: 'Sari Dewi' })]

    renderWithRouter(<OnboardingBoard />)

    expect(screen.getByText('Rina Wulandari')).toBeInTheDocument()
    expect(screen.getByText('Sari Dewi')).toBeInTheDocument()
    expect(screen.getByText('50%')).toBeInTheDocument()
    expect(screen.getByText(i18n.t('onboarding.planComplete'))).toBeInTheDocument()
    expect(
      screen.getAllByRole('button', { name: i18n.t('onboarding.openChecklist') }),
    ).toHaveLength(2)
  })

  it('shows an empty state when nothing is onboarding', () => {
    renderWithRouter(<OnboardingBoard />)

    expect(screen.getByText(i18n.t('onboarding.emptyPlans'))).toBeInTheDocument()
  })

  it('creates the hire and starts the plan in one flow', async () => {
    createEmployeeMock.mockResolvedValue(employee({ id: 'emp-9', full_name: 'Budi Santoso' }))
    startPlanMock.mockResolvedValue({ status: 201, plan: plan({ id: 'plan-9' }) })
    renderWithRouter(<OnboardingBoard />)

    await userEvent.click(screen.getByRole('button', { name: i18n.t('onboarding.startPlan') }))
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('onboarding.startDialog.newHire') }),
    )
    await userEvent.type(
      screen.getByLabelText(i18n.t('onboarding.startDialog.fullName')),
      'Budi Santoso',
    )
    await userEvent.type(
      screen.getByLabelText(i18n.t('onboarding.startDialog.createdBy')),
      'Sinta Prabowo',
    )
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('onboarding.startDialog.confirm') }),
    )

    expect(createEmployeeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        full_name: 'Budi Santoso',
        created_by: 'Sinta Prabowo',
      }),
    )
    expect(startPlanMock).toHaveBeenCalledWith({
      employee_id: 'emp-9',
      created_by: 'Sinta Prabowo',
      template_id: null,
    })
  })

  it('refuses to start without a named person', async () => {
    state.employees = [employee()]
    startPlanMock.mockResolvedValue({ status: 201, plan: plan() })
    renderWithRouter(<OnboardingBoard />)

    await userEvent.click(screen.getByRole('button', { name: i18n.t('onboarding.startPlan') }))
    await userEvent.selectOptions(
      screen.getByLabelText(i18n.t('onboarding.startDialog.employee')),
      'emp-1',
    )
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('onboarding.startDialog.confirm') }),
    )

    expect(startPlanMock).not.toHaveBeenCalled()
    expect(screen.getByText(i18n.t('onboarding.errors.byRequired'))).toBeInTheDocument()
  })
})

describe('OnboardingChecklist', () => {
  const route = '/w/onboarding?room=queue&plan=plan-1'

  it('orders the checklist and shows document state', () => {
    state.plans = [
      plan({
        steps: [
          step({ key: 'done', status: 'done' }),
          step({ key: 'laptop', title: 'Order laptop', kind: 'task', required: false }),
          step({ key: 'ktp', is_overdue: true }),
        ],
      }),
    ]
    state.documentStatus = { ktp: 'verified' }

    renderWithRouter(<OnboardingChecklist />, route)

    const titles = screen.getAllByRole('listitem').map((item) => item.textContent ?? '')
    expect(titles[0]).toContain('Collect KTP')
    expect(titles[2]).toContain('Collect KTP')
    expect(screen.getByText(i18n.t('onboarding.overdue'))).toBeInTheDocument()
  })

  it('completes a step with a named actor', async () => {
    state.plans = [plan()]
    completeStepMock.mockResolvedValue({ status: 200, plan: plan() })
    renderWithRouter(<OnboardingChecklist />, route)

    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('onboarding.actions.complete') }),
    )
    await userEvent.type(screen.getByLabelText(i18n.t('onboarding.fields.by')), 'Sinta Prabowo')
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('onboarding.actions.confirmComplete') }),
    )

    expect(completeStepMock).toHaveBeenCalledWith('plan-1', 'ktp', {
      by: 'Sinta Prabowo',
      note: null,
    })
  })

  it('only offers a waiver for optional steps and demands a reason', async () => {
    state.plans = [
      plan({
        steps: [step({ key: 'swag', title: 'Send welcome swag', kind: 'task', required: false })],
      }),
    ]
    waiveStepMock.mockResolvedValue({ status: 200, plan: plan() })
    renderWithRouter(<OnboardingChecklist />, route)

    await userEvent.click(screen.getByRole('button', { name: i18n.t('onboarding.actions.waive') }))
    await userEvent.type(screen.getByLabelText(i18n.t('onboarding.fields.by')), 'Sinta Prabowo')
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('onboarding.actions.confirmWaive') }),
    )

    expect(waiveStepMock).not.toHaveBeenCalled()
    expect(screen.getByText(i18n.t('onboarding.errors.reasonRequired'))).toBeInTheDocument()

    await userEvent.type(
      screen.getByLabelText(i18n.t('onboarding.fields.reason')),
      'Not needed in this country',
    )
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('onboarding.actions.confirmWaive') }),
    )

    expect(waiveStepMock).toHaveBeenCalledWith('plan-1', 'swag', {
      by: 'Sinta Prabowo',
      reason: 'Not needed in this country',
    })
  })

  it('offers the document link only for document steps without a document', () => {
    state.plans = [
      plan({
        steps: [
          step({ key: 'ktp', kind: 'document' }),
          step({ key: 'linked', kind: 'document', linked_document_id: 'doc-9' }),
          step({ key: 'laptop', kind: 'task', required: false }),
        ],
      }),
    ]

    renderWithRouter(<OnboardingChecklist />, route)

    expect(
      screen.getAllByRole('button', { name: i18n.t('onboarding.actions.linkDocument') }),
    ).toHaveLength(1)
  })

  it('asks for a plan before showing a checklist', () => {
    state.plans = [plan()]

    renderWithRouter(<OnboardingChecklist />, '/w/onboarding?room=queue')

    expect(screen.getByText(i18n.t('onboarding.checklist.empty'))).toBeInTheDocument()
  })
})
