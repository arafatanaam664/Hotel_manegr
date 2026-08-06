// طبقة API لوحدة الفندق — أنواع وجلب موحد
import { api } from './api'

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
