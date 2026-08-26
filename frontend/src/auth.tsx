// سياق المصادقة: جلسة + أفعال (دخول/خروج) + فحص صلاحية
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import { api, loadSession, saveSession, type Session } from './api'
import type { TokenPair } from './types'

interface AuthCtx {
  session: Session | null
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  has: (perm: string) => boolean
}

const Ctx = createContext<AuthCtx>({
  session: null,
  login: async () => {},
  logout: async () => {},
  has: () => false,
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(loadSession())

  const value = useMemo<AuthCtx>(() => ({
    session,
    has: (perm: string) =>
      !!session && (session.user.perms.includes('*') || session.user.perms.includes(perm)),
    login: async (username, password) => {
      const pair = await api<TokenPair>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      const s: Session = {
        access_token: pair.access_token,
        refresh_token: pair.refresh_token,
        user: pair.user,
      }
      saveSession(s)
      setSession(s)
    },
    logout: async () => {
      const s = loadSession()
      if (s) {
        try {
          await api('/api/auth/logout', {
            method: 'POST',
            body: JSON.stringify({ refresh_token: s.refresh_token }),
          })
        } catch {
          /* الخروج محلياً حتى لو فشل الخادم */
        }
      }
      saveSession(null)
      setSession(null)
    },
  }), [session])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth() {
  return useContext(Ctx)
}
