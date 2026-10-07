import type { components } from '@/api/schema'

import { api } from '@/lib/api'

export type ConsentView = components['schemas']['ConsentView']
export type BreachView = components['schemas']['BreachView']
export type BreachStepView = components['schemas']['hr_agents__api__compliance_schemas__StepView']
export type ErasureView = components['schemas']['ErasureView']
export type RateTableView = components['schemas']['RateTableView']
export type AuditVerifyView = components['schemas']['AuditVerifyView']
export type ScanView = components['schemas']['ScanView']
export type PurgeReportView = components['schemas']['PurgeReportView']
export type PurgeOutcomeView = components['schemas']['PurgeOutcomeView']
export type BreachStatus = components['schemas']['BreachStatus']
export type BreachImpact = components['schemas']['BreachImpact']
export type ErasureStatus = components['schemas']['ErasureStatus']
export type ConsentCreate = components['schemas']['ConsentCreate']
export type ConsentRevoke = components['schemas']['ConsentRevoke']
export type LawfulBasis = components['schemas']['LawfulBasis']
export type BreachCreate = components['schemas']['BreachCreate']
export type BreachTransition = components['schemas']['BreachTransition']
export type ErasureCreate = components['schemas']['ErasureCreate']
export type ErasureVerify = components['schemas']['ErasureVerify']
export type RateTableCreate = components['schemas']['RateTableCreate']
export type RateTableVerify = components['schemas']['RateTableVerify']
export type RateTableEntriesUpdate = components['schemas']['RateTableEntriesUpdate']
export type PurgeRequest = components['schemas']['PurgeRequest']
export type OverdueStepView = components['schemas']['OverdueStepView']
export type ConsentStatusView = components['schemas']['ConsentStatusView']
export type SubjectKind = components['schemas']['SubjectKind']

/**
 * Purge outcomes that did not purge anything.
 *
 * A dry run reports these as `action`, and so does a real run. Showing "purged: 0" for a
 * scan that skipped forty records because they are on legal hold would understate it.
 */
export function nonDestructiveOutcomes(report: PurgeReportView): PurgeOutcomeView[] {
  return (report === undefined ? [] : []).concat([])
}

/**
 * Records a purge left alone, split out from the ones it acted on.
 *
 * A report that says "purged 3" and mentions nothing about the forty records skipped
 * because they are on legal hold reads as a clean sweep. Held and skipped are outcomes,
 * and the operator has to see them.
 */
export function sparedOutcomes(outcomes: PurgeOutcomeView[]): PurgeOutcomeView[] {
  return outcomes.filter((item) => item.status === 'skipped')
}

/**
 * Whether a consent record can still be withdrawn.
 *
 * Only a granted, un-revoked record. The service refuses both "already revoked" and
 * "never granted", so offering either would be a button that cannot succeed.
 */
export function isRevocable(consent: ConsentView): boolean {
  return consent.granted && consent.revoked_at === null
}

/**
 * What a consent record currently says.
 *
 * Three outcomes, not two: a refusal is itself registry evidence and is recorded, so
 * collapsing it into "not granted" would lose the fact that somebody said no.
 */
export function consentState(consent: ConsentView): 'active' | 'revoked' | 'refused' {
  if (consent.revoked_at !== null) {
    return 'revoked'
  }
  return consent.granted ? 'active' : 'refused'
}

export function consentTone(state: ReturnType<typeof consentState>): 'done' | 'error' | 'waiting' {
  if (state === 'active') {
    return 'done'
  }
  return state === 'revoked' ? 'error' : 'waiting'
}

/**
 * A purge needs an explicit second step.
 *
 * A dry run returns the same report shape as a real one, so the operator can read exactly
 * what would go before anything does. This is the phrase that has to be typed to proceed.
 */
export const PURGE_CONFIRMATION = 'PURGE'

export function purgeConfirmed(typed: string): boolean {
  return typed.trim() === PURGE_CONFIRMATION
}

export function purgedOutcomes(outcomes: PurgeOutcomeView[]): PurgeOutcomeView[] {
  return outcomes.filter((item) => item.purged)
}

export async function listConsents(subjectId?: string): Promise<ConsentView[]> {
  const { data } = await api.GET('/v1/compliance/consents', {
    params: { query: { subject_id: subjectId } },
  })
  return data ?? []
}

