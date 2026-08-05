// عميل المرحلة 7: الأصول الثابتة + القوائم المالية (02 §10) + إقفال السنة (02 §5)
import { api } from './api'

function get<T>(path: string): Promise<T> {
  return api<T>(path)
}
function post<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
}

export interface FaAsset {
  id: string; code: string; name: string; category: string
  purchase_date: string; cost: string; salvage: string
  life_months: number; method: 'STRAIGHT' | 'DECLINING'
  depreciated_total: string; nbv: string; status: 'ACTIVE' | 'DISPOSED'
  last_run_month: string | null; disposed_at: string | null
}
export interface FaRunLine {
  asset_id: string; code: string; name: string; method: string
  cost: string; nbv_before: string; charge: string; nbv_after: string
}
export interface FaRun {
  id: string; month: string; total: string; asset_count: number
  lines: FaRunLine[]; posted_entry_id: string | null
  created_at: string | null
}
export interface FaRegister {
  rows: FaAsset[]
  totals: { cost: string; depreciated: string; nbv: string }
  gl: { asset_accounts_cost: string; accum_depreciation: string; nbv: string }
  matches_gl: boolean; note: string
}
export interface MoneyRow { code: string; name: string; amount: string }
export interface UsaliDept { key: string; name: string; revenues: MoneyRow[]
  expenses: MoneyRow[]; revenue_total: string; expense_total: string
  dept_income: string }
export interface IncomeStatement {
  from: string; to: string; method: string
  departments: UsaliDept[]; departments_income: string
  other_revenue: MoneyRow[]; other_revenue_total: string
  undistributed: MoneyRow[]; undistributed_total: string
  gop: string; non_operating: MoneyRow[]; non_operating_total: string
  net_income: string
}
export interface BalanceSheet {
  as_of: string; current_assets: MoneyRow[]; fixed_assets: MoneyRow[]
  system_accounts: MoneyRow[]; total_assets: string
  liabilities: MoneyRow[]; total_liabilities: string
  equity: MoneyRow[]; current_year_earnings: string; total_equity: string
  balanced: boolean; diff: string
}
export interface CashFlow {
  from: string; to: string; method: string
  net_income: string; depreciation_addback: string
  delta_receivables: string; delta_inventory: string
  delta_operating_liabilities: string; operating: string
  delta_fixed_assets_gross: string; investing: string
  delta_loans: string; delta_owner_current: string; delta_capital: string
  financing: string; equity_and_system_transfers: string
  net_change: string; cash_delta_actual: string
  reconciliation_diff: string; identity_holds: boolean
}
export interface AgingRow { party: string; party_name: string
  party_type: string; buckets: Record<string, string>; total: string }
export interface Aging {
  account: string; account_name: string; as_of: string; method: string
  rows: AgingRow[]; totals: Record<string, string>; grand_total: string
  gl_balance: string; matches_gl: boolean
}
export interface FiscalYearInfo {
  id: string; year_no: number; start_date: string; end_date: string
  status: string; periods: { id: string; no: number; status: string }[]
}
export interface CloseCheck { key: string; ok: boolean; label: string
  rows?: { code: string; name: string; balance: string;
    blocking: boolean }[] }
export interface ClosePrecheck {
  year_no: number; status: string; start_date: string; end_date: string
  checks: CloseCheck[]; ready: boolean
}
export interface CloseResult {
  year_no: number; closing_entry_id: string; closing_entry_no: string
  revenue_closed: string; expense_closed: string; net_income: string
  opening_entry_id: string | null; opening_entry_no: string | null
  opening_lines: number; next_year_no: number; next_year_start: string
  status: string
}

const q = (o: Record<string, string>) => {
  const s = Object.entries(o).filter(([, v]) => v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&')
  return s ? '?' + s : s
}

export const finApi = {
  // الأصول
  assets: () => get<FaAsset[]>('/api/fa/assets'),
  createAsset: (b: unknown) => post<{ id: string; code: string }>(
    '/api/fa/assets', b),
  disposeAsset: (id: string, b: unknown) =>
    post<FaAsset>(`/api/fa/assets/${id}/dispose`, b),
  schedule: (id: string, from_month: string) =>
    get<{ asset: FaAsset; schedule: { month: string; charge: string;
      acc_dep: string; nbv: string }[] }>(
      `/api/fa/assets/${id}/schedule` + q({ from_month })),
  register: () => get<FaRegister>('/api/fa/register'),
  runs: () => get<FaRun[]>('/api/fa/runs'),
  runMonth: (month: string) => post<FaRun>('/api/fa/runs', { month }),
  // القوائم
  incomeStatement: (from: string, to: string) =>
    get<IncomeStatement>('/api/reports/income-statement' + q({ from, to })),
  balanceSheet: (as_of: string) =>
    get<BalanceSheet>('/api/reports/balance-sheet' + q({ as_of })),
  cashFlow: (from: string, to: string) =>
    get<CashFlow>('/api/reports/cash-flow' + q({ from, to })),
  aging: (account: string, as_of: string) =>
    get<Aging>('/api/reports/aging' + q({ account, as_of })),
  // الفترات والإقفال
  years: () => get<FiscalYearInfo[]>('/api/years'),
  precheck: (year_no: number) =>
    get<ClosePrecheck>(`/api/years/${year_no}/close-precheck`),
  closeYear: (year_no: number) =>
    post<CloseResult>(`/api/years/${year_no}/close`),
  closePeriod: (id: string) => post(`/api/periods/${id}/close`),
  hardClosePeriod: (id: string) => post(`/api/periods/${id}/hard-close`),
}

export const FA_METHOD_AR: Record<string, string> = {
  STRAIGHT: 'قسط ثابت', DECLINING: 'متناقص مضاعف' }
export const PERIOD_STATUS_AR: Record<string, string> = {
  OPEN: 'مفتوحة', SOFT_CLOSED: 'مغلقة ليناً', CLOSED: 'مغلقة',
  HARD_CLOSED: 'مغلقة صلباً 🔒' }
