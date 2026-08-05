// طبقة API لوحدة المخزون والمشتريات — ملف 05
import { api } from './api'

function get<T>(path: string): Promise<T> {
  return api<T>(path)
}
function post<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
}
function put<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: 'PUT', body: JSON.stringify(body) })
}
function patch<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
}

export interface InvCategory {
  id: string; code: string; name_ar: string; default_account_code: string
  valuation_method: string; method_locked: boolean; is_active: boolean
}

export interface InvItem {
  id: string; code: string; name_ar: string; name_en: string
  category_id: string; category: string; base_unit: string
  alt_units: { unit: string; factor: string }[]; barcode: string
  reorder_level: string; safety_level: string
  inventory_account_code: string; track_expiry: boolean
  pos_item_id: string | null; is_active: boolean
  on_hand_total: string; value_total: string
}

export interface Warehouse {
  id: string; code: string; name_ar: string; kind: 'MAIN' | 'SUB' | 'OUTLET'
  inventory_account_code: string; keeper_user_id: string | null
  keeper_name: string | null; allow_negative: boolean
  pos_outlet_id: string | null; cost_center_code: string
  is_active: boolean; skus: number; stock_value: string
}

export interface Supplier {
  id: string; code: string; name: string; contact_person: string
  phone: string; address: string; terms_days: number; currency: string
  notes: string; rating_commitment: number; rating_quality: number
  is_active: boolean; balance: string
}

export interface SupplierPrice {
  id: string; item_id: string; item_code: string; price: string
  valid_from: string; valid_to: string | null
}

export interface PR {
  id: string; pr_no: string; department: string; status: string
  notes: string; created_by: string; created_at: string
  approved_by: string | null; reject_reason: string | null
  lines: { item_id: string; item_code: string; qty: string; note: string }[]
}

export interface POLine {
  id: string; item_id: string; item_code: string; item_name: string
  uom: string; factor: string; qty: string; base_qty: string
  unit_price: string; line_total: string; received_qty: string
}

export interface PO {
  id: string; po_no: string; supplier_id: string; supplier: string
  status: string; pr_id: string | null; expected_date: string | null
  terms: string; subtotal: string; tax_amount: string; total: string
  approve_level_required: number; created_by: string; created_at: string
  approved1_by: string | null; approved2_by: string | null
  reject_reason: string | null; lines: POLine[]
}

export interface GRN {
  id: string; grn_no: string; status: string; po_id: string | null
  supplier_id: string; supplier: string; warehouse_id: string
  warehouse: string; purchase_type: 'CASH' | 'CREDIT'
  supplier_invoice_no: string; payment_account_code: string
  subtotal: string; tax_amount: string; total: string
  entry_id: string | null; note: string; created_by: string
  created_at: string; posted_by: string | null; posted_at: string | null
  lines: {
    item_id: string; item_code: string; qty_ordered: string
    qty_received: string; qty_rejected: string; reject_reason: string | null
    unit_price: string; line_total: string; batch_no: string
    expiry_date: string | null
  }[]
}

export interface SInvoice {
  id: string; sinv_no: string; supplier_invoice_no: string
  supplier_id: string; supplier: string; po_id: string | null
  grn_id: string | null; invoice_date: string; status: string
  subtotal: string; tax_amount: string; total: string
  paid_amount: string; remaining: string
  match_report: { checked_at: string; result: string; issues: {
    item: string; issue: string; detail: string; diff?: string }[] } | null
  variance_approved_by: string | null; created_by: string
  created_at: string; approved_by: string | null
  lines: { item_id: string; item_code: string; qty: string
    unit_price: string; line_total: string }[]
}

export interface Payment {
  id: string; pay_no: string; supplier: string; payment_date: string
  method: string; account_code: string; amount: string; discount: string
  allocations: { invoice_id: string; sinv_no: string; amount: string }[]
  created_by: string
}

export interface SReturn {
  id: string; srt_no: string; status: string; supplier: string
  warehouse: string; refund_to: string; total: string; reason: string
  created_at: string
  lines: { item_code: string; qty: string; unit_cost: string
    line_total: string }[]
}

