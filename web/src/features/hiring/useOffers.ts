import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

import type { OfferView } from './offer'

export function useOffers(applicationId: string | undefined) {
  return useQuery({
    queryKey: ['offers', applicationId],
    enabled: applicationId !== undefined,
    queryFn: async (): Promise<OfferView[]> => {
      const { data } = await api.GET('/v1/offers', {
        params: { query: { application_id: applicationId } },
      })
      return data ?? []
    },
  })
}
