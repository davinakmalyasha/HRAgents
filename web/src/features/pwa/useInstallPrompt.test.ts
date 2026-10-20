import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useInstallPrompt } from './useInstallPrompt'

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

describe('useInstallPrompt', () => {
  it('keeps the browser prompt until it is used once', async () => {
    const { result } = renderHook(() => useInstallPrompt())
    expect(result.current.canInstall).toBe(false)

    const { event, prompt } = beforeInstall()
    act(() => {
      window.dispatchEvent(event)
    })
    expect(result.current.canInstall).toBe(true)

    await act(async () => {
      await result.current.install()
    })
    expect(prompt).toHaveBeenCalledTimes(1)
    expect(result.current.canInstall).toBe(false)
  })

  it('stops offering install after the app is installed', () => {
    const { result } = renderHook(() => useInstallPrompt())
    const { event } = beforeInstall()
    act(() => {
      window.dispatchEvent(event)
    })
    expect(result.current.canInstall).toBe(true)

    act(() => {
      window.dispatchEvent(new Event('appinstalled'))
    })
    expect(result.current.canInstall).toBe(false)
    expect(result.current.installed).toBe(true)
  })

  it('does nothing when there is no pending prompt', async () => {
    const { result } = renderHook(() => useInstallPrompt())
    await act(async () => {
      await result.current.install()
    })
    expect(result.current.canInstall).toBe(false)
  })
})