export interface Issue {
  id: string; iss_no: string; status: string
  from_warehouse: string; from_warehouse_id: string
  to_warehouse: string; to_warehouse_id: string
  department: string; reason: string; entry_id: string | null
  created_by: string; created_at: string
  approved_by: string | null; issued_by: string | null
  lines: { item_id: string; item_code: string; qty: string
    unit_cost: string | null; line_value: string | null }[]
}

export interface Transfer {
  id: string; trf_no: string; status: string
  from_warehouse: string; from_warehouse_id: string
  to_warehouse: string; to_warehouse_id: string
  requires_receive: boolean; reason: string; entry_id: string | null
  created_by: string; created_at: string
  dispatched_by: string | null; received_by: string | null
  lines: { item_id: string; item_code: string; qty: string
    unit_cost: string | null }[]
}

export interface Waste {
  id: string; wst_no: string; status: string; warehouse: string
  warehouse_id: string; reason: string; photo_ref: string
  total_value: string; entry_id: string | null; created_by: string
  created_at: string; approved_by: string | null
  reject_reason: string | null
  lines: { item_id: string; item_code: string; qty: string
    unit_cost: string; line_value: string; line_reason: string }[]
}

export interface Count {
  id: string; cnt_no: string; status: string; warehouse: string
  warehouse_id: string; category_id: string | null
  short_value: string; over_value: string
  short_entry_id: string | null; over_entry_id: string | null
  created_by: string; created_at: string; counted_by: string | null
  approved1_by: string | null; approved2_by: string | null
  posted_at: string | null
  lines?: {
    item_id: string; item_code: string; item_name: string
    system_qty: string; counted_qty: string | null; unit_cost: string
    variance_qty: string | null; variance_value: string | null
  }[]
}

export interface StockValueRow {
  warehouse_id: string; warehouse: string; warehouse_code: string
  account_code: string; item_id: string; item_code: string
  item_name: string; unit: string; qty: string; avg_cost: string
  value: string
}

export interface StockValueReport {
  rows: StockValueRow[]
  accounts_match: {
    account_code: string; stock_value: string; ledger_balance: string
    diff: string; matched: boolean
  }[]
  all_matched: boolean
}

export interface MoveRow {
  id: string; business_date: string; warehouse: string
  item_code: string; item_name: string; qty_delta: string
  unit_cost: string; value_delta: string; reason: string
  ref_type: string; ref_id: string; batch_no: string
  expiry_date: string | null
}

export interface Alerts {
  reorder: {
    item_id: string; code: string; name: string; unit: string
    on_hand: string; reorder_level: string; safety_level: string
    avg_daily_consumption: string; suggested_qty: string
  }[]
  expiry: {
    item_id: string; code: string; name: string; warehouse: string
    batch_no: string; expiry_date: string; days_left: number
    window: number; qty: string
  }[]
  stagnant: {
    item_id: string; code: string; name: string; qty: string
    last_move_date: string | null; idle_days: number | null
  }[]
  ledger_mismatch: { account_code: string; diff: string }[]
  ledger_ok: boolean
}

export interface Policy {
  po_l0_limit: string; po_l1_limit: string
  price_tolerance_pct: string; qty_tolerance_pct: string
  expiry_windows: number[]; stagnant_days: number
  consumption_days: number
}

