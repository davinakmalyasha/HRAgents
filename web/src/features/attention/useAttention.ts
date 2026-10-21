import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { HttpError } from '@/lib/httpError'
import { fetchAllPages } from '@/lib/pagination'

import {
  attentionFailure,
  buildAttention,
  type AttentionFailure,
  type Handoff,
  type Task,
  type Approval,
} from './attention'

function usePendingApprovals() {
  return useQuery({
    queryKey: ['attention', 'approvals', 'pending'],
    queryFn: async (): Promise<Approval[]> => {
      return fetchAllPages(async (limit, offset) => {
        const { data, response } = await api.GET('/v1/approvals', {
          params: { query: { status: 'pending', limit, offset } },
        })
        if (!response.ok) throw new HttpError(response.status)
        return data ?? undefined
      })
    },
  })
}

function useOpenTasks() {
  return useQuery({
    queryKey: ['attention', 'tasks', 'open'],
    queryFn: async (): Promise<Task[]> => {
      return fetchAllPages(async (limit, offset) => {
        const { data, response } = await api.GET('/v1/tasks', {
          params: { query: { limit, offset } },
        })
        if (!response.ok) throw new HttpError(response.status)
        return data ?? undefined
      })
    },
  })
}

function useOpenHandoffs() {
  return useQuery({
    queryKey: ['attention', 'handoffs', 'open'],
    queryFn: async (): Promise<Handoff[]> => {
      return fetchAllPages(async (limit, offset) => {
        const { data, response } = await api.GET('/v1/chat/handoffs', {
          params: { query: { limit, offset } },
        })
        if (!response.ok) throw new HttpError(response.status)
        return data ?? undefined
      })
    },
  })
}

/**
 * The attention-first home reads three queues directly.
 *
 * A role-scoped 403 is reported as such instead of rendering as an empty
 * queue; any other failure is reported as a failure with a retry. "Nothing
 * needs you" is only allowed when all three queues actually answered.
 */
export function useAttention() {
  const approvals = usePendingApprovals()
  const tasks = useOpenTasks()
  const handoffs = useOpenHandoffs()
  const attention = buildAttention({
    approvals: approvals.data ?? [],
    tasks: tasks.data ?? [],
    handoffs: handoffs.data ?? [],
  })

  const failures = [
    attentionFailure('approvals', approvals.error),
    attentionFailure('tasks', tasks.error),
    attentionFailure('handoffs', handoffs.error),
  ].filter((failure): failure is AttentionFailure => failure !== null)

  function retry() {
    if (approvals.isError) {
      void approvals.refetch()
    }
    if (tasks.isError) {
      void tasks.refetch()
    }
    if (handoffs.isError) {
      void handoffs.refetch()
    }
  }

  return {
    ...attention,
    isLoading: approvals.isLoading || tasks.isLoading || handoffs.isLoading,
    failures,
    retry,
  }
}
