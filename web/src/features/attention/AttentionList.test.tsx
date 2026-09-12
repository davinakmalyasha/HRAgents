import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import i18n from '@/i18n'

import { AttentionList } from './AttentionList'
import { buildAttention, type Approval, type Handoff, type Task } from './attention'

function approval(overrides: Partial<Approval> = {}): Approval {
  return {
    id: 'a1',
    subject: 'leave_request',
    subject_id: 'subject-1',
    title: 'Leave request — 3 days',
    summary: 'Budi asks for leave',
    requested_by: 'budi',
    requested_by_agent: false,
    assignee_role: 'manager',
    urgency: 'normal',
    status: 'pending',
    escalation_count: 0,
    created_at: '2026-09-01T00:00:00Z',
    sla_deadline: '2026-09-10T00:00:00Z',
    is_overdue: false,
    ...overrides,
  }
}

function task(overrides: Partial<Task> = {}): Task {
  return {
    id: 't1',
    title: 'Collect signed contract',
    description: 'Budi',
    assignee_role: null,
    due_on: '2026-09-20',
    priority: 'normal',
    status: 'open',
    source: 'manual',
    related_subject: 'onboarding',
    related_id: null,
    created_by: 'hr',
    is_overdue: false,
    ...overrides,
  }
}

function handoff(overrides: Partial<Handoff> = {}): Handoff {
  return {
    id: 'h1',
    source_workspace: 'policy',
    target_workspace: 'payroll',
    text: 'Prepare THR for Budi',
    status: 'open',
    requested_by: 'hr-admin',
    created_at: '2026-09-05T00:00:00Z',
    updated_at: '2026-09-05T00:00:00Z',
    ...overrides,
  }
}

describe('buildAttention', () => {
  it('splits overdue decisions from agent-handled work', () => {
    const { needsYou, watching } = buildAttention({
      approvals: [approval({ is_overdue: true })],
      tasks: [task()],
      handoffs: [],
    })

    expect(needsYou).toHaveLength(1)
    expect(needsYou[0]?.tone).toBe('error')
    expect(watching).toHaveLength(1)
    expect(watching[0]?.tone).toBe('waiting')
  })

  it('routes open handoffs into needs-you with their target workspace', () => {
    const { needsYou } = buildAttention({ approvals: [], tasks: [], handoffs: [handoff()] })

    expect(needsYou[0]?.source).toBe('handoff')
    expect(needsYou[0]?.workspace).toBe('payroll')
  })

  it('maps approval subjects to their workspace', () => {
    const { watching } = buildAttention({
      approvals: [approval({ subject: 'erasure_request' })],
      tasks: [],
      handoffs: [],
    })

    expect(watching[0]?.workspace).toBe('compliance')
  })

  it('keeps unknown-related tasks unlinked', () => {
    const { watching } = buildAttention({
      approvals: [],
      tasks: [task({ related_subject: 'not-a-workspace' })],
      handoffs: [],
    })

    expect(watching[0]?.workspace).toBeNull()
  })

  it('sorts by deadline with missing deadlines last', () => {
    const { needsYou } = buildAttention({
      approvals: [approval({ id: 'late', is_overdue: true, sla_deadline: '2026-09-30T00:00:00Z' })],
      tasks: [
        task({ id: 'early', is_overdue: true, due_on: '2026-09-01' }),
        task({ id: 'undated', is_overdue: true, due_on: null }),
      ],
      handoffs: [],
    })

    expect(needsYou.map((item) => item.id)).toEqual(['task-early', 'approval-late', 'task-undated'])
  })

  it('ignores decided approvals', () => {
    const { needsYou, watching } = buildAttention({
      approvals: [approval({ status: 'approved' })],
      tasks: [],
      handoffs: [],
    })

    expect(needsYou).toHaveLength(0)
    expect(watching).toHaveLength(0)
  })
})

describe('AttentionList', () => {
  it('renders items with status label and a deep link to the workspace queue', () => {
    const { needsYou } = buildAttention({
      approvals: [approval({ is_overdue: true })],
      tasks: [],
      handoffs: [],
    })

    render(
      <MemoryRouter>
        <AttentionList items={needsYou} />
      </MemoryRouter>,
    )

    expect(screen.getByText('Leave request — 3 days')).toBeInTheDocument()
    expect(screen.getByText(i18n.t('status.error'))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: i18n.t('workspaces.leave.name') })).toHaveAttribute(
      'href',
      '/w/leave?room=queue',
    )
  })
})
