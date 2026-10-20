import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'
import type { SetupStatus } from '@/features/setup/setupApi'

const setupState = vi.hoisted(() => ({
  current: { data: undefined } as { data: SetupStatus | undefined },
  seed: { isPending: false, isError: false, mutate: vi.fn() },
}))

vi.mock('@/features/setup/useSetup', () => ({
  useSetup: () => setupState.current,
  useSeedStarters: () => setupState.seed,
}))

const attention = vi.hoisted(() => ({
  current: { isLoading: false, needsYou: [], watching: [] } as {
    isLoading: boolean
    needsYou: Array<Record<string, unknown>>
    watching: Array<Record<string, unknown>>
  },
}))

vi.mock('@/features/attention/useAttention', () => ({
  useAttention: () => attention.current,
}))

import { HomePage } from './HomePage'

beforeEach(() => {
  attention.current = { isLoading: false, needsYou: [], watching: [] }
  setupState.current = { data: undefined }
  setupState.seed.mutate.mockClear()
})

function renderHome() {
  return render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  )
}

describe('HomePage', () => {
  it('renders needs-you and watching items with workspace deep links', () => {
    attention.current = {
      isLoading: false,
      needsYou: [
        {
          id: 'approval-1',
          source: 'approval',
          title: 'Approve leave',
          detail: 'Budi',
          workspace: 'leave',
          tone: 'error',
          dueAt: null,
        },
      ],
      watching: [
        {
          id: 'task-1',
          source: 'task',
          title: 'Collect contract',
          detail: '',
          workspace: 'onboarding',
          tone: 'waiting',
          dueAt: null,
        },
      ],
    }

    renderHome()

    expect(screen.getByText('Approve leave')).toBeInTheDocument()
    expect(screen.getByText('Collect contract')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: i18n.t('workspaces.leave.name') })).toHaveAttribute(
      'href',
      '/w/leave?room=queue',
    )
  })

  it('celebrates empty queues', () => {
    renderHome()

    expect(screen.getByText(i18n.t('home.needsYouEmpty'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('home.watchingEmpty'))).toBeInTheDocument()
  })

  it('offers the first-run checklist while the install is empty', () => {
    setupState.current = {
      data: {
        app_name: 'HRAgents',
        operator_name: '',
        timezone: 'Asia/Jakarta',
        store_backend: 'postgres',
        llm_model: 'test',
        auth_configured: false,
        counts: {
          employees: 0,
          jobs: 0,
          onboarding_templates: 0,
          offboarding_templates: 0,
          rate_tables: 0,
          unverified_rate_tables: 0,
        },
      },
    }

    renderHome()

    expect(screen.getByText(i18n.t('setup.title'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: i18n.t('setup.seed') })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: i18n.t('setup.firstEmployeeLink') })).toHaveAttribute(
      'href',
      '/w/records',
    )
    expect(screen.getByRole('link', { name: i18n.t('setup.firstJobLink') })).toHaveAttribute(
      'href',
      '/w/hiring',
    )
  })

  it('hides the checklist once an employee exists', () => {
    setupState.current = {
      data: {
        app_name: 'HRAgents',
        operator_name: 'Rina',
        timezone: 'Asia/Jakarta',
        store_backend: 'postgres',
        llm_model: 'test',
        auth_configured: true,
        counts: {
          employees: 1,
          jobs: 0,
          onboarding_templates: 0,
          offboarding_templates: 0,
          rate_tables: 0,
          unverified_rate_tables: 0,
        },
      },
    }

    renderHome()

    expect(screen.queryByText(i18n.t('setup.title'))).not.toBeInTheDocument()
  })
})
