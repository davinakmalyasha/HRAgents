import type { components } from '@/api/schema'

export type ApplicationSummary = components['schemas']['ApplicationSummary']
export type ApplicationStatus = components['schemas']['ApplicationStatus']

export const PIPELINE_STAGES = ['intake', 'screened', 'decision', 'interview', 'closed'] as const
export type PipelineStage = (typeof PIPELINE_STAGES)[number]

const STAGE_BY_STATUS: Record<string, PipelineStage> = {
  queued: 'intake',
  processing: 'intake',
  evaluated: 'screened',
  gated: 'decision',
  scheduled: 'interview',
  rejected: 'closed',
  withdrawn: 'closed',
}

export function stageOf(status: string): PipelineStage {
  return STAGE_BY_STATUS[status] ?? 'intake'
}

export interface PipelineColumn {
  stage: PipelineStage
  items: ApplicationSummary[]
}

/**
 * Group pipeline cards into the five columns HR actually reads.
 *
 * Stages derive from deterministic statuses; manual moves are only *requests*
 * that go through the gated stage endpoint (`intentForDrop` mirrors the
 * server's table for routing, never as authority).
 */
export function groupIntoStages(applications: ApplicationSummary[]): PipelineColumn[] {
  const columns: PipelineColumn[] = PIPELINE_STAGES.map((stage) => ({ stage, items: [] }))
  const byStage = new Map(columns.map((column) => [column.stage, column]))

  for (const application of applications) {
    byStage.get(stageOf(application.status))?.items.push(application)
  }
  return columns
}

export function shortId(id: string): string {
  return id.slice(0, 8)
}

export type DropIntent =
  | { kind: 'system' }
  | { kind: 'noop' }
  | { kind: 'move'; status: ApplicationStatus }
  | { kind: 'choice' }

/**
 * Resolve a cross-column drop into the board's transition intent.
 *
 * Mirrors `docs/architecture/board-transitions.md` for UX routing only — the
 * stage endpoint re-validates every move, so a stale client can never bypass
 * a gate.
 */
export function intentForDrop(currentStatus: string, targetStage: PipelineStage): DropIntent {
  if (stageOf(currentStatus) === targetStage) {
    return { kind: 'noop' }
  }
  if (currentStatus === 'queued' || currentStatus === 'processing') {
    return { kind: 'system' }
  }
  if (targetStage === 'intake' || targetStage === 'screened') {
    return { kind: 'system' }
  }
  if (targetStage === 'closed') {
    return { kind: 'choice' }
  }
  if (targetStage === 'decision') {
    return { kind: 'move', status: 'gated' }
  }
  return { kind: 'move', status: 'scheduled' }
}

export function waitingLabel(hours: number): string {
  if (hours < 24) {
    return `${Math.round(hours)}h`
  }
  return `${Math.round(hours / 24)}d`
}
