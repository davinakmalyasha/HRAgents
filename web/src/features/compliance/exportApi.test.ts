import { afterEach, describe, expect, it, vi } from 'vitest'

import { ExportRequestError, fetchTenantExport } from './exportApi'

function respond(
  body: unknown,
  { status = 200, filename }: { status?: number; filename?: string } = {},
): Response {
  const headers: Record<string, string> = { 'content-type': 'application/json' }
  if (filename) headers['content-disposition'] = `attachment; filename="${filename}"`
  return new Response(JSON.stringify(body), { status, headers })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('fetchTenantExport', () => {
  it('returns the blob and the filename the API served', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(respond({ manifest: {} }, { filename: 'export.json' })),
    )

    const result = await fetchTenantExport()

    expect(result.filename).toBe('export.json')
    expect(result.blob.size).toBeGreaterThan(0)
  })

  it('falls back to a stable name when the header is missing', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond({ manifest: {} })))

    const result = await fetchTenantExport()

    expect(result.filename).toBe('hragents-export.json')
  })

  it('keeps the status and the refusal detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ detail: 'needs Postgres' }), { status: 409 }),
        ),
    )

    await expect(fetchTenantExport()).rejects.toMatchObject({
      status: 409,
      detail: 'needs Postgres',
    })
  })

  it('tags a refused credential as a permission error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond({ detail: 'no' }, { status: 403 })))

    await expect(fetchTenantExport()).rejects.toBeInstanceOf(ExportRequestError)
  })
})
