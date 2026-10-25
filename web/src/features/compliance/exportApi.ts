import { storedApiKey } from '@/lib/auth'

export class ExportRequestError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string | null = null,
  ) {
    super(detail ?? `export failed with status ${status}`)
    this.name = 'ExportRequestError'
  }
}

export interface TenantExport {
  blob: Blob
  filename: string
}

/**
 * Fetch the full export as a file.
 *
 * This bypasses the generated client on purpose: the response is a streamed
 * document, and `openapi-fetch` would parse it into one large object before the
 * browser could save it. The credential is the same key every other call uses.
 */
export async function fetchTenantExport(): Promise<TenantExport> {
  const headers: Record<string, string> = {}
  const key = storedApiKey()
  if (key !== null) {
    headers['X-API-Key'] = key
  }
  const response = await fetch('/v1/export', { headers })
  if (!response.ok) {
    let detail: string | null = null
    try {
      const body: unknown = await response.json()
      if (body !== null && typeof body === 'object' && 'detail' in body) {
        const value = (body as { detail?: unknown }).detail
        detail = typeof value === 'string' ? value : null
      }
    } catch {
      // A refusal with no JSON body still carries its status.
    }
    throw new ExportRequestError(response.status, detail)
  }
  const disposition = response.headers.get('content-disposition') ?? ''
  const match = /filename="([^"]+)"/.exec(disposition)
  return {
    blob: await response.blob(),
    filename: match?.[1] ?? 'hragents-export.json',
  }
}

export function saveExport({ blob, filename }: TenantExport): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
