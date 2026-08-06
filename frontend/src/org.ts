// طبقة API لإدارة المستخدمين والأدوار والصلاحيات (ADR-0037)
import { api } from './api'

export interface OrgUser {
  id: string; username: string; full_name: string
  email: string | null; is_active: boolean
  mfa_enabled: boolean; must_change_password: boolean
  last_login_at: string | null; locked_until: string | null
  roles: string[]; grants: string[]; denies: string[]
  login_windows: { from: string; to: string }[]
  branch_ids: string[]
}

export interface OrgRole {
  code: string; name: string; description: string
  permissions: string[]; is_system: boolean; users_count: number
}

export interface PermGroup {
  key: string; name: string
  perms: { code: string; name: string }[]
}

type Json = Record<string, unknown>
const _post = <T>(path: string, body?: Json) =>
  api<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
const _patch = <T>(path: string, body: Json) =>
  api<T>(path, { method: 'PATCH', body: JSON.stringify(body) })

export const orgApi = {
  users: () => api<OrgUser[]>('/api/org/users'),
  createUser: (b: Json) => _post<{ id: string; username: string }>('/api/org/users', b),
  patchUser: (id: string, b: Json) => _patch<OrgUser>(`/api/org/users/${id}`, b),
  toggleUser: (id: string) =>
    _post<{ is_active: boolean; sessions_revoked: number }>(`/api/org/users/${id}/toggle-active`),
  resetPassword: (id: string, new_password: string) =>
    _post<{ sessions_revoked: number }>(`/api/org/users/${id}/reset-password`, { new_password }),
  unlock: (id: string) => _post<{ unlocked: boolean }>(`/api/org/users/${id}/unlock`),
  revokeSessions: (id: string) =>
    _post<{ sessions_revoked: number }>(`/api/org/users/${id}/revoke-sessions`),
  effectivePerms: (id: string) =>
    api<{ username: string; perms: string[] }>(`/api/org/users/${id}/effective-perms`),
  roles: () => api<OrgRole[]>('/api/org/roles'),
  createRole: (b: Json) =>
    _post<{ code: string; name: string; permissions: string[] }>('/api/org/roles', b),
  patchRole: (code: string, b: Json) =>
    _patch<{ code: string; name: string; permissions: string[] }>(`/api/org/roles/${code}`, b),
  deleteRole: (code: string) =>
    api<{ deleted: boolean }>(`/api/org/roles/${code}`, { method: 'DELETE' }),
  catalog: () => api<PermGroup[]>('/api/org/permissions'),
}

export async function changeMyPassword(current_password: string, new_password: string) {
  return api<{ changed: boolean; other_sessions_revoked: number }>(
    '/api/auth/change-password',
    { method: 'POST', body: JSON.stringify({ current_password, new_password }) })
}
