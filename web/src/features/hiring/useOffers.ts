import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { fetchAllPages } from '@/lib/pagination'

import type { OfferView } from './offer'

export function useOffers(applicationId: string | undefined) {
  return useQuery({
    queryKey: ['offers', applicationId],
    enabled: applicationId !== undefined,
    queryFn: async (): Promise<OfferView[]> => {
      return fetchAllPages(async (limit, offset) => {
        const { data } = await api.GET('/v1/offers', {
          params: { query: { application_id: applicationId, limit, offset } },
        })
        return data ?? undefined
      })
    },
  })
}
