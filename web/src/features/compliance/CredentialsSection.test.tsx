import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

import { CredentialsSection } from './CredentialsSection'
import type { CredentialRegistryView } from './credentialsApi'

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  save: vi.fn(),
  verify: vi.fn(),
  remove: vi.fn(),
  registries: { isLoading: false, data: [] as unknown[] },
}))

vi.mock('./useCredentials', () => ({
  useCredentialRegistries: () => mocks.registries,
  useCreateCredentialRegistry: () => ({
    mutate: mocks.create,
    isPending: false,
    isError: false,
  }),
  useSetCredentialEntries: () => ({ mutate: mocks.save, isPending: false }),
  useVerifyCredentialRegistry: () => ({ mutate: mocks.verify, isPending: false }),
  useDeleteCredentialRegistry: () => ({ mutate: mocks.remove, isPending: false }),
}))

function registry(overrides: Partial<CredentialRegistryView> = {}): CredentialRegistryView {
  return {
    id: 'registry-1',
    name: 'AWS certifications',
    issuer: 'AWS',
    entries: [
      {
        name: 'AWS Solutions Architect',
        status: 'verified',
        credential_id: null,
        expires_on: null,
        notes: null,
      },
    ],
    verified: false,
    verified_by: null,
    verified_at: null,
    source_note: null,
    updated_at: '2026-10-24T00:00:00Z',
    usable: false,
    ...overrides,
  }
}

describe('CredentialsSection', () => {
  beforeEach(() => {
    mocks.create.mockClear()
    mocks.save.mockClear()
    mocks.verify.mockClear()
    mocks.remove.mockClear()
    mocks.registries = { isLoading: false, data: [] }
  })

  it('creates a registry from a name and issuer', async () => {
    const user = userEvent.setup()
    render(<CredentialsSection />)

    await user.type(
      screen.getByLabelText(i18n.t('compliance.credentials.newName')),
      'AWS certifications',
    )
    await user.type(screen.getByLabelText(i18n.t('compliance.credentials.newIssuer')), 'AWS')
    await user.click(screen.getByRole('button', { name: i18n.t('compliance.credentials.create') }))

    expect(mocks.create).toHaveBeenCalledWith(
      { name: 'AWS certifications', issuer: 'AWS' },
      expect.anything(),
    )
  })

  it('shows the rows and will not verify without a source', async () => {
    mocks.registries = { isLoading: false, data: [registry()] }
    const user = userEvent.setup()
    render(<CredentialsSection />)

    expect(screen.getByText('AWS certifications')).toBeInTheDocument()
    expect(screen.getByText(i18n.t('compliance.credentials.unverified'))).toBeInTheDocument()
    expect(screen.getByLabelText(i18n.t('compliance.credentials.importLabel'))).toHaveValue(
      'AWS Solutions Architect | verified',
    )

    const verify = screen.getByRole('button', {
      name: i18n.t('compliance.credentials.verify'),
    })
    expect(verify).toBeDisabled()

    await user.type(
      screen.getByLabelText(i18n.t('compliance.credentials.sourceLabel')),
      'issuer page, 2026-10-24',
    )
    expect(verify).toBeEnabled()
    await user.click(verify)

    expect(mocks.verify).toHaveBeenCalledWith(
      { registryId: 'registry-1', sourceNote: 'issuer page, 2026-10-24' },
      expect.anything(),
    )
  })

  it('refuses a malformed row instead of saving it', async () => {
    mocks.registries = { isLoading: false, data: [registry()] }
    const user = userEvent.setup()
    render(<CredentialsSection />)

    const rows = screen.getByLabelText(i18n.t('compliance.credentials.importLabel'))
    await user.clear(rows)
    await user.type(rows, 'CKA | maybe')
    await user.click(
      screen.getByRole('button', { name: i18n.t('compliance.credentials.saveRows') }),
    )

    expect(mocks.save).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent(
      i18n.t('compliance.credentials.parseError', { line: 1 }),
    )
  })

  it('saves parsed rows', async () => {
    mocks.registries = { isLoading: false, data: [registry()] }
    const user = userEvent.setup()
    render(<CredentialsSection />)

    const rows = screen.getByLabelText(i18n.t('compliance.credentials.importLabel'))
    await user.clear(rows)
    await user.type(rows, 'CKA | failed | CKA-1')
    await user.click(
      screen.getByRole('button', { name: i18n.t('compliance.credentials.saveRows') }),
    )

    expect(mocks.save).toHaveBeenCalledWith(
      {
        registryId: 'registry-1',
        entries: [
          {
            name: 'CKA',
            status: 'failed',
            credential_id: 'CKA-1',
            expires_on: null,
            notes: null,
          },
        ],
      },
      expect.anything(),
    )
  })
})
