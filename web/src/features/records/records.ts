import type { components } from '@/api/schema'

type OrgUnitView = components['schemas']['OrgUnitView']
type DocumentView = components['schemas']['DocumentView']
type EmployeeView = components['schemas']['EmployeeView']
type ContractView = components['schemas']['ContractView']
type EmployeeStatus = components['schemas']['EmployeeStatus']

export type RecordsOrgUnit = OrgUnitView
export type RecordsDocument = DocumentView
export type RecordsEmployee = EmployeeView
export type RecordsContract = ContractView
export type RecordsEmployeeStatus = EmployeeStatus

export const DEFAULT_EXPIRY_WINDOW_DAYS = 60

export interface OrgTreeNode extends RecordsOrgUnit {
  depth: number
  totalHeadcount: number
}

/**
 * Org units as a flat, depth-annotated list: the records workspace renders a
 * tree from it, and the ordering is deterministic (parents before children,
 * then by name) so two renders always agree.
 */
export function orgTree(units: RecordsOrgUnit[]): OrgTreeNode[] {
  const byParent = new Map<string | null, RecordsOrgUnit[]>()
  for (const unit of units) {
    const key = unit.parent_id ?? null
    byParent.set(key, [...(byParent.get(key) ?? []), unit])
  }
  const nodes: OrgTreeNode[] = []
  const visited = new Set<string>()
  const byName = (left: RecordsOrgUnit, right: RecordsOrgUnit): number =>
    left.name.localeCompare(right.name)
  const visit = (parent: string | null, depth: number): void => {
    for (const unit of [...(byParent.get(parent) ?? [])].sort(byName)) {
      if (visited.has(unit.id)) {
        continue
      }
      visited.add(unit.id)
      nodes.push({ ...unit, depth, totalHeadcount: headcountBelow(unit, byParent) })
      visit(unit.id, depth + 1)
    }
  }
  visit(null, 0)
  // A unit whose parent is not in the payload still has people: show it as a
  // root rather than hiding it.
  for (const unit of [...units].sort(byName)) {
    if (!visited.has(unit.id)) {
      visited.add(unit.id)
      nodes.push({ ...unit, depth: 0, totalHeadcount: headcountBelow(unit, byParent) })
      visit(unit.id, 1)
    }
  }
  return nodes
}

function headcountBelow(
  unit: RecordsOrgUnit,
  byParent: Map<string | null, RecordsOrgUnit[]>,
): number {
  let total = unit.headcount
  for (const child of byParent.get(unit.id) ?? []) {
    total += child.headcount
  }
  return total
}

export interface ExpiryBucket {
  documents: RecordsDocument[]
  overdue: number
  expiringSoon: number
}

/** Split the vault by urgency: already expired, expiring soon, everything else. */
export function bucketByExpiry(
  documents: RecordsDocument[],
  withinDays: number = DEFAULT_EXPIRY_WINDOW_DAYS,
): ExpiryBucket {
  const overdue: RecordsDocument[] = []
  const soon: RecordsDocument[] = []
  const rest: RecordsDocument[] = []
  for (const document of documents) {
    const days = document.days_to_expiry
    if (days !== null && days < 0) {
      overdue.push(document)
    } else if (days !== null && days <= withinDays) {
      soon.push(document)
    } else {
      rest.push(document)
    }
  }
  return {
    documents: [...overdue, ...soon].sort(
      (left, right) => (left.days_to_expiry ?? 0) - (right.days_to_expiry ?? 0),
    ),
    overdue: overdue.length,
    expiringSoon: soon.length,
  }
}

export function documentNeedsAttention(document: RecordsDocument): boolean {
  return document.status === 'claimed' || document.status === 'failed'
}

export function headcountByStatus(employees: RecordsEmployee[]): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const employee of employees) {
    counts[employee.status] = (counts[employee.status] ?? 0) + 1
  }
  return counts
}

export function activeContracts(contracts: RecordsContract[]): RecordsContract[] {
  return contracts.filter((contract) => contract.status === 'active')
}
