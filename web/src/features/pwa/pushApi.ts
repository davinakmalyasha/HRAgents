import type { components } from '@/api/schema'

import { api } from '@/lib/api'
import { fetchAllPages } from '@/lib/pagination'

export type PushConfigView = components['schemas']['PushConfigView']
export type PushSubscriptionView = components['schemas']['PushSubscriptionView']
export type PushTestView = components['schemas']['PushTestView']

export interface PushSubscriptionPayload {
  endpoint: string
  keys: { p256dh: string; auth: string }
  user_agent: string | null
}

export class PushRequestError extends Error {
  constructor(readonly status: number) {
    super(`push request failed with status ${status}`)
    this.name = 'PushRequestError'
  }
}

/** Whether push is available and the browser's application server key. */
export async function fetchPushConfig(): Promise<PushConfigView> {
  const { data, response } = await api.GET('/v1/push/config')
  if (!response.ok) throw new PushRequestError(response.status)
  if (data === undefined) throw new PushRequestError(response.status)
  return data
}

/** The caller's own endpoints. Nobody else's are addressable. */
export async function listPushSubscriptions(): Promise<PushSubscriptionView[]> {
  return fetchAllPages(async (limit, offset) => {
    const { data, response } = await api.GET('/v1/push/subscriptions', {
      params: { query: { limit, offset } },
    })
    if (!response.ok) throw new PushRequestError(response.status)
    return data ?? undefined
  })
}

export async function registerPushSubscription(
  payload: PushSubscriptionPayload,
): Promise<PushSubscriptionView> {
  const { data, response } = await api.POST('/v1/push/subscriptions', { body: payload })
  if (!response.ok) throw new PushRequestError(response.status)
  if (data === undefined) throw new PushRequestError(response.status)
  return data
}

export async function removePushSubscription(id: string): Promise<void> {
  const { response } = await api.DELETE('/v1/push/subscriptions/{subscription_id}', {
    params: { path: { subscription_id: id } },
  })
  if (!response.ok) throw new PushRequestError(response.status)
}

/** Remove the server row whose endpoint matches this browser's. */
export async function removeSubscriptionByEndpoint(endpoint: string): Promise<boolean> {
  const subscriptions = await listPushSubscriptions()
  const match = subscriptions.find((item) => item.endpoint === endpoint)
  if (match === undefined) return false
  await removePushSubscription(match.id)
  return true
}

/** One explicit delivery, so the toggle can prove itself. */
export async function sendPushTest(): Promise<PushTestView> {
  const { data, response } = await api.POST('/v1/push/test')
  if (!response.ok) throw new PushRequestError(response.status)
  if (data === undefined) throw new PushRequestError(response.status)
  return data
}
