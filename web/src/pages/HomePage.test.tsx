import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

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
})
