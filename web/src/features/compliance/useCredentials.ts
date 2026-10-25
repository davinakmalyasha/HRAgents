import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createCredentialRegistry,
  deleteCredentialRegistry,
  listCredentialRegistries,
  setCredentialEntries,
  verifyCredentialRegistry,
  type CredentialEntryInput,
} from './credentialsApi'

export function useCredentialRegistries() {
  return useQuery({
    queryKey: ['credentials'],
    queryFn: listCredentialRegistries,
    staleTime: 30_000,
    retry: false,
  })
}

function useRefresh() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: ['credentials'] })
}

export function useCreateCredentialRegistry() {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: ({ name, issuer }: { name: string; issuer: string }) =>
      createCredentialRegistry(name, issuer),
    onSuccess: refresh,
  })
}

export function useSetCredentialEntries() {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: ({
      registryId,
      entries,
    }: {
      registryId: string
      entries: CredentialEntryInput[]
    }) => setCredentialEntries(registryId, entries),
    onSuccess: refresh,
  })
}

export function useVerifyCredentialRegistry() {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: ({ registryId, sourceNote }: { registryId: string; sourceNote: string }) =>
      verifyCredentialRegistry(registryId, sourceNote),
    onSuccess: refresh,
  })
}

export function useDeleteCredentialRegistry() {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: (registryId: string) => deleteCredentialRegistry(registryId),
    onSuccess: refresh,
  })
}