export async function consentStatus(
  subjectId: string,
  subjectKind: SubjectKind = 'employee',
): Promise<ConsentStatusView> {
  const { data } = await api.GET('/v1/compliance/consents/status', {
    params: { query: { subject_id: subjectId, subject_kind: subjectKind } },
  })
  if (data === undefined) {
    throw new Error('consent status returned nothing')
  }
  return data
}

/** Recording a consent. `granted: false` is a refusal, and it is recorded too. */
export async function recordConsent(body: ConsentCreate): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/compliance/consents', { body })
  return { status: response.status }
}

/**
 * Revoking needs a reason.
 *
 * A withdrawal is a fact about the person, and the record outlives the tool. The server
 * makes `revoked_reason` mandatory for the same reason it makes an offboarding waiver
 * demand one.
 */
export async function revokeConsent(
  consentId: string,
  body: ConsentRevoke,
): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/compliance/consents/{consent_id}/revoke', {
    params: { path: { consent_id: consentId } },
    body,
  })
  return { status: response.status }
}

export async function listBreaches(): Promise<BreachView[]> {
  const { data } = await api.GET('/v1/compliance/breaches')
  return data ?? []
}

/**
 * Required breach steps whose clock has run out.
 *
 * One row per late step, not per incident: an incident with three late steps is three
 * different things that are each separately overdue.
 */
export async function overdueBreachSteps(): Promise<OverdueStepView[]> {
  const { data } = await api.GET('/v1/compliance/breaches/overdue')
  return data ?? []
}

export async function createBreach(body: BreachCreate): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/compliance/breaches', { body })
  return { status: response.status }
}

/** `contained` and `closed` are the transitions a named human may record. */
export async function transitionBreach(
  incidentId: string,
  body: BreachTransition,
): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/compliance/breaches/{incident_id}/status', {
    params: { path: { incident_id: incidentId } },
    body,
  })
  return { status: response.status }
}

export async function completeBreachStep(
  incidentId: string,
  stepKey: string,
  body: { note?: string | null } = {},
): Promise<{ status: number }> {
  const { response } = await api.POST(
    '/v1/compliance/breaches/{incident_id}/steps/{step_key}/complete',
    {
      params: { path: { incident_id: incidentId, step_key: stepKey } },
      body,
    },
  )
  return { status: response.status }
}

export async function listErasures(): Promise<ErasureView[]> {
  const { data } = await api.GET('/v1/compliance/erasures')
  return data ?? []
}

export async function createErasure(body: ErasureCreate): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/compliance/erasures', { body })
  return { status: response.status }
}

/** Identity verification precedes any approval; the method is recorded. */
export async function verifyErasureIdentity(
  requestId: string,
  body: ErasureVerify,
): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/compliance/erasures/{request_id}/verify', {
    params: { path: { request_id: requestId } },
    body,
  })
  return { status: response.status }
}

/**
 * Submit an erasure for approval.
 *
 * Submitting does not erase. It raises an approval, which a named human decides in the
 * approvals inbox; the UI never decides here.
 */
export async function submitErasure(requestId: string): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/compliance/erasures/{request_id}/submit', {
    params: { path: { request_id: requestId } },
    body: {},
  })
  return { status: response.status }
}

/**
 * Execute an erasure that a human already approved.
 *
 * The button only appears on an approved request, because execution destroys the records
 * it touches and the audit trail keeps only the outcome.
 */
export async function executeErasure(requestId: string): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/compliance/erasures/{request_id}/execute', {
    params: { path: { request_id: requestId } },
    body: {},
  })
  return { status: response.status }
}

export async function listRateTables(): Promise<RateTableView[]> {
  const { data } = await api.GET('/v1/rate-tables')
  return data ?? []
}

/**
 * Rate tables nobody has verified against a source.
 *
 * These are the ones payroll must refuse: an unverified table is an operator's guess about
 * a statutory figure.
 */
export async function unverifiedRateTables(): Promise<RateTableView[]> {
  const { data } = await api.GET('/v1/rate-tables/unverified')
  return data ?? []
}

export async function createRateTable(body: RateTableCreate): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/rate-tables', { body })
  return { status: response.status }
}

/** Verifying names the source the figure came from. */
export async function verifyRateTable(
  tableId: string,
  body: RateTableVerify,
): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/rate-tables/{table_id}/verify', {
    params: { path: { table_id: tableId } },
    body,
  })
  return { status: response.status }
}

