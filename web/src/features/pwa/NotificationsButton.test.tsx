import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

import { NotificationsButton } from './NotificationsButton'

const state = vi.hoisted(() => ({
  status: 'disabled' as string,
  error: null as string | null,
  toggle: vi.fn(),
}))

vi.mock('./usePushNotifications', () => ({
  usePushNotifications: () => state,
}))

describe('NotificationsButton', () => {
  beforeEach(() => {
    state.status = 'disabled'
    state.error = null
    state.toggle.mockClear()
  })

  it('offers the toggle when the browser can subscribe', async () => {
    const user = userEvent.setup()
    render(<NotificationsButton />)

    const button = screen.getByRole('button', { name: i18n.t('push.turnOn') })
    expect(button).toHaveAttribute('aria-pressed', 'false')

    await user.click(button)
    expect(state.toggle).toHaveBeenCalledTimes(1)
  })

  it('says on, and is pressed, once subscribed', () => {
    state.status = 'enabled'
    render(<NotificationsButton />)

    expect(screen.getByRole('button', { name: i18n.t('push.on') })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('names a browser block instead of offering a dead button', () => {
    state.status = 'blocked'
    render(<NotificationsButton />)

    const button = screen.getByRole('button', { name: i18n.t('push.blocked') })
    expect(button).toBeDisabled()
  })

  it('renders nothing when push is not available at all', () => {
    for (const status of ['loading', 'unsupported', 'unconfigured']) {
      state.status = status
      const { unmount } = render(<NotificationsButton />)
      expect(screen.queryByRole('button')).toBeNull()
      unmount()
    }
  })

  it('shows the failure next to the toggle', () => {
    state.error = 'deliver'
    render(<NotificationsButton />)

    expect(screen.getByRole('status')).toHaveTextContent(i18n.t('push.error.deliver'))
  })
})
