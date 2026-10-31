import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

vi.mock('./attendanceApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('./attendanceApi')>()
  return {
    ...original,
    previewAttendance: vi.fn(),
    commitAttendance: vi.fn(),
    fileToBase64: vi.fn().mockResolvedValue('QQ=='),
  }
})

import { commitAttendance, previewAttendance } from './attendanceApi'
import { AttendanceImportDialog } from './AttendanceImportDialog'
import type { RunView } from './payrollApi'

const previewMock = vi.mocked(previewAttendance)
const commitMock = vi.mocked(commitAttendance)

const RUN: RunView = {
  id: 'run-1',
  period_year: 2026,
  period_month: 6,
  kind: 'monthly',
  status: 'draft',
  approval_id: null,
  signed_off_by: null,
  blocking_count: 0,
  anomalies: [],
  lines: [],
  totals: { employees: 0, gross: 0, total_deductions: 0, net: 0, employer_cost: 0 },
}

const PREVIEW = {
  period_year: 2026,
  period_month: 6,
  working_days: 21,
  file_hash: 'a'.repeat(64),
  standard_hours_per_day: 8,
  rows: [
    {
      employee_number: 'EMP-1',
      employee_id: 'emp-1',
      days_present: 20,
      overtime_hours: 3,
      absence_days: 1,
      on_leave_days: 0,
      flags: [],
    },
  ],
  errors: [],
}

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onOpenChange = vi.fn()
  render(
    <QueryClientProvider client={client}>
      <AttendanceImportDialog run={RUN} open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  )
  return { onOpenChange }
}

beforeEach(() => {
  previewMock.mockReset()
  commitMock.mockReset()
})

describe('AttendanceImportDialog', () => {
  it('previews pasted CSV and applies the same body on commit', async () => {
    previewMock.mockResolvedValue({ status: 200, preview: PREVIEW })
    commitMock.mockResolvedValue({ status: 200, run: null })
    const { onOpenChange } = renderDialog()

    await userEvent.type(
      screen.getByLabelText(i18n.t('payroll.attendance.paste')),
      'employee_number,date,clock_in,clock_out\nEMP-1,2026-06-01,08:00,17:00',
    )
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('payroll.attendance.preview') }),
    )

    expect(previewMock).toHaveBeenCalledTimes(1)
    expect(previewMock.mock.calls[0]?.[1]).toMatchObject({
      csv_text: expect.stringContaining('EMP-1'),
      header_row: 1,
      mapping: {
        employee_number: 'employee_number',
        date: 'date',
        clock_in: 'clock_in',
        clock_out: 'clock_out',
      },
    })
    expect(screen.getByText('EMP-1')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: i18n.t('payroll.attendance.commit') }))

    expect(commitMock).toHaveBeenCalledTimes(1)
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('refuses to commit while a row is refused', async () => {
    previewMock.mockResolvedValue({
      status: 200,
      preview: {
        ...PREVIEW,
        rows: [],
        errors: [{ row: 2, employee_number: 'GHOST', code: 'unknown_employee', detail: 'no one' }],
      },
    })
    renderDialog()

    await userEvent.type(
      screen.getByLabelText(i18n.t('payroll.attendance.paste')),
      'employee_number,date,clock_in,clock_out\nGHOST,2026-06-01,08:00,17:00',
    )
    await userEvent.click(
      screen.getByRole('button', { name: i18n.t('payroll.attendance.preview') }),
    )

    expect(screen.getByRole('alert')).toHaveTextContent('unknown_employee')
    expect(screen.getByRole('button', { name: i18n.t('payroll.attendance.commit') })).toBeDisabled()
  })
})
