// أنواع واجهة البرمجة — مرآة لمخططات الخادم (المبالغ تصل كنصوص Decimal)
export interface ApiError {
  error: { code: string; message_ar: string; detail?: string }
}

export interface UserOut {
  id: string
  username: string
  full_name: string
  tenant_id: string
  roles: string[]
  perms: string[]
  branches: string[]
  mfa_enabled?: boolean
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: UserOut
}

export interface Account {
  id: string
  code: string
  name_ar: string
  name_en: string
  parent_id: string | null
  level: number
  type: string
  nature: string
  is_postable: boolean
  is_active: boolean
  party_required: boolean
  is_system: boolean
}

export interface JournalLine {
  line_no: number
  account_code: string
  account_name: string
  debit: string
  credit: string
  party_type: string | null
  cost_center: string | null
  description: string
}

export interface Journal {
  id: string
  journal_type: string
  entry_no: string
  entry_date: string
  status: string
  currency_code: string
  narration: string
  reference: string | null
  source_type: string | null
  event_key: string | null
  reversal_of_entry_id: string | null
  reversed_entry_id: string | null
  total_debit: string
  total_credit: string
  created_at: string
  posted_at: string | null
  lines: JournalLine[]
}

export interface Paged<T> {
  total: number
  page: number
  page_size: number
  items: T[]
}

export interface TBRow {
  account_code: string
  account_name: string
  level: number
  nature: string
  debit_sum: string
  credit_sum: string
  balance: string
  balance_side: string
}

export interface TrialBalance {
  as_of: string
  total_debit: string
  total_credit: string
  balanced: boolean
  net_balance_zero: boolean
  rows: TBRow[]
}

export interface LedgerRow {
  entry_no: string
  entry_date: string
  journal_type: string
  narration: string
  debit: string
  credit: string
  running_balance: string
}

export interface Ledger {
  account_code: string
  account_name: string
  opening_balance: string
  closing_balance: string
  rows: LedgerRow[]
}

export interface Period {
  id: string
  period_no: number
  start_date: string
  end_date: string
  status: string
  year_no: number
}

export interface AuditItem {
  id: string
  at: string
  actor: string
  actor_type: string
  module: string
  action: string
  entity: string
  entity_id: string | null
  after: Record<string, unknown> | null
  business_date: string | null
}

export interface TenantInfo {
  id: string
  legal_name: string
  trade_name: string
  country: string
  base_currency: string
  timezone: string
  status: string
  branches: { id: string; code: string; name: string }[]
}

export interface DemoResult {
  year: number
  month: number
  days: number
  entries_posted: number
  daily_balance_ok: boolean
  issues: string[]
  total_debit: string
  total_credit: string
  balanced: boolean
  net_zero: boolean
}
