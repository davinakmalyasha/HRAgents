import type { components } from '@/api/schema'

export type JobView = components['schemas']['JobView']
export type JobStatus = components['schemas']['JobStatus']
export type ScoreDimension = components['schemas']['ScoreDimension']
export type Seniority = components['schemas']['Seniority']
export type JobFamily = components['schemas']['JobFamily']

export const JOB_STATUSES = [
  'draft',
  'open',
  'paused',
  'closed',
] as const satisfies readonly JobStatus[]

export const SENIORITIES = [
  'intern',
  'junior',
  'mid',
  'senior',
  'lead',
  'principal',
] as const satisfies readonly Seniority[]

/**
 * Occupation families, which select the scoring rubric on the server.
 *
 * Every value here has a `DimensionTemplate` (`services/dimensions.py`), so a family
 * cannot be picked in the UI and then score by evidence it has no vocabulary for. The
 * server rejects an unknown family outright rather than falling back.
 */
export const JOB_FAMILIES = [
  'engineering',
  'finance',
  'education',
  'healthcare',
  'legal',
  'operations',
  'sales',
  'general',
] as const satisfies readonly JobFamily[]

export const DEFAULT_JOB_FAMILY: JobFamily = 'engineering'

export const DIMENSIONS = [
  'technical_depth',
  'stack_alignment',
  'systems_literacy',
  'verifiable_certifications',
] as const satisfies readonly ScoreDimension[]

export const DEFAULT_WEIGHTS: Record<ScoreDimension, number> = {
  technical_depth: 0.4,
  stack_alignment: 0.3,
  systems_literacy: 0.2,
  verifiable_certifications: 0.1,
}

export const WEIGHT_TOLERANCE = 1e-3

/** Mirrors the server lifecycle (`JOB_TRANSITIONS` in `services/recruiting.py`). */
export const JOB_TRANSITIONS: Record<JobStatus, readonly JobStatus[]> = {
  draft: ['open', 'closed'],
  open: ['paused', 'closed'],
  paused: ['open', 'closed'],
  closed: [],
}

export type WeightsParse =
  { ok: true; weights: Record<ScoreDimension, number> } | { ok: false; reason: 'number' | 'sum' }

export function parseList(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter((item) => item !== '')
}

export function formatList(items: string[]): string {
  return items.join(', ')
}

export function weightsTotal(weights: Record<ScoreDimension, number>): number {
  return DIMENSIONS.reduce((total, dimension) => total + (weights[dimension] ?? 0), 0)
}

export function weightsSumToOne(weights: Record<ScoreDimension, number>): boolean {
  return Math.abs(weightsTotal(weights) - 1) <= WEIGHT_TOLERANCE
}

export function parseWeights(input: Record<ScoreDimension, string>): WeightsParse {
  const parsed = {} as Record<ScoreDimension, number>
  for (const dimension of DIMENSIONS) {
    const value = Number(input[dimension])
    if (input[dimension].trim() === '' || !Number.isFinite(value) || value < 0) {
      return { ok: false, reason: 'number' }
    }
    parsed[dimension] = value
  }
  if (!weightsSumToOne(parsed)) {
    return { ok: false, reason: 'sum' }
  }
  return { ok: true, weights: parsed }
}

export function transitionLabelKey(from: JobStatus, to: JobStatus): string {
  if (to === 'closed') {
    return 'jobs.actions.close'
  }
  if (to === 'paused') {
    return 'jobs.actions.pause'
  }
  return from === 'paused' ? 'jobs.actions.reopen' : 'jobs.actions.open'
}
