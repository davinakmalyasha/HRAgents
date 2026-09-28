import { api } from '@/lib/api'
import type { components } from '@/api/schema'

import type {
  EmployeeDocument,
  EmployeeView,
  OnboardingPlan,
  OnboardingTemplate,
} from './onboarding'

export type PlanStartRequest = components['schemas']['PlanStartRequest']
export type StepWaiveRequest = components['schemas']['StepWaiveRequest']
export type StepActionRequest = components['schemas']['StepActionRequest']
export type StepLinkDocumentRequest = components['schemas']['StepLinkDocumentRequest']
export type EmployeeCreate = components['schemas']['EmployeeCreate']

export interface PlanResult {
  status: number
  plan?: OnboardingPlan
}

export async function listPlans(activeOnly: boolean): Promise<OnboardingPlan[]> {
  const { data } = await api.GET('/v1/onboarding/plans', {
    params: { query: { active_only: activeOnly } },
  })
  return data ?? []
}

export async function getPlan(planId: string): Promise<OnboardingPlan | null> {
  const { data } = await api.GET('/v1/onboarding/plans/{plan_id}', {
    params: { path: { plan_id: planId } },
  })
  return data ?? null
}

export async function listTemplates(): Promise<OnboardingTemplate[]> {
  const { data } = await api.GET('/v1/onboarding/templates')
  return data ?? []
}

export async function startPlan(body: PlanStartRequest): Promise<PlanResult> {
  const { data, response } = await api.POST('/v1/onboarding/plans', { body })
  return { status: response.status, plan: data }
}

export async function completeStep(
  planId: string,
  stepKey: string,
  body: StepActionRequest,
): Promise<PlanResult> {
  const { data, response } = await api.POST(
    '/v1/onboarding/plans/{plan_id}/steps/{step_key}/complete',
    { params: { path: { plan_id: planId, step_key: stepKey } }, body },
  )
  return { status: response.status, plan: data }
}

export async function waiveStep(
  planId: string,
  stepKey: string,
  body: StepWaiveRequest,
): Promise<PlanResult> {
  const { data, response } = await api.POST(
    '/v1/onboarding/plans/{plan_id}/steps/{step_key}/waive',
    {
      params: { path: { plan_id: planId, step_key: stepKey } },
      body,
    },
  )
  return { status: response.status, plan: data }
}

export async function linkDocument(
  planId: string,
  stepKey: string,
  body: StepLinkDocumentRequest,
): Promise<PlanResult> {
  const { data, response } = await api.POST(
    '/v1/onboarding/plans/{plan_id}/steps/{step_key}/link-document',
    { params: { path: { plan_id: planId, step_key: stepKey } }, body },
  )
  return { status: response.status, plan: data }
}

export async function documentStatus(planId: string): Promise<Record<string, string>> {
  const { data } = await api.GET('/v1/onboarding/plans/{plan_id}/document-status', {
    params: { path: { plan_id: planId } },
  })
  return data ?? {}
}

export async function listEmployees(status?: string): Promise<EmployeeView[]> {
  const { data } = await api.GET('/v1/employees', {
    params: {
      query:
        status === undefined
          ? {}
          : { status: status as 'active' | 'probation' | 'notice_period' | 'offboarded' },
    },
  })
  return data ?? []
}

export async function createEmployee(body: EmployeeCreate): Promise<EmployeeView | null> {
  const { data, response } = await api.POST('/v1/employees', { body })
  return response.status === 201 ? (data ?? null) : null
}

export async function listEmployeeDocuments(employeeId: string): Promise<EmployeeDocument[]> {
  const { data } = await api.GET('/v1/employees/{employee_id}/documents', {
    params: { path: { employee_id: employeeId } },
  })
  return data ?? []
}
