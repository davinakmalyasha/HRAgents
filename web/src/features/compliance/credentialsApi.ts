import type { components } from '@/api/schema'

import { api } from '@/lib/api'
import { fetchAllPages } from '@/lib/pagination'

export type CredentialEntryInput = components['schemas']['CredentialEntryInput']
export type CredentialEntryView = components['schemas']['CredentialEntryView']
export type CredentialRegistryView = components['schemas']['CredentialRegistryView']
export type VerificationStatus = components['schemas']['VerificationStatus']

export class CredentialRequestError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string | null = null,
  ) {
    super(detail ?? `credential request failed with status ${status}`)
    this.name = 'CredentialRequestError'
  }
}

async function failure(response: Response): Promise<CredentialRequestError> {
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
  return new CredentialRequestError(response.status, detail)
}

export async function listCredentialRegistries(): Promise<CredentialRegistryView[]> {
  return fetchAllPages(async (limit, offset) => {
    const { data, response } = await api.GET('/v1/credentials', {
      params: { query: { limit, offset } },
    })
    if (!response.ok) throw await failure(response)
    return data ?? undefined
  })
}

export async function createCredentialRegistry(
  name: string,
  issuer: string,
): Promise<CredentialRegistryView> {
  const { data, response } = await api.POST('/v1/credentials', {
    body: { name, issuer },
  })
  if (!response.ok) throw await failure(response)
  if (data === undefined) throw new CredentialRequestError(response.status)
  return data
}

export async function setCredentialEntries(
  registryId: string,
  entries: CredentialEntryInput[],
): Promise<CredentialRegistryView> {
  const { data, response } = await api.PUT('/v1/credentials/{registry_id}/entries', {
    params: { path: { registry_id: registryId } },
    body: { entries },
  })
  if (!response.ok) throw await failure(response)
  if (data === undefined) throw new CredentialRequestError(response.status)
  return data
}

export async function verifyCredentialRegistry(
  registryId: string,
  sourceNote: string,
): Promise<CredentialRegistryView> {
  const { data, response } = await api.POST('/v1/credentials/{registry_id}/verify', {
    params: { path: { registry_id: registryId } },
    body: { source_note: sourceNote },
  })
  if (!response.ok) throw await failure(response)
  if (data === undefined) throw new CredentialRequestError(response.status)
  return data
}

export async function deleteCredentialRegistry(registryId: string): Promise<void> {
  const { response } = await api.DELETE('/v1/credentials/{registry_id}', {
    params: { path: { registry_id: registryId } },
  })
  if (!response.ok) throw await failure(response)
}

/** Why the import is a text format: an operator pastes what the issuer showed. */
export function entryToLine(entry: CredentialEntryView): string {
  const parts = [entry.name, entry.status]
  if (entry.credential_id) parts.push(entry.credential_id)
  if (entry.expires_on) parts.push(entry.expires_on)
  if (entry.notes) parts.push(entry.notes)
  return parts.join(' | ')
}

export class EntryParseError extends Error {
  constructor(readonly line: number) {
    super(`line ${line}`)
    this.name = 'EntryParseError'
  }
}

const STATUSES = new Set<VerificationStatus>(['verified', 'failed', 'expired'])

/**
 * Parse `name | status | credential-id | YYYY-MM-DD | notes` per line.
 *
 * Only the status is constrained beyond the name: an operator may not know a
 * credential id or an expiry, and the registry does not invent one. A blank
 * line is skipped; a bad status or date is a refusal naming the line.
 */
export function parseEntries(text: string): CredentialEntryInput[] {
  const entries: CredentialEntryInput[] = []
  text.split(/\r?\n/).forEach((raw, index) => {
    const line = raw.trim()
    if (line === '') return
    const fields = line.split('|').map((field) => field.trim())
    const name = fields[0] ?? ''
    if (name === '') throw new EntryParseError(index + 1)
    const status = (fields[1] ?? '') === '' ? 'verified' : fields[1]
    if (status === undefined || !STATUSES.has(status as VerificationStatus)) {
      throw new EntryParseError(index + 1)
    }
    const expires = fields[3] ?? ''
    if (expires !== '' && !/^\d{4}-\d{2}-\d{2}$/.test(expires)) {
      throw new EntryParseError(index + 1)
    }
    entries.push({
      name,
      status: status as VerificationStatus,
      credential_id: fields[2] ? fields[2] : null,
      expires_on: expires === '' ? null : expires,
      notes: fields[4] ? fields.slice(4).join(' | ') : null,
    })
  })
  if (entries.length === 0) throw new EntryParseError(1)
  return entries
}
