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
  isDraftable,
  isOpenCycle,
  isSummaryWindow,
  REVIEW_DIMENSIONS,
  collectRatings,
  employeesWithSubmittedForms,
  isProgressable,
  isReviewable,
  progressPercent,
  summariesByEmployee,
  type AssignmentView,
  type CycleView,
  type GoalView,
  type SummaryView,
} from './growthApi'
import {
  useCycleAssignments,
  useDraftSummary,
  useFinalizeSummary,
  useGrowthCycles,
  useGrowthGoals,
  useMyAssignments,
  useOverdueGoals,
  useRecordGoalProgress,
  useRunReminders,
  useSubmitAssignment,
  useSummaries,
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

  return (
    <div className="flex flex-col gap-6">
      <section aria-labelledby="growth-queue" className="flex flex-col gap-3">
        <h2 id="growth-queue" className="text-ink-strong text-lg font-medium">
          {t('growth.assignmentsTitle', { count: list.length })}
        </h2>
        {list.length === 0 ? (
          <EmptyState title={t('growth.assignmentsEmpty')} />
        ) : (
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
        )}
      </section>
      {/**
       * Drafting summaries and running reminders do not depend on the viewer having
       * assignments of their own. These used to sit inside the non-empty branch, so a
       * fresh install -- exactly when a first review cycle is being set up -- showed
       * neither.
       */}
      <SummarySection />
      <ReminderPanel />
    </div>
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

/**
 * Summary editor: the drafts written from submitted forms, and the human act of making
 * one final.
 *
 * Finalising is human-only in the service and the final text is what gets shared, so this
 * never finalises implicitly: a person reads the draft, edits it, and commits.
 * `pending_review` is the only status that offers the button -- re-finalising would
 * overwrite text somebody may already have given the employee.
 */
export function SummarySection() {
  const { t } = useTranslation()
  const cycles = useGrowthCycles()
  const [chosen, setChosen] = useState<string | null>(null)
  const assignments = useCycleAssignments(chosen)
  const summaries = useSummaries(chosen)
  const employees = useEmployees()
  const draft = useDraftSummary()
  const finalize = useFinalizeSummary()

  const names = useMemo(() => {
    const map = new Map<string, string>()
    for (const employee of employees.data ?? []) {
      map.set(employee.id, employee.full_name)
    }
    return map
  }, [employees.data])

  const writeableCycles = (cycles.data ?? []).filter((item) => isSummaryWindow(item.status))
  const selected = chosen ?? writeableCycles[0]?.id ?? null

  if (writeableCycles.length === 0) {
    return (
      <section aria-labelledby="growth-summaries" className="flex flex-col gap-3">
        <h2 id="growth-summaries" className="text-ink-strong text-lg font-medium">
          {t('growth.summariesTitle')}
        </h2>
        <EmptyState title={t('growth.summariesEmpty')} />
      </section>
    )
  }

  const submitted = employeesWithSubmittedForms(assignments.data ?? [])
  const byEmployee = summariesByEmployee(summaries.data ?? [])

  return (
    <section aria-labelledby="growth-summaries" className="flex flex-col gap-3">
      <h2 id="growth-summaries" className="text-ink-strong text-lg font-medium">
        {t('growth.summariesTitle')}
      </h2>
      <p className="text-ink-muted text-xs">{t('growth.summariesHint')}</p>

      <label className="text-ink-muted text-xs" htmlFor="growth-summary-cycle">
        {t('growth.cycleField')}
      </label>
      <select
        id="growth-summary-cycle"
        className="border-line w-full max-w-sm rounded border p-2 text-sm"
        value={selected ?? ''}
        onChange={(event) => setChosen(event.target.value)}
      >
        {writeableCycles.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </select>

      {assignments.isLoading || summaries.isLoading ? (
        <Skeleton className="h-24" />
      ) : submitted.length === 0 ? (
        <EmptyState title={t('growth.noSubmittedForms')} />
      ) : (
        <ul className="flex flex-col gap-3">
          {submitted.map((employeeId) => (
            <SummaryRow
              key={employeeId}
              employeeName={names.get(employeeId) ?? employeeId}
              summary={byEmployee.get(employeeId)}
              draftBusy={draft.isPending}
              finalizeBusy={finalize.isPending}
              onDraft={(text) =>
                selected !== null &&
                draft.mutate({
                  cycle_id: selected,
                  employee_id: employeeId,
                  draft_text: text,
                })
              }
              onFinalize={(summaryId, text) => finalize.mutate({ summaryId, finalText: text })}
            />
          ))}
        </ul>
      )}

      {draft.isError || finalize.isError ? (
        <p role="alert" className="text-error text-sm">
          {t('growth.summaryActionFailed')}
        </p>
      ) : null}
    </section>
  )
}

function SummaryRow({
  employeeName,
  summary,
  draftBusy,
  finalizeBusy,
  onDraft,
  onFinalize,
}: {
  employeeName: string
  summary: SummaryView | undefined
  draftBusy: boolean
  finalizeBusy: boolean
  onDraft: (text: string) => void
  onFinalize: (summaryId: string, text: string) => void
}) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  /**
   * The textarea starts empty rather than pre-filled with the agent draft: the final text
   * is what gets shared, and a summary nobody wrote is not the reviewer's words.
   */
  const [text, setText] = useState('')
  const blank = text.trim() === ''
  const canFinalize = summary !== undefined && isDraftable(summary.status)

  return (
    <li className="border-line rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-ink-strong font-medium">{employeeName}</p>
        <StatusBadge
          tone={summary?.status === 'finalized' ? 'done' : 'waiting'}
          labelKey={summary ? `growth.summaryStatus.${summary.status}` : 'growth.summaryMissing'}
        />
      </div>

      {summary ? (
        <>
          <p className="text-ink-muted mt-2 text-xs font-medium">{t('growth.agentDraftLabel')}</p>
          <p className="border-line mt-1 rounded border border-dashed p-2 text-sm whitespace-pre-wrap">
            {summary.agent_draft}
          </p>
        </>
      ) : null}

      {summary?.status === 'finalized' ? (
        <>
          <p className="text-ink-muted mt-2 text-xs font-medium">{t('growth.finalLabel')}</p>
          <p className="mt-1 text-sm whitespace-pre-wrap">{summary.final_text}</p>
          {summary.finalized_by ? (
            <p className="text-ink-muted mt-1 text-xs">
              {t('growth.finalizedBy', { who: summary.finalized_by })}
            </p>
          ) : null}
        </>
      ) : null}

      {canFinalize && !editing ? (
        <Button className="mt-2" size="sm" disabled={finalizeBusy} onClick={() => setEditing(true)}>
          {t('growth.finalizeAction')}
        </Button>
      ) : null}

      {canFinalize && editing && summary ? (
        <div className="mt-2 flex flex-col gap-2">
          <label className="text-ink-muted text-xs" htmlFor={`final-${summary.id}`}>
            {t('growth.finalTextLabel')}
          </label>
          <textarea
            id={`final-${summary.id}`}
            className="border-line w-full rounded border p-2 text-sm"
            rows={5}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              disabled={finalizeBusy || blank}
              onClick={() => onFinalize(summary.id, text.trim())}
            >
              {t('growth.confirmFinalize')}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setEditing(false)
                setText('')
              }}
            >
              {t('growth.cancel')}
            </Button>
            {blank ? (
              <p className="text-ink-muted text-xs">{t('growth.finalTextRequired')}</p>
            ) : null}
          </div>
        </div>
      ) : null}

      {summary === undefined ? (
        <div className="mt-2 flex flex-col gap-2">
          <label className="text-ink-muted text-xs" htmlFor={`draft-${employeeName}`}>
            {t('growth.draftTextLabel')}
          </label>
          <textarea
            id={`draft-${employeeName}`}
            className="border-line w-full rounded border p-2 text-sm"
            rows={4}
            placeholder={t('growth.draftTextPlaceholder')}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <Button size="sm" disabled={draftBusy || blank} onClick={() => onDraft(text.trim())}>
            {t('growth.saveDraft')}
          </Button>
        </div>
      ) : null}
    </li>
  )
}

