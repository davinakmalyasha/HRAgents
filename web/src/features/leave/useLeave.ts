import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

import {
  employeeBalances,
  listPolicies,
  listRequests,
  type BalanceAdjustRequest,
  type LeaveType,
  type RequestStatus,
} from './leaveApi'

export function useLeavePolicies() {
  return useQuery({
    queryKey: ['leave', 'policies'],
    queryFn: listPolicies,
  })
}

export function useLeaveRequests(status?: RequestStatus) {
  return useQuery({
    queryKey: ['leave', 'requests', { status: status ?? 'all' }],
    queryFn: () => listRequests(status === undefined ? {} : { status }),
  })
}

export function useEmployeeBalances(employeeId: string | null) {
  return useQuery({
    queryKey: ['leave', 'balances', employeeId],
    queryFn: () => employeeBalances(employeeId as string),
    enabled: employeeId !== null,
  })
}

/**
 * Every leave mutation needs a reason and answers with a status rather than throwing.
 *
 * The reason-less form is a 422 carrying `reason_required`, which the view turns into a
 * prompt. Returning the status keeps the view in charge of which message a person sees --
 * `problemMessage` already maps it, and the reason-less case is the one worth
 * distinguishing from a genuine refusal.
 */
export function useCancelLeaveRequest() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ requestId, reason }: { requestId: string; reason: string }) => {
      const { response } = await api.POST('/v1/leave/requests/{request_id}/cancel', {
        params: { path: { request_id: requestId } },
        body: { reason },
      })
      return { status: response.status }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['leave'] }),
  })
}

export function useAdjustLeaveBalance() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      employeeId,
      leaveType,
      days,
      year,
    }: {
      employeeId: string
      leaveType: LeaveType
      days: number
      year?: number
    }) => {
      const body: BalanceAdjustRequest = { days, year }
      const { response } = await api.POST('/v1/leave/balances/{employee_id}/{leave_type}/adjust', {
        params: { path: { employee_id: employeeId, leave_type: leaveType } },
        body,
      })
      return { status: response.status }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['leave'] }),
  })
}

/** Pull the leave service's view of any approval decided through another surface. */
export function useSyncLeaveApproval() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (approvalId: string) => {
      const { response } = await api.POST('/v1/leave/approvals/{approval_id}/sync', {
        params: { path: { approval_id: approvalId } },
      })
      return { status: response.status }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['leave'] }),
  })
}
