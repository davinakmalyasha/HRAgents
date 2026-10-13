import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

import '@/i18n'

afterEach(cleanup)

/**
 * jsdom implements neither, and cmdk (the command palette) uses both: it
 * observes its list to keep the active item visible and calls
 * `scrollIntoView` when the keyboard moves the selection. Without these, the
 * palette mounts but throws on the first arrow key.
 */
if (!('ResizeObserver' in globalThis)) {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  ;(globalThis as Record<string, unknown>).ResizeObserver = ResizeObserverStub
}

// Some suites run in the node environment (`theme.guard.test.ts` reads files),
// where neither `Element` nor a DOM exists.
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}
