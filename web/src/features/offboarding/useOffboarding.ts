import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

import {
  completeStep,
  createPlan,
  defaultTemplate,
  finalisePlan,
  assetsForEmployee,
  listPlans,
  listTemplates,
  markAssetMissing,
  returnAsset,
  waiveStep,
  type AssetView,
  type PlanCreate,
  type PlanView,
} from './offboardingApi'

export function useOffboardingTemplates() {
  return useQuery({ queryKey: ['offboarding', 'templates'], queryFn: listTemplates })
}

export function useDefaultOffboardingTemplate() {
  return useQuery({
    queryKey: ['offboarding', 'templates', 'default'],
    queryFn: defaultTemplate,
  })
}

export function useOffboardingPlans() {
  return useQuery({ queryKey: ['offboarding', 'plans'], queryFn: listPlans })
}

export function useOffboardingAssets(employeeId: string | null) {
  return useQuery({
    queryKey: ['offboarding', 'assets', employeeId],
    queryFn: () => assetsForEmployee(employeeId as string),
    enabled: employeeId !== null,
  })
}

/** A step or plan mutation changes the plan *and* the assets it gates, so both invalidate. */
function invalidate(queryClient: ReturnType<typeof useQueryClient>) {
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ['offboarding'] })
  }
}

export function useStartOffboarding() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: PlanCreate) => createPlan(body),
    onSuccess: invalidate(queryClient),
  })
}

export function useCompleteOffboardingStep() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      planId,
      stepKey,
      note,
    }: {
      planId: string
      stepKey: string
      note?: string
    }) => completeStep(planId, stepKey, { note: note ?? null }),
    onSuccess: invalidate(queryClient),
  })
}

/**
 * Waive a step.
 *
 * A waiver is the one action here that can skip a requirement, so `reason` is required by
 * the server. Sending a blank one returns `reason_required`, which the view renders as a
 * prompt rather than a failure.
 */
export function useWaiveOffboardingStep() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      planId,
      stepKey,
      reason,
    }: {
      planId: string
      stepKey: string
      reason: string
    }) => waiveStep(planId, stepKey, { reason, note: reason }),
    onSuccess: invalidate(queryClient),
  })
}

export function useFinaliseOffboarding() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (planId: string) => finalisePlan(planId),
    onSuccess: invalidate(queryClient),
  })
}

export function useReturnAsset() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (assetId: string) => returnAsset(assetId),
    onSuccess: invalidate(queryClient),
  })
}

/** Declaring an asset missing is an admission, not a return, so it carries a note. */
export function useMarkAssetMissing() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ assetId, note }: { assetId: string; note: string }) =>
      markAssetMissing(assetId, { note }),
    onSuccess: invalidate(queryClient),
  })
}

/** Look up the plan for one employee, for the asset panel. */
export async function plansForEmployee(employeeId: string): Promise<PlanView[]> {
  const { data } = await api.GET('/v1/offboarding/employees/{employee_id}/plans', {
    params: { path: { employee_id: employeeId } },
  })
  return data ?? []
}

export type { AssetView }
