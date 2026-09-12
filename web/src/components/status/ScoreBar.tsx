import { cn } from 'cn'

interface ScoreBarProps {
  value: number
  label: string
  flagged?: boolean
  className?: string
}

/** Score bars use the gray ramp; only a flagged score takes a status color. */
export function ScoreBar({ value, label, flagged = false, className }: ScoreBarProps) {
  const clamped = Math.min(Math.max(value, 0), 1)

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(clamped * 100)}
        className="bg-surface-subtle h-1.5 w-24 overflow-hidden rounded-full"
      >
        <div
          className={cn('h-full rounded-full', flagged ? 'bg-error' : 'bg-ink')}
          style={{ width: `${clamped * 100}%` }}
        />
      </div>
      <span className="text-2xs text-ink-muted font-mono tabular-nums">{clamped.toFixed(2)}</span>
    </div>
  )
}
