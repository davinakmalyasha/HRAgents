import { QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router'

import { AppShell } from '@/components/layout/AppShell'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { queryClient } from '@/lib/query'
import { ApplicationDetailPage } from '@/pages/ApplicationDetailPage'
import { HomePage } from '@/pages/HomePage'
import { ImportPage } from '@/pages/ImportPage'
import { JobsPage } from '@/pages/JobsPage'
import { LoginPage } from '@/pages/LoginPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { WorkspacePage } from '@/pages/WorkspacePage'

export function AppRoutes() {
  return (
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
        <Route
          path="w/:workspaceId/applications/:applicationId"
          element={<ApplicationDetailPage />}
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
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
