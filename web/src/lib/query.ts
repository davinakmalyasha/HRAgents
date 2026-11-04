import { QueryClient } from '@tanstack/react-query'

import { ATTENTION_QUERY_KEY } from '@/lib/queryKeys'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
    mutations: {
      // Every write can change what is waiting on the home: a decided approval
      // removes an item, a completed task removes another, a new handoff adds
      // one. Each workspace invalidates its own keys already, and none of them
      // knows about the shared queues, so the queue keys are invalidated here,
      // once, instead of in sixty call sites.
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: ATTENTION_QUERY_KEY })
      },
    },
  },
})
