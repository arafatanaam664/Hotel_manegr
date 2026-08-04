// طبقة API لوحدة الفندق — أنواع وجلب موحد
import { api } from './api'

export interface RoomType {
  id: string; code: string; name_ar: string
  capacity_adults: number; capacity_children: number; beds: string
  base_rate: string; is_active: boolean
}

export interface RoomRackItem {
  id: string; room_no: string; floor: number
  type: string; type_code: string
  hk_status: string; occupied: boolean
  ooo_reason: string | null
  ooo_from: string | null; ooo_to: string | null
  current_rsv: string | null
  blocked_for_sale: boolean
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
