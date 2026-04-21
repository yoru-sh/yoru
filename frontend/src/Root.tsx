import { QueryClientProvider } from "@tanstack/react-query"
import { ReactQueryDevtools } from "@tanstack/react-query-devtools"
import { createBrowserRouter, RouterProvider } from "react-router-dom"
import { AuthProvider } from "./auth/AuthProvider"
import { RequireAuth } from "./auth/RequireAuth"
import { AppShell } from "./components/AppShell"
import { Toaster } from "./components/Toaster"
import { AuthCallback } from "./pages/AuthCallback"
import { BillingCancelPage } from "./pages/BillingCancelPage"
import { BillingPage } from "./pages/BillingPage"
import { BillingSuccessPage } from "./pages/BillingSuccessPage"
import { DocsInstallPage } from "./pages/DocsInstallPage"
import { NotFound } from "./pages/NotFound"
import { SessionDetailPage } from "./pages/SessionDetailPage"
import { SessionsListPage } from "./pages/SessionsListPage"
import { SignInPage } from "./pages/SignInPage"
import { SmokePage } from "./pages/SmokePage"
import { WelcomePage } from "./pages/WelcomePage"
import { queryClient } from "./lib/queryClient"

const router = createBrowserRouter([
  { path: "/signin", element: <SignInPage /> },
  { path: "/auth/callback", element: <AuthCallback /> },
  { path: "/docs/install", element: <DocsInstallPage /> },
  { path: "/__smoke", element: <SmokePage /> },
  {
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { path: "/", element: <SessionsListPage /> },
      { path: "/welcome", element: <WelcomePage /> },
      { path: "/s/:id", element: <SessionDetailPage /> },
      // TODO: nest under a /settings shell once US-21 tabs land.
      { path: "/settings/billing", element: <BillingPage /> },
      { path: "/billing/success", element: <BillingSuccessPage /> },
      { path: "/billing/cancel", element: <BillingCancelPage /> },
    ],
  },
  { path: "*", element: <NotFound /> },
])

export function Root() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
        <Toaster />
        {import.meta.env.DEV && <ReactQueryDevtools initialIsOpen={false} />}
      </AuthProvider>
    </QueryClientProvider>
  )
}
