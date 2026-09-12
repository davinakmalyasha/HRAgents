import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

vi.mock('./useHiring', () => ({
  useJobs: () => ({ data: [{ id: 'job-1', title: 'Backend Engineer' }], isLoading: false }),
  useApplications: () => ({
    isLoading: false,
    data: [
      {
        application_id: 'app-1',
        candidate_id: 'cand-1',
        job_id: 'job-1',
        status: 'queued',
        priority_score: 0.82,
        s_tech: null,
        hours_waiting: 4,
      },
      {
        application_id: 'app-2',
        candidate_id: 'cand-2',
        job_id: 'job-1',
        status: 'gated',
        priority_score: 0.91,
        s_tech: 0.76,
        hours_waiting: 30,
      },
    ],
  }),
}))

import { PipelineBoard } from './PipelineBoard'

describe('PipelineBoard', () => {
  it('renders all five stages with their cards', () => {
    render(
      <MemoryRouter>
        <PipelineBoard />
      </MemoryRouter>,
    )

    for (const stage of ['intake', 'screened', 'decision', 'interview', 'closed'] as const) {
      expect(
        screen.getByRole('region', { name: i18n.t(`hiring.stages.${stage}`) }),
      ).toBeInTheDocument()
    }

    const card = screen.getByRole('link', { name: /cand-2/ })
    expect(card).toHaveAttribute('href', '/w/hiring/applications/app-2')
    expect(screen.getByText(i18n.t('hiring.inPipeline', { count: 2 }))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('hiring.notScored'))).toBeInTheDocument()
  })
})
