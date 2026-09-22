import { describe, expect, it } from 'vitest'

import {
  DEFAULT_WEIGHTS,
  JOB_TRANSITIONS,
  WEIGHT_TOLERANCE,
  formatList,
  parseList,
  parseWeights,
  transitionLabelKey,
  weightsSumToOne,
  weightsTotal,
} from './jobForm'

describe('parseList', () => {
  it('splits on commas and new lines, trimming and dropping blanks', () => {
    expect(parseList('Python, FastAPI\n Postgres ,, ')).toEqual(['Python', 'FastAPI', 'Postgres'])
  })

  it('returns an empty list for blank input', () => {
    expect(parseList('  \n , ')).toEqual([])
  })
})

describe('formatList', () => {
  it('round-trips through parseList', () => {
    const items = ['Python', 'FastAPI', 'Postgres']
    expect(parseList(formatList(items))).toEqual(items)
  })
})

describe('weights', () => {
  it('ships defaults that sum to one', () => {
    expect(weightsTotal(DEFAULT_WEIGHTS)).toBeCloseTo(1)
    expect(weightsSumToOne(DEFAULT_WEIGHTS)).toBe(true)
  })

  it('accepts totals within the tolerance', () => {
    const weights = { ...DEFAULT_WEIGHTS, technical_depth: 0.4 + WEIGHT_TOLERANCE / 2 }
    expect(weightsSumToOne(weights)).toBe(true)
  })

  it('rejects a total outside the tolerance', () => {
    expect(weightsSumToOne({ ...DEFAULT_WEIGHTS, technical_depth: 0.5 })).toBe(false)
  })

  it('parses a valid weight set', () => {
    const parsed = parseWeights({
      technical_depth: '0.5',
      stack_alignment: '0.2',
      systems_literacy: '0.2',
      verifiable_certifications: '0.1',
    })

    expect(parsed).toEqual({
      ok: true,
      weights: {
        technical_depth: 0.5,
        stack_alignment: 0.2,
        systems_literacy: 0.2,
        verifiable_certifications: 0.1,
      },
    })
  })

  it('rejects non-numbers and blanks', () => {
    const parsed = parseWeights({
      technical_depth: '',
      stack_alignment: '0.3',
      systems_literacy: '0.2',
      verifiable_certifications: '0.1',
    })

    expect(parsed).toEqual({ ok: false, reason: 'number' })
  })

  it('rejects negative weights', () => {
    const parsed = parseWeights({
      technical_depth: '-0.1',
      stack_alignment: '0.5',
      systems_literacy: '0.3',
      verifiable_certifications: '0.3',
    })

    expect(parsed).toEqual({ ok: false, reason: 'number' })
  })

  it('rejects sets that do not sum to one', () => {
    const parsed = parseWeights({
      technical_depth: '0.9',
      stack_alignment: '0.3',
      systems_literacy: '0.2',
      verifiable_certifications: '0.1',
    })

    expect(parsed).toEqual({ ok: false, reason: 'sum' })
  })
})

describe('JOB_TRANSITIONS', () => {
  it('mirrors the server lifecycle', () => {
    expect([...JOB_TRANSITIONS.draft].sort()).toEqual(['closed', 'open'])
    expect([...JOB_TRANSITIONS.open].sort()).toEqual(['closed', 'paused'])
    expect([...JOB_TRANSITIONS.paused].sort()).toEqual(['closed', 'open'])
    expect(JOB_TRANSITIONS.closed).toEqual([])
  })
})

describe('transitionLabelKey', () => {
  it('opens from draft and reopens from paused', () => {
    expect(transitionLabelKey('draft', 'open')).toBe('jobs.actions.open')
    expect(transitionLabelKey('paused', 'open')).toBe('jobs.actions.reopen')
  })

  it('labels pause and close', () => {
    expect(transitionLabelKey('open', 'paused')).toBe('jobs.actions.pause')
    expect(transitionLabelKey('draft', 'closed')).toBe('jobs.actions.close')
  })
})
