import { useQuery } from '@tanstack/react-query'

import {
  documentStatus,
  listEmployeeDocuments,
  listEmployees,
  listPlans,
  listTemplates,
} from './onboardingApi'

export function useOnboardingPlans(activeOnly = true) {
  return useQuery({
    queryKey: ['onboarding', 'plans', { activeOnly }],
    queryFn: async () => listPlans(activeOnly),
  })
}

export function useOnboardingTemplates(enabled: boolean) {
  return useQuery({
    queryKey: ['onboarding', 'templates'],
    enabled,
    queryFn: listTemplates,
  })
}

export function useEmployeeDocuments(employeeId: string | undefined) {
  return useQuery({
    queryKey: ['onboarding', 'documents', employeeId],
    enabled: employeeId !== undefined,
    queryFn: async () => listEmployeeDocuments(employeeId ?? ''),
  })
}

export function useDocumentStatus(planId: string | undefined) {
  return useQuery({
    queryKey: ['onboarding', 'document-status', planId],
    enabled: planId !== undefined,
    queryFn: async () => documentStatus(planId ?? ''),
  })
}

export function useEmployees(enabled: boolean) {
  return useQuery({
    queryKey: ['onboarding', 'employees'],
    enabled,
    queryFn: async () => listEmployees(),
  })
}
