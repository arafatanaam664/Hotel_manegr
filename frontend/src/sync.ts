// عميل المرحلة 10: مركز المزامنة (ملف 09) — الحالة، الدفع الفوري، التعارضات،
// الرفع الأولي، USB المشفر، سحب التراخيص، النبض — كلها عبر نفس بوابة API.
import { api } from './api'

function get<T>(path: string): Promise<T> {
  return api<T>(path)
}
function post<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
}

export interface SyncGap { from: number; to: number }

export interface SyncStatus {
  site_id: string
  cloud_url: string
  paired: boolean
  receiver_mode: boolean
  cycle_seconds: number
  lean_mode: boolean
  pending: number
  sent_unacked: number
  acked: number
  last_ack_seq: number
  gaps: SyncGap[]
  last_push_at: string
  last_success_at: string
  last_error: string | null
  last_heartbeat_at: string
  open_conflicts: number
  latency_note: string
}

export interface SyncEvent {
  seq: number
  entity: string
  entity_id: string
  op: string
  version: number
  state: string
  occurred_at: string
}

export interface SyncConflict {
  id: number
  entity: string
  entity_id: string
  reason: string
  local_val: Record<string, unknown>
  remote_val: Record<string, unknown>
  detected_at: string
}

export interface PushResult {
  pushed: number
  ack_seq?: number
  gaps?: SyncGap[]
  held?: number
  sent?: number
  pending?: number
  reason?: string
  error?: string
}

export interface BackfillResult {
  total: number
  created: Record<string, number>
  push?: PushResult
}

export const ENTITY_AR: Record<string, string> = {
  JOURNAL: 'قيد يومية',
  ROOM: 'غرفة',
  INV_ITEM: 'صنف مخزون',
}

export const EVENT_STATE_AR: Record<string, string> = {
  PENDING: 'بانتظار الإرسال',
  SENT: 'أُرسل — بانتظار التأكيد',
  ACKED: 'مؤكَّد ✓',
}

export const OP_AR: Record<string, string> = {
  INSERT: 'إضافة', UPDATE: 'تعديل', DELETE: 'شطب',
}

export const syncApi = {
  status: () => get<SyncStatus>('/api/sync/status'),
  pushNow: () => post<PushResult>('/api/sync/push-now'),
  backfill: (push: boolean) =>
    post<BackfillResult>('/api/sync/backfill', { push }),
  lean: (on: boolean) =>
    post<{ lean_mode: boolean }>(`/api/sync/lean/${on ? 'on' : 'off'}`),
  pullLicenses: () =>
    post<Record<string, unknown>>('/api/sync/pull-licenses'),
  heartbeat: () => post<Record<string, unknown>>('/api/sync/heartbeat-now'),
  conflicts: () => get<SyncConflict[]>('/api/sync/conflicts'),
  resolve: (id: number, choice: 'LOCAL' | 'REMOTE') =>
    post<{ resolved: boolean; applied: string }>(
      `/api/sync/conflicts/${id}/resolve`, { choice }),
  exportUsb: (password: string) => api<Record<string, unknown>>(
    `/api/sync/export-usb?password=${encodeURIComponent(password)}`),
  events: (limit = 50) => get<SyncEvent[]>(`/api/sync/events?limit=${limit}`),
}
