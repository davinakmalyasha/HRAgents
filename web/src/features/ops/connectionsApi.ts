import { api } from '@/lib/api'
import type { components } from '@/api/schema'

export type McpServerView = components['schemas']['McpServerView']
export type McpServerConfig = components['schemas']['McpServerConfig']
export type McpProbeResult = components['schemas']['McpProbeResult']

/** A non-2xx answer from the connections endpoints, with the API's detail. */
export class ConnectionsRequestError extends Error {
  constructor(
    readonly status: number,
    readonly detail?: string,
  ) {
    super(detail ?? `connections request failed with status ${status}`)
    this.name = 'ConnectionsRequestError'
  }
}

async function failure(response: Response): Promise<ConnectionsRequestError> {
  let detail: string | undefined
  try {
    const body = (await response.json()) as {
      detail?: unknown
    }
    if (typeof body.detail === 'string') {
      detail = body.detail
    } else if (Array.isArray(body.detail)) {
      detail = body.detail
        .map((item) => (item as { msg?: string }).msg)
        .filter((msg): msg is string => typeof msg === 'string')
        .join('; ')
    }
  } catch {
    detail = undefined
  }
  return new ConnectionsRequestError(response.status, detail)
}

export async function listConnections(): Promise<McpServerView[]> {
  const { data, response } = await api.GET('/v1/ops/mcp/servers')
  if (!response.ok) throw await failure(response)
  return data ?? []
}

export async function saveConnection(config: McpServerConfig): Promise<McpServerView> {
  const { data, response } = await api.PUT('/v1/ops/mcp/servers/{name}', {
    params: { path: { name: config.name } },
    body: config,
  })
  if (!response.ok) throw await failure(response)
  if (data === undefined) throw new ConnectionsRequestError(response.status)
  return data
}

export async function removeConnection(name: string): Promise<void> {
  const { response } = await api.DELETE('/v1/ops/mcp/servers/{name}', {
    params: { path: { name } },
  })
  if (!response.ok) throw await failure(response)
}

export async function testConnection(name: string): Promise<McpProbeResult> {
  const { data, response } = await api.GET('/v1/ops/mcp/servers/{name}/test', {
    params: { path: { name } },
  })
  if (!response.ok) throw await failure(response)
  if (data === undefined) throw new ConnectionsRequestError(response.status)
  return data
}
