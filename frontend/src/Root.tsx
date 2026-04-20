import { QueryClientProvider } from "@tanstack/react-query"
import { ReactQueryDevtools } from "@tanstack/react-query-devtools"
import { createBrowserRouter, RouterProvider } from "react-router-dom"
import { AuthProvider } from "./auth/AuthProvider"
import { RequireAuth } from "./auth/RequireAuth"
import { AppShell } from "./components/AppShell"
import { ToasterProvider } from "./components/Toaster"
import { AuthCallback } from "./pages/AuthCallback"
import { NotFound } from "./pages/NotFound"
import { SessionDetailPage } from "./pages/SessionDetailPage"
import { SessionsListPage } from "./pages/SessionsListPage"
import { SignInPage } from "./pages/SignInPage"
import { SmokePage } from "./pages/SmokePage"
import { queryClient } from "./lib/queryClient"

const router = createBrowserRouter([
  { path: "/signin", element: <SignInPage /> },
  { path: "/auth/callback", element: <AuthCallback /> },
  { path: "/__smoke", element: <SmokePage /> },
  {
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { path: "/", element: <SessionsListPage /> },
      { path: "/s/:id", element: <SessionDetailPage /> },
    ],
  },
  { path: "*", element: <NotFound /> },
])

export function Root() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ToasterProvider>
          <RouterProvider router={router} />
          {import.meta.env.DEV && <ReactQueryDevtools initialIsOpen={false} />}
        </ToasterProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}
