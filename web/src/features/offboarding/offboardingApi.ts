import type { components } from '@/api/schema'

import { api } from '@/lib/api'

export type PlanView = components['schemas']['hr_agents__api__offboarding_schemas__PlanView']
export type StepView = components['schemas']['hr_agents__api__offboarding_schemas__StepView']
export type TemplateView =
  components['schemas']['hr_agents__api__offboarding_schemas__TemplateView']
export type AssetView = components['schemas']['AssetView']
export type HandoverView = components['schemas']['HandoverView']
export type StepStatus = components['schemas']['StepStatus']
export type PlanCreate = components['schemas']['PlanCreate']
export type StepAction = components['schemas']['StepAction']
export type AssetCreate = components['schemas']['AssetCreate']

export const STEP_STATUS_LABELS: Record<StepStatus, string> = {
  pending: 'Pending',
  in_progress: 'In progress',
  blocked: 'Blocked',
  done: 'Done',
  waived: 'Waived',
}

/** Steps in a terminal state: done or waived. Mirrors `TERMINAL_STEP_STATUSES`. */
const TERMINAL: ReadonlySet<StepStatus> = new Set<StepStatus>(['done', 'waived'])

export function isTerminal(status: StepStatus): boolean {
  return TERMINAL.has(status)
}

/**
 * Required steps that are not finished -- what actually blocks leaving.
 *
 * A plan is complete when every *required* step is terminal; optional steps are tracked
 * but never block. This mirrors `OnboardingPlan.is_complete`, and conflating the two
 * would make an offboarding look blocked over an optional step nobody agreed to.
 */
export function outstandingRequiredSteps(plan: PlanView): StepView[] {
  return plan.steps.filter((step) => step.required && !isTerminal(step.status))
}

/**
 * Assets that still block clearance.
 *
 * Read from `blocks_clearance` rather than derived from `status`, because "returned",
 * "missing" and "written off" all clear an asset in different ways and only the server
 * knows which applies.
 */
export function blockingAssets(assets: AssetView[]): AssetView[] {
  return assets.filter((asset) => asset.blocks_clearance)
}

/**
 * Whether the plan can be finalised.
 *
 * Mirrors the server: required steps outstanding, or assets not cleared, both block. The
 * button is disabled with a reason rather than left to fail, because "finalise failed" is
 * not something a person can act on.
 */
export function finalisationBlockers(plan: PlanView, assets: AssetView[]): string[] {
  const blockers: string[] = []
  const steps = outstandingRequiredSteps(plan)
  if (steps.length > 0) {
    blockers.push('steps')
  }
  if (blockingAssets(assets).length > 0) {
    blockers.push('assets')
  }
  return blockers
}

export function canFinalise(plan: PlanView, assets: AssetView[]): boolean {
  return !plan.is_complete && finalisationBlockers(plan, assets).length === 0
}

export async function listTemplates(): Promise<TemplateView[]> {
  const { data } = await api.GET('/v1/offboarding/templates')
  return data ?? []
}

export async function defaultTemplate(): Promise<TemplateView | null> {
  const { data } = await api.GET('/v1/offboarding/templates/default')
  return data ?? null
}

/** Neither list endpoint is filterable; per-employee views use their own routes. */
export async function listPlans(): Promise<PlanView[]> {
  const { data } = await api.GET('/v1/offboarding/plans')
  return data ?? []
}

export async function listAssets(): Promise<AssetView[]> {
  const { data } = await api.GET('/v1/offboarding/assets')
  return data ?? []
}

export async function assetsForEmployee(employeeId: string): Promise<AssetView[]> {
  const { data } = await api.GET('/v1/offboarding/employees/{employee_id}/assets', {
    params: { path: { employee_id: employeeId } },
  })
  return data ?? []
}

export async function createPlan(body: PlanCreate): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/offboarding/plans', { body })
  return { status: response.status }
}

/**
 * Every step mutation returns the whole plan, so a caller never has to guess whether its
 * cached copy is stale.
 */
async function stepAction(
  path:
    | '/v1/offboarding/plans/{plan_id}/steps/{step_key}/complete'
    | '/v1/offboarding/plans/{plan_id}/steps/{step_key}/waive',
  planId: string,
  stepKey: string,
  body: StepAction,
): Promise<{ status: number }> {
  const { response } = await api.POST(path, {
    params: { path: { plan_id: planId, step_key: stepKey } },
    body,
  })
  return { status: response.status }
}

export function completeStep(
  planId: string,
  stepKey: string,
  body: StepAction,
): Promise<{ status: number }> {
  return stepAction(
    '/v1/offboarding/plans/{plan_id}/steps/{step_key}/complete',
    planId,
    stepKey,
    body,
  )
}

/**
 * Waive a step.
 *
 * Waiving is the one action here that can skip something the law requires, so the server
 * demands a reason. The UI sends the note and, when it is blank, the server's
 * `reason_required` answer becomes the prompt.
 */
export function waiveStep(
  planId: string,
  stepKey: string,
  body: StepAction,
): Promise<{ status: number }> {
  return stepAction('/v1/offboarding/plans/{plan_id}/steps/{step_key}/waive', planId, stepKey, body)
}

export async function finalisePlan(planId: string): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/offboarding/plans/{plan_id}/complete', {
    params: { path: { plan_id: planId } },
    body: {},
  })
  return { status: response.status }
}

export async function returnAsset(
  assetId: string,
  body: { note?: string | null } = {},
): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/offboarding/assets/{asset_id}/return', {
    params: { path: { asset_id: assetId } },
    body,
  })
  return { status: response.status }
}

/**
 * Declaring an asset missing is an admission of loss, so the server makes the note
 * mandatory. It is the one asset action that records a fact nobody witnessed.
 */
export async function markAssetMissing(
  assetId: string,
  body: { note: string },
): Promise<{ status: number }> {
  const { response } = await api.POST('/v1/offboarding/assets/{asset_id}/missing', {
    params: { path: { asset_id: assetId } },
    body,
  })
  return { status: response.status }
}