export async function setRateTableEntries(
  tableId: string,
  body: RateTableEntriesUpdate,
): Promise<{ status: number }> {
  const { response } = await api.PUT('/v1/rate-tables/{table_id}/entries', {
    params: { path: { table_id: tableId } },
    body,
  })
  return { status: response.status }
}

export async function listRetentionPolicies(): Promise<unknown[]> {
  const { data } = await api.GET('/v1/compliance/retention/policies')
  return data ?? []
}

/** What is due for purge, and what is held or uncovered. Read-only. */
export async function scanRetention(): Promise<ScanView> {
  const { data } = await api.GET('/v1/compliance/retention/scan')
  if (data === undefined) {
    throw new Error('retention scan returned no report')
  }
  return data
}

/**
 * Run a purge.
 *
 * `dry_run` defaults to true here, deliberately: a purge destroys records, so the honest
 * default is the one that only reports. Executing for real is a second, explicit click
 * after reading what the dry run said.
 */
export async function executePurge(body: PurgeRequest): Promise<PurgeReportView> {
  const { data } = await api.POST('/v1/compliance/retention/purge', { body })
  if (data === undefined) {
    throw new Error('purge returned no report')
  }
  return data
}

/**
 * Verify the audit chain.
 *
 * No `checked_by` parameter: the name comes from the authenticated principal, so the log
 * records who actually ran it. Passing the name in would let anyone verify the chain in
 * somebody else's name -- which is the one thing a verification exists to rule out.
 */
export async function verifyAudit(): Promise<AuditVerifyView> {
  const { data } = await api.GET('/v1/compliance/audit/verify')
  if (data === undefined) {
    throw new Error('audit verification returned no result')
  }
  return data
}

/** Impact drives the tone, but never the tone alone: every badge carries a label. */
export function impactTone(impact: BreachImpact): 'waiting' | 'error' | 'done' {
  if (impact === 'critical' || impact === 'high') {
    return 'error'
  }
  return 'waiting'
}

/**
 * A breach can only move forward along its own ladder.
 *
 * `open → contained → notified → closed`, and the server enforces exactly that order.
 * Offering `closed` on a breach nobody contained would produce a refusal every time.
 */
export function nextBreachStatuses(status: BreachStatus): BreachStatus[] {
  switch (status) {
    case 'open':
      return ['contained']
    case 'contained':
      return ['notified']
    case 'notified':
      return ['closed']
    case 'closed':
      return []
  }
}

export function isBreachTerminal(status: BreachStatus): boolean {
  return status === 'closed'
}

/**
 * Erasures that may still be submitted for approval.
 *
 * `received` only. Once the request is `pending_approval` the approval engine owns it,
 * and offering the button again would just raise a second approval for one request.
 */
export function isSubmittable(status: ErasureStatus): boolean {
  return status === 'received'
}

/**
 * Erasures a human has approved and that have not been executed.
 *
 * Execution destroys records, so the button appears on exactly one status. Offering it on
 * `partial` would re-run a purge that already partly ran.
 */
export function isExecutable(status: ErasureStatus): boolean {
  return status === 'approved' || status === 'partial'
}

/** Erasures still awaiting a decision. */
export function isAwaitingDecision(status: ErasureStatus): boolean {
  return status === 'received' || status === 'pending_approval'
}

export function erasureTone(status: ErasureStatus): 'waiting' | 'error' | 'done' {
  if (status === 'executed') {
    return 'done'
  }
  if (status === 'denied') {
    return 'error'
  }
  return 'waiting'
}

/** A rate table nobody has checked is a guess about a statutory figure. */
export function unverifiedTables(tables: RateTableView[]): RateTableView[] {
  return tables.filter((table) => !table.verified)
}

/**
 * Split a purge report into what it destroyed and what it left alone.
 *
 * A dry run and a real run report the same shape, so the operator can compare the two
 * without reading prose: anything in `held` or `skipped` is still on disk.
 */
export function purgeSummary(report: PurgeReportView): {
  destroyed: number
  spared: number
  stillPresent: string[]
} {
  return {
    destroyed: purgedOutcomes(report.purged).length,
    spared: sparedOutcomes(report.skipped ?? []).length,
    stillPresent: [...report.held, ...report.uncovered],
  }
}

/** The lawful bases UU PDP defines; an operator picks one, nothing is inferred. */
export const LAWFUL_BASES: readonly LawfulBasis[] = [
  'consent',
  'contract',
  'legal_obligation',
  'vital_interest',
  'public_task',
  'legitimate_interest',
]