/**
 * Reminder runner: create the tasks for forms and summaries that are coming due.
 *
 * The server deduplicates, so this is safe to press on any schedule. The list below is
 * what the press *created*, not everything outstanding -- an existing open task is left
 * alone, and saying otherwise would make "2 reminders" read as "only 2 things are due".
 */
export function ReminderPanel() {
  const { t } = useTranslation()
  const run = useRunReminders()
  const [windowDays, setWindowDays] = useState(3)

  const created = run.data ?? []

  return (
    <section aria-labelledby="growth-reminders" className="flex flex-col gap-3">
      <h2 id="growth-reminders" className="text-ink-strong text-lg font-medium">
        {t('growth.remindersTitle')}
      </h2>
      <p className="text-ink-muted text-xs">{t('growth.remindersHint')}</p>

      <div className="flex flex-wrap items-end gap-3">
        <span className="flex flex-col gap-1">
          <label className="text-ink-muted text-xs" htmlFor="reminder-window">
            {t('growth.reminderWindow')}
          </label>
          {/* 0-60 is what `RemindersRun.window_days` accepts; the input says so. */}
          <input
            id="reminder-window"
            className="border-line w-20 rounded border px-2 py-1 text-sm"
            type="number"
            min={0}
            max={60}
            value={windowDays}
            onChange={(event) => setWindowDays(Number(event.target.value))}
          />
        </span>
        <Button
          size="sm"
          disabled={run.isPending || Number.isNaN(windowDays)}
          onClick={() => run.mutate({ window_days: windowDays })}
        >
          {t('growth.runReminders')}
        </Button>
      </div>

      {run.isSuccess ? (
        created.length === 0 ? (
          <p className="text-ink-muted text-sm">{t('growth.noNewReminders')}</p>
        ) : (
          <>
            <p className="text-ink-strong text-sm">
              {t('growth.remindersCreated', { count: created.length })}
            </p>
            <ul className="flex flex-col gap-1">
              {created.map((reminder) => (
                <li key={reminder.task_id} className="border-line rounded border p-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-ink-strong text-sm">{reminder.detail}</p>
                    <StatusBadge tone="waiting" labelKey={`growth.reminderKind.${reminder.kind}`} />
                  </div>
                </li>
              ))}
            </ul>
          </>
        )
      ) : null}

      {run.isError ? (
        <p role="alert" className="text-error text-sm">
          {t('growth.remindersFailed')}
        </p>
      ) : null}
    </section>
  )
}
