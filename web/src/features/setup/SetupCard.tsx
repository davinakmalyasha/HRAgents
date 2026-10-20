import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { StatusBadge } from '@/components/status/StatusBadge'
import { Button } from '@/components/ui/button'

import type { SetupStatus } from './setupApi'
import { useSeedStarters } from './useSetup'

/**
 * The first-run checklist.
 *
 * Only the two configuration facts the server owns are shown as pass/fail; the
 * rest are counts. The one action is seeding starter content, because it is the
 * only step that can be done from here without inventing a settings store.
 */
export function SetupCard({ status }: { status: SetupStatus }) {
  const { t } = useTranslation()
  const seed = useSeedStarters()
  const startersDone =
    status.counts.onboarding_templates > 0 && status.counts.offboarding_templates > 0
  const tablesDone = status.counts.rate_tables > 0 && status.counts.unverified_rate_tables === 0

  return (
    <section
      aria-labelledby="setup-title"
      className="border-line bg-surface-subtle flex flex-col gap-4 rounded-lg border p-4"
    >
      <div>
        <h2 id="setup-title" className="text-ink-strong text-lg font-medium">
          {t('setup.title')}
        </h2>
        <p className="text-ink-muted text-sm">{t('setup.subtitle')}</p>
      </div>

      <ul className="flex flex-col gap-3">
        <Item
          label={t('setup.operator')}
          done={status.operator_name.trim() !== ''}
          hint={
            status.operator_name.trim() !== ''
              ? t('setup.operatorReady', { name: status.operator_name })
              : t('setup.operatorMissing')
          }
        />
        <Item
          label={t('setup.starters')}
          done={startersDone}
          hint={startersDone ? t('setup.seeded') : t('setup.startersHint')}
        />
        <Item
          label={t('setup.rateTables')}
          done={tablesDone}
          hint={
            tablesDone
              ? t('setup.rateTablesDone')
              : t('setup.rateTablesHint', {
                  unverified: status.counts.unverified_rate_tables,
                  total: status.counts.rate_tables,
                })
          }
        />
        <Item
          label={t('setup.model')}
          done
          hint={
            status.llm_model === 'test'
              ? t('setup.modelOffline')
              : t('setup.modelOnline', { model: status.llm_model })
          }
        />
      </ul>

      <div className="flex flex-wrap items-center gap-3">
        {!startersDone ? (
          <Button disabled={seed.isPending} onClick={() => seed.mutate()}>
            {seed.isPending ? t('setup.seeding') : t('setup.seed')}
          </Button>
        ) : null}
        <Link className="text-sm font-medium underline" to="/w/records">
          {t('setup.firstEmployeeLink')}
        </Link>
        <Link className="text-sm font-medium underline" to="/w/hiring">
          {t('setup.firstJobLink')}
        </Link>
      </div>

      {seed.isError ? (
        <p role="alert" className="text-error text-sm">
          {t('setup.seedFailed')}
        </p>
      ) : null}
    </section>
  )
}

function Item({ label, done, hint }: { label: string; done: boolean; hint: string }) {
  return (
    <li className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-ink text-sm">{label}</span>
        <StatusBadge
          tone={done ? 'done' : 'waiting'}
          labelKey={done ? 'setup.done' : 'setup.todo'}
        />
      </div>
      <p className="text-ink-muted text-xs">{hint}</p>
    </li>
  )
}
