import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'
import type { components } from '@/api/schema'

type JobView = components['schemas']['JobView']

const state = vi.hoisted(() => ({ jobs: [] as unknown[] }))

vi.mock('./useHiring', () => ({ useJobs: () => ({ isLoading: false, data: state.jobs }) }))

vi.mock('./jobApi', () => ({
  createJob: vi.fn(),
  updateJob: vi.fn(),
  changeJobStatus: vi.fn(),
}))

import { changeJobStatus, createJob } from './jobApi'
import { JobManager } from './JobManager'

const createJobMock = vi.mocked(createJob)
const changeJobStatusMock = vi.mocked(changeJobStatus)

function job(overrides: Partial<JobView> = {}): JobView {
  return {
    id: 'job-1',
    title: 'Backend Engineer',
    status: 'draft',
    seniority: 'mid',
    min_years_experience: 3,
    description: '',
    responsibilities: [],
    must_have_skills: [],
    nice_to_have_skills: [],
    stack: [],
    location: null,
    job_family: 'engineering',
    dimension_weights: null,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    created_by: null,
    ...overrides,
  }
}

beforeEach(() => {
  state.jobs = [job()]
  createJobMock.mockReset()
  changeJobStatusMock.mockReset()
})

function renderManager() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <JobManager />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('JobManager', () => {
  it('lists jobs with their status and lifecycle actions', () => {
    renderManager()

    expect(screen.getByText('Backend Engineer')).toBeInTheDocument()
    expect(screen.getByText(i18n.t('jobs.status.draft'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: i18n.t('jobs.actions.open') })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: i18n.t('jobs.actions.close') })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: i18n.t('jobs.edit') })).toBeInTheDocument()
  })

  it('treats closed jobs as read-only', () => {
    state.jobs = [job({ status: 'closed' })]
    renderManager()

    expect(screen.queryByRole('button', { name: i18n.t('jobs.edit') })).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: i18n.t('jobs.actions.open') }),
    ).not.toBeInTheDocument()
  })

  it('records the status change without asking the user to name themselves', async () => {
    changeJobStatusMock.mockResolvedValue({ status: 200, job: job({ status: 'open' }) })
    renderManager()

    await userEvent.click(screen.getByRole('button', { name: i18n.t('jobs.actions.open') }))
    // No "changed by" field: the server attributes the transition to the key holder.
    expect(screen.queryByLabelText(i18n.t('jobs.transitionBy'))).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: i18n.t('jobs.transitionConfirm') }))

    expect(changeJobStatusMock).toHaveBeenCalledWith('job-1', 'open')
  })

  it('blocks weights that do not sum to one and submits a valid specification', async () => {
    createJobMock.mockResolvedValue({ status: 201, job: job() })
    renderManager()

    await userEvent.click(screen.getByRole('button', { name: i18n.t('jobs.create') }))
    await userEvent.type(screen.getByLabelText(i18n.t('jobs.fields.title')), 'Backend Engineer')
    // No "saved by" field: the server attributes the job to the API key holder.
    expect(screen.queryByLabelText(i18n.t('jobs.fields.savedBy'))).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(i18n.t('jobs.dimensions.technical_depth')), {
      target: { value: '0.9' },
    })
    await userEvent.click(screen.getByRole('button', { name: i18n.t('jobs.save') }))

    expect(createJobMock).not.toHaveBeenCalled()
    expect(screen.getByText(i18n.t('jobs.errors.weightsSum'))).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(i18n.t('jobs.dimensions.technical_depth')), {
      target: { value: '0.4' },
    })
    await userEvent.click(screen.getByRole('button', { name: i18n.t('jobs.save') }))

    expect(createJobMock).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Backend Engineer',
        seniority: 'mid',
        dimension_weights: {
          technical_depth: 0.4,
          stack_alignment: 0.3,
          systems_literacy: 0.2,
          verifiable_certifications: 0.1,
        },
      }),
    )
  })

  it('celebrates an empty job list', () => {
    state.jobs = []
    renderManager()

    expect(screen.getByText(i18n.t('jobs.empty'))).toBeInTheDocument()
  })
})
