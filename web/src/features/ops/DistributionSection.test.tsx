import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

import { OpsRequestError } from './opsApi'
import { DistributionSection } from './DistributionSection'

const state = vi.hoisted(() => ({
  data: null as unknown,
  isLoading: false,
  isError: false,
  error: null as unknown,
}))

vi.mock('./useOps', () => ({
  useFairness: () => state,
}))

const report = {
  since: '2026-07-01T00:00:00Z',
  until: '2026-10-01T00:00:00Z',
  evaluations: 3,
  truncated: false,
  jobs: [
    {
      job_title: 'Backend Engineer',
      evaluations: 2,
      mean: 0.79,
      minimum: 0.68,
      maximum: 0.9,
      bins: [],
      recommendations: {},
      requires_human: 1,
      flagged: 0,
    },
  ],
  note: 'Protected attributes are never collected or scored.',
}

beforeEach(() => {
  state.data = null
  state.isLoading = false
  state.isError = false
  state.error = null
})

describe('the score distribution panel', () => {
  it('renders the per-job numbers and the limits note', () => {
    state.data = report
    render(<DistributionSection />)

    expect(screen.getByText('Backend Engineer')).toBeInTheDocument()
    expect(screen.getByText('0.79')).toBeInTheDocument()
    expect(screen.getByText('0.68–0.90')).toBeInTheDocument()
    expect(screen.getByText(report.note)).toBeInTheDocument()
  })

  it('says when the window has no evaluations', () => {
    state.data = { ...report, evaluations: 0, jobs: [] }
    render(<DistributionSection />)
    expect(screen.getByText(i18n.t('distribution.empty'))).toBeInTheDocument()
  })

  it('names the permission when the API refuses', () => {
    state.isError = true
    state.error = new OpsRequestError(403)
    render(<DistributionSection />)
    expect(screen.getByText(i18n.t('distribution.forbidden'))).toBeInTheDocument()
  })
})
