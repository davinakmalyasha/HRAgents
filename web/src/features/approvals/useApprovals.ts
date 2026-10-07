import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  decideApproval,
  escalateOverdue,
  listApprovals,
  readSession,
  type ApprovalStatus,
  type RoleId,
} from './approvalsApi'

/**
 * Who the server thinks this caller is.
 *
 * `/v1/session` rather than anything the browser can infer: the role here is the one
 * every permission check uses, so guessing it locally is how an inbox ends up offering a
 * decision the server refuses.
 */
export function useSession() {
  return useQuery({ queryKey: ['session'], queryFn: readSession, staleTime: 60_000 })
}

/** Approvals still awaiting a decision, newest last so the queue reads in order. */
export function useApprovals(status: ApprovalStatus = 'pending') {
  return useQuery({
    queryKey: ['approvals', status],
    queryFn: () => listApprovals({ status }),
  })
}

export function useDecideApproval() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      approvalId,
      approve,
      reason,
    }: {
      approvalId: string
      approve: boolean
      reason: string
    }) => decideApproval(approvalId, { approve, reason }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['approvals'] })
      await queryClient.invalidateQueries({ queryKey: ['attention'] })
    },
  })
}

/** Escalating is a system move, not a decision: no actor, no reason. */
export function useEscalateOverdue() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: escalateOverdue,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['approvals'] })
    },
  })
}

export type { ApprovalStatus, RoleId }
