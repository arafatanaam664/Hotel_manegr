// طبقة API لوحدة الفندق — أنواع وجلب موحد
import { api, HttpError, loadSession } from './api'

export interface RoomType {
  id: string; code: string; name_ar: string; name_en: string
  capacity_adults: number; capacity_children: number; beds: string
  amenities: string[]; display_order: number
  base_rate: string; is_active: boolean
}

export interface RoomRackItem {
  id: string; room_no: string; floor: number
  type: string; type_code: string; base_rate: string
  hk_status: string; occupied: boolean
  ooo_reason: string | null
  ooo_from: string | null; ooo_to: string | null
  current_rsv: string | null
  blocked_for_sale: boolean
  kind: string; is_suite: boolean
  parent_room_no: string | null
  components: string[]
  is_active: boolean
  features: string[]
  suite_note: string | null
}

export interface RatePlan {
  id: string; code: string; name_ar: string
  ref_rate: string | null; includes_breakfast: boolean
  cancel_policy: string; min_nights: number; for_corporate: boolean
  tax_inclusive: boolean; meals_included: string[]; is_active: boolean
}

export interface CalendarEntry {
  id: string; day: string; price: string
  day_type: string; rate_plan: string | null
}

export interface ExtraFull {
  id: string; code: string; name_ar: string; price: string
  revenue_account_code: string; is_active: boolean
}

type Json = Record<string, unknown>
const _post = <T>(path: string, body?: Json) =>
  api<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
const _patch = <T>(path: string, body: Json) =>
  api<T>(path, { method: 'PATCH', body: JSON.stringify(body) })

export const roomsApi = {
  createRoom: (b: Json) => _post<{ id: string; room_no: string }>('/api/hotel/rooms', b),
  updateRoom: (id: string, b: Json) => _patch<{ id: string }>(`/api/hotel/rooms/${id}`, b),
  components: (id: string) =>
    api<{ suite: string; components: { id: string; room_no: string }[] }>(`/api/hotel/rooms/${id}/components`),
  createType: (b: Json) => _post<{ id: string; code: string }>('/api/hotel/room-types', b),
  updateType: (id: string, b: Json) => _patch<{ id: string; base_rate: string }>(`/api/hotel/room-types/${id}`, b),
  plans: () => api<RatePlan[]>('/api/hotel/rate-plans'),
  createPlan: (b: Json) => _post<{ id: string; code: string }>('/api/hotel/rate-plans', b),
  updatePlan: (id: string, b: Json) => _patch<{ id: string; code: string }>(`/api/hotel/rate-plans/${id}`, b),
  calendar: (roomType: string, from: string, to: string) =>
    api<CalendarEntry[]>(`/api/hotel/rate-calendar?room_type=${encodeURIComponent(roomType)}&date_from=${from}&date_to=${to}`),
  calendarBulk: (b: Json) =>
    _post<{ days: number; created: number; updated: number }>('/api/hotel/rate-calendar/bulk', b),
  deleteCalendar: (id: string) => api<{ deleted: boolean }>(`/api/hotel/rate-calendar/${id}`, { method: 'DELETE' }),
  extrasAll: () => api<ExtraFull[]>('/api/hotel/extras?all=true'),
  createExtra: (b: Json) => _post<{ id: string; code: string }>('/api/hotel/extras', b),
  updateExtra: (id: string, b: Json) => _patch<{ id: string; price: string }>(`/api/hotel/extras/${id}`, b),
}

export interface Reservation {
  id: string; confirmation_no: string; status: string; source: string
  guest_name: string; guest_id_masked: string
  corporate: string | null; corporate_id: string | null
  room_no: string | null; room_type: string
  arrival_date: string; departure_date: string; nights: number
  adults: number; children: number
  agreed_rate: string; est_total: string
  deposit_balance: string
  checked_in_at: string | null; checked_out_at: string | null
  purpose: string; origin_gov: string; origin_district: string
  vehicle_note: string; police_notes: string
  companions?: Companion[]
  night_rates?: { date: string; rate: string; origin: string }[]
  folios?: FolioSummary[]
}

export interface FolioSummary {
  id: string; window: number; type: string; status: string
  credit_limit: string | null; balance: string
}

export interface FolioLine {
  entry_id: string; entry_no: string; date: string
  narration: string; line_desc: string
  debit: string; credit: string; running: string
}

export interface FolioDetail {
  folio_id: string; window: number; type: string; status: string
  reservation_id: string; conf: string
  credit_limit: string | null
  lines: FolioLine[]
  charges: string; payments: string; balance: string
  high_balance: boolean
}

export interface Extra { code: string; name_ar: string; price: string; revenue_account_code: string }

