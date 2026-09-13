import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

vi.mock('@/features/hiring/useHiring', () => ({
  useJobs: () => ({
    isLoading: false,
    data: [{ id: 'job-1', title: 'Backend Engineer' }],
  }),
}))

vi.mock('@/features/hiring/importApi', () => ({
  uploadCvs: vi.fn(),
  submitImportBatch: vi.fn(),
}))

import { submitImportBatch } from '@/features/hiring/importApi'
import { ImportPage } from '@/pages/ImportPage'

const submitImportBatchMock = vi.mocked(submitImportBatch)

const CSV = 'name,email\nBudi Santoso,budi@example.com\nSinta,sinta@example.com\n'

function renderPage() {
  return render(
    <MemoryRouter>
      <ImportPage />
    </MemoryRouter>,
  )
}

async function chooseJob() {
  await userEvent.click(screen.getByRole('button', { name: i18n.t('hiring.job') }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'Backend Engineer' }))
}

beforeEach(() => {
  submitImportBatchMock.mockReset()
})

describe('ImportPage', () => {
  it('requires a job, valid rows, and consent before submitting', async () => {
    renderPage()

    const submit = screen.getByRole('button', { name: i18n.t('import.submit', { count: 0 }) })
    expect(submit).toBeDisabled()

    await userEvent.type(screen.getByRole('textbox', { name: i18n.t('import.csv') }), CSV)
    await chooseJob()
    await userEvent.click(screen.getByRole('checkbox', { name: i18n.t('import.consent') }))

    expect(
      screen.getByRole('button', { name: i18n.t('import.submit', { count: 2 }) }),
    ).toBeEnabled()
  })

  it('blocks invalid rows and names the problem', async () => {
    renderPage()

    await userEvent.type(
      screen.getByRole('textbox', { name: i18n.t('import.csv') }),
      'name,email\n,nope\n',
    )
    await chooseJob()
    await userEvent.click(screen.getByRole('checkbox', { name: i18n.t('import.consent') }))
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('import.submit', { count: 1 }) }),
    )

    expect(submitImportBatchMock).not.toHaveBeenCalled()
    expect(
      screen.getByText(i18n.t('import.errors.badEmail', { line: 2, count: 0 })),
    ).toBeInTheDocument()
  })

  it('submits the batch and reports accepted and conflicts', async () => {
    submitImportBatchMock.mockResolvedValue({
      accepted: 1,
      items: [
        { application_id: 'a1', status: 'queued', error: null },
        { application_id: null, status: 'conflict', error: 'duplicate submission' },
      ],
    })
    renderPage()

    await userEvent.type(screen.getByRole('textbox', { name: i18n.t('import.csv') }), CSV)
    await chooseJob()
    await userEvent.click(screen.getByRole('checkbox', { name: i18n.t('import.consent') }))
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('import.submit', { count: 2 }) }),
    )

    expect(submitImportBatchMock).toHaveBeenCalledWith('job-1', [
      {
        full_name: 'Budi Santoso',
        emails: ['budi@example.com'],
        links: '',
        document_id: null,
      },
      {
        full_name: 'Sinta',
        emails: ['sinta@example.com'],
        links: '',
        document_id: null,
      },
    ])
    expect(await screen.findByText(i18n.t('import.done'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('import.accepted', { count: 1 }))).toBeInTheDocument()
    expect(screen.getByText('duplicate submission')).toBeInTheDocument()
  })
})
