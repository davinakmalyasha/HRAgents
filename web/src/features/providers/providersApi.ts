import type { components } from '@/api/schema'

import { api } from '@/lib/api'
import { fetchAllPages } from '@/lib/pagination'

export type ProviderStatusView = components['schemas']['ProviderStatusView']

/**
 * A non-2xx answer from the provider surface.
 *
 * "No providers" and "you may not see them" are different statements, so the
 * error keeps the status instead of degrading to an empty list.
 */
export class ProviderRequestError extends Error {
  constructor(readonly status: number) {
    super(`provider request failed with status ${status}`)
    this.name = 'ProviderRequestError'
  }
}

/** What each capability is wired to, and whether it answers. */
export async function listProviders(): Promise<ProviderStatusView[]> {
  return fetchAllPages(async (limit, offset) => {
    const { data, response } = await api.GET('/v1/providers', {
      params: { query: { limit, offset } },
    })
    if (!response.ok) throw new ProviderRequestError(response.status)
    return data ?? undefined
  })
}
