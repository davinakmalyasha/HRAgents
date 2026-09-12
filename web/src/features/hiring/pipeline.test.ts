import { describe, expect, it } from 'vitest'

import {
  groupIntoStages,
  shortId,
  stageOf,
  waitingLabel,
  type ApplicationSummary,
} from './pipeline'

function application(overrides: Partial<ApplicationSummary> = {}): ApplicationSummary {
  return {
    application_id: '00000000-0000-0000-0000-0000000000aa',
    candidate_id: '00000000-0000-0000-0000-0000000000bb',
    job_id: '00000000-0000-0000-0000-0000000000cc',
    status: 'queued',
    priority_score: 0.5,
    s_tech: null,
    hours_waiting: 3.2,
    ...overrides,
  }
}

describe('pipeline stages', () => {
  it('maps every platform status into a column', () => {
    expect(stageOf('queued')).toBe('intake')
    expect(stageOf('processing')).toBe('intake')
    expect(stageOf('evaluated')).toBe('screened')
    expect(stageOf('gated')).toBe('decision')
    expect(stageOf('scheduled')).toBe('interview')
    expect(stageOf('rejected')).toBe('closed')
    expect(stageOf('withdrawn')).toBe('closed')
  })

  it('groups cards without dropping or duplicating any', () => {
    const applications = [
      application({ application_id: 'a', status: 'queued' }),
      application({ application_id: 'b', status: 'evaluated' }),
      application({ application_id: 'c', status: 'gated' }),
      application({ application_id: 'd', status: 'rejected' }),
      application({ application_id: 'e', status: 'scheduled' }),
    ]

    const columns = groupIntoStages(applications)

    expect(columns.map((column) => column.stage)).toEqual([
      'intake',
      'screened',
      'decision',
      'interview',
      'closed',
    ])
    expect(columns.flatMap((column) => column.items.map((item) => item.application_id))).toEqual([
      'a',
      'b',
      'c',
      'e',
      'd',
    ])
  })

  it('keeps unknown statuses visible in intake instead of hiding them', () => {
    const columns = groupIntoStages([application({ status: 'mystery' })])
    expect(columns[0]?.items).toHaveLength(1)
  })

  it('formats ids and waiting time for dense scanning', () => {
    expect(shortId('12345678-aaaa-bbbb-cccc-ddddeeeeffff')).toBe('12345678')
    expect(waitingLabel(5.4)).toBe('5h')
    expect(waitingLabel(50)).toBe('2d')
  })
})
