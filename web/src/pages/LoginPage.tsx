import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { readSession } from '@/features/auth/session'
import { forgetApiKey, isAuthRequired, rememberApiKey } from '@/lib/auth'

type Phase = 'checking' | 'signIn' | 'unreachable'

/**
 * Sign-in: enter the API key this browser should act as.
 *
 * The first thing it does is call `/v1/session` with whatever it holds -- usually
 * nothing. If the API answers, then no keys are configured and this install runs
 * as a single local operator, so there is nothing to sign in to and the page gets
 * out of the way. That is what keeps the zero-config development flow unchanged
 * while making a key-configured install usable.
 */
export function LoginPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const [phase, setPhase] = useState<Phase>('checking')
  const [key, setKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const from = (location.state as { from?: string } | null)?.from ?? '/'

  useEffect(() => {
    let cancelled = false
    readSession()
      .then(() => {
        if (!cancelled) {
          navigate(from, { replace: true })
        }
      })
      .catch((failure: unknown) => {
        if (cancelled) {
          return
        }
        setPhase(isAuthRequired(failure) ? 'signIn' : 'unreachable')
      })
    return () => {
      cancelled = true
    }
  }, [from, navigate])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    const candidate = key.trim()
    if (candidate === '') {
      return
    }
    setBusy(true)
    setError(null)
    rememberApiKey(candidate)
    try {
      await readSession()
      navigate(from, { replace: true })
    } catch (failure) {
      /**
       * A key that the server refused is dropped rather than kept for the next
       * request: it will never start working, and leaving it would send it on
       * every call. Only the refusal branch forgets it -- an unreachable server
       * says nothing about whether the key is right.
       */
      if (isAuthRequired(failure)) {
        forgetApiKey()
        setError(t('auth.wrongKey'))
      } else {
        forgetApiKey()
        setError(t('auth.unreachable'))
      }
    } finally {
      setBusy(false)
    }
  }

  if (phase === 'checking') {
    return (
      <main className="bg-surface text-ink flex min-h-dvh items-center justify-center">
        <p className="text-ink-muted text-sm">{t('auth.checking')}</p>
      </main>
    )
  }

  if (phase === 'unreachable') {
    return (
      <main className="bg-surface text-ink flex min-h-dvh items-center justify-center px-4">
        <section className="border-line w-full max-w-sm rounded-lg border p-6">
          <h1 className="text-ink-strong text-lg font-medium">{t('auth.title')}</h1>
          <p className="text-error mt-3 text-sm">{t('auth.unreachable')}</p>
          <Button className="mt-4 w-full" onClick={() => setPhase('checking')}>
            {t('auth.retry')}
          </Button>
        </section>
      </main>
    )
  }

  return (
    <main className="bg-surface text-ink flex min-h-dvh items-center justify-center px-4">
      <section className="border-line w-full max-w-sm rounded-lg border p-6">
        <h1 className="text-ink-strong text-lg font-medium">{t('auth.title')}</h1>
        <p className="text-ink-muted mt-2 text-xs">{t('auth.hint')}</p>

        <form className="mt-4 flex flex-col gap-3" onSubmit={(event) => void submit(event)}>
          <label className="text-ink-muted flex flex-col gap-1 text-xs" htmlFor="api-key">
            {t('auth.keyLabel')}
            <Input
              id="api-key"
              type="password"
              autoComplete="off"
              autoFocus
              value={key}
              onChange={(event) => setKey(event.target.value)}
            />
          </label>
          <Button type="submit" disabled={busy || key.trim() === ''}>
            {busy ? t('auth.signingIn') : t('auth.signIn')}
          </Button>
        </form>

        {error !== null ? (
          <p role="alert" className="text-error mt-3 text-sm">
            {error}
          </p>
        ) : null}

        {/*
          The key is exchanged for a role on the server; the dashboard never
          decides what it can see. Worth saying on the screen, because "enter my
          key" otherwise looks like a form that merely unlocks a UI.
        */}
        <p className="text-ink-muted mt-4 text-xs">{t('auth.roleNote')}</p>
      </section>
    </main>
  )
}
