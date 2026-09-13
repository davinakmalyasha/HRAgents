import { useMemo, useState, type ChangeEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { EmptyState } from '@/components/feedback/EmptyState'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'

import { JobSelector } from '@/features/hiring/JobSelector'
import {
  submitImportBatch,
  uploadCvs,
  type BatchReport,
  type UploadedCv,
} from '@/features/hiring/importApi'
import { parseImportCsv, toImportItems, validateImportRows } from '@/features/hiring/importCsv'
import { useJobs } from '@/features/hiring/useHiring'

/**
 * CSV batch import: paste or drop candidate rows, upload CVs, preview, submit.
 *
 * Consent is explicit: nothing submits until the operator confirms every
 * candidate on the list agreed to evaluation.
 */
export function ImportPage() {
  const { t } = useTranslation()
  const jobs = useJobs()
  const [jobId, setJobId] = useState<string | null>(null)
  const [csvText, setCsvText] = useState('')
  const [uploads, setUploads] = useState<UploadedCv[]>([])
  const [uploading, setUploading] = useState(false)
  const [consented, setConsented] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(false)
  const [report, setReport] = useState<BatchReport | null>(null)

  const uploadedNames = useMemo(
    () =>
      new Set(uploads.filter((upload) => upload.error === null).map((upload) => upload.filename)),
    [uploads],
  )
  const cvDocuments = useMemo(() => {
    const map = new Map<string, string>()
    for (const upload of uploads) {
      if (upload.documentId !== null) {
        map.set(upload.filename, upload.documentId)
      }
    }
    return map
  }, [uploads])

  const parsed = useMemo(() => parseImportCsv(csvText), [csvText])
  const issues = useMemo(
    () => validateImportRows(parsed.rows, uploadedNames),
    [parsed, uploadedNames],
  )
  const preview = useMemo(
    () => toImportItems(parsed.rows.slice(0, 8), cvDocuments),
    [parsed, cvDocuments],
  )

  const canSubmit =
    jobId !== null && consented && parsed.rows.length > 0 && issues.length === 0 && !submitting

  async function handleFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files
    if (files === null || files.length === 0 || uploading) {
      return
    }
    setUploading(true)
    try {
      const results = await uploadCvs([...files])
      setUploads((previous) => [...previous, ...results])
    } finally {
      setUploading(false)
    }
  }

  async function handleSubmit() {
    if (!canSubmit || jobId === null) {
      return
    }
    setSubmitting(true)
    setSubmitError(false)
    try {
      setReport(await submitImportBatch(jobId, toImportItems(parsed.rows, cvDocuments)))
    } catch {
      setSubmitError(true)
    } finally {
      setSubmitting(false)
    }
  }

  if (report !== null) {
    const conflicts = report.items.filter((item) => item.error !== null)
    return (
      <div className="flex flex-col gap-6">
        <h1 className="text-ink-strong text-2xl font-semibold">{t('import.done')}</h1>
        <p className="text-ink text-sm">
          <span>{t('import.accepted', { count: report.accepted })}</span>
          {conflicts.length > 0 ? (
            <span>{` · ${t('import.conflicts', { count: conflicts.length })}`}</span>
          ) : null}
        </p>
        {conflicts.length > 0 ? (
          <ul className="border-line flex flex-col gap-1 rounded-lg border p-3">
            {conflicts.map((item, index) => (
              <li key={index} className="text-error flex items-center gap-2 text-xs">
                <span aria-hidden="true">●</span>
                {item.error}
              </li>
            ))}
          </ul>
        ) : null}
        <div className="flex gap-2">
          <Button asChild size="sm">
            <Link to="/w/hiring?room=board">{t('import.openBoard')}</Link>
          </Button>
          <Button variant="outline" size="sm" onClick={() => setReport(null)}>
            {t('import.more')}
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex max-w-3xl flex-col gap-8">
      <div className="flex flex-col gap-3">
        <Button asChild variant="ghost" size="xs" className="self-start">
          <Link to="/w/hiring?room=board">{t('import.back')}</Link>
        </Button>
        <h1 className="text-ink-strong text-2xl font-semibold">{t('import.title')}</h1>
      </div>

      <section aria-labelledby="import-job" className="flex flex-col gap-2">
        <h2 id="import-job" className="text-ink-strong text-xl font-medium">
          {t('import.job')}
        </h2>
        {jobs.isLoading ? (
          <Skeleton className="h-9 w-64" />
        ) : (
          <JobSelector jobs={jobs.data ?? []} value={jobId} onChange={setJobId} />
        )}
      </section>

      <section aria-labelledby="import-csv" className="flex flex-col gap-2">
        <h2 id="import-csv" className="text-ink-strong text-xl font-medium">
          {t('import.csv')}
        </h2>
        <p className="text-ink-muted text-xs">{t('import.csvHelp')}</p>
        <Textarea
          value={csvText}
          onChange={(event) => setCsvText(event.target.value)}
          placeholder={t('import.csvPlaceholder')}
          aria-label={t('import.csv')}
          rows={6}
          className="font-mono text-xs"
        />
      </section>

      <section aria-labelledby="import-cvs" className="flex flex-col gap-2">
        <h2 id="import-cvs" className="text-ink-strong text-xl font-medium">
          {t('import.cvs')}
        </h2>
        <p className="text-ink-muted text-xs">{t('import.cvsHelp')}</p>
        <label className="border-line text-ink-muted hover:border-line-strong flex cursor-pointer items-center justify-center rounded-lg border border-dashed px-6 py-6 text-center text-xs transition-colors">
          <input
            type="file"
            multiple
            accept=".pdf,.doc,.docx,.txt,.md"
            className="sr-only"
            aria-label={t('import.cvs')}
            onChange={(event) => void handleFiles(event)}
          />
          {uploading ? t('import.uploading') : t('import.chooseFiles')}
        </label>
        {uploads.length > 0 ? (
          <ul className="flex flex-col gap-1">
            {uploads.map((upload, index) => (
              <li
                key={`${upload.filename}-${index}`}
                className="text-ink-muted flex items-center gap-2 text-xs"
              >
                <span aria-hidden="true">{upload.error === null ? '✓' : '●'}</span>
                <span className="font-mono">{upload.filename}</span>
                {upload.error !== null ? <span className="text-error">{upload.error}</span> : null}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section aria-labelledby="import-preview" className="flex flex-col gap-2">
        <h2 id="import-preview" className="text-ink-strong text-xl font-medium">
          {t('import.preview')}
        </h2>
        {issues.length > 0 ? (
          <ul role="alert" className="text-error flex flex-col gap-1 text-xs">
            {issues.map((issue, index) => (
              <li key={index} className="flex items-center gap-1">
                <span aria-hidden="true">●</span>
                {t(issue.messageKey, { line: issue.line, count: issue.count ?? 0 })}
              </li>
            ))}
          </ul>
        ) : null}
        {preview.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('hiring.candidate')}</TableHead>
                <TableHead>email</TableHead>
                <TableHead>cv</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {preview.map((item, index) => (
                <TableRow key={index}>
                  <TableCell className="font-medium">{item.full_name}</TableCell>
                  <TableCell className="text-2xs font-mono">{item.emails.join(', ')}</TableCell>
                  <TableCell className="text-2xs font-mono">
                    {item.document_id === null ? '—' : item.document_id.slice(0, 8)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState title={t('import.previewEmpty')} />
        )}
      </section>

      <div className="border-line flex flex-col gap-3 border-t pt-4">
        <label className="text-ink flex cursor-pointer items-start gap-2 text-xs">
          <input
            type="checkbox"
            checked={consented}
            onChange={(event) => setConsented(event.target.checked)}
            className="accent-primary mt-0.5 size-4"
          />
          {t('import.consent')}
        </label>
        {submitError ? (
          <p role="alert" className="text-error flex items-center gap-1 text-xs">
            <span aria-hidden="true">●</span>
            {t('import.failed')}
          </p>
        ) : null}
        <Button
          size="sm"
          className="self-start"
          disabled={!canSubmit}
          onClick={() => void handleSubmit()}
        >
          {t('import.submit', { count: parsed.rows.length })}
        </Button>
      </div>
    </div>
  )
}
