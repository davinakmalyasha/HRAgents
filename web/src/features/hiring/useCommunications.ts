import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

import type { CommunicationView, OverrideView } from './communication'

export function useCommunications(candidateId: string | undefined) {
  return useQuery({
    queryKey: ['communications', candidateId],
    enabled: candidateId !== undefined,
    queryFn: async (): Promise<CommunicationView[]> => {
      const { data } = await api.GET('/v1/candidates/{candidate_id}/communications', {
        params: { path: { candidate_id: candidateId ?? '' } },
      })
      return data ?? []
    },
  })
}

export function useEvaluationOverrides(evaluationId: string | undefined) {
  return useQuery({
    queryKey: ['overrides', evaluationId],
    enabled: evaluationId !== undefined,
    queryFn: async (): Promise<OverrideView[]> => {
      const { data } = await api.GET('/v1/evaluations/{evaluation_id}/overrides', {
        params: { path: { evaluation_id: evaluationId ?? '' } },
      })
      return data ?? []
    },
  })
}
