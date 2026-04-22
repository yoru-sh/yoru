import { createContext, useCallback, useEffect, useState, type ReactNode } from "react"
import { getMe, signout as apiSignout, type AuthUser } from "../lib/auth-api"

interface AuthCtx {
  user: AuthUser | null
  loading: boolean
  refresh: () => Promise<void>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthCtx>({
  user: null,
  loading: true,
  refresh: async () => {},
  signOut: async () => {},
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    const me = await getMe()
    setUser(me)
    setLoading(false)
  }, [])

  useEffect(() => {
    let mounted = true
    getMe()
      .then((me) => {
        if (!mounted) return
        setUser(me)
      })
      .catch(() => {
        if (!mounted) return
        setUser(null)
      })
      .finally(() => {
        if (!mounted) return
        setLoading(false)
      })
    return () => {
      mounted = false
    }
  }, [])

  const signOut = useCallback(async () => {
    try {
      await apiSignout()
    } catch {
      // ignore — cookies will be cleared regardless once browser refreshes
    }
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, refresh, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}
