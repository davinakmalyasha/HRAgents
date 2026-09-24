import { api } from '@/lib/api'
import type { components } from '@/api/schema'

import type { CommunicationView, ReplyView } from './communication'

export type RejectionQueueRequest = components['schemas']['RejectionQueueRequest']
export type OfferQueueRequest = components['schemas']['OfferQueueRequest']

export interface CommunicationResult {
  status: number
  communication?: CommunicationView
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

export async function markCommunicationSent(
  communicationId: string,
  by: string,
): Promise<CommunicationResult> {
  const { data, response } = await api.POST('/v1/communications/{communication_id}/sent', {
    params: { path: { communication_id: communicationId } },
    body: { by },
  })
  return { status: response.status, communication: data }
}

export async function listReplies(candidateId: string): Promise<ReplyView[]> {
  const { data } = await api.GET('/v1/candidates/{candidate_id}/replies', {
    params: { path: { candidate_id: candidateId } },
  })
  return data ?? []
}
