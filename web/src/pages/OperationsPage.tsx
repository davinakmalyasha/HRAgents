import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { EmptyState } from '@/components/feedback/EmptyState'
import { StatusBadge } from '@/components/status/StatusBadge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDateTime } from '@/lib/dates'

import { OpsRequestError, type DeadLetterView } from '@/features/ops/opsApi'
import { ConnectionsSection } from '@/features/ops/ConnectionsSection'
import { useDeadLetters, useRequeueDeadLetter, useUsage } from '@/features/ops/useOps'
import { ProviderList } from '@/features/providers/ProviderList'
import { ProviderRequestError } from '@/features/providers/providersApi'
import { useProviders } from '@/features/providers/useProviders'

/**
 * The operations queue: submissions the pipeline accepted and could not process.
 *
 * Requeueing is a named human act with a reason, and the API records it on the
 * audit chain. The payload itself is never shown -- it carries the résumé --
 * only its key names, so an operator can identify the message type without
 * reading candidate data on an ops screen.
 */
export function OperationsPage() {
  const { t } = useTranslation()
  const letters = useDeadLetters()
  const providers = useProviders()

  return (
    <section aria-labelledby="ops-heading" className="flex flex-col gap-5">
      <div>
        <h1 id="ops-heading" className="text-ink-strong text-xl font-semibold">
          {t('ops.title')}
        </h1>
        <p className="text-ink-muted mt-1 max-w-prose text-sm">{t('ops.hint')}</p>
      </div>

      <section aria-labelledby="providers-heading" className="flex flex-col gap-2">
        <h2 id="providers-heading" className="text-ink-strong text-lg font-medium">
          {t('providers.title')}
        </h2>
        <p className="text-ink-muted max-w-prose text-sm">{t('providers.hint')}</p>
        {providers.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : providers.isError ? (
          <EmptyState
            title={
              providers.error instanceof ProviderRequestError && providers.error.status === 403
                ? t('providers.forbidden')
                : t('providers.unavailable')
            }
          />
        ) : (
          <ProviderList providers={providers.data ?? []} />
        )}
      </section>

      <ConnectionsSection />

      <ModelUsage />

      {letters.isLoading ? (
        <Skeleton className="h-40" />
      ) : letters.isError ? (
        <EmptyState
          title={
            letters.error instanceof OpsRequestError && letters.error.status === 403
              ? t('ops.forbidden')
              : t('ops.unavailable')
          }
        />
      ) : (letters.data ?? []).length === 0 ? (
        <EmptyState title={t('ops.empty')} />
      ) : (
        <ul className="flex flex-col gap-2">
          {(letters.data ?? []).map((letter) => (
            <DeadLetterRow key={letter.message_id} letter={letter} />
          ))}
        </ul>
      )}
    </section>
  )
}

function DeadLetterRow({ letter }: { letter: DeadLetterView }) {
  const { t } = useTranslation()
  const requeue = useRequeueDeadLetter()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')

  return (
    <li className="border-line rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-ink-strong font-mono text-sm">{letter.topic}</p>
          <p className="text-ink-muted text-xs">
            {t('ops.attempts', { count: letter.attempts })} ·{' '}
            {t('ops.failedAt', {
              date: formatDateTime(letter.failed_at ?? letter.created_at),
            })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge tone="error" labelKey="ops.deadLetter" />
          {!open ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setOpen(true)
                setReason('')
              }}
            >
              {t('ops.requeue')}
            </Button>
          ) : null}
        </div>
      </div>

      {letter.failed_reason ? (
        <p className="text-error mt-2 text-xs">
          {t('ops.reason', { reason: letter.failed_reason })}
        </p>
      ) : null}

      <p className="text-ink-muted text-2xs mt-1 font-mono">
        {t('ops.payloadKeys', { keys: letter.payload_keys.join(', ') })}
      </p>
      {letter.application_id ? (
        <Link
          to={`/w/hiring/applications/${letter.application_id}`}
          className="text-accent mt-1 inline-block text-xs hover:underline"
        >
          {t('ops.openApplication')}
        </Link>
      ) : null}

      {open ? (
        <div className="mt-2 flex flex-col gap-2">
          <label className="text-ink-muted text-xs" htmlFor={`requeue-${letter.message_id}`}>
            {t('ops.requeueReason')}
          </label>
          <textarea
            id={`requeue-${letter.message_id}`}
            className="border-line w-full rounded border p-2 text-sm"
            rows={2}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          {requeue.isError ? (
            <p role="alert" className="text-error text-xs">
              {t('ops.requeueFailed')}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="destructive"
              disabled={requeue.isPending || reason.trim() === ''}
              onClick={() =>
                requeue.mutate(
                  { messageId: letter.message_id, reason: reason.trim() },
                  { onSuccess: () => setOpen(false) },
                )
              }
            >
              {t('ops.confirmRequeue')}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setOpen(false)}>
              {t('ops.cancel')}
            </Button>
          </div>
        </div>
      ) : null}
    </li>
  )
}

/**
 * Token totals are the operator's cost signal; the dollars are their contract,
 * so the panel reports tokens and requests and leaves pricing to them.
 */
function ModelUsage() {
  const { t } = useTranslation()
  const usage = useUsage()
  if (usage.isLoading) {
    return <Skeleton className="h-24 w-full" />
  }
  if (usage.isError || usage.data === undefined) {
    return <EmptyState title={t('ops.usage.unavailable')} />
  }
  const { totals } = usage.data
  const byModel = usage.data.by_model ?? []
  return (
    <section aria-labelledby="usage-heading" className="flex flex-col gap-2">
      <h2 id="usage-heading" className="text-ink-strong text-lg font-medium">
        {t('ops.usage.title')}
      </h2>
      <p className="text-ink-muted text-sm">
        {t('ops.usage.totals', {
          tokens: totals.total_tokens,
          requests: totals.requests,
        })}
      </p>
      {byModel.length === 0 ? (
        <EmptyState title={t('ops.usage.empty')} />
      ) : (
        <ul className="text-ink-muted text-xs">
          {byModel.map((item) => (
            <li
              key={`${item.provider_id}-${item.model ?? 'unknown'}`}
              className="border-line flex flex-wrap items-baseline justify-between gap-2 border-b py-1 last:border-b-0"
            >
              <span className="font-mono">
                {item.provider_id} · {item.model ?? 'unknown'}
              </span>
              <span>
                {t('ops.usage.breakdown', {
                  input: item.input_tokens,
                  output: item.output_tokens,
                  requests: item.requests,
                })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
