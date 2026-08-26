// عميل المرحلة 8: الترخيص (ملف 07) — الحالة + التثبيت + التفعيل المعزول
import { api } from './api'

function get<T>(path: string): Promise<T> {
  return api<T>(path)
}
function post<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
}

export interface LicenseStatus {
  state: 'TRIAL' | 'LICENSED' | 'GRACE' | 'READ_ONLY' | 'SUSPENDED' |
    'REVOKED' | 'INVALID' | 'CLOCK_LOCK'
  status_reason: string
  package: string
  legal_name: string
  license_id: string
  support_level: string
  issued_at: string | null
  valid_until: string | null
  grace_until: string | null
  days_to_expire: number | null
  in_grace: boolean
  trial: boolean
  trial_started: string | null
  modules_enabled: string[]
  modules_disabled: string[]
  features_flags: Record<string, unknown>
  limits: {
    max_users: number; used_users: number
    max_branches: number; used_branches: number
  }
  fingerprint: { bound: boolean; match_components: number; passing: boolean; hash: string }
  clock_anchor_date: string | null
  last_check: string | null
  revocation_serial: number
  site_id: string
}

export interface ActivationRequest {
  kind: string
  tenant_id: string
  site_id: string
  date: string
  hardware_fingerprint: Record<string, string>
  hardware_fingerprint_hash: string
  nonce: string
}

export const STATE_AR: Record<string, string> = {
  TRIAL: 'تجريبي',
  LICENSED: 'مرخّص وساري',
  GRACE: 'مهلة تجديد',
  READ_ONLY: 'قراءة فقط',
  SUSPENDED: 'موقوف (قرار شركة)',
  REVOKED: 'ملغى — قراءة فقط',
  INVALID: 'غير صالح',
  CLOCK_LOCK: 'قفل ساعة احترازي',
}

export const STATE_COLOR: Record<string, string> = {
  TRIAL: '#8a6d1a',
  LICENSED: '#1a7a3c',
  GRACE: '#b8860b',
  READ_ONLY: '#c0392b',
  SUSPENDED: '#7b241c',
  REVOKED: '#c0392b',
  INVALID: '#c0392b',
  CLOCK_LOCK: '#7b241c',
}

export const MODULE_AR: Record<string, string> = {
  ACCOUNTING: 'المحاسبة', HOTEL: 'الفندقة', POS: 'نقاط البيع',
  INVENTORY: 'المخزون', HR: 'الموارد البشرية',
  ASSETS: 'الأصول الثابتة', MULTIBRANCH: 'تعدد الفروع',
}

export const PACKAGE_AR: Record<string, string> = {
  LOCAL: 'محلي', CLOUD: 'سحابي', HYBRID: 'هجين',
}

export const licApi = {
  status: () => get<LicenseStatus>('/api/license/status'),
  evaluate: () => post<LicenseStatus>('/api/license/evaluate'),
  install: (payload: unknown) =>
    post<{ installed: boolean; already: boolean; status: LicenseStatus }>(
      '/api/license/install', { payload }),
  activationRequest: () => get<ActivationRequest>('/api/license/activation-request'),
  importRevocations: (payload: unknown) =>
    post<{ imported: boolean; revocation_serial: number; status: LicenseStatus }>(
      '/api/license/revocations', { payload }),
}
