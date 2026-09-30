import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useState } from 'react'

import { StatusBadge } from '@/components/status/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'

import { linkDocument, type PlanResult } from './onboardingApi'
import type { OnboardingStep } from './onboarding'
import { useEmployeeDocuments } from './useOnboarding'

function documentTone(status: string): 'waiting' | 'done' | 'error' {
  if (status === 'verified') {
    return 'done'
  }
  if (status === 'failed') {
    return 'error'
  }
  return 'waiting'
}

/**
 * Attach an already-uploaded employee document to a checklist step. The
 * document vault itself lives in the Records workspace; onboarding only links
 * what is on file, and the step still has to be completed by a human.
 */
export function LinkDocumentDialog({
  planId,
  employeeId,
  step,
  open,
  onOpenChange,
  onDone,
}: {
  planId: string
  employeeId: string
  step: OnboardingStep
  open: boolean
  onOpenChange: (open: boolean) => void
  onDone: (result: PlanResult) => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const documents = useEmployeeDocuments(open ? employeeId : undefined)
  const [selected, setSelected] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleLink() {
    if (selected === '') {
      setProblem(t('onboarding.errors.documentRequired'))
      return
    }
    setProblem(null)
    setBusy(true)
    const result = await linkDocument(planId, step.key, {
      document_id: selected,
    })
    setBusy(false)
    if (result.status === 200 && result.plan !== undefined) {
      await queryClient.invalidateQueries({ queryKey: ['onboarding'] })
      onOpenChange(false)
      onDone(result)
      return
    }
    setProblem(
      result.status === 404
        ? t('onboarding.errors.documentNotFound')
        : t('onboarding.errors.failed'),
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('onboarding.linkDialog.title')}</DialogTitle>
          <DialogDescription>
            {step.title} · {t('onboarding.linkDialog.hint')}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          {problem !== null ? (
            <p role="alert" className="text-error flex items-center gap-1 text-xs">
              <span aria-hidden="true">●</span>
              {problem}
            </p>
          ) : null}

          {documents.isLoading ? (
            <Skeleton className="h-16 w-full" />
          ) : (documents.data ?? []).length === 0 ? (
            <p className="text-2xs text-ink-muted">{t('onboarding.linkDialog.noDocuments')}</p>
          ) : (
            <ul className="divide-line border-line flex flex-col divide-y rounded-md border">
              {(documents.data ?? []).map((document) => (
                <li key={document.id} className="flex items-center justify-between gap-2 px-3 py-2">
                  <label className="flex min-w-0 items-center gap-2 text-xs">
                    <input
                      type="radio"
                      name="onboarding-document"
                      value={document.id}
                      checked={selected === document.id}
                      onChange={() => setSelected(document.id)}
                    />
                    <span className="text-ink-strong truncate">
                      {t(`onboarding.documentKinds.${document.kind}`)}
                    </span>
                    {document.filename === null ? null : (
                      <span className="text-ink-muted truncate">{document.filename}</span>
                    )}
                  </label>
                  <span className="flex items-center gap-2">
                    {document.expires_on !== null ? (
                      <Badge variant="outline" className="text-2xs">
                        {t('onboarding.expires', { date: document.expires_on })}
                      </Badge>
                    ) : null}
                    <StatusBadge
                      tone={documentTone(document.status)}
                      labelKey={`onboarding.documentStatuses.${document.status}`}
                    />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <DialogFooter>
          <Button size="sm" disabled={busy} onClick={() => void handleLink()}>
            {t('onboarding.linkDialog.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
