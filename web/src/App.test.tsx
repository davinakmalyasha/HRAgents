import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'
import { api } from '@/lib/api'

import { AppRoutes } from './App'

/**
 * A signed-in-enough API for the shell.
 *
 * `api.use` is part of the mock because the real client registers its credential
 * middleware at module scope: an object without `use` throws at import, which
 * fails every test in this file for a reason unrelated to routing. `/v1/session`
 * answers with a local-operator session so the shell's gate lets the routes
 * through -- what these tests are about.
 */
const SESSION = {
  actor_id: 'local-dev',
  role: 'hr_admin',
  employee_id: null,
  api_key: false,
  decides_approver_roles: [],
}

vi.mock('@/lib/api', () => ({
  api: {
    GET: vi.fn((path: string) => Promise.resolve({ data: path === '/v1/session' ? SESSION : [] })),
    use: vi.fn(),
  },
}))

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AppRoutes', () => {
  /**
   * Every assertion below waits for the shell's session query to settle, because
   * the routes do not mount until then -- rendering them while the session is
   * still unknown fires a request per workspace that is going to be refused.
   * `findBy` is the assertion that says "the app finished coming up".
   */
  it('renders the attention-first home with Needs you and Watching', async () => {
    renderAt('/')

    expect(
      await screen.findByRole('heading', { name: i18n.t('home.needsYou') }),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: i18n.t('home.watching') })).toBeInTheDocument()
  })

  it('renders every workspace with the three rooms', async () => {
    renderAt('/w/hiring')

    expect(
      await screen.findByRole(
        'heading',
        { name: i18n.t('workspaces.hiring.name') },
        { timeout: 5000 },
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: i18n.t('rooms.board') })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: i18n.t('rooms.queue') })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: i18n.t('rooms.chat') })).toBeInTheDocument()
  })

  it('renders the chat room instead of a placeholder', async () => {
    renderAt('/w/hiring')

    await userEvent.click(
      await screen.findByRole('tab', { name: i18n.t('rooms.chat') }, { timeout: 5000 }),
    )

    expect(screen.getByRole('textbox', { name: i18n.t('chat.placeholder') })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: i18n.t('chat.send') })).toBeInTheDocument()
  })

  it('deep-links to a room through the query string', async () => {
    renderAt('/w/hiring?room=chat')

    expect(
      await screen.findByRole('textbox', { name: i18n.t('chat.placeholder') }, { timeout: 5000 }),
    ).toBeInTheDocument()
  })

  it('redirects unknown workspaces to home', async () => {
    renderAt('/w/unknown')

    expect(
      await screen.findByRole('heading', { name: i18n.t('home.needsYou') }, { timeout: 5000 }),
    ).toBeInTheDocument()
  })
})

describe('the sign-in route', () => {
  /** A session the server refused: no body, just the status. */
  const refused = { data: undefined, response: new Response(null, { status: 401 }) }

  function respondWith(handler: (path: string) => unknown) {
    vi.mocked(api.GET).mockImplementation(((path: string) =>
      Promise.resolve(handler(path))) as never)
  }

  it('shows the key form when the server refuses the session', async () => {
    respondWith((path) => (path === '/v1/session' ? refused : { data: [] }))

    renderAt('/login')

    expect(await screen.findByRole('heading', { name: i18n.t('auth.title') })).toBeInTheDocument()
    // A password input has no 	extbox role; the label is how it is reached.
    expect(screen.getByLabelText(i18n.t('auth.keyLabel'))).toBeInTheDocument()
    /** The button waits for a key; an empty submit would only produce a 401. */
    expect(screen.getByRole('button', { name: i18n.t('auth.signIn') })).toBeDisabled()
  })

  it('gets out of the way when the install has no keys configured', async () => {
    /**
     * With no keys configured the API answers as the local operator, so there is
     * nothing to sign in to. Showing a form anyway would ask the solo operator
     * for a credential their own install does not have.
     */
    respondWith((path) => (path === '/v1/session' ? { data: SESSION } : { data: [] }))

    renderAt('/login')

    expect(
      await screen.findByRole('heading', { name: i18n.t('home.needsYou') }),
    ).toBeInTheDocument()
  })

  it('sends a refused workspace visit to the sign-in route', async () => {
    respondWith((path) => (path === '/v1/session' ? refused : { data: [] }))

    renderAt('/w/payroll')

    expect(await screen.findByRole('heading', { name: i18n.t('auth.title') })).toBeInTheDocument()
  })

  it('renders nothing but the check while the session is unresolved', () => {
    /**
     * The routes mount only after the session resolves; mounting them earlier
     * fires one request per workspace that is going to be refused.
     */
    respondWith(() => new Promise(() => undefined))

    renderAt('/w/payroll')

    expect(screen.getByText(i18n.t('auth.checking'))).toBeInTheDocument()
    expect(screen.queryByLabelText(i18n.t('auth.keyLabel'))).toBeNull()
  })
})

describe('the command palette', () => {
  it('opens with Ctrl+K and navigates to the workspace it finds', async () => {
    vi.mocked(api.GET).mockImplementation(((path: string) =>
      Promise.resolve({ data: path === '/v1/session' ? SESSION : [] })) as never)
    renderAt('/')
    await screen.findByRole('heading', { name: i18n.t('home.needsYou') })

    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    const input = await screen.findByPlaceholderText(i18n.t('palette.placeholder'))
    /**
     * The palette searches labels and keywords, but the workspace names come
     * from the API; with the stubbed empty list the fallback i18n name is what
     * is displayed, so that is what the search has to match too.
     */
    await userEvent.type(input, 'Payroll')
    await userEvent.keyboard('{Enter}')

    expect(
      await screen.findByRole(
        'heading',
        { name: i18n.t('workspaces.payroll.name') },
        { timeout: 5000 },
      ),
    ).toBeInTheDocument()
  })

  it('offers no sign-out in the local-operator install', async () => {
    vi.mocked(api.GET).mockImplementation(((path: string) =>
      Promise.resolve({ data: path === '/v1/session' ? SESSION : [] })) as never)
    renderAt('/')
    await screen.findByRole('heading', { name: i18n.t('home.needsYou') })

    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    await screen.findByPlaceholderText(i18n.t('palette.placeholder'))

    expect(screen.queryByText(i18n.t('auth.signOut'))).toBeNull()
  })
})

describe('accessibility landmarks', () => {
  it('offers a skip link that targets the main landmark', async () => {
    /**
     * The sidebar renders every workspace and three rooms, so without this the
     * only way into the page by keyboard is through fourteen links that are not
     * the content. The assertion pins both halves: the link, and the landmark it
     * has to land on -- a skip link pointing at a missing id is worse than none.
     */
    renderAt('/')
    await screen.findByRole('heading', { name: i18n.t('home.needsYou') })

    const link = screen.getByRole('link', { name: i18n.t('common.skipToContent') })

    expect(link).toHaveAttribute('href', '#main-content')
    expect(document.querySelector('#main-content')).not.toBeNull()
  })
})
