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