export const invApi = {
  categories: () => get<InvCategory[]>('/api/inv/categories'),
  createCategory: (b: unknown) => post('/api/inv/categories', b),
  items: (q = '', categoryId = '') =>
    get<InvItem[]>(`/api/inv/items?q=${encodeURIComponent(q)}&category_id=${categoryId}`),
  createItem: (b: unknown) => post('/api/inv/items', b),
  patchItem: (id: string, b: unknown) => patch(`/api/inv/items/${id}`, b),
  warehouses: () => get<Warehouse[]>('/api/inv/warehouses'),
  createWarehouse: (b: unknown) => post('/api/inv/warehouses', b),
  suppliers: () => get<Supplier[]>('/api/inv/suppliers'),
  createSupplier: (b: unknown) => post('/api/inv/suppliers', b),
  supplierPrices: (id: string) => get<SupplierPrice[]>(`/api/inv/suppliers/${id}/prices`),
  addSupplierPrice: (id: string, b: unknown) => post(`/api/inv/suppliers/${id}/prices`, b),
  statement: (id: string) => get<unknown>(`/api/inv/suppliers/${id}/statement`),
  prs: (status = '') => get<PR[]>(`/api/inv/pr?status=${status}`),
  createPr: (b: unknown) => post<PR>('/api/inv/pr', b),
  submitPr: (id: string) => post<PR>(`/api/inv/pr/${id}/submit`),
  approvePr: (id: string, approve = true, reason = '') =>
    post<PR>(`/api/inv/pr/${id}/approve?approve=${approve}`, reason ? { reason } : {}),
  pos: (status = '') => get<PO[]>(`/api/inv/po?status=${status}`),
  createPo: (b: unknown) => post<PO>('/api/inv/po', b),
  approvePo: (id: string) => post<PO>(`/api/inv/po/${id}/approve`),
  rejectPo: (id: string, reason: string) => post<PO>(`/api/inv/po/${id}/reject`, { reason }),
  cancelPo: (id: string, reason: string) => post<PO>(`/api/inv/po/${id}/cancel`, { reason }),
  grns: (status = '') => get<GRN[]>(`/api/inv/grn?status=${status}`),
  createGrn: (b: unknown) => post<GRN>('/api/inv/grn', b),
  postGrn: (id: string) => post<GRN>(`/api/inv/grn/${id}/post`),
  reverseGrn: (id: string, reason: string) => post<GRN>(`/api/inv/grn/${id}/reverse`, { reason }),
  invoices: (status = '') => get<SInvoice[]>(`/api/inv/invoices?status=${status}`),
  createInvoice: (b: unknown) => post<SInvoice>('/api/inv/invoices', b),
  approveInvoice: (id: string) => post<SInvoice>(`/api/inv/invoices/${id}/approve`),
  resolveVariance: (id: string, b: unknown) =>
    post<SInvoice>(`/api/inv/invoices/${id}/resolve-variance`, b),
  payments: (supplierId = '') =>
    get<Payment[]>(`/api/inv/payments?supplier_id=${supplierId}`),
  createPayment: (b: unknown) => post('/api/inv/payments', b),
  returns: () => get<SReturn[]>('/api/inv/returns'),
  createReturn: (b: unknown) => post<SReturn>('/api/inv/returns', b),
  postReturn: (id: string) => post<SReturn>(`/api/inv/returns/${id}/post`),
  issues: (status = '') => get<Issue[]>(`/api/inv/issues?status=${status}`),
  createIssue: (b: unknown) => post<Issue>('/api/inv/issues', b),
  approveIssue: (id: string) => post<Issue>(`/api/inv/issues/${id}/approve`),
  rejectIssue: (id: string, reason: string) =>
    post<Issue>(`/api/inv/issues/${id}/reject`, { reason }),
  executeIssue: (id: string) => post<Issue>(`/api/inv/issues/${id}/execute`),
  transfers: (status = '') => get<Transfer[]>(`/api/inv/transfers?status=${status}`),
  createTransfer: (b: unknown) => post<Transfer>('/api/inv/transfers', b),
  dispatchTransfer: (id: string) => post<Transfer>(`/api/inv/transfers/${id}/dispatch`),
  receiveTransfer: (id: string) => post<Transfer>(`/api/inv/transfers/${id}/receive`),
  waste: (status = '') => get<Waste[]>(`/api/inv/waste?status=${status}`),
  createWaste: (b: unknown) => post<Waste>('/api/inv/waste', b),
  submitWaste: (id: string) => post<Waste>(`/api/inv/waste/${id}/submit`),
  approveWaste: (id: string) => post<Waste>(`/api/inv/waste/${id}/approve`),
  rejectWaste: (id: string, reason: string) =>
    post<Waste>(`/api/inv/waste/${id}/reject`, { reason }),
  counts: (status = '') => get<Count[]>(`/api/inv/counts?status=${status}`),
  count: (id: string) => get<Count>(`/api/inv/counts/${id}`),
  createCount: (b: unknown) => post<Count>('/api/inv/counts', b),
  enterCount: (id: string, counted: unknown[]) =>
    post<Count>(`/api/inv/counts/${id}/enter`, { counted }),
  finishCount: (id: string) => post<Count>(`/api/inv/counts/${id}/finish`),
  approveCount: (id: string, level: number) =>
    post<Count>(`/api/inv/counts/${id}/approve`, { level }),
  cancelCount: (id: string, reason: string) =>
    post<Count>(`/api/inv/counts/${id}/cancel`, { reason }),
  stockValue: (warehouseId = '') =>
    get<StockValueReport>(`/api/inv/reports/stock-value?warehouse_id=${warehouseId}`),
  reconciliation: () =>
    get<{ ok: boolean; alerts: unknown[]; checked: number }>('/api/inv/reports/reconciliation'),
  moves: (params: Record<string, string>) =>
    get<MoveRow[]>(`/api/inv/reports/moves?${new URLSearchParams(params)}`),
  purchases: (from: string, to: string) =>
    get<{ supplier_id: string; supplier: string; grn_count: number
      cash_total: string; credit_total: string; total: string }[]>(
      `/api/inv/reports/purchases?date_from=${from}&date_to=${to}`),
  supplierPerf: () => get<unknown[]>(`/api/inv/reports/suppliers`),
  ppv: (from: string, to: string) => get<unknown[]>(`/api/inv/reports/ppv?date_from=${from}&date_to=${to}`),
  wasteReport: () => get<{ months: { month: string; moves: number
    qty: string; value: string }[] }>('/api/inv/reports/waste'),
  consumption: (from: string, to: string) =>
    get<{ rows: { item_id: string; code: string; name: string; unit: string
      theoretical_qty: string; actual_qty: string; variance_qty: string
      waste_count_qty: string; variance_pct: string | null }[]; note: string }>(
      `/api/inv/reports/consumption?date_from=${from}&date_to=${to}`),
  alerts: () => get<Alerts>('/api/inv/alerts'),
  policy: () => get<Policy>('/api/inv/settings/policy'),
  putPolicy: (b: unknown) => put('/api/inv/settings/policy', b),
}

