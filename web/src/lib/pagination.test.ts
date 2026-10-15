import { describe, expect, it, vi } from 'vitest'

import { fetchAllPages, type PageResult } from './pagination'

function page<T>(items: T[], total: number, limit: number, offset: number): PageResult<T> {
  return { items, total, limit, offset }
}

describe('fetchAllPages', () => {
  it('walks pages until the total is reached', async () => {
    const fetchPage = vi
      .fn<(limit: number, offset: number) => Promise<PageResult<string>>>()
      .mockResolvedValueOnce(page(['a', 'b'], 5, 2, 0))
      .mockResolvedValueOnce(page(['c', 'd'], 5, 2, 2))
      .mockResolvedValueOnce(page(['e'], 5, 2, 4))

    const items = await fetchAllPages(fetchPage, { pageLimit: 2 })

    expect(items).toEqual(['a', 'b', 'c', 'd', 'e'])
    expect(fetchPage).toHaveBeenCalledTimes(3)
    expect(fetchPage).toHaveBeenLastCalledWith(2, 4)
  })

  it('stops on the first page when everything fits', async () => {
    const fetchPage = vi.fn().mockResolvedValue(page(['a'], 1, 200, 0))
    expect(await fetchAllPages(fetchPage)).toEqual(['a'])
    expect(fetchPage).toHaveBeenCalledTimes(1)
  })

  it('treats an empty collection and an empty first response as empty', async () => {
    const empty = vi.fn().mockResolvedValue(page([], 0, 200, 0))
    expect(await fetchAllPages(empty)).toEqual([])

    const missing = vi.fn().mockResolvedValue(undefined)
    expect(await fetchAllPages(missing)).toEqual([])
  })

  it('returns early when a page comes back empty despite a larger total', async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce(page(['a'], 3, 1, 0))
      .mockResolvedValueOnce(page([], 3, 1, 1))
    expect(await fetchAllPages(fetchPage, { pageLimit: 1 })).toEqual(['a'])
  })

  it('refuses to silently truncate when a later page fails', async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce(page(['a'], 2, 1, 0))
      .mockResolvedValueOnce(undefined)
    await expect(fetchAllPages(fetchPage, { pageLimit: 1 })).rejects.toThrow('stopped after 1')
  })

  it('refuses to loop forever when the server never finishes', async () => {
    const fetchPage = vi.fn().mockResolvedValue(page(['a'], 1000, 1, 0))
    await expect(fetchAllPages(fetchPage, { pageLimit: 1, maxPages: 3 })).rejects.toThrow(
      'exceeded 3 pages',
    )
  })
})
