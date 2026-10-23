import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  clearProvider,
  fetchProviderOptions,
  listProviders,
  saveProvider,
  testProvider,
  type ProviderCapability,
} from './providersApi'

export function useProviders() {
  return useQuery({
    queryKey: ['providers'],
    queryFn: listProviders,
    staleTime: 30_000,
    retry: false,
  })
}

export function useProviderOptions(capability: ProviderCapability | null) {
  return useQuery({
    queryKey: ['provider-options', capability],
    queryFn: () => fetchProviderOptions(capability as ProviderCapability),
    enabled: capability !== null,
    retry: false,
  })
}

export function useSaveProvider() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      capability,
      providerId,
      config,
    }: {
      capability: ProviderCapability
      providerId: string
      config: Record<string, unknown>
    }) => saveProvider(capability, providerId, config),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['providers'] }),
  })
}

export function useClearProvider() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (capability: ProviderCapability) => clearProvider(capability),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['providers'] }),
  })
}

export function useTestProvider() {
  return useMutation({
    mutationFn: ({
      capability,
      providerId,
      config,
    }: {
      capability: ProviderCapability
      providerId: string
      config: Record<string, unknown>
    }) => testProvider(capability, providerId, config),
  })
}
