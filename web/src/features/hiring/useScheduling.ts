import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

import type { SchedulingProposal } from './scheduling'

export function useSchedulingProposals() {
  return useQuery({
    queryKey: ['scheduling', 'proposals'],
    queryFn: async (): Promise<SchedulingProposal[]> => {
      const { data } = await api.GET('/v1/scheduling/proposals')
      return data ?? []
    },
  })
}
