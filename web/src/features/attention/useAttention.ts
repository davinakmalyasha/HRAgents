import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { fetchAllPages } from '@/lib/pagination'

import { buildAttention, type Handoff, type Task, type Approval } from './attention'

function usePendingApprovals() {
  return useQuery({
    queryKey: ['attention', 'approvals', 'pending'],
    queryFn: async (): Promise<Approval[]> => {
      return fetchAllPages(async (limit, offset) => {
        const { data } = await api.GET('/v1/approvals', {
          params: { query: { status: 'pending', limit, offset } },
        })
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
        const { data } = await api.GET('/v1/tasks', { params: { query: { limit, offset } } })
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
        const { data } = await api.GET('/v1/chat/handoffs', {
          params: { query: { limit, offset } },
        })
        return data ?? undefined
      })
    },
  })
}

/**
 * The attention-first home reads three queues directly.
 *
 * Role-scoped 403s degrade to empty sections rather than error walls: a user
 * without `people:read` simply has nothing to decide there.
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

  return {
    ...attention,
    isLoading: approvals.isLoading || tasks.isLoading || handoffs.isLoading,
  }
}
