import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
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
  templates: [{ id: 'tpl-1', name: 'Engineering onboarding', step_count: 6 }] as unknown[],
  starter: null as unknown,
}))

vi.mock('./useOnboarding', () => ({
  useOnboardingPlans: () => ({ isLoading: false, data: state.plans }),
  useOnboardingTemplates: () => ({
    isLoading: false,
    data: state.templates,
  }),
  useStarterTemplate: () => ({ isLoading: false, data: state.starter }),
  useEmployees: () => ({ isLoading: false, data: state.employees }),
  useEmployeeDocuments: () => ({ isLoading: false, data: state.documents }),
  useDocumentStatus: () => ({ isLoading: false, data: state.documentStatus }),
}))

vi.mock('./onboardingApi', () => ({
  startPlan: vi.fn(),
  createEmployee: vi.fn(),
  createTemplate: vi.fn(),
  getStarterTemplate: vi.fn(),
  completeStep: vi.fn(),
  waiveStep: vi.fn(),
  linkDocument: vi.fn(),
}))

import { completeStep, createEmployee, createTemplate, startPlan, waiveStep } from './onboardingApi'
import { OnboardingBoard } from './OnboardingBoard'
import { OnboardingChecklist } from './OnboardingChecklist'

const startPlanMock = vi.mocked(startPlan)
const createEmployeeMock = vi.mocked(createEmployee)
const createTemplateMock = vi.mocked(createTemplate)
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
  state.templates = [{ id: 'tpl-1', name: 'Engineering onboarding', step_count: 6 }]
  state.starter = null
  startPlanMock.mockReset()
  createEmployeeMock.mockReset()
  createTemplateMock.mockReset()
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
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('onboarding.startDialog.confirm') }),
    )

    expect(createEmployeeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        full_name: 'Budi Santoso',
      }),
    )
    // Nothing in this flow names the actor: the server attributes the employee,
    // the template and the plan to the API key holder.
    expect(startPlanMock).toHaveBeenCalledWith({
      employee_id: 'emp-9',
      template_id: null,
    })
  })

  it('offers the starter checklist when no template exists yet', async () => {
    state.templates = []
    state.starter = {
      name: 'Engineering (PKWT/PKWTT) - starter',
      description: 'Starter checklist',
      applies_to_contract_types: [],
      applies_to_roles: ['engineer'],
      steps: [{ key: 'collect_ktp', title: 'Collect KTP', kind: 'document' }],
    }
    createTemplateMock.mockResolvedValue({
      id: 'tpl-new',
      name: 'Engineering (PKWT/PKWTT) - starter',
      description: 'Starter checklist',
      active: true,
      applies_to_contract_types: [],
      applies_to_roles: ['engineer'],
      step_count: 1,
    })
    startPlanMock.mockResolvedValue({ status: 201, plan: plan({ id: 'plan-9' }) })
    createEmployeeMock.mockResolvedValue(employee({ id: 'emp-9' }))

    renderWithRouter(<OnboardingBoard />)
    await userEvent.click(screen.getByRole('button', { name: i18n.t('onboarding.startPlan') }))

    expect(screen.getByText(i18n.t('onboarding.startDialog.noTemplates'))).toBeInTheDocument()

    // One click: seeding the starter template no longer needs a name typed in.
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('onboarding.startDialog.createStarter') }),
    )

    expect(createTemplateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        steps: [expect.objectContaining({ key: 'collect_ktp' })],
      }),
    )
  })

  it('starts a plan for an existing hire without asking for a name', async () => {
    state.employees = [employee()]
    startPlanMock.mockResolvedValue({ status: 201, plan: plan() })
    renderWithRouter(<OnboardingBoard />)

    await userEvent.click(screen.getByRole('button', { name: i18n.t('onboarding.startPlan') }))
    expect(
      screen.queryByLabelText(i18n.t('onboarding.startDialog.createdBy')),
    ).not.toBeInTheDocument()
    await userEvent.selectOptions(
      screen.getByLabelText(i18n.t('onboarding.startDialog.employee')),
      'emp-1',
    )
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('onboarding.startDialog.confirm') }),
    )

    expect(startPlanMock).toHaveBeenCalledWith({
      employee_id: 'emp-1',
      template_id: null,
    })
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
    // No actor field: the server attributes the step to the API key holder.
    expect(screen.queryByLabelText(i18n.t('onboarding.fields.by'))).not.toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('onboarding.actions.confirmComplete') }),
    )

    expect(completeStepMock).toHaveBeenCalledWith('plan-1', 'ktp', {
      note: null,
    })
  })

  it('offers a waiver for every unfinished step and demands a reason', async () => {
    state.plans = [
      plan({
        steps: [
          step({ key: 'swag', title: 'Send welcome swag', kind: 'task', required: false }),
          step({ key: 'ktp' }),
        ],
      }),
    ]
    waiveStepMock.mockResolvedValue({ status: 200, plan: plan() })
    renderWithRouter(<OnboardingChecklist />, route)

    expect(
      screen.getAllByRole('button', { name: i18n.t('onboarding.actions.waive') }),
    ).toHaveLength(2)

    const optionalRow = screen.getByText('Send welcome swag').closest('li')
    expect(optionalRow).not.toBeNull()
    await userEvent.click(
      within(optionalRow as HTMLElement).getByRole('button', {
        name: i18n.t('onboarding.actions.waive'),
      }),
    )
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

  it('warns that waiving a required step is an audited exception', async () => {
    state.plans = [plan()]
    renderWithRouter(<OnboardingChecklist />, route)

    await userEvent.click(screen.getByRole('button', { name: i18n.t('onboarding.actions.waive') }))

    expect(screen.getByText(i18n.t('onboarding.actions.requiredStepNotice'))).toBeInTheDocument()
  })

  it('asks for a plan before showing a checklist', () => {
    state.plans = [plan()]

    renderWithRouter(<OnboardingChecklist />, '/w/onboarding?room=queue')

    expect(screen.getByText(i18n.t('onboarding.checklist.empty'))).toBeInTheDocument()
  })
})
