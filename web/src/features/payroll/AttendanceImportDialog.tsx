import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

import { fileToBase64, type AttendanceCommitBody } from './attendanceApi'
import type { RunView } from './payrollApi'
import { useAttendanceImport } from './useAttendanceImport'

const fieldClass = 'flex flex-col gap-1.5'
const labelClass = 'text-ink-strong text-xs font-medium'

const EXCEL = /\.(xlsx|xlsm)$/i

/**
 * Attendance import for one editable run: upload (or paste) → preview → commit.
 *
 * The preview is the same code path as the commit, so what the operator sees is
 * what the run will receive. A file that the parser refuses never reaches the
 * commit button; the refusal names its row. CSV stays available because a small
 * month is often pasted by hand, and the workbook path is for the machine export.
 */
export function AttendanceImportDialog({
  run,
  open,
  onOpenChange,
}: {
  run: RunView
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const { preview, commit } = useAttendanceImport(run.id)
  const [file, setFile] = useState<File | null>(null)
  const [pasted, setPasted] = useState('')
  const [headerRow, setHeaderRow] = useState('1')
  const [columns, setColumns] = useState({
    employee_number: 'employee_number',
    date: 'date',
    clock_in: 'clock_in',
    clock_out: 'clock_out',
  })
  const [problem, setProblem] = useState<string | null>(null)

  const usingWorkbook = file !== null
  const usingCsv = !usingWorkbook && pasted.trim() !== ''
  const canPreview = usingWorkbook || usingCsv

  function body(): AttendanceCommitBody | null {
    if (usingWorkbook) {
      return null
    }
    return { csv_text: pasted, header_row: Number(headerRow) || 1, mapping: columns }
  }

  async function workbookBody(): Promise<AttendanceCommitBody> {
    const base64 = await fileToBase64(file as File)
    return {
      file_base64: base64,
      filename: (file as File).name,
      header_row: Number(headerRow) || 1,
      mapping: columns,
    }
  }

  async function handlePreview() {
    setProblem(null)
    try {
      const payload = usingWorkbook ? await workbookBody() : body()
      if (payload === null) {
        return
      }
      const result = await preview.mutateAsync(payload)
      if (result.status !== 200) {
        setProblem(t('payroll.attendance.errors.previewFailed', { status: result.status }))
      }
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error))
    }
  }

  async function handleCommit(event: FormEvent) {
    event.preventDefault()
    setProblem(null)
    try {
      const payload = usingWorkbook ? await workbookBody() : body()
      if (payload === null) {
        return
      }
      const result = await commit.mutateAsync(payload)
      if (result.status === 200) {
        onOpenChange(false)
        setFile(null)
        setPasted('')
        preview.reset()
        return
      }
      setProblem(t('payroll.attendance.errors.commitFailed', { status: result.status }))
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error))
    }
  }

  const result = preview.data?.preview
  const blocking = result?.errors ?? []
  const canCommit = result !== undefined && blocking.length === 0 && result.rows.length > 0
  const busy = preview.isPending || commit.isPending

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('payroll.attendance.title')}</DialogTitle>
          <DialogDescription>{t('payroll.attendance.hint')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={(event) => void handleCommit(event)} className="flex flex-col gap-4">
          {problem !== null ? (
            <p role="alert" className="text-error text-xs">
              {problem}
            </p>
          ) : null}

          <div className={fieldClass}>
            <label htmlFor={`attendance-file-${run.id}`} className={labelClass}>
              {t('payroll.attendance.file')}
            </label>
            <Input
              id={`attendance-file-${run.id}`}
              type="file"
              accept=".csv,.xlsx,.xlsm"
              onChange={(event) => {
                const chosen = event.target.files?.[0] ?? null
                preview.reset()
                if (chosen === null) {
                  setFile(null)
                  return
                }
                if (EXCEL.test(chosen.name)) {
                  setFile(chosen)
                  setPasted('')
                  return
                }
                // A picked CSV is read as text: the workbook parser cannot read it,
                // and the CSV path is the one the operator already knows.
                setFile(null)
                void chosen.text().then((text) => setPasted(text))
              }}
            />
            <p className="text-ink-muted text-2xs">{t('payroll.attendance.fileHint')}</p>
          </div>

          {!usingWorkbook ? (
            <div className={fieldClass}>
              <label htmlFor={`attendance-paste-${run.id}`} className={labelClass}>
                {t('payroll.attendance.paste')}
              </label>
              <textarea
                id={`attendance-paste-${run.id}`}
                className="border-line min-h-24 w-full rounded border p-2 font-mono text-xs"
                value={pasted}
                placeholder={t('payroll.attendance.pastePlaceholder')}
                onChange={(event) => {
                  setPasted(event.target.value)
                  preview.reset()
                }}
              />
            </div>
          ) : null}

          <details className="text-xs">
            <summary className="text-ink-strong cursor-pointer font-medium">
              {t('payroll.attendance.columns')}
            </summary>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {(
                [
                  ['employee_number', 'columnEmployee'],
                  ['date', 'columnDate'],
                  ['clock_in', 'columnIn'],
                  ['clock_out', 'columnOut'],
                ] as const
              ).map(([field, label]) => (
                <div className={fieldClass} key={field}>
                  <label htmlFor={`attendance-${field}-${run.id}`} className={labelClass}>
                    {t(`payroll.attendance.${label}`)}
                  </label>
                  <Input
                    id={`attendance-${field}-${run.id}`}
                    value={columns[field]}
                    onChange={(event) => {
                      setColumns({ ...columns, [field]: event.target.value })
                      preview.reset()
                    }}
                  />
                </div>
              ))}
              {usingWorkbook ? (
                <div className={fieldClass}>
                  <label htmlFor={`attendance-header-${run.id}`} className={labelClass}>
                    {t('payroll.attendance.headerRow')}
                  </label>
                  <Input
                    id={`attendance-header-${run.id}`}
                    inputMode="numeric"
                    value={headerRow}
                    onChange={(event) => {
                      setHeaderRow(event.target.value)
                      preview.reset()
                    }}
                  />
                </div>
              ) : null}
            </div>
          </details>

          {result !== undefined ? (
            <section
              aria-labelledby={`attendance-result-${run.id}`}
              className="flex flex-col gap-2"
            >
              <h3
                id={`attendance-result-${run.id}`}
                className="text-ink-strong text-sm font-medium"
              >
                {t('payroll.attendance.resultTitle', {
                  working: result.working_days,
                  threshold: result.standard_hours_per_day,
                })}
              </h3>
              {blocking.length > 0 ? (
                <ul role="alert" className="text-error flex flex-col gap-1 text-xs">
                  {blocking.slice(0, 20).map((error) => (
                    <li key={`${error.row}-${error.code}-${error.employee_number ?? ''}`}>
                      {t('payroll.attendance.rowError', {
                        row: error.row,
                        code: error.code,
                        detail: error.detail,
                      })}
                    </li>
                  ))}
                </ul>
              ) : (
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-ink-muted text-left">
                      <th className="py-1 font-medium">{t('payroll.attendance.employee')}</th>
                      <th className="py-1 font-medium">{t('payroll.attendance.daysPresent')}</th>
                      <th className="py-1 font-medium">{t('payroll.attendance.overtime')}</th>
                      <th className="py-1 font-medium">{t('payroll.attendance.absence')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row) => (
                      <tr key={row.employee_number} className="border-line border-t">
                        <td className="py-1 font-mono">{row.employee_number}</td>
                        <td className="py-1">{row.days_present}</td>
                        <td className="py-1">{row.overtime_hours}</td>
                        <td className="py-1">{row.absence_days}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!canPreview || busy}
              onClick={() => void handlePreview()}
            >
              {t('payroll.attendance.preview')}
            </Button>
            <Button type="submit" size="sm" disabled={!canCommit || busy}>
              {t('payroll.attendance.commit')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
