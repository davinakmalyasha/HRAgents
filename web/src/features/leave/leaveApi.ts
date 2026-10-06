import type { components } from '@/api/schema'
import { api } from '@/lib/api'

export type LeaveType = components['schemas']['LeaveType']
export type RequestStatus = components['schemas']['hr_agents__models__leave__RequestStatus']
export type BalanceView = components['schemas']['BalanceView']
export type LeaveRequestView = components['schemas']['LeaveRequestView']
export type PolicyView = components['schemas']['hr_agents__api__leave_schemas__PolicyView']
export type BalanceAdjustRequest = components['schemas']['BalanceAdjust']

/**
 * A request plus the employee it belongs to, resolved once on the client.
 *
 * `LeaveRequestView` carries only an `employee_id`. A queue of "3 days, awaiting
 * approval" rows is unreadable, and every view that lists requests would otherwise repeat
 * the same join against the directory the records workspace already fetched.
 */
export interface LeaveRequestWithEmployee {
  request: LeaveRequestView
  employeeName: string
}

/**
 * Human labels for the leave types the API returns.
 *
 * Kept here rather than in the locales because they are also used as `title` attributes and
 * in `aria-label`s where an i18n key would show through on a missing translation -- the
 * same reason `problem.ts` treats a returned key as "absent".
 */
export const LEAVE_TYPE_LABELS: Record<LeaveType, string> = {
  annual: 'Annual',
  sick: 'Sick',
  personal: 'Personal',
  maternity: 'Maternity',
  paternity: 'Paternity',
  bereavement: 'Bereavement',
  marriage: 'Marriage',
  unpaid: 'Unpaid',
  other: 'Other',
}

export const REQUEST_STATUS_LABELS: Record<RequestStatus, string> = {
  draft: 'Draft',
  pending: 'Pending',
  approved: 'Approved',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
}

/** The calendar endpoint takes a single anchor date, not a range. */
export interface CalendarParams {
  onDate?: string
}

export async function listPolicies(): Promise<PolicyView[]> {
  const { data } = await api.GET('/v1/leave/policies')
  return data ?? []
}

export async function listRequests(
  params: {
    employeeId?: string
    status?: RequestStatus
  } = {},
): Promise<LeaveRequestView[]> {
  const { data } = await api.GET('/v1/leave', {
    params: {
      query: {
        employee_id: params.employeeId,
        status: params.status,
      },
    },
  })
  return data ?? []
}

export async function listCalendar(params: CalendarParams = {}) {
  const { data } = await api.GET('/v1/leave/calendar', {
    params: { query: { on_date: params.onDate } },
  })
  return data ?? []
}

export async function employeeBalances(employeeId: string): Promise<BalanceView[]> {
  const { data } = await api.GET('/v1/leave/balances/{employee_id}', {
    params: { path: { employee_id: employeeId } },
  })
  return data ?? []
}

/**
 * Attach names to requests.
 *
 * Sorted by start date so the queue reads as a calendar rather than an arbitrary id
 * order, and requests whose employee is missing from the directory keep the raw id rather
 * than being dropped -- a leave request that belongs to someone who left the directory is
 * still a request somebody has to decide.
 */
export function withEmployeeNames(
  requests: LeaveRequestView[],
  nameById: ReadonlyMap<string, string>,
): LeaveRequestWithEmployee[] {
  return [...requests]
    .sort((left, right) => left.start_date.localeCompare(right.start_date))
    .map((request) => ({
      request,
      employeeName: nameById.get(request.employee_id) ?? request.employee_id,
    }))
}

export function pendingFirst(rows: LeaveRequestWithEmployee[]): LeaveRequestWithEmployee[] {
  const rank = (status: RequestStatus): number => (status === 'pending' ? 0 : 1)
  return [...rows].sort(
    (left, right) =>
      rank(left.request.status) - rank(right.request.status) ||
      left.request.start_date.localeCompare(right.request.start_date),
  )
}

/** Working days still unaccounted for, as the API reports them. */
export function balanceTone(balance: BalanceView): 'ok' | 'warn' | 'over' {
  if (balance.available < 0) {
    return 'over'
  }
  return balance.available <= 1 ? 'warn' : 'ok'
}
