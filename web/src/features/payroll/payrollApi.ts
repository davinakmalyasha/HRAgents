import type { components } from '@/api/schema'

import { api } from '@/lib/api'

export type RunView = components['schemas']['RunView']
export type LineView = components['schemas']['LineView']
export type AnomalyView = components['schemas']['AnomalyView']
export type TotalsView = components['schemas']['TotalsView']
export type RunStatus = components['schemas']['PayrollRunStatus']
export type RunKind = components['schemas']['PayrollRunKind']
export type RunCreate = components['schemas']['RunCreate']

/**
 * Rupiah, without decimals.
 *
 * The server sends exact two-place decimals, so the digits a person reconciles against a
 * bank transfer are the ones before the separator. Truncating to whole rupiah rather than
 * rounding keeps the displayed figure equal to what will be paid, and grouping keeps a
 * seven-digit amount readable on a phone.
 */
const RUPIAH = new Intl.NumberFormat('id-ID', {
  style: 'currency',
  currency: 'IDR',
  maximumFractionDigits: 0,
})

export function rupiah(amount: number): string {
  return RUPIAH.format(amount)
}

/** Plain grouped digits, for table cells where the currency symbol repeats per row. */
export function amount(amountValue: number): string {
  return new Intl.NumberFormat('id-ID', { maximumFractionDigits: 0 }).format(amountValue)
}

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  draft: 'Draft',
  assembling: 'Assembling inputs',
  ready_for_review: 'Ready for review',
  pending_signoff: 'Awaiting sign-off',
  approved: 'Signed off',
  rejected: 'Rejected by approver',
  exported: 'Exported',
  cancelled: 'Cancelled',
}

export const RUN_KIND_LABELS: Record<RunKind, string> = {
  monthly: 'Monthly payroll',
  thr: 'Termination (THR)',
  adjustment: 'Adjustment',
  final: 'Final settlement',
}

/** Statuses a run can be computed from. */
export function isComputable(status: RunStatus): boolean {
  return status === 'draft' || status === 'assembling'
}

/**
 * Statuses a run can be submitted for sign-off from.
 *
 * Excludes anything already decided or exported: a second sign-off on an approved run
 * would produce a second transfer instruction for the same period.
 */
export function isSubmittable(status: RunStatus): boolean {
  return status === 'ready_for_review'
}

/** Whether a reviewer may download the review packet. */
export function isExportable(status: RunStatus): boolean {
  return status === 'approved'
}

/**
 * A run may only be cancelled before it is approved or exported.
 *
 * Mirrors `PayrollService.cancel_run`, which refuses both. Offering the button anyway
 * would produce a 409 the user cannot act on.
 */
export function isCancellable(status: RunStatus): boolean {
  return !['approved', 'exported', 'cancelled'].includes(status)
}

/**
 * Whether sign-off is blocked, and why.
 *
 * `RunView.blocking_count` is the server's own count of ERROR-severity anomalies, so the
 * UI does not have to re-derive it and cannot disagree with the gate that enforces it.
 */
export function blocksSignoff(run: RunView): boolean {
  return run.blocking_count > 0
}

/** The anomalies a person must resolve before this run can be signed off. */
export function blockingAnomalies(run: RunView): AnomalyView[] {
  return run.anomalies.filter((anomaly) => anomaly.severity === 'error')
}

export function advisoryAnomalies(run: RunView): AnomalyView[] {
  return run.anomalies.filter((anomaly) => anomaly.severity !== 'error')
}

/** Sum the employee-facing deductions, which the line fields report separately. */
export function deductionBreakdown(line: LineView): {
  bpjs: number
  tax: number
  other: number
} {
  return {
    bpjs: line.bpjs_kesehatan_employee + line.bpjs_jht_employee + line.bpjs_jp_employee,
    tax: line.pph21,
    other: line.other_deductions,
  }
}

export async function listRuns(): Promise<RunView[]> {
  const { data } = await api.GET('/v1/payroll/runs')
  return data ?? []
}

export async function getRun(runId: string): Promise<RunView | null> {
  const { data } = await api.GET('/v1/payroll/runs/{run_id}', {
    params: { path: { run_id: runId } },
  })
  return data ?? null
}

export async function createRun(body: RunCreate): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/payroll/runs', { body })
  return { status: response.status }
}

export async function computeRun(runId: string): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/payroll/runs/{run_id}/compute', {
    params: { path: { run_id: runId } },
    body: {},
  })
  return { status: response.status }
}

export async function submitRun(runId: string): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/payroll/runs/{run_id}/submit', {
    params: { path: { run_id: runId } },
    body: {},
  })
  return { status: response.status }
}

export async function cancelRun(runId: string, reason: string): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/payroll/runs/{run_id}/cancel', {
    params: { path: { run_id: runId } },
    body: { reason },
  })
  return { status: response.status }
}

/**
 * The URL of the XLSX review packet.
 *
 * A plain link rather than a fetch: the endpoint returns a file, and fetching it would put
 * the bytes through the JSON client only to unwrap them again.
 */
export function packetUrl(runId: string): string {
  return `/v1/payroll/runs/${runId}/packet.xlsx`
}
