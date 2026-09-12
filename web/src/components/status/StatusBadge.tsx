import { useTranslation } from 'react-i18next'

import { cn } from 'cn'

export type StatusTone = 'waiting' | 'error' | 'done'

const TONES: Record<StatusTone, { icon: string; className: string }> = {
  waiting: { icon: '▲', className: 'text-waiting' },
  error: { icon: '●', className: 'text-error' },
  done: { icon: '✓', className: 'text-done' },
}

interface StatusBadgeProps {
  tone: StatusTone
  labelKey: string
  className?: string
}

/**
 * Status is never color-only: the tone always renders its icon and label.
 * Status colors are deliberately confined to this component (and ScoreBar).
 */
export function StatusBadge({ tone, labelKey, className }: StatusBadgeProps) {
  const { t } = useTranslation()
  const { icon, className: toneClassName } = TONES[tone]

  return (
    <span
      role="status"
      className={cn(
        'text-2xs inline-flex items-center gap-1 font-medium',
        toneClassName,
        className,
      )}
    >
      <span aria-hidden="true">{icon}</span>
      <span>{t(labelKey)}</span>
    </span>
  )
}
