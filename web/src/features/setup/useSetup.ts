import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { readSetup, seedStarters } from './setupApi'

/**
 * The first-run status. A refusal (a non-admin key) is not retried: the card is
 * simply absent for that caller.
 */
export function useSetup() {
  return useQuery({
    queryKey: ['setup'],
    queryFn: readSetup,
    staleTime: 30_000,
    retry: false,
  })
}

export function useSeedStarters() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: seedStarters,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['setup'] })
      await queryClient.invalidateQueries({ queryKey: ['onboarding'] })
      await queryClient.invalidateQueries({ queryKey: ['offboarding'] })
    },
  })
}
