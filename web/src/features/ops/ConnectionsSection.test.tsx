import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'
import type { components } from '@/api/schema'

import { ConnectionsSection } from './ConnectionsSection'

type McpServerView = components['schemas']['McpServerView']

const state = vi.hoisted(() => ({
  data: [] as McpServerView[],
  isLoading: false,
  isError: false,
  error: null as unknown,
  test: vi.fn(),
  remove: vi.fn(),
  save: vi.fn(),
}))

vi.mock('./useConnections', () => ({
  useConnections: () => ({
    data: state.data,
    isLoading: state.isLoading,
    isError: state.isError,
    error: state.error,
  }),
  useSaveConnection: () => ({ mutate: state.save, isPending: false }),
  useRemoveConnection: () => ({ mutate: state.remove, isPending: false }),
  useTestConnection: () => ({ mutateAsync: state.test, isPending: false }),
}))

function view(overrides: Partial<McpServerView>): McpServerView {
  return {
    name: 'ats',
    url: 'https://mcp.example.com/mcp',
    source: 'dashboard',
    auth_env: 'ATS_MCP_TOKEN',
    timeout_seconds: 5,
    allowed_agents: ['screening_coordinator'],
    tools: { get_candidate: 'read' },
    status: {
      name: 'ats',
      url: 'https://mcp.example.com/mcp',
      connected: true,
      detail: 'connected',
      tools: ['get_candidate'],
      tool_count: 1,
    },
    ...overrides,
  }
}

beforeEach(() => {
  state.data = []
  state.isLoading = false
  state.isError = false
  state.error = null
  state.test = vi.fn()
  state.remove = vi.fn()
  state.save = vi.fn()
})

describe('the connections section', () => {
  it('says when there are no connections', () => {
    render(<ConnectionsSection />)
    expect(screen.getByText(i18n.t('connections.empty'))).toBeInTheDocument()
  })

  it('shows a dashboard connection with source, tools and status', () => {
    state.data = [view({})]
    render(<ConnectionsSection />)

    expect(screen.getByText('ats')).toBeInTheDocument()
    expect(screen.getByText(i18n.t('connections.dashboard'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('connections.connected'))).toBeInTheDocument()
    expect(screen.getByText('get_candidate')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: i18n.t('connections.edit') })).toBeInTheDocument()
  })

  it('offers only a test for an environment connection', () => {
    state.data = [view({ source: 'environment' })]
    render(<ConnectionsSection />)

    expect(screen.getByText(i18n.t('connections.managedByEnv'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: i18n.t('connections.test') })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: i18n.t('connections.edit') })).toBeNull()
    expect(screen.queryByRole('button', { name: i18n.t('connections.delete') })).toBeNull()
  })

  it('runs a probe and shows the tools the server offers', async () => {
    state.data = [view({})]
    state.test.mockResolvedValue({ connected: true, tools: ['get_candidate'] })
    render(<ConnectionsSection />)

    await userEvent.click(screen.getByRole('button', { name: i18n.t('connections.test') }))

    expect(state.test).toHaveBeenCalledWith('ats')
    expect(
      await screen.findByText(i18n.t('connections.offered', { tools: 'get_candidate' })),
    ).toBeInTheDocument()
  })

  it('shows a refused connection without hiding the row', () => {
    state.data = [
      view({
        status: {
          name: 'ats',
          url: 'https://mcp.example.com/mcp',
          connected: false,
          detail: 'ATS_MCP_TOKEN is not set',
          tools: [],
          tool_count: 0,
        },
      }),
    ]
    render(<ConnectionsSection />)

    expect(screen.getByText('ATS_MCP_TOKEN is not set')).toBeInTheDocument()
    expect(screen.getByText(i18n.t('connections.unreachable'))).toBeInTheDocument()
  })
})
