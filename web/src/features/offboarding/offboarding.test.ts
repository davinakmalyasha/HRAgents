import { describe, expect, it } from 'vitest'

import type { components } from '@/api/schema'

import {
  STEP_STATUS_LABELS,
  blockingAssets,
  canFinalise,
  finalisationBlockers,
  isTerminal,
  outstandingRequiredSteps,
  type StepStatus,
} from './offboardingApi'

type Plan = components['schemas']['hr_agents__api__offboarding_schemas__PlanView']
type Step = components['schemas']['hr_agents__api__offboarding_schemas__StepView']
type Asset = components['schemas']['AssetView']

function step(overrides: Partial<Step> = {}): Step {
  return {
    key: 'recover_assets',
    title: 'Recover company assets',
    kind: 'asset_return',
    required: true,
    requires_human_signoff: false,
    assignee_role: 'hr_admin',
    status: 'pending',
    document_kind: null,
    due_on: null,
    linked_task_id: null,
    completed_by: null,
    completed_at: null,
    note: null,
    scheduled_for: null,
    ...overrides,
  }
}

function plan(overrides: Partial<Plan> = {}): Plan {
  return {
    id: 'plan-1',
    employee_id: 'emp-1',
    template_id: 'tpl-1',
    template_name: 'Standard resignation',
    reason: 'resignation',
    last_working_day: '2026-11-30',
    started_at: '2026-10-01T00:00:00Z',
    completed_at: null,
    final_pay_run_id: null,
    handover_notes: [],
    is_complete: false,
    progress: 0,
    steps: [step()],
    ...overrides,
  }
}

function asset(overrides: Partial<Asset> = {}): Asset {
  return {
    id: 'asset-1',
    employee_id: 'emp-1',
    plan_id: 'plan-1',
    name: 'Laptop',
    asset_code: 'LT-0042',
    category: 'Hardware',
    assigned_on: '2024-02-01',
    status: 'assigned',
    returned_on: null,
    returned_by: null,
    note: null,
    blocks_clearance: true,
    ...overrides,
  }
}

describe('only done and waived are terminal', () => {
  it('treats a waiver as terminal but not as completed', () => {
    /**A waived step stops blocking, but it is not "done" -- conflating the two would
    report an exit interview as completed when HR skipped it.
    */
    expect(isTerminal('done')).toBe(true)
    expect(isTerminal('waived')).toBe(true)
    for (const status of ['pending', 'in_progress', 'blocked'] as StepStatus[]) {
      expect(isTerminal(status)).toBe(false)
    }
  })

  it('has a label for every status the API can return', () => {
    const everyStatus: StepStatus[] = ['pending', 'in_progress', 'blocked', 'done', 'waived']
    for (const status of everyStatus) {
      expect(STEP_STATUS_LABELS[status]).toBeTruthy()
    }
  })
})

describe('only required steps block leaving', () => {
  it('ignores outstanding optional steps', () => {
    /**`PlanView.is_complete` is `all(step.complete for step in required_steps)`.
    Treating an optional step as a blocker would make an offboarding look stuck over
    something nobody agreed to.
    */
    const subject = plan({
      is_complete: false,
      steps: [
        step({ key: 'optional_wellness', required: false, status: 'pending' }),
        step({ key: 'required_exit', required: true, status: 'done' }),
      ],
    })

    expect(outstandingRequiredSteps(subject)).toHaveLength(0)
  })

  it('counts a waived required step as resolved', () => {
    const subject = plan({
      steps: [step({ status: 'waived', note: 'No laptop was ever issued' })],
    })

    expect(outstandingRequiredSteps(subject)).toHaveLength(0)
  })

  it('counts a blocked required step as outstanding', () => {
    const subject = plan({ steps: [step({ status: 'blocked' })] })
    expect(outstandingRequiredSteps(subject)).toHaveLength(1)
  })
})

describe('assets block clearance by the server flag, not by a derived status', () => {
  it('reads blocks_clearance rather than inferring it', () => {
    /**"returned", "missing" and "written_off" all clear an asset, and only the server
    knows which applies. Deriving from `status` would be a second, divergent opinion.
    */
    const subject = [
      asset({ id: 'a1', status: 'returned', blocks_clearance: false }),
      asset({ id: 'a2', status: 'missing', blocks_clearance: true }),
      asset({ id: 'a3', status: 'written_off', blocks_clearance: false }),
    ]

    expect(blockingAssets(subject).map((item) => item.id)).toEqual(['a2'])
  })
})

describe('finalisation is gated on both steps and assets', () => {
  it('blocks while a required step is outstanding', () => {
    const subject = plan({ steps: [step({ status: 'pending' })] })
    expect(finalisationBlockers(subject, [])).toContain('steps')
    expect(canFinalise(subject, [])).toBe(false)
  })

  it('blocks while an asset is outstanding, even with every step done', () => {
    /**The steps and the assets are two independent gates. Clearing both is what
    "assets not cleared" in the server's refusal refers to.
    */
    const subject = plan({ steps: [step({ status: 'done' })] })
    const assets = [asset({ blocks_clearance: true })]

    expect(finalisationBlockers(subject, assets)).toEqual(['assets'])
    expect(canFinalise(subject, assets)).toBe(false)
  })

  it('allows finalisation only when both are clear', () => {
    const subject = plan({
      steps: [step({ status: 'done' }), step({ key: 'exit', status: 'waived' })],
    })
    const assets = [asset({ blocks_clearance: false })]

    expect(finalisationBlockers(subject, assets)).toEqual([])
    expect(canFinalise(subject, assets)).toBe(true)
  })

  it('refuses to finalise a plan that is already complete', () => {
    /**`OffboardingService.complete_plan` refuses a completed plan, so offering the button
    would produce a conflict the user cannot act on.
    */
    const subject = plan({ is_complete: true, completed_at: '2026-11-01T00:00:00Z' })
    expect(canFinalise(subject, [])).toBe(false)
  })

  it('names both blockers when there are two', () => {
    const subject = plan({ steps: [step({ status: 'pending' })] })
    expect(finalisationBlockers(subject, [asset()])).toEqual(['steps', 'assets'])
  })
})
