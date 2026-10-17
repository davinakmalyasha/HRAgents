import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge } from '@/components/status/StatusBadge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate } from '@/lib/dates'

import type { CalendarEntryCategory, CalendarItemView } from './complianceApi'
import { groupByDay, monthWindow, shiftMonth } from './calendar'
import { useCalendar, useCreateCalendarEntry, useRemoveCalendarEntry } from './useCompliance'

const CATEGORIES: readonly CalendarEntryCategory[] = [
  'tax',
  'bpjs',
  'labour',
  'thr',
  'reporting',
  'other',
]

/**
 * The compliance calendar: what is due this month, from two sources.
 *
 * Deadlines the system computes itself deep-link into the records workspace,
 * where the fix lives; operator dates carry their source note and can be
 * removed with a reason, because both the date and its removal outlive the
 * person who typed them.
 */
export function CalendarBoard() {
  const { t, i18n } = useTranslation()
  const [anchor, setAnchor] = useState(() => {
    const now = new Date()
    return { year: now.getFullYear(), month: now.getMonth() + 1 }
  })
  const [adding, setAdding] = useState(false)
  const { start, end } = monthWindow(anchor.year, anchor.month)
  const calendar = useCalendar(start, end)

  const days = groupByDay(calendar.data ?? [])
  const label = new Intl.DateTimeFormat(i18n.language, { month: 'long', year: 'numeric' }).format(
    new Date(Date.UTC(anchor.year, anchor.month - 1, 1)),
  )

  return (
    <section aria-labelledby="compliance-calendar" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="compliance-calendar" className="text-ink-strong text-base font-medium">
          {t('compliance.calendar.title')}
        </h3>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            aria-label={t('compliance.calendar.previousMonth')}
            onClick={() => setAnchor(shiftMonth(anchor.year, anchor.month, -1))}
          >
            ‹
          </Button>
          <span className="text-ink-strong text-sm font-medium">{label}</span>
          <Button
            size="sm"
            variant="outline"
            aria-label={t('compliance.calendar.nextMonth')}
            onClick={() => setAnchor(shiftMonth(anchor.year, anchor.month, 1))}
          >
            ›
          </Button>
          <Button size="sm" variant="outline" onClick={() => setAdding((open) => !open)}>
            {t('compliance.calendar.addDate')}
          </Button>
        </div>
      </div>

      {adding ? <AddEntryForm onDone={() => setAdding(false)} /> : null}

      {calendar.isLoading ? (
        <Skeleton className="h-24" />
      ) : days.length === 0 ? (
        <EmptyState title={t('compliance.calendar.empty')} />
      ) : (
        <ul className="flex flex-col gap-3">
          {days.map((day) => (
            <li key={day.dueOn} className="flex flex-col gap-1">
              <p className="text-ink-muted text-2xs font-medium">{formatDate(day.dueOn)}</p>
              <ul className="flex flex-col gap-2">
                {day.items.map((item) => (
                  <CalendarRow key={rowKey(item)} item={item} />
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function rowKey(item: CalendarItemView): string {
  if (item.entry_id) return `entry:${item.entry_id}`
  return `deadline:${item.kind}:${item.subject_id ?? ''}:${item.detail}`
}

function CalendarRow({ item }: { item: CalendarItemView }) {
  const { t } = useTranslation()
  const [removing, setRemoving] = useState(false)
  const [reason, setReason] = useState('')
  const remove = useRemoveCalendarEntry()
  const isEntry = item.source === 'entry'

  return (
    <li className="border-line rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          {isEntry ? (
            <p className="text-ink-strong text-sm font-medium">{item.title}</p>
          ) : (
            <Link to="/w/records" className="text-ink-strong text-sm font-medium hover:underline">
              {t(`compliance.calendar.kinds.${item.kind}`)}
              {item.subject_name ? ` · ${item.subject_name}` : ''}
              {item.detail ? ` · ${item.detail}` : ''}
            </Link>
          )}
          {isEntry ? (
            <>
              <p className="text-ink-muted text-xs">
                {t(`compliance.calendar.categories.${item.category ?? 'other'}`)}
              </p>
              {item.source_note ? (
                <p className="text-ink-muted text-xs">
                  {t('compliance.calendar.source', { note: item.source_note })}
                </p>
              ) : null}
            </>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {item.overdue ? (
            <StatusBadge tone="error" labelKey="compliance.calendar.overdue" />
          ) : null}
          {isEntry && !removing ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setRemoving(true)
                setReason('')
              }}
            >
              {t('compliance.calendar.remove')}
            </Button>
          ) : null}
        </div>
      </div>

      {isEntry && removing ? (
        <div className="mt-2 flex flex-col gap-2">
          <label className="text-ink-muted text-xs" htmlFor={`calendar-remove-${item.entry_id}`}>
            {t('compliance.calendar.removeReasonLabel')}
          </label>
          <textarea
            id={`calendar-remove-${item.entry_id}`}
            className="border-line w-full rounded border p-2 text-sm"
            rows={2}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="destructive"
              disabled={remove.isPending || reason.trim() === ''}
              onClick={() =>
                remove.mutate(
                  { entryId: item.entry_id ?? '', reason: reason.trim() },
                  { onSuccess: () => setRemoving(false) },
                )
              }
            >
              {t('compliance.calendar.confirmRemove')}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setRemoving(false)}>
              {t('compliance.calendar.cancel')}
            </Button>
          </div>
        </div>
      ) : null}
    </li>
  )
}

function AddEntryForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const create = useCreateCalendarEntry()
  const [title, setTitle] = useState('')
  const [dueOn, setDueOn] = useState('')
  const [category, setCategory] = useState<CalendarEntryCategory>('tax')
  const [sourceNote, setSourceNote] = useState('')
  const [notes, setNotes] = useState('')
  const valid = title.trim() !== '' && dueOn !== '' && sourceNote.trim() !== ''

  return (
    <form
      className="border-line flex flex-col gap-3 rounded-lg border p-3"
      onSubmit={(event) => {
        event.preventDefault()
        if (!valid) return
        create.mutate(
          {
            title: title.trim(),
            due_on: dueOn,
            category,
            jurisdiction: 'ID',
            source_note: sourceNote.trim(),
            notes: notes.trim() === '' ? null : notes.trim(),
          },
          { onSuccess: () => onDone() },
        )
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-ink-muted text-xs" htmlFor="calendar-entry-title">
          {t('compliance.calendar.form.title')}
          <Input
            id="calendar-entry-title"
            className="mt-1"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label className="text-ink-muted text-xs" htmlFor="calendar-entry-due">
          {t('compliance.calendar.form.dueOn')}
          <Input
            id="calendar-entry-due"
            className="mt-1"
            type="date"
            value={dueOn}
            onChange={(event) => setDueOn(event.target.value)}
          />
        </label>
        <label className="text-ink-muted text-xs" htmlFor="calendar-entry-category">
          {t('compliance.calendar.form.category')}
          <select
            id="calendar-entry-category"
            className="border-line mt-1 w-full rounded border p-2 text-sm"
            value={category}
            onChange={(event) => setCategory(event.target.value as CalendarEntryCategory)}
          >
            {CATEGORIES.map((value) => (
              <option key={value} value={value}>
                {t(`compliance.calendar.categories.${value}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-ink-muted text-xs" htmlFor="calendar-entry-source">
          {t('compliance.calendar.form.sourceNote')}
          <Input
            id="calendar-entry-source"
            className="mt-1"
            placeholder={t('compliance.calendar.form.sourceNotePlaceholder')}
            value={sourceNote}
            onChange={(event) => setSourceNote(event.target.value)}
          />
        </label>
      </div>
      <label className="text-ink-muted text-xs" htmlFor="calendar-entry-notes">
        {t('compliance.calendar.form.notes')}
        <Input
          id="calendar-entry-notes"
          className="mt-1"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
        />
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" type="submit" disabled={!valid || create.isPending}>
          {t('compliance.calendar.form.submit')}
        </Button>
        <Button size="sm" type="button" variant="outline" onClick={onDone}>
          {t('compliance.calendar.cancel')}
        </Button>
      </div>
    </form>
  )
}
