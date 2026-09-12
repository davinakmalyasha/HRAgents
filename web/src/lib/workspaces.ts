import {
  Briefcase,
  CalendarDays,
  LogOut,
  MessagesSquare,
  ShieldCheck,
  TrendingUp,
  UserPlus,
  Users,
  Wallet,
  type LucideIcon,
} from 'lucide-react'

export const WORKSPACE_IDS = [
  'hiring',
  'policy',
  'onboarding',
  'records',
  'leave',
  'payroll',
  'growth',
  'offboarding',
  'compliance',
] as const

export type WorkspaceId = (typeof WORKSPACE_IDS)[number]

export const WORKSPACE_ICONS: Record<WorkspaceId, LucideIcon> = {
  hiring: Briefcase,
  policy: MessagesSquare,
  onboarding: UserPlus,
  records: Users,
  leave: CalendarDays,
  payroll: Wallet,
  growth: TrendingUp,
  offboarding: LogOut,
  compliance: ShieldCheck,
}

export function isWorkspaceId(value: string | undefined): value is WorkspaceId {
  return value !== undefined && (WORKSPACE_IDS as readonly string[]).includes(value)
}
