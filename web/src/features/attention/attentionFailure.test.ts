import { describe, expect, it } from 'vitest'

import { HttpError } from '@/lib/httpError'

import { attentionFailure } from './attention'

describe('attentionFailure', () => {
  it('treats a missing error as a successful read', () => {
    expect(attentionFailure('tasks', undefined)).toBeNull()
    expect(attentionFailure('tasks', null)).toBeNull()
  })

  it('names a 403 as a permission fact', () => {
    expect(attentionFailure('approvals', new HttpError(403))).toEqual({
      queue: 'approvals',
      kind: 'forbidden',
    })
  })

  it('names every other failure as a failure', () => {
    expect(attentionFailure('handoffs', new HttpError(500))).toEqual({
      queue: 'handoffs',
      kind: 'failed',
    })
    expect(attentionFailure('tasks', new Error('offline'))).toEqual({
      queue: 'tasks',
      kind: 'failed',
    })
  })
})
