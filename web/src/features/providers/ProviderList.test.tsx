import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

import { ProviderList } from './ProviderList'
import type { ProviderStatusView } from './providersApi'

vi.mock('./ProviderSettingsDialog', () => ({
  ProviderSettingsDialog: ({
    provider,
  }: {
    provider: ProviderStatusView
    open: boolean
    onOpenChange: (open: boolean) => void
  }) => <div role="dialog">configure {provider.capability}</div>,
}))

function provider(overrides: Partial<ProviderStatusView> = {}): ProviderStatusView {
  return {
    capability: 'llm',
    provider_id: 'llm.openai_compatible',
    display_name: 'OpenAI-compatible model',
    status: 'ok',
    detail: 'configuration valid',
    locked: false,
    source: 'default',
    requires_network: true,
    docs_url: null,
    config: {},
    editable: true,
    ...overrides,
  } as ProviderStatusView
}

describe('ProviderList', () => {
  it('names the provider, its capability and its state', () => {
    render(<ProviderList providers={[provider()]} />)

    expect(screen.getByText('OpenAI-compatible model')).toBeInTheDocument()
    expect(screen.getByText(/llm\.openai_compatible/)).toBeInTheDocument()
    expect(screen.getByText(i18n.t('providers.status.ok'))).toBeInTheDocument()
    expect(screen.getByText('configuration valid')).toBeInTheDocument()
  })

  it('marks a provider the environment locked', () => {
    render(<ProviderList providers={[provider({ locked: true, editable: false })]} />)

    expect(screen.getByText(i18n.t('providers.locked'))).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Configure/ })).toBeNull()
  })

  it('shows the masked configuration, never a secret', () => {
    render(<ProviderList providers={[provider({ config: { api_key: '…alue' } })]} />)

    expect(screen.getByText('…alue')).toBeInTheDocument()
    expect(document.body.textContent).toContain('api_key=')
  })

  it('opens the configuration form only when the row is editable', async () => {
    const user = userEvent.setup()
    render(<ProviderList providers={[provider()]} />)

    await user.click(
      screen.getByRole('button', {
        name: i18n.t('providers.configure.action', { capability: 'Model' }),
      }),
    )

    expect(screen.getByRole('dialog')).toHaveTextContent('configure llm')
  })

  it('explains the read-only state when no key is configured', () => {
    render(<ProviderList providers={[provider({ editable: false })]} />)

    expect(screen.getByText(i18n.t('providers.readOnlyHint'))).toBeInTheDocument()
  })
})
