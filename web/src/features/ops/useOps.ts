import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getFairness, getUsage, listDeadLetters, requeueDeadLetter } from './opsApi'

export function useUsage(days = 30) {
  return useQuery({
    queryKey: ['ops', 'usage', days],
    queryFn: () => getUsage(days),
    staleTime: 60_000,
    retry: false,
  })
}

export function useDeadLetters() {
  return useQuery({
    queryKey: ['ops', 'dead-letters'],
    queryFn: listDeadLetters,
  })
}

export function useRequeueDeadLetter() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ messageId, reason }: { messageId: string; reason: string }) =>
      requeueDeadLetter(messageId, reason),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ops', 'dead-letters'] })
    },
  })
}

export function useFairness(days = 90) {
  return useQuery({
    queryKey: ['ops', 'fairness', days],
    queryFn: () => getFairness(days),
    staleTime: 60_000,
    retry: false,
  })
}
