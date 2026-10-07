import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  completeBreachStep,
  consentStatus,
  executeErasure,
  listBreaches,
  listConsents,
  listErasures,
  listRateTables,
  overdueBreachSteps,
  recordConsent,
  revokeConsent,
  scanRetention,
  submitErasure,
  transitionBreach,
  unverifiedRateTables,
  verifyAudit,
  verifyErasureIdentity,
  verifyRateTable,
  type BreachTransition,
  type ConsentCreate,
  type ConsentRevoke,
  type ErasureVerify,
  type PurgeRequest,
  type RateTableVerify,
  type SubjectKind,
} from './complianceApi'

export function useConsents(subjectId: string | null) {
  return useQuery({
    queryKey: ['compliance', 'consents', subjectId],
    queryFn: () => listConsents(subjectId as string),
    enabled: subjectId !== null,
  })
}

export function useConsentStatus(subjectId: string | null, subjectKind: SubjectKind) {
  return useQuery({
    queryKey: ['compliance', 'consents', 'status', subjectId, subjectKind],
    queryFn: () => consentStatus(subjectId as string, subjectKind),
    enabled: subjectId !== null,
  })
}

export function useBreaches() {
  return useQuery({ queryKey: ['compliance', 'breaches'], queryFn: listBreaches })
}

/** Required breach steps whose clock has run out, one row per step. */
export function useOverdueBreachSteps() {
  return useQuery({ queryKey: ['compliance', 'breaches', 'overdue'], queryFn: overdueBreachSteps })
}

export function useErasures() {
  return useQuery({ queryKey: ['compliance', 'erasures'], queryFn: listErasures })
}

export function useRateTables() {
  return useQuery({ queryKey: ['compliance', 'rate-tables'], queryFn: listRateTables })
}

/** Tables nobody has verified. Payroll refuses to compute from these. */
export function useUnverifiedRateTables() {
  return useQuery({
    queryKey: ['compliance', 'rate-tables', 'unverified'],
    queryFn: unverifiedRateTables,
  })
}

/** The retention scan is a report, not a purge: nothing is destroyed by reading it. */
export function useRetentionScan(enabled: boolean) {
  return useQuery({
    queryKey: ['compliance', 'retention', 'scan'],
    queryFn: scanRetention,
    enabled,
  })
}

/**
 * The audit verification result.
 *
 * Deliberately not polled and not cached long: this is the one read an operator takes to
 * find out whether the log can be believed.
 */
export function useAuditVerification(enabled: boolean) {
  return useQuery({
    queryKey: ['compliance', 'audit', 'verify'],
    queryFn: verifyAudit,
    enabled,
    staleTime: 0,
  })
}

function invalidate(queryClient: ReturnType<typeof useQueryClient>) {
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ['compliance'] })
  }
}

export function useRecordConsent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: ConsentCreate) => recordConsent(body),
    onSuccess: invalidate(queryClient),
  })
}

/** Withdrawing consent records a reason; the record outlives the tool. */
export function useRevokeConsent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      consentId,
      reason,
    }: {
      consentId: string
      reason: ConsentRevoke['reason']
    }) => revokeConsent(consentId, { reason }),
    onSuccess: invalidate(queryClient),
  })
}

export function useTransitionBreach() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ incidentId, body }: { incidentId: string; body: BreachTransition }) =>
      transitionBreach(incidentId, body),
    onSuccess: invalidate(queryClient),
  })
}

export function useCompleteBreachStep() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      incidentId,
      stepKey,
      note,
    }: {
      incidentId: string
      stepKey: string
      note?: string | null
    }) => completeBreachStep(incidentId, stepKey, note === undefined ? {} : { note }),
    onSuccess: invalidate(queryClient),
  })
}

export function useVerifyErasureIdentity() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      requestId,
      method,
    }: {
      requestId: string
      method: ErasureVerify['method']
    }) => verifyErasureIdentity(requestId, { method }),
    onSuccess: invalidate(queryClient),
  })
}

/** Raising the approval. It does not erase; a named human decides that. */
export function useSubmitErasure() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (requestId: string) => submitErasure(requestId),
    onSuccess: invalidate(queryClient),
  })
}

/** Destroying the records. Only offered once a human has approved. */
export function useExecuteErasure() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (requestId: string) => executeErasure(requestId),
    onSuccess: invalidate(queryClient),
  })
}

/** Naming the source a statutory figure came from. */
export function useVerifyRateTable() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ tableId, body }: { tableId: string; body: RateTableVerify }) =>
      verifyRateTable(tableId, body),
    onSuccess: invalidate(queryClient),
  })
}

export type { PurgeRequest }
