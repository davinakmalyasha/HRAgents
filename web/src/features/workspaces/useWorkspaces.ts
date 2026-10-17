import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { fetchAllPages } from '@/lib/pagination'

import type { WorkspaceId } from '@/lib/workspaces'

export interface WorkspaceMeta {
  id: WorkspaceId
  name_en: string
  name_id: string
  summary_en: string
  summary_id: string
}

export function useWorkspaces() {
  return useQuery({
    queryKey: ['workspaces'],
    queryFn: async (): Promise<WorkspaceMeta[]> => {
      return fetchAllPages(async (limit, offset) => {
        const { data } = await api.GET('/v1/workspaces', {
          params: { query: { limit, offset } },
        })
        return data ?? undefined
      })
    },
  })
}

export function workspaceName(
  workspaces: WorkspaceMeta[] | undefined,
  id: WorkspaceId,
  language: string,
  fallback: string,
): string {
  const meta = workspaces?.find((item) => item.id === id)
  if (meta === undefined) {
    return fallback
  }
  return language.startsWith('id') ? meta.name_id : meta.name_en
}
