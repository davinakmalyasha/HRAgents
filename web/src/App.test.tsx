import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import i18n from '@/i18n'

import { AppRoutes } from './App'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
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

  it('redirects unknown workspaces to home', () => {
    renderAt('/w/unknown')

    expect(screen.getByRole('heading', { name: i18n.t('home.needsYou') })).toBeInTheDocument()
  })
})
