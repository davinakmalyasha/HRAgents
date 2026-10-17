import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { fetchAllPages } from '@/lib/pagination'

import type { ApplicationSummary } from './pipeline'

export function useJobs() {
  return useQuery({
    queryKey: ['jobs'],
    queryFn: async () => {
      return fetchAllPages(async (limit, offset) => {
        const { data } = await api.GET('/v1/jobs', { params: { query: { limit, offset } } })
        return data ?? undefined
      })
    },
  })
}

export function useApplications(jobId: string | null) {
  return useQuery({
    queryKey: ['applications', jobId ?? 'all'],
    queryFn: async (): Promise<ApplicationSummary[]> => {
      return fetchAllPages(async (limit, offset) => {
        const { data } = await api.GET('/v1/applications', {
          params: {
            query: { limit, offset, ...(jobId === null ? {} : { job_id: jobId }) },
          },
        })
        return data ?? undefined
      })
    },
  })
}

export function useGatedApplications() {
  return useQuery({
    queryKey: ['applications', 'status', 'gated'],
    queryFn: async (): Promise<ApplicationSummary[]> => {
      return fetchAllPages(async (limit, offset) => {
        const { data } = await api.GET('/v1/applications', {
          params: { query: { status: 'gated', limit, offset } },
        })
        return data ?? undefined
      })
    },
  })
}

export function useApplication(applicationId: string | undefined) {
  return useQuery({
    queryKey: ['application', applicationId],
    enabled: applicationId !== undefined,
    queryFn: async () => {
      const { data } = await api.GET('/v1/applications/{application_id}', {
        params: { path: { application_id: applicationId ?? '' } },
      })
      return data ?? null
    },
  })
}

export function useEvaluation(applicationId: string | undefined) {
  return useQuery({
    queryKey: ['evaluation', applicationId],
    enabled: applicationId !== undefined,
    queryFn: async () => {
      const { data, response } = await api.GET('/v1/applications/{application_id}/evaluation', {
        params: { path: { application_id: applicationId ?? '' } },
      })
      if (response.status === 404) {
        return null
      }
      return data ?? null
    },
  })
}
