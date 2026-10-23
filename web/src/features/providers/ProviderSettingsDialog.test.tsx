import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

import { ProviderSettingsDialog } from './ProviderSettingsDialog'
import type { ProviderStatusView } from './providersApi'

const hooks = vi.hoisted(() => ({
  options: {
    capability: 'llm',
    selected_provider_id: 'llm.anthropic',
    source: 'settings',
    locked: false,
    editable: true,
    providers: [
      {
        provider_id: 'llm.anthropic',
        display_name: 'Anthropic (Claude)',
        description: 'Claude models via the Anthropic API.',
        docs_url: null,
        requires_network: true,
        fields: [
          {
            name: 'api_key',
            title: 'Api Key',
            type: 'string',
            required: false,
            secret: true,
            description: '',
            default: null,
          },
          {
            name: 'model',
            title: 'Model',
            type: 'string',
            required: false,
            secret: false,
            description: '',
            default: 'claude-sonnet-4-5',
          },
          {
            name: 'retries',
            title: 'Retries',
            type: 'integer',
            required: false,
            secret: false,
            description: '',
            default: 0,
          },
        ],
      },
    ],
  },
  save: vi.fn(),
  clear: vi.fn(),
  test: vi.fn(),
  reset: vi.fn(),
}))

vi.mock('./useProviders', () => ({
  useProviderOptions: () => ({ isLoading: false, isError: false, data: hooks.options }),
  useSaveProvider: () => ({ mutate: hooks.save, isPending: false }),
  useClearProvider: () => ({ mutate: hooks.clear, isPending: false }),
  useTestProvider: () => ({
    mutate: hooks.test,
    isPending: false,
    data: undefined,
    reset: hooks.reset,
  }),
}))

function provider(): ProviderStatusView {
  return {
    capability: 'llm',
    provider_id: 'llm.anthropic',
    display_name: 'Anthropic (Claude)',
    status: 'ok',
    detail: '',
    locked: false,
    source: 'settings',
    requires_network: true,
    docs_url: null,
    config: { api_key: '…cret', model: 'claude-sonnet-4-5', retries: 2 },
    editable: true,
  } as ProviderStatusView
}

describe('ProviderSettingsDialog', () => {
  beforeEach(() => {
    hooks.save.mockClear()
    hooks.clear.mockClear()
    hooks.test.mockClear()
  })

  it('prefills non-secrets and never the secret mask', () => {
    render(<ProviderSettingsDialog provider={provider()} open onOpenChange={vi.fn()} />)

    expect(screen.getByRole('heading')).toHaveTextContent(
      i18n.t('providers.configure.title', { capability: 'Model' }),
    )
    expect(screen.getByLabelText('Model')).toHaveValue('claude-sonnet-4-5')
    expect(screen.getByLabelText('Retries')).toHaveValue(2)
    expect(screen.getByLabelText('Api Key')).toHaveValue('')
    expect(screen.getByLabelText('Api Key')).toHaveAttribute(
      'placeholder',
      i18n.t('providers.configure.secretKept', { mask: '…cret' }),
    )
  })

  it('saves typed values, coerces numbers, and omits a blank secret', async () => {
    const user = userEvent.setup()
    render(<ProviderSettingsDialog provider={provider()} open onOpenChange={vi.fn()} />)

    await user.clear(screen.getByLabelText('Model'))
    await user.type(screen.getByLabelText('Model'), 'claude-opus-4-1')
    await user.clear(screen.getByLabelText('Retries'))
    await user.type(screen.getByLabelText('Retries'), '4')
    await user.click(screen.getByRole('button', { name: i18n.t('providers.configure.save') }))

    expect(hooks.save).toHaveBeenCalledTimes(1)
    expect(hooks.save.mock.calls[0]?.[0]).toMatchObject({
      capability: 'llm',
      providerId: 'llm.anthropic',
      config: { model: 'claude-opus-4-1', retries: 4 },
    })
    expect(hooks.save.mock.calls[0]?.[0].config).not.toHaveProperty('api_key')
  })

  it('tests without saving', async () => {
    const user = userEvent.setup()
    render(<ProviderSettingsDialog provider={provider()} open onOpenChange={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: i18n.t('providers.configure.test') }))

    expect(hooks.test).toHaveBeenCalledTimes(1)
    expect(hooks.save).not.toHaveBeenCalled()
  })

  it('asks once before clearing a stored setting', async () => {
    const user = userEvent.setup()
    render(<ProviderSettingsDialog provider={provider()} open onOpenChange={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: i18n.t('providers.configure.clear') }))
    expect(hooks.clear).not.toHaveBeenCalled()

    await user.click(
      screen.getByRole('button', { name: i18n.t('providers.configure.confirmClear') }),
    )
    expect(hooks.clear).toHaveBeenCalledTimes(1)
  })
})
