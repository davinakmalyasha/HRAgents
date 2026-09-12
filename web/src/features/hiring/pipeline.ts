import type { components } from '@/api/schema'

export type ApplicationSummary = components['schemas']['ApplicationSummary']

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
 * The board is read-only: pipeline status is set by the deterministic worker
 * and append-only human overrides, never by dragging a card around.
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

export function waitingLabel(hours: number): string {
  if (hours < 24) {
    return `${Math.round(hours)}h`
  }
  return `${Math.round(hours / 24)}d`
}
