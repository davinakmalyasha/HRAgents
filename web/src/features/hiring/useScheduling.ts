import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { fetchAllPages } from '@/lib/pagination'

import type { SchedulingProposal } from './scheduling'

export function useSchedulingProposals() {
  return useQuery({
    queryKey: ['scheduling', 'proposals'],
    queryFn: async (): Promise<SchedulingProposal[]> => {
      return fetchAllPages(async (limit, offset) => {
        const { data } = await api.GET('/v1/scheduling/proposals', {
          params: { query: { limit, offset } },
        })
        return data ?? undefined
      })
    },
  })
}
