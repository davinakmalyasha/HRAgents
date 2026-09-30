import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'
import type { components } from '@/api/schema'

type StepView = components['schemas']['hr_agents__api__onboarding_schemas__StepView']
type DocumentView = components['schemas']['DocumentView']
type PlanView = components['schemas']['hr_agents__api__onboarding_schemas__PlanView']

const state = vi.hoisted(() => ({ documents: [] as unknown[] }))

vi.mock('./useOnboarding', () => ({
  useEmployeeDocuments: () => ({ isLoading: false, data: state.documents }),
  useDocumentStatus: () => ({ isLoading: false, data: {} }),
  useOnboardingPlans: () => ({ isLoading: false, data: [] }),
  useOnboardingTemplates: () => ({ isLoading: false, data: [] }),
  useEmployees: () => ({ isLoading: false, data: [] }),
}))

vi.mock('./onboardingApi', () => ({
  linkDocument: vi.fn(),
  completeStep: vi.fn(),
  waiveStep: vi.fn(),
  startPlan: vi.fn(),
  createEmployee: vi.fn(),
}))

import { linkDocument } from './onboardingApi'
import { LinkDocumentDialog } from './LinkDocumentDialog'

const linkDocumentMock = vi.mocked(linkDocument)

function document(overrides: Partial<DocumentView> = {}): DocumentView {
  return {
    id: 'doc-1',
    employee_id: 'emp-1',
    kind: 'ktp',
    storage_key: 'employees/emp-1/ktp.pdf',
    sha256: 'a'.repeat(64),
    status: 'verified',
    filename: 'ktp.pdf',
    issued_on: null,
    expires_on: null,
    days_to_expiry: null,
    ...overrides,
  }
}

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

function renderDialog(node: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

beforeEach(() => {
  state.documents = []
  linkDocumentMock.mockReset()
})

describe('LinkDocumentDialog', () => {
  it('links a document without asking the user to name themselves', async () => {
    state.documents = [document()]
    linkDocumentMock.mockResolvedValue({ status: 200, plan: plan() })

    renderDialog(
      <LinkDocumentDialog
        planId="plan-1"
        employeeId="emp-1"
        step={step()}
        open
        onOpenChange={vi.fn()}
        onDone={vi.fn()}
      />,
    )

    await userEvent.click(await screen.findByRole('radio', { name: /KTP/ }))
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('onboarding.linkDialog.confirm') }),
    )

    expect(linkDocumentMock).toHaveBeenCalledWith('plan-1', 'ktp', {
      document_id: 'doc-1',
    })
  })

  it('needs a document to be selected', async () => {
    state.documents = [document()]

    renderDialog(
      <LinkDocumentDialog
        planId="plan-1"
        employeeId="emp-1"
        step={step()}
        open
        onOpenChange={vi.fn()}
        onDone={vi.fn()}
      />,
    )

    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('onboarding.linkDialog.confirm') }),
    )

    expect(linkDocumentMock).not.toHaveBeenCalled()
    expect(screen.getByText(i18n.t('onboarding.errors.documentRequired'))).toBeInTheDocument()
  })

  it('points at the Records workspace when the vault is empty', () => {
    renderDialog(
      <LinkDocumentDialog
        planId="plan-1"
        employeeId="emp-1"
        step={step()}
        open
        onOpenChange={vi.fn()}
        onDone={vi.fn()}
      />,
    )

    expect(screen.getByText(i18n.t('onboarding.linkDialog.noDocuments'))).toBeInTheDocument()
  })
})
