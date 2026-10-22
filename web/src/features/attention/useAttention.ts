import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { HttpError } from '@/lib/httpError'
import type { WorkspaceId } from '@/lib/workspaces'

import {
  attentionFailure,
  buildAttention,
  dominantWorkspace,
  type AttentionFailure,
  type AttentionItem,
  type AttentionQueue,
  type Handoff,
  type Task,
  type Approval,
} from './attention'

/**
 * How many items of one queue the home reads.
 *
 * The home used to walk every page of three queues on every load, so a long-lived
 * install paid for its whole history to show a screen. One page is the working
 * set; the queue total says what was left out, and the link goes to the rest.
 */
const ATTENTION_PAGE_SIZE = 50

interface QueuePage<T> {
  items: T[]
  total: number
}

export interface AttentionQueueSummary {
  queue: AttentionQueue
  shown: number
  total: number
  workspace: WorkspaceId | null
}

function usePendingApprovals() {
  return useQuery({
    queryKey: ['attention', 'approvals', 'pending'],
    queryFn: async (): Promise<QueuePage<Approval>> => {
      const { data, response } = await api.GET('/v1/approvals', {
        params: { query: { status: 'pending', limit: ATTENTION_PAGE_SIZE, offset: 0 } },
      })
      if (!response.ok) throw new HttpError(response.status)
      return { items: data?.items ?? [], total: data?.total ?? 0 }
    },
  })
}

function useOpenTasks() {
  return useQuery({
    queryKey: ['attention', 'tasks', 'open'],
    queryFn: async (): Promise<QueuePage<Task>> => {
      const { data, response } = await api.GET('/v1/tasks', {
        params: { query: { limit: ATTENTION_PAGE_SIZE, offset: 0 } },
      })
      if (!response.ok) throw new HttpError(response.status)
      return { items: data?.items ?? [], total: data?.total ?? 0 }
    },
  })
}

function useOpenHandoffs() {
  return useQuery({
    queryKey: ['attention', 'handoffs', 'open'],
    queryFn: async (): Promise<QueuePage<Handoff>> => {
      const { data, response } = await api.GET('/v1/chat/handoffs', {
        params: { query: { limit: ATTENTION_PAGE_SIZE, offset: 0 } },
      })
      if (!response.ok) throw new HttpError(response.status)
      return { items: data?.items ?? [], total: data?.total ?? 0 }
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
    approvals: approvals.data?.items ?? [],
    tasks: tasks.data?.items ?? [],
    handoffs: handoffs.data?.items ?? [],
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

  const all: AttentionItem[] = [...attention.needsYou, ...attention.watching]
  const queues: AttentionQueueSummary[] = [
    {
      queue: 'approvals',
      shown: approvals.data?.items.length ?? 0,
      total: approvals.data?.total ?? 0,
      workspace: 'approvals',
    },
    {
      queue: 'tasks',
      shown: tasks.data?.items.length ?? 0,
      total: tasks.data?.total ?? 0,
      workspace: dominantWorkspace(all.filter((item) => item.source === 'task')),
    },
    {
      queue: 'handoffs',
      shown: handoffs.data?.items.length ?? 0,
      total: handoffs.data?.total ?? 0,
      workspace: dominantWorkspace(all.filter((item) => item.source === 'handoff')),
    },
  ]

  return {
    ...attention,
    isLoading: approvals.isLoading || tasks.isLoading || handoffs.isLoading,
    failures,
    retry,
    queues,
    limitedQueues: queues.filter((queue) => queue.shown < queue.total),
  }
}
