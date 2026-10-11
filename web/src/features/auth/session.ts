import { useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { AuthRequiredError, forgetApiKey } from '@/lib/auth'

export type SessionView = import('@/api/schema').components['schemas']['SessionView']

/**
 * Who the server thinks this browser is.
 *
 * A 401 becomes `AuthRequiredError` rather than "session returned nothing":
 * the gate that sends somebody to sign in cannot distinguish an absent body
 * from a dropped connection, and those need opposite responses.
 */
export async function readSession(): Promise<SessionView> {
  const { data, response } = await api.GET('/v1/session')
  if (data !== undefined) {
    return data
  }
  if (response.status === 401) {
    throw new AuthRequiredError(response.status, await responseCode(response))
  }
  throw new Error(`session request failed with ${response.status}`)
}

async function responseCode(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json()
    if (body !== null && typeof body === 'object' && 'code' in body) {
      const code = (body as { code?: unknown }).code
      return typeof code === 'string' ? code : null
    }
  } catch {
    // No body is fine: the status is what the gate acts on.
  }
  return null
}

/**
 * The session query. One cache entry per app, so the shell, the topbar and the
 * workspaces agree on who is signed in.
 */
export function useSession() {
  return useQuery({
    queryKey: ['session'],
    queryFn: readSession,
    staleTime: 60_000,
    /**
     * A refused credential is not going to start working because we asked
     * three more times; retrying only delays the sign-in screen.
     */
    retry: (failureCount, error) => !(error instanceof AuthRequiredError) && failureCount < 3,
  })
}

export function useSignOut() {
  const queryClient = useQueryClient()
  return () => {
    forgetApiKey()
    // Nothing cached belongs to whoever signs in next.
    queryClient.clear()
  }
}
