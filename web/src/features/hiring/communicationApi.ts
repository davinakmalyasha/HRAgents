import { api } from '@/lib/api'
import type { components } from '@/api/schema'

import type { CommunicationView, ReplyView, WhatsappDispatchLinkView } from './communication'

export type RejectionQueueRequest = components['schemas']['RejectionQueueRequest']
export type RejectionPreviewRequest = components['schemas']['RejectionPreviewRequest']
export type OfferQueueRequest = components['schemas']['OfferQueueRequest']
export type CommunicationPreview = components['schemas']['CommunicationPreviewView']

export interface CommunicationResult {
  status: number
  communication?: CommunicationView
}

export interface PreviewResult {
  status: number
  preview?: CommunicationPreview
}

/**
 * Ask the server what queueing would produce. This is a read: the preview stores
 * nothing, so a human can check the wording and the blockers before committing.
 */
export async function previewRejectionMessage(
  candidateId: string,
  body: RejectionPreviewRequest,
): Promise<PreviewResult> {
  const { data, response } = await api.POST(
    '/v1/candidates/{candidate_id}/communications/rejection/preview',
    {
      params: { path: { candidate_id: candidateId } },
      body,
    },
  )
  return { status: response.status, preview: data }
}

export interface DispatchLinkResult {
  status: number
  link?: WhatsappDispatchLinkView
}

export async function queueRejectionMessage(
  candidateId: string,
  body: RejectionQueueRequest,
): Promise<CommunicationResult> {
  const { data, response } = await api.POST(
    '/v1/candidates/{candidate_id}/communications/rejection',
    {
      params: { path: { candidate_id: candidateId } },
      body,
    },
  )
  return { status: response.status, communication: data }
}

export async function queueOfferMessage(
  candidateId: string,
  body: OfferQueueRequest,
): Promise<CommunicationResult> {
  const { data, response } = await api.POST('/v1/candidates/{candidate_id}/communications/offer', {
    params: { path: { candidate_id: candidateId } },
    body,
  })
  return { status: response.status, communication: data }
}

export async function markCommunicationSent(communicationId: string): Promise<CommunicationResult> {
  const { data, response } = await api.POST('/v1/communications/{communication_id}/sent', {
    params: { path: { communication_id: communicationId } },
    body: {},
  })
  return { status: response.status, communication: data }
}

export async function listReplies(candidateId: string): Promise<ReplyView[]> {
  const { data } = await api.GET('/v1/candidates/{candidate_id}/replies', {
    params: { path: { candidate_id: candidateId } },
  })
  return data ?? []
}

export async function composeDispatchLink(
  communicationId: string,
  toPhone?: string,
): Promise<DispatchLinkResult> {
  const { data, response } = await api.POST('/v1/communications/{communication_id}/dispatch-link', {
    params: { path: { communication_id: communicationId } },
    body: { to_phone: toPhone ?? null },
  })
  return { status: response.status, link: data }
}
