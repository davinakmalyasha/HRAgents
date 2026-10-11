import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  decideApproval,
  escalateOverdue,
  listApprovals,
  type ApprovalStatus,
  type RoleId,
} from './approvalsApi'

/**
 * Who the server thinks this caller is.
 *
 * Moved to `features/auth/session.ts`, where the sign-in screen and the shell
 * read the same query. Re-exported here because the inbox was its first caller
 * and importing it from two places under two names is how cache keys drift.
 */
export { useSession } from '@/features/auth/session'

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
