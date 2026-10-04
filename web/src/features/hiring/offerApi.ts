import { api } from '@/lib/api'
import type { ProblemDetail } from '@/lib/problem'
import type { components } from '@/api/schema'

import type { OfferView } from './offer'

export type OfferCreateRequest = components['schemas']['OfferCreate']
export type OfferReviseRequest = components['schemas']['OfferReviseRequest']
export type OfferDecisionRequest = components['schemas']['OfferDecisionRequest']
export type OfferMessageRequest = components['schemas']['OfferMessageRequest']
export type OfferAcceptanceRequest = components['schemas']['OfferAcceptanceRequest']

export interface OfferResult {
  status: number
  offer?: OfferView
  problem?: ProblemDetail
}

function toResult(response: Response, data: OfferView | undefined, error: unknown): OfferResult {
  const problem = error as { title?: string } | null | undefined
  return {
    status: response.status,
    offer: data,
    problem: (problem ?? undefined) as ProblemDetail | undefined,
  }
}

export async function createOffer(body: OfferCreateRequest): Promise<OfferResult> {
  const { data, error, response } = await api.POST('/v1/offers', { body })
  return toResult(response, data, error)
}

export async function reviseOffer(offerId: string, body: OfferReviseRequest): Promise<OfferResult> {
  const { data, error, response } = await api.PATCH('/v1/offers/{offer_id}', {
    params: { path: { offer_id: offerId } },
    body,
  })
  return toResult(response, data, error)
}

export async function submitOffer(
  offerId: string,
  body: components['schemas']['OfferSubmitRequest'],
): Promise<OfferResult> {
  const { data, error, response } = await api.POST('/v1/offers/{offer_id}/submit', {
    params: { path: { offer_id: offerId } },
    body,
  })
  return toResult(response, data, error)
}

export async function decideOffer(
  offerId: string,
  body: OfferDecisionRequest,
): Promise<OfferResult> {
  const { data, error, response } = await api.POST('/v1/offers/{offer_id}/decision', {
    params: { path: { offer_id: offerId } },
    body,
  })
  return toResult(response, data, error)
}

export async function queueOfferMessage(
  offerId: string,
  body: OfferMessageRequest,
): Promise<OfferResult> {
  const { data, error, response } = await api.POST('/v1/offers/{offer_id}/message', {
    params: { path: { offer_id: offerId } },
    body,
  })
  return toResult(response, data, error)
}

export async function recordOfferAcceptance(
  offerId: string,
  body: OfferAcceptanceRequest,
): Promise<OfferResult> {
  const { data, error, response } = await api.POST('/v1/offers/{offer_id}/acceptance', {
    params: { path: { offer_id: offerId } },
    body,
  })
  return toResult(response, data, error)
}
