import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge } from '@/components/status/StatusBadge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { useEmployees } from '@/features/records/useRecords'
import { formatDate } from '@/lib/dates'

import {
  isOpenCycle,
  REVIEW_DIMENSIONS,
  collectRatings,
  isProgressable,
  isReviewable,
  progressPercent,
  type AssignmentView,
  type CycleView,
  type GoalView,
} from './growthApi'
import {
  useGrowthCycles,
  useGrowthGoals,
  useMyAssignments,
  useOverdueGoals,
  useRecordGoalProgress,
  useSubmitAssignment,
} from './useGrowth'

/**
 * Growth board: cycles in flight, what is overdue, and the goals still open.
 *
 * Read-only. Writing a review belongs in the queue, because a review is attributable to a
 * named person -- it should not be a click away from a summary people expect to skim.
 */
export function GrowthBoard() {
  const { t } = useTranslation()
  const cycles = useGrowthCycles()
  const goals = useGrowthGoals()
  const overdue = useOverdueGoals()

  if (cycles.isLoading || goals.isLoading) {
    return <Skeleton className="h-40" />
  }

  const openCycles = (cycles.data ?? []).filter((cycle) => isOpenCycle(cycle.status))
  const openGoals = (goals.data ?? []).filter((goal) => isProgressable(goal.status))
  const late = overdue.data ?? []

  return (
    <section aria-labelledby="growth-board" className="flex flex-col gap-5">
      <h2 id="growth-board" className="text-ink-strong text-lg font-medium">
        {t('growth.boardTitle')}
      </h2>

      <section aria-labelledby="growth-cycles">
        <h3 id="growth-cycles" className="text-ink-strong text-base font-medium">
          {t('growth.cyclesTitle')}
        </h3>
        {openCycles.length === 0 ? (
          <EmptyState title={t('growth.cyclesEmpty')} />
        ) : (
          <ul className="mt-2 flex flex-col gap-2">
            {openCycles.map((cycle) => (
              <li key={cycle.id} className="border-line rounded-lg border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-ink-strong font-medium">{cycle.name}</p>
                    <p className="text-ink-muted text-sm">
                      {t('growth.period', {
                        start: formatDate(cycle.period_start),
                        end: formatDate(cycle.period_end),
                      })}
                    </p>
                  </div>
                  <StatusBadge tone="waiting" labelKey={`growth.cycleStatus.${cycle.status}`} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="growth-late">
        <h3 id="growth-late" className="text-ink-strong text-base font-medium">
          {t('growth.overdueTitle', { count: late.length })}
        </h3>
        {late.length === 0 ? (
          <EmptyState title={t('growth.noOverdue')} />
        ) : (
          <ul className="mt-2 flex flex-col gap-2">
            {late.map((goal) => (
              <li key={goal.id} className="border-line rounded-lg border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-ink-strong text-sm font-medium">{goal.title}</p>
                  <StatusBadge tone="error" labelKey="growth.overdue" />
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="growth-goals">
        <h3 id="growth-goals" className="text-ink-strong text-base font-medium">
          {t('growth.goalsTitle', { count: openGoals.length })}
        </h3>
        <OpenGoals goals={openGoals} />
      </section>
    </section>
  )
}

function OpenGoals({ goals }: { goals: GoalView[] }) {
  const { t } = useTranslation()
  const progress = useRecordGoalProgress()

  if (goals.length === 0) {
    return <EmptyState title={t('growth.goalsEmpty')} />
  }

  return (
    <ul className="mt-2 flex flex-col gap-2">
      {goals.map((goal) => {
        const percent = progressPercent(goal)
        return (
          <li key={goal.id} className="border-line rounded-lg border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-ink-strong text-sm font-medium">{goal.title}</p>
                {goal.metric || goal.due_on ? (
                  <p className="text-ink-muted text-xs">
                    {goal.metric ? goal.metric : null}
                    {goal.due_on
                      ? ` · ${t('growth.due', { date: formatDate(goal.due_on) })}`
                      : null}
                  </p>
                ) : null}
              </div>
              <div className="flex items-center gap-2">
                {goal.status === 'completed' ? (
                  <StatusBadge tone="done" labelKey="growth.goalStatus.completed" />
                ) : null}
                <Button
                  size="sm"
                  disabled={progress.isPending}
                  onClick={() =>
                    progress.mutate({
                      goalId: goal.id,
                      percent: Math.min(100, percent + 10),
                      note: t('growth.progressNote'),
                    })
                  }
                >
                  {t('growth.bumpProgress')}
                </Button>
              </div>
            </div>
            <Progress
              className="mt-2"
              value={percent}
              aria-label={t('growth.progressFor', { title: goal.title })}
            />
            <p className="text-ink-muted mt-1 text-xs tabular-nums">
              {t('growth.percent', { percent })}
            </p>
          </li>
        )
      })}
    </ul>
  )
}

/**
 * Growth queue: the caller's own review assignments.
 *
 * A skipped assignment is shown as skipped, not as work still to do -- skipping is a
 * recorded decision, and listing it as outstanding would tell a manager they owe a review
 * they deliberately did not write.
 */
export function GrowthQueue() {
  const { t } = useTranslation()
  const assignments = useMyAssignments()
  const cycles = useGrowthCycles()
  const employees = useEmployees()

  const names = useMemo(() => {
    const map = new Map<string, string>()
    for (const employee of employees.data ?? []) {
      map.set(employee.id, employee.full_name)
    }
    return map
  }, [employees.data])

  const cycleById = useMemo(() => {
    const map = new Map<string, CycleView>()
    for (const cycle of cycles.data ?? []) {
      map.set(cycle.id, cycle)
    }
    return map
  }, [cycles.data])

  if (assignments.isLoading || cycles.isLoading) {
    return <Skeleton className="h-40" />
  }

  const list = assignments.data ?? []
  if (list.length === 0) {
    return <EmptyState title={t('growth.assignmentsEmpty')} />
  }

  return (
    <section aria-labelledby="growth-queue" className="flex flex-col gap-3">
      <h2 id="growth-queue" className="text-ink-strong text-lg font-medium">
        {t('growth.assignmentsTitle', { count: list.length })}
      </h2>
      <ul className="flex flex-col gap-2">
        {list.map((assignment) => {
          const cycle = cycleById.get(assignment.cycle_id)
          /**
           * The write form appears only while the cycle is active, because that is the
           * only window `submit_assignment` accepts. Assignments span every cycle, so
           * the status that gates the write lives on the cycle -- offering a form and
           * letting the server refuse it would be worse than not offering one.
           */
          return (
            <AssignmentRow
              key={assignment.id}
              assignment={assignment}
              cycle={cycle}
              employeeName={names.get(assignment.employee_id) ?? assignment.employee_id}
            />
          )
        })}
      </ul>
    </section>
  )
}

function AssignmentRow({
  assignment,
  cycle,
  employeeName,
}: {
  assignment: AssignmentView
  cycle: CycleView | undefined
  employeeName: string
}) {
  const { t } = useTranslation()
  const submit = useSubmitAssignment()
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [comments, setComments] = useState('')

  const writable =
    assignment.status === 'pending' && cycle !== undefined && isReviewable(cycle.status)
  const ratings = collectRatings(draft, cycle)
  const missingComments = comments.trim() === ''

  function submitForm() {
    if (cycle === undefined) {
      return
    }
    submit.mutate({ assignmentId: assignment.id, ratings, comments: comments.trim() })
    setDraft({})
    setComments('')
  }

  return (
    <li className="border-line rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-ink-strong font-medium">{employeeName}</p>
          <p className="text-ink-muted text-sm">{cycle?.name ?? assignment.cycle_id}</p>
          {assignment.due_on ? (
            <p className="text-ink-muted text-xs">
              {t('growth.due', { date: formatDate(assignment.due_on) })}
            </p>
          ) : null}
          {assignment.skip_reason ? (
            <p className="text-ink-muted mt-1 text-xs italic">
              {t('growth.skippedBecause', { reason: assignment.skip_reason })}
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge
            tone={
              assignment.status === 'submitted'
                ? 'done'
                : assignment.status === 'skipped'
                  ? 'error'
                  : 'waiting'
            }
            labelKey={`growth.assignmentStatus.${assignment.status}`}
          />
        </div>
      </div>

      {assignment.status === 'submitted' ? (
        <ul className="text-ink-muted mt-2 flex flex-wrap gap-3 text-xs">
          {Object.entries(assignment.ratings).map(([dimension, value]) => (
            <li key={dimension}>
              <span className="text-ink-strong">{dimension}</span> {value}
            </li>
          ))}
        </ul>
      ) : null}

      {writable && cycle ? (
        <form
          className="mt-3 flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            submitForm()
          }}
        >
          <fieldset className="flex flex-col gap-2">
            <legend className="text-ink-strong text-sm font-medium">
              {t('growth.ratingsLegend', {
                min: cycle.rating_scale_min,
                max: cycle.rating_scale_max,
              })}
            </legend>
            <ul className="flex flex-col gap-1">
              {REVIEW_DIMENSIONS.map((dimension) => (
                <li key={dimension} className="flex items-center gap-2">
                  <label
                    className="text-ink-muted text-xs"
                    htmlFor={`rating-${assignment.id}-${dimension}`}
                  >
                    {dimension}
                  </label>
                  <input
                    id={`rating-${assignment.id}-${dimension}`}
                    className="border-line w-24 rounded border px-2 py-1 text-sm"
                    type="number"
                    inputMode="decimal"
                    min={cycle.rating_scale_min}
                    max={cycle.rating_scale_max}
                    step={0.5}
                    value={draft[dimension] ?? ''}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, [dimension]: event.target.value }))
                    }
                  />
                </li>
              ))}
            </ul>
          </fieldset>
          <textarea
            className="border-line w-full rounded border p-2 text-sm"
            rows={3}
            aria-label={t('growth.commentsLabel')}
            placeholder={t('growth.commentsPlaceholder')}
            value={comments}
            onChange={(event) => setComments(event.target.value)}
          />
          <Button
            type="submit"
            size="sm"
            className="self-start"
            /**
             * `submit_assignment` refuses an empty rating map and a blank comment, so
             * the button is disabled until there is at least one rating and something
             * written. A server error the user could have avoided is still an error.
             */
            disabled={submit.isPending || Object.keys(ratings).length === 0 || missingComments}
          >
            {t('growth.writeReview')}
          </Button>
          {submit.isError ? (
            <p role="alert" className="text-error text-xs">
              {t('growth.submitFailed')}
            </p>
          ) : null}
        </form>
      ) : null}
    </li>
  )
}
