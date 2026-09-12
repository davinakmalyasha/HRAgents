import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

vi.mock('@/features/hiring/useHiring', () => ({
  useApplication: () => ({
    isLoading: false,
    data: {
      application_id: 'app-1',
      candidate_id: 'cand-1',
      job_id: 'job-1',
      status: 'evaluated',
      received_at: '2026-09-01T10:00:00Z',
      s_tech: 0.81,
      sigma: 0.04,
      priority_score: 0.9,
      timeline: [
        { at: '2026-09-01T10:00:00Z', event: 'application.received' },
        { at: '2026-09-01T10:05:00Z', event: 'evaluation.registered' },
      ],
    },
  }),
  useEvaluation: () => ({
    isLoading: false,
    data: {
      id: 'eval-1',
      application_id: 'app-1',
      candidate_id: 'cand-1',
      job_id: 'job-1',
      s_tech: 0.81,
      sigma: 0.04,
      recommendation: 'advance',
      policy: {
        decision: 'advance',
        reasons: [],
        thresholds: {},
        evaluated_at: '2026-09-01T10:05:00Z',
      },
      policy_version: '1.0',
      flags: ['low_confidence_extraction'],
      breakdown: [
        {
          dimension: 'systems_literacy',
          score: 0.84,
          weight: 0.3,
          rationale: 'Repository shows layered architecture.',
        },
      ],
      created_at: '2026-09-01T10:05:00Z',
      mean_vector: {},
      dimension_stddev: {},
      weights: {},
    },
  }),
}))

import { ApplicationDetailPage } from './ApplicationDetailPage'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/w/hiring/applications/app-1']}>
      <Routes>
        <Route
          path="w/:workspaceId/applications/:applicationId"
          element={<ApplicationDetailPage />}
        />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ApplicationDetailPage', () => {
  it('shows status, timeline, and the evaluation breakdown', () => {
    renderPage()

    expect(screen.getByText('evaluated')).toBeInTheDocument()
    expect(screen.getByText('application.received')).toBeInTheDocument()
    expect(screen.getByText('evaluation.registered')).toBeInTheDocument()
    expect(screen.getByText('Repository shows layered architecture.')).toBeInTheDocument()
    expect(screen.getByText('low_confidence_extraction')).toBeInTheDocument()
    expect(screen.getByText(i18n.t('hiring.back'))).toBeInTheDocument()
  })
})
