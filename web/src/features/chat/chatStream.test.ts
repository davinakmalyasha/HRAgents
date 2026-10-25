import { afterEach, describe, expect, it, vi } from 'vitest'

import { streamHr } from './chatApi'

function sse(frames: string): Response {
  return new Response(new TextEncoder().encode(frames), {
    status: 200,
    headers: { 'content-type': 'text/event-stream' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('streamHr', () => {
  it('reports the routed workspace before the reply', async () => {
    const frames = [
      'event: routing',
      'data: {"workspace":"leave","reason":"keyword","matched_keywords":["cuti"],"handoff_options":[]}',
      '',
      'event: reply',
      'data: {"conversation_id":"c-1","workspace":"leave","route_reason":"keyword","matched_keywords":[],"handoff_options":[],"answer":"Halo","citations":[],"escalate":false}',
      '',
      '',
    ].join('\n')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sse(frames)))
    const routing: string[] = []
    const replies: string[] = []

    const result = await streamHr(
      { message: 'cuti?', workspace: 'leave', conversationId: null },
      {
        onRouting: (decision) => routing.push(decision.workspace),
        onReply: (reply) => replies.push(reply.answer),
      },
    )

    expect(routing).toEqual(['leave'])
    expect(replies).toEqual(['Halo'])
    expect(result.status).toBe(200)
    expect(result.reply?.answer).toBe('Halo')
  })

  it('returns the status for a refused conversation instead of parsing a body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 409 })))

    const result = await streamHr({ message: 'x', workspace: 'payroll' }, {})

    expect(result).toEqual({ status: 409 })
    expect(result.reply).toBeUndefined()
  })
})
