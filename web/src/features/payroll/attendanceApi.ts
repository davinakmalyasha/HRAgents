import type { components } from '@/api/schema'
import { api } from '@/lib/api'

import type { RunView } from './payrollApi'

export type AttendanceCommitBody = components['schemas']['AttendanceCommit']
export type AttendancePreviewView = components['schemas']['AttendancePreviewView']

export interface PreviewResult {
  status: number
  preview?: AttendancePreviewView
}

export async function previewAttendance(
  runId: string,
  body: AttendanceCommitBody,
): Promise<PreviewResult> {
  const { data, response } = await api.POST('/v1/payroll/runs/{run_id}/attendance:preview', {
    params: { path: { run_id: runId } },
    body,
  })
  return { status: response.status, preview: data ?? undefined }
}

export async function commitAttendance(
  runId: string,
  body: AttendanceCommitBody,
): Promise<{ status: number; run: RunView | null }> {
  const { data, response } = await api.POST('/v1/payroll/runs/{run_id}/attendance:commit', {
    params: { path: { run_id: runId } },
    body,
  })
  return { status: response.status, run: data ?? null }
}

/** Encode a file as base64 without spreading a 10 MiB array onto the stack. */
export async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  const chunk = 0x8000
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk))
  }
  return btoa(binary)
}
