import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

import { ExportSection } from './ExportSection'

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  save: vi.fn(),
}))

vi.mock('./exportApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./exportApi')>()
  return { ...actual, fetchTenantExport: mocks.fetch, saveExport: mocks.save }
})

describe('ExportSection', () => {
  beforeEach(() => {
    mocks.fetch.mockReset()
    mocks.save.mockReset()
  })

  it('downloads the export and names the saved file', async () => {
    mocks.fetch.mockResolvedValue({
      blob: new Blob(['{}']),
      filename: 'hragents-export-2026-10-24.json',
    })
    const user = userEvent.setup()
    render(<ExportSection />)

    await user.click(screen.getByRole('button', { name: i18n.t('compliance.export.download') }))

    expect(mocks.save).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('status')).toHaveTextContent(
      i18n.t('compliance.export.saved', { name: 'hragents-export-2026-10-24.json' }),
    )
  })

  it('names a role refusal instead of pretending it worked', async () => {
    const { ExportRequestError } = await import('./exportApi')
    mocks.fetch.mockRejectedValue(new ExportRequestError(403))
    const user = userEvent.setup()
    render(<ExportSection />)

    await user.click(screen.getByRole('button', { name: i18n.t('compliance.export.download') }))

    expect(mocks.save).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent(i18n.t('compliance.export.forbidden'))
  })

  it('surfaces the server detail when there is no durable backend', async () => {
    const { ExportRequestError } = await import('./exportApi')
    mocks.fetch.mockRejectedValue(
      new ExportRequestError(409, 'a full export needs the Postgres backend'),
    )
    const user = userEvent.setup()
    render(<ExportSection />)

    await user.click(screen.getByRole('button', { name: i18n.t('compliance.export.download') }))

    expect(screen.getByRole('alert')).toHaveTextContent('a full export needs the Postgres backend')
  })
})
