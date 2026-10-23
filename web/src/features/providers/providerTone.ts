import type { ProviderHealthStatus } from './providersApi'

/** Status colour is never the only signal; the badge always carries a label. */
export function toneForProvider(status: ProviderHealthStatus): 'waiting' | 'error' | 'done' {
  if (status === 'ok') {
    return 'done'
  }
  if (status === 'degraded') {
    return 'waiting'
  }
  return 'error'
}
