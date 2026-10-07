import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  activateCycle,
  closeCycle,
  createCycle,
  createGoal,
  cycleAssignments,
  draftSummary,
  finalizeSummary,
  listCycles,
  listGoals,
  listOverdueGoals,
  listSummaries,
  myAssignments,
  openReviewing,
  recordGoalProgress,
  runReminders,
  skipAssignment,
  submitAssignment,
  type CycleCreate,
  type GoalCreate,
  type RemindersRun,
  type SummaryDraft,
} from './growthApi'

export function useGrowthCycles() {
  return useQuery({ queryKey: ['growth', 'cycles'], queryFn: listCycles })
}

export function useGrowthGoals() {
  return useQuery({ queryKey: ['growth', 'goals'], queryFn: listGoals })
}

/** The server's own overdue list, rather than filtering dates in the UI. */
export function useOverdueGoals() {
  return useQuery({ queryKey: ['growth', 'goals', 'overdue'], queryFn: listOverdueGoals })
}

/** The caller's own review assignments, across every cycle. */
export function useMyAssignments() {
  return useQuery({ queryKey: ['growth', 'assignments', 'mine'], queryFn: myAssignments })
}

function invalidate(queryClient: ReturnType<typeof useQueryClient>) {
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ['growth'] })
  }
}

/** Every form in one cycle, for the reviewer roster and the summary editor. */
export function useCycleAssignments(cycleId: string | null) {
  return useQuery({
    queryKey: ['growth', 'assignments', cycleId],
    queryFn: () => cycleAssignments(cycleId as string),
    enabled: cycleId !== null,
  })
}

export function useSummaries(cycleId: string | null) {
  return useQuery({
    queryKey: ['growth', 'summaries', cycleId],
    queryFn: () => listSummaries(cycleId as string),
    enabled: cycleId !== null,
  })
}

export function useCreateCycle() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: CycleCreate) => createCycle(body),
    onSuccess: invalidate(queryClient),
  })
}

export function useCycleTransition() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      cycleId,
      action,
      reason,
    }: {
      cycleId: string
      action: 'activate' | 'reviewing' | 'close'
      reason?: string
    }) => {
      if (action === 'activate') return activateCycle(cycleId)
      if (action === 'reviewing') return openReviewing(cycleId)
      return closeCycle(cycleId, reason ?? '')
    },
    onSuccess: invalidate(queryClient),
  })
}

export function useSubmitAssignment() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      assignmentId,
      ratings,
      comments,
    }: {
      assignmentId: string
      ratings: Record<string, number>
      comments: string
    }) => submitAssignment(assignmentId, { ratings, comments }),
    onSuccess: invalidate(queryClient),
  })
}

/** Skipping admits a review did not happen, so the reason is mandatory. */
export function useSkipAssignment() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ assignmentId, reason }: { assignmentId: string; reason: string }) =>
      skipAssignment(assignmentId, reason),
    onSuccess: invalidate(queryClient),
  })
}

export function useCreateGoal() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: GoalCreate) => createGoal(body),
    onSuccess: invalidate(queryClient),
  })
}

export function useRecordGoalProgress() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      goalId,
      percent,
      note,
    }: {
      goalId: string
      percent: number
      note: string
    }) => recordGoalProgress(goalId, percent, note),
    onSuccess: invalidate(queryClient),
  })
}

export function useDraftSummary() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: SummaryDraft) => draftSummary(body),
    onSuccess: invalidate(queryClient),
  })
}

/**
 * Finalising is human-only on the server, and the final text is what gets shared --
 * so this mutation is never wired to an agent path.
 */
export function useFinalizeSummary() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ summaryId, finalText }: { summaryId: string; finalText: string }) =>
      finalizeSummary(summaryId, finalText),
    onSuccess: invalidate(queryClient),
  })
}

/** Running reminders returns what it created; it is not a query. */
export function useRunReminders() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: RemindersRun) => runReminders(body),
    onSuccess: invalidate(queryClient),
  })
}
