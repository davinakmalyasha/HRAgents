import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import i18n from '@/i18n'

import { OfflineNotice } from './AppShell'

function setOnline(value: boolean) {
  Object.defineProperty(window.navigator, 'onLine', {
    configurable: true,
    get: () => value,
  })
}

describe('OfflineNotice', () => {
  afterEach(() => setOnline(true))

  it('appears when the connection drops and clears when it returns', () => {
    setOnline(true)
    render(<OfflineNotice />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    setOnline(false)
    act(() => {
      window.dispatchEvent(new Event('offline'))
    })
    expect(screen.getByRole('status')).toHaveTextContent(i18n.t('common.offline'))

    setOnline(true)
    act(() => {
      window.dispatchEvent(new Event('online'))
    })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
