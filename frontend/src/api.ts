// عميل API: مركزية أخطاء موحّدة + تجديد تلقائي لرمز الوصول عند 401
import type { TokenPair } from './types'

const LS_KEY = 'sijill.session'

export interface Session {
  access_token: string
  refresh_token: string
  user: TokenPair['user']
}

export function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? (JSON.parse(raw) as Session) : null
  } catch {
    return null
  }
}

export function saveSession(s: Session | null) {
  if (s) localStorage.setItem(LS_KEY, JSON.stringify(s))
  else localStorage.removeItem(LS_KEY)
}

export class HttpError extends Error {
  code: string
  status: number
  constructor(status: number, code: string, messageAr: string) {
    super(messageAr)
    this.status = status
    this.code = code
  }
}

let refreshing: Promise<boolean> | null = null

async function tryRefresh(): Promise<boolean> {
  const s = loadSession()
  if (!s) return false
  try {
    const r = await fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: s.refresh_token }),
    })
    if (!r.ok) return false
    const pair = (await r.json()) as TokenPair
    saveSession({
      access_token: pair.access_token,
      refresh_token: pair.refresh_token,
      user: pair.user,
    })
    return true
  } catch {
    return false
  }
}

export async function api<T = unknown>(
  path: string,
  opts: RequestInit = {},
  retry = true,
): Promise<T> {
  const s = loadSession()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(opts.headers as Record<string, string>),
  }
  if (s) headers['Authorization'] = `Bearer ${s.access_token}`
  const r = await fetch(path, { ...opts, headers })
  if (r.status === 401 && retry && s) {
    refreshing = refreshing ?? tryRefresh()
    const ok = await refreshing
    refreshing = null
    if (ok) return api<T>(path, opts, false)
    saveSession(null)
    window.location.href = '/login'
    throw new HttpError(401, 'AUTH.SESSION_EXPIRED', 'انتهت الجلسة')
  }
  if (!r.ok) {
    let code = `HTTP.${r.status}`
    let msg = 'حدث خطأ غير متوقع'
    try {
      const body = await r.json()
      if (body?.error) {
        code = body.error.code
        msg = body.error.message_ar + (body.error.detail ? ` — ${body.error.detail}` : '')
      }
    } catch {
      /* جسم غير JSON */
    }
    throw new HttpError(r.status, code, msg)
  }
  return (await r.json()) as T
}

/** تنسيق مبلغ Decimal النصي: فاصلة آلاف و4 خانات اختيارية */
export function fmt(n: string | number | null | undefined, dp = 2): string {
  if (n === null || n === undefined) return '—'
  const v = typeof n === 'string' ? parseFloat(n) : n
  if (Number.isNaN(v)) return String(n)
  return v.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
}

export function todayISO(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
