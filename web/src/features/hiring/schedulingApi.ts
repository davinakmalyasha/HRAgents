import { api } from '@/lib/api'
import type { components } from '@/api/schema'

import type { SchedulingProposal } from './scheduling'

export type ProposalDecisionRequest = components['schemas']['ProposalDecisionRequest']

export interface ProposalDecisionResult {
  status: number
  proposal?: SchedulingProposal
  replacement?: SchedulingProposal | null
  detail?: string
}

export async function decideProposal(
  proposalId: string,
  body: ProposalDecisionRequest,
): Promise<ProposalDecisionResult> {
  const { data, error, response } = await api.POST(
    '/v1/scheduling/proposals/{proposal_id}/decision',
    {
      params: { path: { proposal_id: proposalId } },
      body,
    },
  )
  const problem = error as { title?: string } | null | undefined
  return {
    status: response.status,
    proposal: data?.proposal,
    replacement: data?.replacement ?? null,
    detail: problem?.title,
  }
}
