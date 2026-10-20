import { QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'
import { useTranslation } from 'react-i18next'

import { AppShell } from '@/components/layout/AppShell'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { queryClient } from '@/lib/query'
import { HomePage } from '@/pages/HomePage'
import { LoginPage } from '@/pages/LoginPage'
import { NotFoundPage } from '@/pages/NotFoundPage'

/**
 * The landing and sign-in stay in the first chunk; everything reachable after
 * that loads on demand. The workspace page alone pulls in ten workspaces, and
 * shipping that before the dashboard can paint was the bulk of the initial JS.
 */
const WorkspacePage = lazy(() =>
  import('@/pages/WorkspacePage').then((module) => ({ default: module.WorkspacePage })),
)
const ApplicationDetailPage = lazy(() =>
  import('@/pages/ApplicationDetailPage').then((module) => ({
    default: module.ApplicationDetailPage,
  })),
)
const ImportPage = lazy(() =>
  import('@/pages/ImportPage').then((module) => ({ default: module.ImportPage })),
)
const JobsPage = lazy(() =>
  import('@/pages/JobsPage').then((module) => ({ default: module.JobsPage })),
)
const OperationsPage = lazy(() =>
  import('@/pages/OperationsPage').then((module) => ({ default: module.OperationsPage })),
)

export function AppRoutes() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        {/* Outside the shell: there is no sidebar to render for somebody who is
              not signed in yet, and the shell's session gate would bounce this
              route back to itself. */}
        <Route path="login" element={<LoginPage />} />
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="w/:workspaceId" element={<WorkspacePage />} />
          <Route path="w/hiring/import" element={<ImportPage />} />
          <Route path="w/hiring/jobs" element={<JobsPage />} />
          <Route path="ops" element={<OperationsPage />} />
          <Route
            path="w/:workspaceId/applications/:applicationId"
            element={<ApplicationDetailPage />}
          />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </Suspense>
  )
}

function RouteFallback() {
  const { t } = useTranslation()
  return (
    <div
      role="status"
      className="bg-surface text-ink-muted flex min-h-dvh items-center justify-center text-sm"
    >
      {t('app.loading')}
    </div>
  )
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <BrowserRouter basename="/app">
          <AppRoutes />
        </BrowserRouter>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  )
}
