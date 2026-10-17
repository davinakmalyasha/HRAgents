import type { CalendarItemView } from './complianceApi'

function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10)
}

/** First and last day of a 1-based month, as ISO dates for the API window. */
export function monthWindow(year: number, month: number): { start: string; end: string } {
  return {
    start: isoDay(new Date(Date.UTC(year, month - 1, 1))),
    end: isoDay(new Date(Date.UTC(year, month, 0))),
  }
}

/** Move a 1-based month by whole months, carrying the year either way. */
export function shiftMonth(
  year: number,
  month: number,
  delta: number,
): { year: number; month: number } {
  const index = year * 12 + (month - 1) + delta
  return { year: Math.floor(index / 12), month: (((index % 12) + 12) % 12) + 1 }
}

/** Items bucketed by due date, days ascending; the API order is kept within a day. */
export function groupByDay(
  items: CalendarItemView[],
): { dueOn: string; items: CalendarItemView[] }[] {
  const groups = new Map<string, CalendarItemView[]>()
  for (const item of items) {
    const bucket = groups.get(item.due_on) ?? []
    bucket.push(item)
    groups.set(item.due_on, bucket)
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([dueOn, entries]) => ({ dueOn, items: entries }))
}
