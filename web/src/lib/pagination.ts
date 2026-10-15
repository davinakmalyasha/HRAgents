/**
 * The one place the web walks a paginated list to the end.
 *
 * List endpoints answer with a Page envelope. Screens that still need the
 * whole collection (employee pickers, workspaces that render everything)
 * keep their old `T[]` contract through this loop instead of silently
 * truncating at the first page. Surfaces that grow should move to
 * page-aware queries and drop the loop.
 */

export interface PageResult<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface FetchAllOptions {
  /** Items per request; 200 is the API's ceiling. */
  pageLimit?: number
  /** Hard stop so a server that never reports completion cannot loop forever. */
  maxPages?: number
}

export async function fetchAllPages<T>(
  fetchPage: (limit: number, offset: number) => Promise<PageResult<T> | undefined>,
  { pageLimit = 200, maxPages = 50 }: FetchAllOptions = {},
): Promise<T[]> {
  const items: T[] = []
  for (let page = 0; page < maxPages; page += 1) {
    const result = await fetchPage(pageLimit, page * pageLimit)
    if (!result) {
      if (items.length === 0) return []
      throw new Error(`paginated read stopped after ${items.length} items`)
    }
    items.push(...result.items)
    if (items.length >= result.total || result.items.length === 0) return items
  }
  throw new Error(`paginated read exceeded ${maxPages} pages`)
}
