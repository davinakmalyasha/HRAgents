import { api } from '@/lib/api'
import type { components } from '@/api/schema'

import type { ImportItem } from './importCsv'

export type DocumentUploadResponse = components['schemas']['DocumentUploadResponse']
export type BatchItemResult = components['schemas']['BatchItemResult']

export interface UploadedCv {
  filename: string
  documentId: string | null
  sha256: string | null
  error: string | null
}

export interface BatchReport {
  accepted: number
  items: BatchItemResult[]
}

/** Upload CV files one by one; a file never blocks the rest. */
export async function uploadCvs(files: File[]): Promise<UploadedCv[]> {
  const results: UploadedCv[] = []
  for (const file of files) {
    const form = new FormData()
    form.append('file', file)
    form.append('kind', 'cv')
    form.append('uploaded_by', 'web-import')
    try {
      const { data, response } = await api.POST('/v1/documents', {
        body: {
          file: file as unknown as string,
          kind: 'cv',
          uploaded_by: 'web-import',
        },
        bodySerializer: () => form,
      })
      if (!response.ok || data === undefined) {
        results.push({
          filename: file.name,
          documentId: null,
          sha256: null,
          error: `${response.status}`,
        })
      } else {
        results.push({
          filename: file.name,
          documentId: data.document_id,
          sha256: data.sha256,
          error: null,
        })
      }
    } catch {
      results.push({ filename: file.name, documentId: null, sha256: null, error: 'network' })
    }
  }
  return results
}

/** Submit validated rows as one batch; the server reports per-item conflicts. */
export async function submitImportBatch(jobId: string, items: ImportItem[]): Promise<BatchReport> {
  const { data, response } = await api.POST('/v1/applications/batch', {
    body: {
      items: items.map((item) => ({
        job_id: jobId,
        source_channel: 'csv-import',
        consent: { granted: true, policy_version: '1.0' },
        candidate: { full_name: item.full_name, emails: item.emails },
        documents: item.document_id === null ? [] : [{ document_id: item.document_id, kind: 'cv' }],
      })),
    },
  })
  if (!response.ok || data === undefined) {
    throw new Error(`batch failed: ${response.status}`)
  }
  return { accepted: data.accepted, items: data.items ?? [] }
}
