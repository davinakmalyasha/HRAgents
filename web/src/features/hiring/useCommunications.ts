import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { fetchAllPages } from '@/lib/pagination'

import type { CommunicationView, OverrideView, ReplyView } from './communication'

export function useCommunications(candidateId: string | undefined) {
  return useQuery({
    queryKey: ['communications', candidateId],
    enabled: candidateId !== undefined,
    queryFn: async (): Promise<CommunicationView[]> => {
      return fetchAllPages(async (limit, offset) => {
        const { data } = await api.GET('/v1/candidates/{candidate_id}/communications', {
          params: { path: { candidate_id: candidateId ?? '' }, query: { limit, offset } },
        })
        return data ?? undefined
      })
    },
  })
}

export function useReplies(candidateId: string | undefined) {
  return useQuery({
    queryKey: ['replies', candidateId],
    enabled: candidateId !== undefined,
    queryFn: async (): Promise<ReplyView[]> => {
      return fetchAllPages(async (limit, offset) => {
        const { data } = await api.GET('/v1/candidates/{candidate_id}/replies', {
          params: { path: { candidate_id: candidateId ?? '' }, query: { limit, offset } },
        })
        return data ?? undefined
      })
    },
  })
}

export function useEvaluationOverrides(evaluationId: string | undefined) {
  return useQuery({
    queryKey: ['overrides', evaluationId],
    enabled: evaluationId !== undefined,
    queryFn: async (): Promise<OverrideView[]> => {
      return fetchAllPages(async (limit, offset) => {
        const { data } = await api.GET('/v1/evaluations/{evaluation_id}/overrides', {
          params: { path: { evaluation_id: evaluationId ?? '' }, query: { limit, offset } },
        })
        return data ?? undefined
      })
    },
  })
}
