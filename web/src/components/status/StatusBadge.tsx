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
 *
 * The tone color sits on the icon only. WCAG AA needs 4.5:1 for the 12px label
 * and the amber/green tokens measure 3.2-3.3:1 as text on light surfaces; as an
 * aria-hidden glyph the icon only needs the 3:1 UI-component ratio, which every
 * tone clears on both --bg and --bg-subtle. The label inherits its surrounding
 * text color, which the neutral ramp already holds at >=4.5:1.
 */
export function StatusBadge({ tone, labelKey, className }: StatusBadgeProps) {
  const { t } = useTranslation()
  const { icon, className: toneClassName } = TONES[tone]

  return (
    <span
      role="status"
      className={cn('text-2xs inline-flex items-center gap-1 font-medium', className)}
    >
      <span aria-hidden="true" className={toneClassName}>
        {icon}
      </span>
      <span className="text-ink">{t(labelKey)}</span>
    </span>
  )
}
