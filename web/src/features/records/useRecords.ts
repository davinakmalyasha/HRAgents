import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { DocumentListParams, DocumentVerifyRequest } from './recordsApi'
import {
  listContracts,
  listDocuments,
  listEmployees,
  listOrgUnits,
  verifyDocument,
} from './recordsApi'
import type { EmployeeStatus } from './recordsApi'

export function useOrgUnits() {
  return useQuery({
    queryKey: ['records', 'org-units'],
    queryFn: listOrgUnits,
  })
}

export function useEmployees(status?: EmployeeStatus) {
  return useQuery({
    queryKey: ['records', 'employees', { status: status ?? 'all' }],
    queryFn: async () => listEmployees(status),
  })
}

export function useContracts() {
  return useQuery({
    queryKey: ['records', 'contracts'],
    queryFn: listContracts,
  })
}

export function useDocuments(params: DocumentListParams = {}) {
  return useQuery({
    queryKey: ['records', 'documents', params],
    queryFn: async () => listDocuments(params),
  })
}

export interface VerifyResult {
  status: number
  documentId: string
}

export function useVerifyDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      documentId,
      body,
    }: {
      documentId: string
      body: DocumentVerifyRequest
    }) => {
      const response = await verifyDocument(documentId, body)
      return { status: response.status, documentId }
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['records', 'documents'] })
    },
  })
}