export interface Guest {
  id: string; full_name: string; phone: string
  id_masked: string; nationality: string; vip: boolean; blacklist: boolean
  id_type: string; id_issue_place: string; id_issue_date: string | null
  has_id: boolean
}

export interface Corporate {
  id: string; name: string; contact_person: string; phone: string
  credit_limit: string | null; discount_pct: string; settlement_period: string
}

export interface AuditPrecheck {
  business_date: string
  pending_arrivals: { id: string; conf: string; arrival: string; departure: string; status: string }[]
  pending_departures: { id: string; conf: string; arrival: string; departure: string; status: string }[]
  in_house_expect_nights: number
  can_run: boolean
}

export const hkNames: Record<string, string> = {
  CLEAN: 'نظيفة', INSPECTED: 'مفحوصة', DIRTY: 'متسخة',
  CLEANING: 'قيد التنظيف', OOO: 'معطلة', OOS: 'خارج الخدمة',
}

export const rsvStatusAr: Record<string, string> = {
  TENTATIVE: 'مبدئي', CONFIRMED: 'مؤكد', CHECKED_IN: 'مقيم',
  CHECKED_OUT: 'غادر', CANCELLED: 'ملغى', NO_SHOW: 'لم يحضر',
}

export async function getRack() {
  return api<{ business_date: string; items: RoomRackItem[] }>('/api/hotel/rooms')
}
export async function getRoomTypes() {
  return api<RoomType[]>('/api/hotel/room-types')
}
export async function getExtras() {
  return api<Extra[]>('/api/hotel/extras')
}
export async function getGuests(q = '') {
  return api<Guest[]>(`/api/hotel/guests?q=${encodeURIComponent(q)}`)
}
export async function getCorporates() {
  return api<Corporate[]>('/api/hotel/corporates')
}
export async function getReservations(params: Record<string, string> = {}) {
  const qs = new URLSearchParams(params).toString()
  return api<{ items: Reservation[]; total: number }>(`/api/hotel/reservations${qs ? '?' + qs : ''}`)
}
export async function getReservation(id: string) {
  return api<Reservation>(`/api/hotel/reservations/${id}`)
}
export async function getFolio(id: string) {
  return api<FolioDetail>(`/api/hotel/folios/${id}`)
}

// ═══ المعلومية اليومية (البحث الجنائي — 0.14.0) ═══
export interface Companion {
  id: string; full_name: string; id_type: string; id_masked: string
  id_issue_place: string; id_issue_date: string | null; phone: string
  origin_gov: string; origin_district: string
  has_id: boolean; sort_order: number
}

export interface PoliceRow {
  kind: 'main' | 'companion'; stay: number; serial: number
  room_no: string; name: string; arrival: string; purpose: string
  origin_gov: string; origin_district: string; id_type: string
  issue_place: string; issue_date: string; phone: string
  in_time: string; notes: string; vehicle: string; has_id: boolean
}

export interface PoliceHeader {
  hotel: string; address: string; district: string
  office: string; weekday: string; date: string
}

export interface PolicePreview {
  header: PoliceHeader; rows: PoliceRow[]
  warnings: string[]; stays_count: number; rows_count: number
}

export interface PoliceRun {
  id: string; report_date: string; generated_by: string
  generated_at: string; rows_count: number; stays_count: number
  sha256: string
}

export const policeApi = {
  preview: (date: string) =>
    api<PolicePreview>(`/api/hotel/police-report/preview?date=${date}`),
  runs: () => api<PoliceRun[]>('/api/hotel/police-report/runs'),
  saveHeader: (b: { address: string; district: string; office_label: string }) =>
    api<{ address: string }>('/api/org/tenant/header', {
      method: 'PATCH', body: JSON.stringify(b) }),
}

/** تنزيل ملف مصادَق كـ Blob مع اسم عربي من ترويسة الخادم */
export async function downloadFile(path: string, fallbackName: string) {
  const s = loadSession()
  const r = await fetch(path, {
    headers: { Authorization: `Bearer ${s?.access_token ?? ''}` },
  })
  if (!r.ok) {
    let code = 'HTTP.' + r.status, msg = 'فشل التنزيل'
    try {
      const j = await r.json()
      code = j.error?.code ?? code
      msg = j.error?.message_ar ?? msg
    } catch { /* غير JSON */ }
    throw new HttpError(r.status, code, msg)
  }
  const cd = r.headers.get('content-disposition') ?? ''
  const m = cd.match(/filename\*=UTF-8''([^;]+)/)
  const name = m ? decodeURIComponent(m[1]) : fallbackName
  const blob = await r.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  a.click()
  URL.revokeObjectURL(a.href)
  return name
}
