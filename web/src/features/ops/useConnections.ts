import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  listConnections,
  removeConnection,
  saveConnection,
  testConnection,
  type McpServerConfig,
} from './connectionsApi'

const KEY = ['ops', 'mcp', 'servers'] as const

export function useConnections() {
  return useQuery({
    queryKey: KEY,
    queryFn: listConnections,
    staleTime: 30_000,
    retry: false,
  })
}

export function useSaveConnection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (config: McpServerConfig) => saveConnection(config),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: KEY })
    },
  })
}

export function useRemoveConnection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => removeConnection(name),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: KEY })
    },
  })
}

export function useTestConnection() {
  return useMutation({ mutationFn: (name: string) => testConnection(name) })
}
