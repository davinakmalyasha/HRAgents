import { api } from '@/lib/api'
import { fetchAllPages } from '@/lib/pagination'
import type { components } from '@/api/schema'

export type DeadLetterView = components['schemas']['DeadLetterView']
export type UsageSummary = components['schemas']['UsageSummary']

/**
 * A non-2xx answer from an ops endpoint.
 *
 * Unlike the workspace reads, an error here must not degrade to an empty list:
 * "no dead letters" and "you are not allowed to see them" are very different
 * statements to put on a screen.
 */
export class OpsRequestError extends Error {
  constructor(readonly status: number) {
    super(`ops request failed with status ${status}`)
    this.name = 'OpsRequestError'
  }
}

/** Tokens consumed by provider and model, for the operator's cost view. */
export async function getUsage(days = 30): Promise<UsageSummary> {
  const { data, response } = await api.GET('/v1/ops/usage', {
    params: { query: { days } },
  })
  if (!response.ok) throw new OpsRequestError(response.status)
  if (data === undefined) throw new OpsRequestError(response.status)
  return data
}

export async function listDeadLetters(): Promise<DeadLetterView[]> {
  return fetchAllPages(async (limit, offset) => {
    const { data, response } = await api.GET('/v1/ops/dead-letters', {
      params: { query: { limit, offset } },
    })
    if (!response.ok) throw new OpsRequestError(response.status)
    return data ?? undefined
  })
}

export async function requeueDeadLetter(messageId: string, reason: string): Promise<void> {
  const { response } = await api.POST('/v1/ops/dead-letters/{message_id}/requeue', {
    params: { path: { message_id: messageId } },
    body: { reason },
  })
  if (!response.ok) throw new OpsRequestError(response.status)
}
