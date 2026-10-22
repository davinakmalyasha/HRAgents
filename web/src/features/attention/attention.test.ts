import { describe, expect, it } from 'vitest'

import { dominantWorkspace, type AttentionItem } from './attention'

function item(overrides: Partial<AttentionItem>): AttentionItem {
  return {
    id: 'item-1',
    source: 'task',
    title: 'Collect contract',
    detail: '',
    workspace: null,
    tone: 'waiting',
    dueAt: null,
    ...overrides,
  }
}

describe('dominantWorkspace', () => {
  it('picks the workspace most of the items live in', () => {
    const items = [
      item({ id: 'a', workspace: 'leave' }),
      item({ id: 'b', workspace: 'leave' }),
      item({ id: 'c', workspace: 'onboarding' }),
    ]

    expect(dominantWorkspace(items)).toBe('leave')
  })

  it('ignores items with no workspace', () => {
    const items = [item({ id: 'a' }), item({ id: 'b' }), item({ id: 'c', workspace: 'records' })]

    expect(dominantWorkspace(items)).toBe('records')
  })

  it('has no answer when nothing is routable', () => {
    expect(dominantWorkspace([item({ id: 'a' })])).toBeNull()
    expect(dominantWorkspace([])).toBeNull()
  })
})