export const INV_STATUS_AR: Record<string, string> = {
  DRAFT: 'مسودة', SUBMITTED: 'مرفوع', APPROVED: 'معتمد', REJECTED: 'مرفوض',
  CONVERTED: 'محوَّل لأمر', PENDING_L1: 'بانتظار اعتماد أول',
  PENDING_L2: 'بانتظار اعتماد ثانٍ', PART_RECEIVED: 'مستلم جزئياً',
  RECEIVED: 'مستلم كلياً', CANCELLED: 'ملغي', POSTED: 'مرحَّل',
  REVERSED: 'معكوس', MATCHED: 'مطابق', VARIANCE_HOLD: 'موقوف لفرق',
  PAID: 'مسدد', REQUESTED: 'مطلوب', ISSUED: 'مصروف',
  IN_TRANSIT: 'على الطريق', PENDING: 'بانتظار الاعتماد',
  FREEZE: 'تجميد وعدّ', COUNTED: 'معدود', OPEN: 'مفتوح',
}

export const MOVE_REASON_AR: Record<string, string> = {
  OPENING: 'افتتاحي', PURCHASE: 'شراء', PURCHASE_REV: 'عكس شراء',
  PURCHASE_RETURN: 'مرتجع مورد', ISSUE_OUT: 'صرف لقسم', ISSUE_IN: 'توريد من صرف',
  TRANSFER_OUT: 'تحويل صادر', TRANSFER_IN: 'تحويل وارد', WASTE: 'هالك',
  COUNT_SHORT: 'عجز جرد', COUNT_OVER: 'زيادة جرد', SALE_POS: 'بيع POS',
  POS_RETURN: 'مرتجع POS', ADJUST: 'تسوية',
}
