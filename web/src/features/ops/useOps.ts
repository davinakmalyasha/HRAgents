import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { listDeadLetters, requeueDeadLetter } from './opsApi'

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
