import type { components } from '@/api/schema'
import { HttpError } from '@/lib/httpError'
import { isWorkspaceId, type WorkspaceId } from '@/lib/workspaces'

export type Approval = components['schemas']['ApprovalView']
export type Task = components['schemas']['TaskView']
export type Handoff = components['schemas']['HandoffView']

export type AttentionTone = 'error' | 'waiting'
export type AttentionQueue = 'approvals' | 'tasks' | 'handoffs'

export interface AttentionFailure {
  queue: AttentionQueue
  kind: 'forbidden' | 'failed'
}

/**
 * A queue that did not answer is not an empty queue.
 *
 * A role-scoped 403 means "you may not see this" and is a permission fact, not
 * a calm queue; anything else means the check itself failed. Collapsing both to
 * ``[]`` made the home page say "nothing needs you" when it had not asked.
 */
export function attentionFailure(queue: AttentionQueue, error: unknown): AttentionFailure | null {
  if (error === null || error === undefined) {
    return null
  }
  return {
    queue,
    kind: error instanceof HttpError && error.status === 403 ? 'forbidden' : 'failed',
  }
}
export type AttentionSource = 'approval' | 'task' | 'handoff'

export interface AttentionItem {
  id: string
  source: AttentionSource
  title: string
  detail: string
  workspace: WorkspaceId | null
  tone: AttentionTone
  dueAt: string | null
}

export interface AttentionInput {
  approvals: Approval[]
  tasks: Task[]
  handoffs: Handoff[]
}

export interface Attention {
  needsYou: AttentionItem[]
  watching: AttentionItem[]
}

const APPROVAL_WORKSPACES: Partial<Record<Approval['subject'], WorkspaceId>> = {
  leave_request: 'leave',
  payroll_run: 'payroll',
  payroll_anomaly: 'payroll',
  contract: 'records',
  candidate_rejection: 'hiring',
  candidate_anomaly: 'hiring',
  offer: 'hiring',
  document_validation: 'records',
  onboarding_step: 'onboarding',
  offboarding_step: 'offboarding',
  erasure_request: 'compliance',
  data_change: 'records',
}

function byDue(items: AttentionItem[]): AttentionItem[] {
  return [...items].sort((left, right) => {
    const leftAt = left.dueAt ?? '9999'
    const rightAt = right.dueAt ?? '9999'
    return leftAt.localeCompare(rightAt)
  })
}

/** Partition live work into "decisions gated on you" and "agents are handling it". */
/**
 * The workspace most of these items live in.
 *
 * A section-level "view all" link needs one destination, and the items in a
 * section can come from several workspaces. The most common one is the honest
 * answer: it is where most of the work actually is.
 */
export function dominantWorkspace(items: AttentionItem[]): WorkspaceId | null {
  const counts = new Map<WorkspaceId, number>()
  for (const item of items) {
    if (item.workspace === null) {
      continue
    }
    counts.set(item.workspace, (counts.get(item.workspace) ?? 0) + 1)
  }
  let best: WorkspaceId | null = null
  let bestCount = 0
  for (const [workspace, count] of counts) {
    if (count > bestCount) {
      best = workspace
      bestCount = count
    }
  }
  return best
}

export function buildAttention(input: AttentionInput): Attention {
  const needsYou: AttentionItem[] = []
  const watching: AttentionItem[] = []

  for (const approval of input.approvals) {
    if (approval.status !== 'pending') {
      continue
    }
    const item: AttentionItem = {
      id: `approval-${approval.id}`,
      source: 'approval',
      title: approval.title,
      detail: approval.summary,
      workspace: APPROVAL_WORKSPACES[approval.subject] ?? null,
      tone: approval.is_overdue ? 'error' : 'waiting',
      dueAt: approval.sla_deadline,
    }
    if (approval.is_overdue) {
      needsYou.push(item)
    } else {
      watching.push(item)
    }
  }

  for (const task of input.tasks) {
    const related = task.related_subject ?? undefined
    const item: AttentionItem = {
      id: `task-${task.id}`,
      source: 'task',
      title: task.title,
      detail: task.description,
      workspace: isWorkspaceId(related) ? related : null,
      tone: task.is_overdue ? 'error' : 'waiting',
      dueAt: task.due_on,
    }
    if (task.is_overdue) {
      needsYou.push(item)
    } else {
      watching.push(item)
    }
  }

  for (const handoff of input.handoffs) {
    needsYou.push({
      id: `handoff-${handoff.id}`,
      source: 'handoff',
      title: handoff.text,
      detail: handoff.requested_by,
      workspace: handoff.target_workspace,
      tone: 'waiting',
      dueAt: handoff.created_at,
    })
  }

  return { needsYou: byDue(needsYou), watching: byDue(watching) }
}
