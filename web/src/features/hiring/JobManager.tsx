import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'
import { Badge } from '@/components/ui/badge'
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
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

import { changeJobStatus } from './jobApi'
import { JobFormDialog } from './JobFormDialog'
import { JOB_TRANSITIONS, transitionLabelKey, type JobStatus, type JobView } from './jobForm'
import { useJobs } from './useHiring'

interface StatusChangeDialogProps {
  job: JobView
  target: JobStatus
  open: boolean
  onOpenChange: (open: boolean) => void
}

function StatusChangeDialog({ job, target, open, onOpenChange }: StatusChangeDialogProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [by, setBy] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function close(next: boolean) {
    if (!next) {
      setBy('')
      setError(null)
    }
    onOpenChange(next)
  }

  async function confirm() {
    if (by.trim() === '') {
      setError(t('jobs.errors.byRequired'))
      return
    }
    setBusy(true)
    const result = await changeJobStatus(job.id, target, by.trim())
    setBusy(false)
    if (result.status === 200) {
      await queryClient.invalidateQueries({ queryKey: ['jobs'] })
      close(false)
      return
    }
    setError(result.status === 409 ? t('jobs.errors.conflict') : t('jobs.errors.transitionFailed'))
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('jobs.transitionTitle')}</DialogTitle>
          <DialogDescription>
            {t('jobs.transitionBody', {
              action: t(transitionLabelKey(job.status, target)),
              title: job.title,
            })}
          </DialogDescription>
        </DialogHeader>

        {error !== null ? (
          <p role="alert" className="text-error flex items-center gap-1 text-xs">
            <span aria-hidden="true">●</span>
            {error}
          </p>
        ) : null}

        <div className="flex flex-col gap-1.5">
          <label htmlFor="job-transition-by" className="text-ink-strong text-xs font-medium">
            {t('jobs.transitionBy')}
          </label>
          <Input
            id="job-transition-by"
            value={by}
            onChange={(event) => setBy(event.target.value)}
            placeholder={t('jobs.fields.savedByPlaceholder')}
            autoComplete="off"
          />
        </div>

        <DialogFooter>
          <Button size="sm" disabled={busy} onClick={() => void confirm()}>
            {t('jobs.transitionConfirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/**
 * Job specifications: create, edit, and drive the guarded status lifecycle.
 *
 * Every transition carries a named human (`by`) and is audited server-side;
 * closed jobs are read-only, matching the service rule.
 */
export function JobManager() {
  const { t, i18n } = useTranslation()
  const jobs = useJobs()
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<JobView | null>(null)
  const [transition, setTransition] = useState<{ job: JobView; target: JobStatus } | null>(null)

  if (jobs.isLoading) {
    return <Skeleton className="h-48 w-full" />
  }

  const items = jobs.data ?? []

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span className="text-2xs text-ink-muted">{t('jobs.count', { count: items.length })}</span>
        <Button
          size="sm"
          onClick={() => {
            setEditing(null)
            setFormOpen(true)
          }}
        >
          {t('jobs.create')}
        </Button>
      </div>

      {items.length === 0 ? (
        <EmptyState title={t('jobs.empty')} />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('jobs.fields.title')}</TableHead>
              <TableHead>{t('jobs.fields.status')}</TableHead>
              <TableHead>{t('jobs.fields.seniority')}</TableHead>
              <TableHead>{t('jobs.fields.minYears')}</TableHead>
              <TableHead>{t('jobs.fields.updated')}</TableHead>
              <TableHead className="text-right">{t('jobs.fields.actions')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((job) => (
              <TableRow key={job.id}>
                <TableCell className="text-ink-strong font-medium">{job.title}</TableCell>
                <TableCell>
                  <Badge variant="outline">{t(`jobs.status.${job.status}`)}</Badge>
                </TableCell>
                <TableCell className="text-ink-muted text-xs">
                  {t(`jobs.seniority.${job.seniority}`)}
                </TableCell>
                <TableCell className="text-ink-muted font-mono text-xs tabular-nums">
                  {job.min_years_experience}
                </TableCell>
                <TableCell className="text-ink-muted text-xs">
                  {new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium' }).format(
                    new Date(job.updated_at),
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1">
                    {job.status !== 'closed' ? (
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() => {
                          setEditing(job)
                          setFormOpen(true)
                        }}
                      >
                        {t('jobs.edit')}
                      </Button>
                    ) : null}
                    {JOB_TRANSITIONS[job.status].map((target) => (
                      <Button
                        key={target}
                        variant="outline"
                        size="xs"
                        onClick={() => setTransition({ job, target })}
                      >
                        {t(transitionLabelKey(job.status, target))}
                      </Button>
                    ))}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {formOpen ? (
        <JobFormDialog key={editing?.id ?? 'new'} job={editing} open onOpenChange={setFormOpen} />
      ) : null}
      {transition !== null ? (
        <StatusChangeDialog
          job={transition.job}
          target={transition.target}
          open
          onOpenChange={(open) => {
            if (!open) {
              setTransition(null)
            }
          }}
        />
      ) : null}
    </div>
  )
}
