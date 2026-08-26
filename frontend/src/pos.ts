// طبقة API لوحدة نقاط البيع — ملف 04
import { api } from './api'

function get<T>(path: string): Promise<T> {
  return api<T>(path)
}
function post<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: 'POST', body: JSON.stringify(body) })
}
function put<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: 'PUT', body: JSON.stringify(body) })
}
function patch<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
}

export interface Outlet {
  id: string; code: string; name_ar: string; name_en: string
  cash_account_code: string; default_revenue_account_code: string
  allow_negative_stock: boolean; cash_variance_tolerance: string
  cost_center_code: string; is_active: boolean
}

export interface Category {
  id: string; code: string; name_ar: string; name_en: string
  color: string; station: string; sort_order: number
}

export interface Item {
  id: string; code: string; name_ar: string; name_en: string
  barcode: string; category_id: string; price: string
  tax_included: boolean; revenue_account_code: string
  item_type: 'STOCK' | 'SERVICE' | 'COMPOSITE'; cost: string
  is_active: boolean
}

export interface Modifier { id: string; name_ar: string; price: string }

export interface OrderLine {
  id: string; item_id: string; item_name: string; station: string
  qty: string; unit_price: string
  modifiers: { id: string; name: string; price: string }[]
  notes: string; line_total: string; discount: string
  status: 'NORMAL' | 'VOID'; void_reason: string | null
  void_by: string | null
}

export interface PosOrder {
  id: string; outlet_id: string; outlet: string; shift_id: string
  type: 'DINE_IN' | 'TAKEAWAY' | 'ROOM_SERVICE'
  status: 'DRAFT' | 'FIRED' | 'CLOSED' | 'CANCELLED'
  table_id: string | null; table_name: string | null
  note: string; cancel_reason: string | null
  opened_by: string; opened_at: string; fired_at: string | null
  total: string; lines: OrderLine[]
}

export interface Table {
  id: string; name: string; zone: string; seats: number; occupied: boolean
}

export interface Invoice {
  id: string; invoice_no: string; type: 'SALE' | 'RETURN'
  outcome?: string; outlet: string; outlet_code: string
  business_date: string; issued_by?: string; issued_at: string
  gross_total?: string; discount_total: string; tax_total?: string
  net_total: string; cost_total?: string
  lines?: { item_id: string; item: string; qty: string; unit_price: string
            modifiers: { name: string; price: string }[]
            notes: string; total: string; discount: string }[]
  payments?: { method: string; amount: string; room_no: string | null
               folio_id: string | null; corporate_id: string | null
               house_reason: string | null }[]
  entry_no?: string | null; return_of?: string | null
  return_reason?: string | null
}

export interface Shift {
  id: string; outlet_id: string; outlet: string; status: 'OPEN' | 'CLOSED'
  opened_by: string; opened_at: string; opening_float: string
  closed_at: string | null; actual_cash: string | null
  expected_cash: string | null; cash_variance: string | null
}

export interface OccupiedRoom {
  folio_id: string; reservation_id: string; room_no: string
  guest_short: string; vip: boolean; balance: string
  credit_limit: string | null
}

export interface StockRow {
  item_id: string; code: string; name: string; type: string
  qty_on_hand: string; unit_cost: string; negative: boolean
}

export interface SettlePayment {
  method: 'CASH' | 'CARD' | 'EWALLET' | 'ROOM' | 'CORPORATE' | 'HOUSE'
  amount: string | number
  folio_id?: string | null; corporate_id?: string | null
  reason?: string | null; approver_pin?: string | null
}

export const posApi = {
  outlets: () => get<Outlet[]>('/api/pos/outlets'),
  categories: () => get<Category[]>('/api/pos/categories'),
  items: (q = '', categoryId = '', limit = 300) =>
    get<{ total: number; items: Item[] }>(
      `/api/pos/items?limit=${limit}&search=${encodeURIComponent(q)}&category_id=${categoryId}`),
  itemModifiers: (itemId: string) =>
    get<Modifier[]>(`/api/pos/items/${itemId}/modifiers`),
  tables: (outletId: string) =>
    get<Table[]>(`/api/pos/tables?outlet_id=${outletId}`),
  stock: (outletId: string) =>
    get<StockRow[]>(`/api/pos/stock?outlet_id=${outletId}`),
  stockLoad: (outletId: string, body: { item_id: string; qty: number; unit_cost: number }) =>
    post(`/api/pos/stock/load?outlet_id=${outletId}`, body),
  orders: (status = '', shiftId = '') =>
    get<PosOrder[]>(`/api/pos/orders?status=${status}&shift_id=${shiftId}`),
  order: (id: string) => get<PosOrder>(`/api/pos/orders/${id}`),
  createOrder: (body: { outlet_id: string; type?: string; table_id?: string | null; note?: string }) =>
    post<PosOrder>('/api/pos/orders', body),
  addLine: (orderId: string, body: { item_id: string; qty: number; modifiers: { id: string }[]; notes?: string; discount?: number }) =>
    post(`/api/pos/orders/${orderId}/lines`, body),
  voidLine: (orderId: string, lineId: string, reason: string) =>
    post(`/api/pos/orders/${orderId}/lines/${lineId}/void`, { reason }),
  fire: (orderId: string) => post<PosOrder>(`/api/pos/orders/${orderId}/fire`, {}),
  cancelOrder: (orderId: string, reason: string) =>
    post(`/api/pos/orders/${orderId}/cancel`, { reason }),
  settle: (orderId: string, body: {
    client_uuid: string; payments: SettlePayment[]
    invoice_discount?: number; discount_reason?: string; approver_pin?: string
  }) => post<{ invoice: Invoice; replayed: boolean }>(
    `/api/pos/orders/${orderId}/settle`, body),
  invoices: (outletId = '', type = '') =>
    get<Invoice[]>(`/api/pos/invoices?outlet_id=${outletId}&type=${type}`),
  invoice: (id: string) => get<Invoice>(`/api/pos/invoices/${id}`),
  returnInvoice: (id: string, reason: string) =>
    post<Invoice>(`/api/pos/invoices/${id}/return`, { reason }),
  occupiedRooms: () => get<OccupiedRoom[]>('/api/pos/room-charge/occupied'),
  shifts: (outletId = '', status = '') =>
    get<Shift[]>(`/api/pos/shifts?outlet_id=${outletId}&status=${status}`),
  openShift: (outletId: string, openingFloat: number) =>
    post('/api/pos/shifts/open', { outlet_id: outletId, opening_float: openingFloat }),
  closeShift: (shiftId: string, actualCash: number) =>
    post<Record<string, unknown>>(`/api/pos/shifts/${shiftId}/close`, { actual_cash: actualCash }),
  zreport: (shiftId: string) =>
    get<{ status: string; live_summary?: Record<string, unknown>; zreport?: Record<string, unknown> }>(`/api/pos/shifts/${shiftId}/zreport`),
  zReports: (outletId = '') =>
    get<{ shift_id: string; zreport: Record<string, unknown> }[]>(`/api/pos/z-reports?outlet_id=${outletId}`),
  setPin: (currentPassword: string, pin: string) =>
    post('/api/pos/users/me/pin', { current_password: currentPassword, pin }),
  salesReport: (from: string, to: string, groupBy: string) =>
    get<{ group: string; net: string; cost: string; count: string; margin: string; margin_pct: number }[]>(
      `/api/pos/reports/sales?date_from=${from}&date_to=${to}&group_by=${groupBy}`),
  controlReport: (from: string, to: string) =>
    get<Record<string, unknown[]>>(`/api/pos/reports/control?date_from=${from}&date_to=${to}`),
}
