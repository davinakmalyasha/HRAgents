import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

import { InstallAppButton } from './InstallAppButton'

function beforeInstall(prompt = vi.fn().mockResolvedValue(undefined)) {
  const event = new Event('beforeinstallprompt', { cancelable: true }) as Event & {
    prompt: () => Promise<void>
    userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
  }
  Object.defineProperty(event, 'prompt', { value: prompt })
  Object.defineProperty(event, 'userChoice', {
    value: Promise.resolve({ outcome: 'accepted' }),
  })
  return { event, prompt }
}

describe('InstallAppButton', () => {
  it('appears only when the browser offers install, and prompts once', async () => {
    const user = userEvent.setup()
    render(<InstallAppButton />)

    expect(screen.queryByRole('button', { name: i18n.t('app.install') })).toBeNull()

    const { event, prompt } = beforeInstall()
    act(() => {
      window.dispatchEvent(event)
    })

    await user.click(screen.getByRole('button', { name: i18n.t('app.install') }))

    expect(prompt).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: i18n.t('app.install') })).toBeNull()
  })
})
