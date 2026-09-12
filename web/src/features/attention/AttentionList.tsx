import { ClipboardCheck, ListTodo, Send } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { StatusBadge } from '@/components/status/StatusBadge'
import { Button } from '@/components/ui/button'

import type { AttentionItem, AttentionSource } from './attention'

const SOURCE_ICONS = {
  approval: ClipboardCheck,
  task: ListTodo,
  handoff: Send,
} satisfies Record<AttentionSource, typeof ClipboardCheck>

interface AttentionListProps {
  items: AttentionItem[]
}

export function AttentionList({ items }: AttentionListProps) {
  const { t } = useTranslation()

  return (
    <ul className="divide-line border-line flex flex-col divide-y rounded-lg border">
      {items.map((item) => {
        const Icon = SOURCE_ICONS[item.source]
        return (
          <li
            key={item.id}
            className="hover:bg-surface-subtle flex items-center justify-between gap-3 px-3 py-2.5 transition-colors"
          >
            <div className="flex min-w-0 items-start gap-2.5">
              <Icon aria-hidden="true" className="text-ink-muted mt-0.5 size-4 shrink-0" />
              <div className="flex min-w-0 flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  <StatusBadge
                    tone={item.tone}
                    labelKey={item.tone === 'error' ? 'status.error' : 'status.waiting'}
                  />
                  <span className="text-ink-strong truncate text-sm font-medium">{item.title}</span>
                </div>
                {item.detail ? (
                  <span className="text-ink-muted truncate text-xs">{item.detail}</span>
                ) : null}
              </div>
            </div>
            {item.workspace ? (
              <Button asChild variant="ghost" size="xs">
                <Link to={`/w/${item.workspace}?room=queue`}>
                  {t(`workspaces.${item.workspace}.name`)}
                </Link>
              </Button>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}
