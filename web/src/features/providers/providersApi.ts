import type { components } from '@/api/schema'

import { api } from '@/lib/api'
import { fetchAllPages } from '@/lib/pagination'

export type ProviderStatusView = components['schemas']['ProviderStatusView']
export type ProviderCapability = ProviderStatusView['capability']
export type ProviderOptionsView = components['schemas']['ProviderOptionsView']
export type ProviderOption = components['schemas']['ProviderOption']
export type ProviderField = components['schemas']['ProviderField']
export type ProviderTestView = components['schemas']['ProviderTestView']
export type ProviderHealthStatus = components['schemas']['ProviderHealthStatus']

/**
 * A non-2xx answer from the provider surface.
 *
 * "No providers" and "you may not see them" are different statements, so the
 * error keeps the status instead of degrading to an empty list. Configuration
 * refusals carry the API's own detail when it has one.
 */
export class ProviderRequestError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string | null = null,
  ) {
    super(detail ?? `provider request failed with status ${status}`)
    this.name = 'ProviderRequestError'
  }
}

async function failure(response: Response): Promise<ProviderRequestError> {
  let detail: string | null = null
  try {
    const body: unknown = await response.json()
    if (body !== null && typeof body === 'object' && 'detail' in body) {
      const value = (body as { detail?: unknown }).detail
      detail = typeof value === 'string' ? value : null
    }
  } catch {
    // A refusal with no JSON body still carries its status.
  }
  return new ProviderRequestError(response.status, detail)
}

/** What each capability is wired to, and whether it answers. */
export async function listProviders(): Promise<ProviderStatusView[]> {
  return fetchAllPages(async (limit, offset) => {
    const { data, response } = await api.GET('/v1/providers', {
      params: { query: { limit, offset } },
    })
    if (!response.ok) throw await failure(response)
    return data ?? undefined
  })
}

/** The providers this capability accepts, with each one's form schema. */
export async function fetchProviderOptions(
  capability: ProviderCapability,
): Promise<ProviderOptionsView> {
  const { data, response } = await api.GET('/v1/providers/{capability}/options', {
    params: { path: { capability } },
  })
  if (!response.ok) throw await failure(response)
  if (data === undefined) throw new ProviderRequestError(response.status)
  return data
}

export async function saveProvider(
  capability: ProviderCapability,
  providerId: string,
  config: Record<string, unknown>,
): Promise<void> {
  const { response } = await api.PUT('/v1/providers/{capability}', {
    params: { path: { capability } },
    body: { provider_id: providerId, config },
  })
  if (!response.ok) throw await failure(response)
}

export async function clearProvider(capability: ProviderCapability): Promise<void> {
  const { response } = await api.DELETE('/v1/providers/{capability}', {
    params: { path: { capability } },
  })
  if (!response.ok) throw await failure(response)
}

export async function testProvider(
  capability: ProviderCapability,
  providerId: string,
  config: Record<string, unknown>,
): Promise<ProviderTestView> {
  const { data, response } = await api.POST('/v1/providers/{capability}/test', {
    params: { path: { capability } },
    body: { provider_id: providerId, config },
  })
  if (!response.ok) throw await failure(response)
  if (data === undefined) throw new ProviderRequestError(response.status)
  return data
}
