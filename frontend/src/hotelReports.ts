import { api } from './api'

export type HotelDailyReport = {
  business_day: string
  rooms_total: number
  rooms_sellable: number
  rooms_sold: number
  rooms_out_of_service: number
  occupancy_pct: string
  room_revenue: string
  adr: string
  revpar: string
  arrivals: number
  departures: number
  in_house: number
  no_shows: number
  housekeeping: Record<string, number>
  revenue_by_source: Record<string, string>
}

export type HotelRangeReport = {
  from_date: string
  to_date: string
  rows: HotelDailyReport[]
  totals: Omit<HotelDailyReport, 'business_day' | 'rooms_total' | 'rooms_sellable' | 'rooms_out_of_service' | 'in_house' | 'housekeeping' | 'revenue_by_source'>
}

export const hotelReportsApi = {
  daily: (day: string, branchId?: string) => api<HotelDailyReport>(`/api/reports/hotel/daily?business_day=${encodeURIComponent(day)}${branchId ? `&branch_id=${encodeURIComponent(branchId)}` : ''}`),
  range: (from: string, to: string, branchId?: string) => api<HotelRangeReport>(`/api/reports/hotel/range?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}${branchId ? `&branch_id=${encodeURIComponent(branchId)}` : ''}`),
}
