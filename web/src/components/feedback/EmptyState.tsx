import type { LucideIcon } from 'lucide-react'

import { cn } from 'cn'

interface EmptyStateProps {
  icon?: LucideIcon
  title: string
  detail?: string
  className?: string
}

export function EmptyState({ icon: Icon, title, detail, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'border-line flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-12 text-center',
        className,
      )}
    >
      {Icon ? <Icon aria-hidden="true" className="text-ink-muted size-5" /> : null}
      <p className="text-ink-strong font-medium">{title}</p>
      {detail ? <p className="text-ink-muted max-w-sm text-xs">{detail}</p> : null}
    </div>
  )
}
