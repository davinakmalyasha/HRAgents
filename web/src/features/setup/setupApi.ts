import type { components } from '@/api/schema'
import { api } from '@/lib/api'

export type SetupStatus = components['schemas']['SetupStatusView']
export type StarterSeed = components['schemas']['StarterSeedView']

/** What this install still needs. Admin-only; the card hides on a refusal. */
export async function readSetup(): Promise<SetupStatus> {
  const { data } = await api.GET('/v1/setup')
  if (data === undefined) {
    throw new Error('setup status unavailable')
  }
  return data
}

/** Create the missing starter checklists and empty rate-table shells. */
export async function seedStarters(): Promise<StarterSeed> {
  const { data } = await api.POST('/v1/setup/starters')
  if (data === undefined) {
    throw new Error('starter seed failed')
  }
  return data
}
