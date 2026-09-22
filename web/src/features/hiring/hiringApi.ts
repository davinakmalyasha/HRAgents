import { api } from '@/lib/api'
import type { components } from '@/api/schema'

export type AuditReceipt = components['schemas']['AuditReceipt']
export type OverrideCreate = components['schemas']['OverrideCreate']
export type PolicyDecision = components['schemas']['PolicyDecision']

export interface OverrideResult {
  status: number
  receipt?: AuditReceipt
}

export async function recordOverride(
  evaluationId: string,
  body: OverrideCreate,
): Promise<OverrideResult> {
  const { data, response } = await api.POST('/v1/evaluations/{evaluation_id}/overrides', {
    params: { path: { evaluation_id: evaluationId } },
    body,
  })
  return { status: response.status, receipt: data }
}

export interface StageMoveResult {
  status: number
  detail?: string
}

export async function moveStage(
  applicationId: string,
  body: {
    target: components['schemas']['ApplicationStatus']
    by: string
    reason: string
  },
): Promise<StageMoveResult> {
  const { error, response } = await api.POST('/v1/applications/{application_id}/stage', {
    params: { path: { application_id: applicationId } },
    body,
  })
  const problem = error as { title?: string } | null | undefined
  return { status: response.status, detail: problem?.title }
}
