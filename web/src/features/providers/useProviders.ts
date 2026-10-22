import { useQuery } from '@tanstack/react-query'

import { listProviders } from './providersApi'

export function useProviders() {
  return useQuery({
    queryKey: ['providers'],
    queryFn: listProviders,
    staleTime: 30_000,
    retry: false,
  })
}
