import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import i18n from '@/i18n'

import { ProviderList } from './ProviderList'
import type { ProviderStatusView } from './providersApi'

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
    render(<ProviderList providers={[provider({ locked: true })]} />)

    expect(screen.getByText(i18n.t('providers.locked'))).toBeInTheDocument()
  })

  it('shows the masked configuration, never a secret', () => {
    render(<ProviderList providers={[provider({ config: { api_key: '…alue' } })]} />)

    expect(screen.getByText('…alue')).toBeInTheDocument()
    expect(document.body.textContent).toContain('api_key=')
  })
})
