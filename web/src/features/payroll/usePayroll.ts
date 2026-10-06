import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

import {
  cancelRun,
  computeRun,
  createRun,
  getRun,
  listRuns,
  submitRun,
  type RunCreate,
} from './payrollApi'

export function usePayrollRuns() {
  return useQuery({
    queryKey: ['payroll', 'runs'],
    queryFn: listRuns,
  })
}

export function usePayrollRun(runId: string | null) {
  return useQuery({
    queryKey: ['payroll', 'run', runId],
    queryFn: () => getRun(runId as string),
    enabled: runId !== null,
  })
}

/** Every payroll mutation invalidates the run list; a stale list hides a new period. */
function invalidateRuns(queryClient: ReturnType<typeof useQueryClient>) {
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ['payroll'] })
  }
}

export function useCreateRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: RunCreate) => createRun(body),
    onSuccess: invalidateRuns(queryClient),
  })
}

export function useComputeRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (runId: string) => computeRun(runId),
    onSuccess: invalidateRuns(queryClient),
  })
}

export function useSubmitRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (runId: string) => submitRun(runId),
    onSuccess: invalidateRuns(queryClient),
  })
}

export function useCancelRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ runId, reason }: { runId: string; reason: string }) =>
      cancelRun(runId, reason),
    onSuccess: invalidateRuns(queryClient),
  })
}

/** Pull the payroll's view of an approval decided through the approvals inbox. */
export function useSyncPayrollApproval() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (approvalId: string) => {
      const { response } = await api.POST('/v1/payroll/approvals/{approval_id}/sync', {
        params: { path: { approval_id: approvalId } },
      })
      return { status: response.status }
    },
    onSuccess: invalidateRuns(queryClient),
  })
}
