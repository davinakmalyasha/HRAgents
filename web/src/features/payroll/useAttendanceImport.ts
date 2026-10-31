import { useMutation, useQueryClient } from '@tanstack/react-query'

import { commitAttendance, previewAttendance, type AttendanceCommitBody } from './attendanceApi'

/**
 * Attendance is a preview then a commit, and both invalidate the run: the
 * preview writes nothing, but a commit changes overtime/absence on every line
 * and a stale detail would show the old figures after the dialog closes.
 */
export function useAttendanceImport(runId: string) {
  const queryClient = useQueryClient()
  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['payroll'] })
  }

  const preview = useMutation({
    mutationFn: async (body: AttendanceCommitBody) => previewAttendance(runId, body),
  })

  const commit = useMutation({
    mutationFn: async (body: AttendanceCommitBody) => commitAttendance(runId, body),
    onSuccess: invalidate,
  })

  return { preview, commit }
}
