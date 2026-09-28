import { api } from '@/lib/api'
import type { components } from '@/api/schema'

import type { RecordsContract, RecordsDocument, RecordsEmployee, RecordsOrgUnit } from './records'

export type OrgUnitCreate = components['schemas']['OrgUnitCreate']
export type DocumentVerifyRequest = components['schemas']['DocumentVerifyRequest']
export type EmployeeCreate = components['schemas']['EmployeeCreate']
export type EmployeeStatus = components['schemas']['EmployeeStatus']

export interface DocumentListParams {
  employeeId?: string
  expiringWithinDays?: number
  status?: string
}

export async function listOrgUnits(): Promise<RecordsOrgUnit[]> {
  const { data } = await api.GET('/v1/org-units')
  return data ?? []
}

export async function createOrgUnit(body: OrgUnitCreate): Promise<RecordsOrgUnit | null> {
  const { data, response } = await api.POST('/v1/org-units', { body })
  return response.status === 201 ? (data ?? null) : null
}

export async function listEmployees(status?: EmployeeStatus): Promise<RecordsEmployee[]> {
  const { data } = await api.GET('/v1/employees', {
    params: { query: status === undefined ? {} : { status } },
  })
  return data ?? []
}

export async function createEmployee(body: EmployeeCreate): Promise<RecordsEmployee | null> {
  const { data, response } = await api.POST('/v1/employees', { body })
  return response.status === 201 ? (data ?? null) : null
}

export async function listContracts(): Promise<RecordsContract[]> {
  const { data } = await api.GET('/v1/contracts')
  return data ?? []
}

export async function listDocuments(params: DocumentListParams = {}): Promise<RecordsDocument[]> {
  const { data } = await api.GET('/v1/documents', {
    params: {
      query: {
        employee_id: params.employeeId,
        expiring_within_days: params.expiringWithinDays,
        status: params.status as
          'claimed' | 'verified' | 'unverified' | 'expired' | 'failed' | undefined,
      },
    },
  })
  return data ?? []
}

export async function verifyDocument(
  documentId: string,
  body: DocumentVerifyRequest,
): Promise<{ status: number; document?: RecordsDocument }> {
  const { data, response } = await api.POST('/v1/documents/{document_id}/verify', {
    params: { path: { document_id: documentId } },
    body,
  })
  return { status: response.status, document: data ?? undefined }
}
