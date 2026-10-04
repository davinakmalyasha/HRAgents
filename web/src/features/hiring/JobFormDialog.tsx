import { useQueryClient } from '@tanstack/react-query'
import { ChevronsUpDown } from 'lucide-react'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { problemMessage } from '@/lib/problem'

import { createJob, updateJob } from './jobApi'
import {
  DEFAULT_WEIGHTS,
  DIMENSIONS,
  SENIORITIES,
  formatList,
  parseList,
  parseWeights,
  type JobView,
  type ScoreDimension,
  type Seniority,
} from './jobForm'

interface JobFormDialogProps {
  job: JobView | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

type Phase = { name: 'form' } | { name: 'submitting' } | { name: 'error'; detail: string }

const fieldClass = 'flex flex-col gap-1.5'
const labelClass = 'text-xs font-medium text-ink-strong'

/**
 * Create or edit a job specification. Client validation mirrors the server
 * (title, named actor, integer years, weights non-negative and summing to 1.0);
 * the API stays authoritative and every write is audited.
 */
export function JobFormDialog({ job, open, onOpenChange }: JobFormDialogProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const baseWeights = job?.dimension_weights ?? DEFAULT_WEIGHTS
  const [title, setTitle] = useState(job?.title ?? '')
  const [seniority, setSeniority] = useState<Seniority>(job?.seniority ?? 'mid')
  const [description, setDescription] = useState(job?.description ?? '')
  const [minYears, setMinYears] = useState(String(job?.min_years_experience ?? 0))
  const [responsibilities, setResponsibilities] = useState(formatList(job?.responsibilities ?? []))
  const [mustHave, setMustHave] = useState(formatList(job?.must_have_skills ?? []))
  const [niceToHave, setNiceToHave] = useState(formatList(job?.nice_to_have_skills ?? []))
  const [stack, setStack] = useState(formatList(job?.stack ?? []))
  const [weights, setWeights] = useState<Record<ScoreDimension, string>>(
    () =>
      Object.fromEntries(
        DIMENSIONS.map((dimension) => [dimension, String(baseWeights[dimension] ?? '')]),
      ) as Record<ScoreDimension, string>,
  )
  const [phase, setPhase] = useState<Phase>({ name: 'form' })
  const [fieldErrors, setFieldErrors] = useState<string[]>([])

  const total = DIMENSIONS.reduce((sum, dimension) => sum + (Number(weights[dimension]) || 0), 0)

  function close(next: boolean) {
    if (!next) {
      setPhase({ name: 'form' })
      setFieldErrors([])
    }
    onOpenChange(next)
  }

  function errorFor(status: number): string {
    return problemMessage(status, undefined, t, 'jobs', {
      overrides: (code) => {
        if (code === 422) {
          return t('jobs.errors.weightsNumber')
        }
        return null
      },
    })
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const problems: string[] = []
    if (title.trim() === '') {
      problems.push(t('jobs.errors.titleRequired'))
    }
    const years = Number(minYears)
    if (minYears.trim() === '' || !Number.isInteger(years) || years < 0 || years > 60) {
      problems.push(t('jobs.errors.yearsInvalid'))
    }
    if (problems.length > 0) {
      setFieldErrors(problems)
      return
    }
    const parsed = parseWeights(weights)
    if (!parsed.ok) {
      setFieldErrors([
        parsed.reason === 'number' ? t('jobs.errors.weightsNumber') : t('jobs.errors.weightsSum'),
      ])
      return
    }
    setFieldErrors([])
    setPhase({ name: 'submitting' })

    const payload = {
      title: title.trim(),
      seniority,
      description,
      responsibilities: parseList(responsibilities),
      must_have_skills: parseList(mustHave),
      nice_to_have_skills: parseList(niceToHave),
      stack: parseList(stack),
      min_years_experience: years,
      dimension_weights: parsed.weights,
    }
    const result =
      job === null
        ? await createJob({ ...payload, status: 'draft' })
        : await updateJob(job.id, { ...payload })

    if (result.status === 200 || result.status === 201) {
      await queryClient.invalidateQueries({ queryKey: ['jobs'] })
      close(false)
      return
    }
    setPhase({ name: 'error', detail: errorFor(result.status) })
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{job === null ? t('jobs.create') : t('jobs.edit')}</DialogTitle>
          <DialogDescription>{t('jobs.formHint')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-4">
          {phase.name === 'error' ? (
            <p role="alert" className="text-error flex items-center gap-1 text-xs">
              <span aria-hidden="true">●</span>
              {phase.detail}
            </p>
          ) : null}

          {fieldErrors.length > 0 ? (
            <ul role="alert" className="text-error flex flex-col gap-1 text-xs">
              {fieldErrors.map((problem) => (
                <li key={problem} className="flex items-center gap-1">
                  <span aria-hidden="true">●</span>
                  {problem}
                </li>
              ))}
            </ul>
          ) : null}

          <div className={fieldClass}>
            <label htmlFor="job-title" className={labelClass}>
              {t('jobs.fields.title')}
            </label>
            <Input
              id="job-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              autoComplete="off"
            />
          </div>

          <div className={fieldClass}>
            <span id="job-seniority-label" className={labelClass}>
              {t('jobs.fields.seniority')}
            </span>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  aria-labelledby="job-seniority-label"
                  className="justify-between"
                >
                  <span>{t(`jobs.seniority.${seniority}`)}</span>
                  <ChevronsUpDown aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuRadioGroup
                  value={seniority}
                  onValueChange={(value) => setSeniority(value as Seniority)}
                >
                  {SENIORITIES.map((option) => (
                    <DropdownMenuRadioItem key={option} value={option}>
                      {t(`jobs.seniority.${option}`)}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          <div className={fieldClass}>
            <label htmlFor="job-years" className={labelClass}>
              {t('jobs.fields.minYears')}
            </label>
            <Input
              id="job-years"
              type="number"
              min="0"
              max="60"
              step="1"
              value={minYears}
              onChange={(event) => setMinYears(event.target.value)}
              className="font-mono text-xs"
            />
          </div>

          <div className={fieldClass}>
            <label htmlFor="job-description" className={labelClass}>
              {t('jobs.fields.description')}
            </label>
            <Textarea
              id="job-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={3}
              className="min-h-16"
            />
          </div>

          {(
            [
              [
                'responsibilities',
                t('jobs.fields.responsibilities'),
                responsibilities,
                setResponsibilities,
              ],
              ['must-have', t('jobs.fields.mustHave'), mustHave, setMustHave],
              ['nice-to-have', t('jobs.fields.niceToHave'), niceToHave, setNiceToHave],
              ['stack', t('jobs.fields.stack'), stack, setStack],
            ] as const
          ).map(([id, label, value, setValue]) => (
            <div key={id} className={fieldClass}>
              <label htmlFor={`job-${id}`} className={labelClass}>
                {label}
              </label>
              <Textarea
                id={`job-${id}`}
                value={value}
                onChange={(event) => setValue(event.target.value)}
                rows={2}
                className="min-h-9"
              />
            </div>
          ))}

          <div className={fieldClass}>
            <span className={labelClass}>{t('jobs.fields.weights')}</span>
            <p className="text-2xs text-ink-muted">{t('jobs.fields.weightsHelp')}</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {DIMENSIONS.map((dimension) => (
                <label key={dimension} className="flex flex-col gap-1">
                  <span className="text-2xs text-ink-muted">
                    {t(`jobs.dimensions.${dimension}`)}
                  </span>
                  <Input
                    type="number"
                    min="0"
                    max="1"
                    step="0.05"
                    value={weights[dimension] ?? ''}
                    onChange={(event) =>
                      setWeights({ ...weights, [dimension]: event.target.value })
                    }
                    aria-label={t(`jobs.dimensions.${dimension}`)}
                    className="font-mono text-xs"
                  />
                </label>
              ))}
            </div>
            <p className="text-2xs text-ink-muted">
              {t('jobs.weightsTotal', { total: total.toFixed(2) })}
            </p>
          </div>

          <DialogFooter>
            <Button type="submit" size="sm" disabled={phase.name === 'submitting'}>
              {job === null ? t('jobs.save') : t('jobs.update')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
