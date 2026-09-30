import { api } from '@/lib/api'
import type { components } from '@/api/schema'

import type { JobStatus, JobView } from './jobForm'

export type JobCreate = components['schemas']['JobCreate']
export type JobUpdate = components['schemas']['JobUpdate']

export interface JobResult {
  status: number
  job?: JobView
}

export async function createJob(body: JobCreate): Promise<JobResult> {
  const { data, response } = await api.POST('/v1/jobs', { body })
  return { status: response.status, job: data }
}

export async function updateJob(jobId: string, body: JobUpdate): Promise<JobResult> {
  const { data, response } = await api.PATCH('/v1/jobs/{job_id}', {
    params: { path: { job_id: jobId } },
    body,
  })
  return { status: response.status, job: data }
}

export async function changeJobStatus(jobId: string, status: JobStatus): Promise<JobResult> {
  const { data, response } = await api.POST('/v1/jobs/{job_id}/status', {
    params: { path: { job_id: jobId } },
    body: { status },
  })
  return { status: response.status, job: data }
}
