import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

import { AppRoutes } from './App'

vi.mock('@/lib/api', () => ({
  api: { GET: vi.fn().mockResolvedValue({ data: [] }) },
}))

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AppRoutes', () => {
  it('renders the attention-first home with Needs you and Watching', () => {
    renderAt('/')

    expect(screen.getByRole('heading', { name: i18n.t('home.needsYou') })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: i18n.t('home.watching') })).toBeInTheDocument()
  })

  it('renders every workspace with the three rooms', () => {
    renderAt('/w/hiring')

    expect(
      screen.getByRole('heading', { name: i18n.t('workspaces.hiring.name') }),
    ).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: i18n.t('rooms.board') })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: i18n.t('rooms.queue') })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: i18n.t('rooms.chat') })).toBeInTheDocument()
  })

  it('renders the chat room instead of a placeholder', async () => {
    renderAt('/w/hiring')

    await userEvent.click(screen.getByRole('tab', { name: i18n.t('rooms.chat') }))

    expect(screen.getByRole('textbox', { name: i18n.t('chat.placeholder') })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: i18n.t('chat.send') })).toBeInTheDocument()
  })

  it('redirects unknown workspaces to home', () => {
    renderAt('/w/unknown')

    expect(screen.getByRole('heading', { name: i18n.t('home.needsYou') })).toBeInTheDocument()
  })
})
