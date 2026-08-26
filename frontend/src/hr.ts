// عميل واجهة الموارد البشرية والرواتب — يلف /api/hr كاملاً (ملف 06)
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

export type EmpStatus = 'ACTIVE' | 'SUSPENDED' | 'TERMINATED'
export type RunStatus = 'DRAFT' | 'REVIEWED' | 'APPROVED' | 'POSTED' |
  'PAID' | 'CANCELLED'
export type RunKind = 'NORMAL' | 'SUPPLEMENTAL' | 'FINAL'

export interface Department {
  id: string; code: string; name_ar: string; cost_center_code: string
  payroll_account_code: string; is_confidential: boolean; is_active: boolean
}
export interface Position {
  id: string; department_id: string; title: string; grade: string
  is_active: boolean
}
export interface Employee {
  id: string; emp_no: string; full_name: string
  national_id: string | null; phone: string; branch_id: string
  department_id: string; department: string; department_code: string
  department_confidential: boolean
  position_id: string | null; shift_id: string | null
  hire_date: string; contract_type: string
  base_salary: string | null; allowances: { code: string; name: string;
    amount?: string; pct_base?: string }[]
  salary_masked: boolean; status: EmpStatus
  termination_date: string | null; termination_reason: string
}
export interface EmpChange {
  id: string; employee_id: string; change_type: string
  before: Record<string, unknown>; after: Record<string, unknown>
  doc_ref: string; effective_from: string; status: string
  approved_by: string | null; reject_reason: string; created_by: string
}
export interface Shift { id: string; name: string; from_time: string;
  to_time: string; overnight: boolean }
export interface RosterRow { id: string; employee_id: string; emp_no: string;
  employee: string; date: string; shift_id: string; shift: string }
export interface AttRow { id: string; employee_id: string; emp_no: string;
  date: string; status: string; in_time: string; out_time: string
  late_min: number; early_min: number; overtime_hours: string
  approved_by: string | null; entered_by: string }
export interface LeaveType { id: string; code: string; name: string;
  paid: boolean; accrual_per_month: string }
export interface LeaveReq { id: string; employee_id: string; emp_no: string;
  employee: string; leave_type: string; paid: boolean; from_date: string;
  to_date: string; days: string; reason: string; status: string
  approved_by: string | null; reject_reason: string; created_by: string }
export interface LeaveBal { employee_id: string; emp_no: string;
  employee: string; leave_type: string; year: number; entitled: string
  used: string; remaining: string }
export interface Advance { id: string; employee_id: string; emp_no: string;
  employee: string; amount: string; installments: number
  installment_amount: string; remaining: string; request_date: string
  first_deduct_month: string; reason: string; status: string
  approved_by: string | null; paid_by: string | null
  paid_entry_id: string | null; created_by: string }
export interface Penalty { id: string; employee_id: string; emp_no: string;
  pen_date: string; apply_month: string; amount: string; reason: string
  doc_ref: string; approved_by: string | null; deducted_run_id: string | null
  created_by: string }
export interface PayItem { id: string; code: string; name: string
  item_type: 'EARNING' | 'DEDUCTION'; calc: string; pct_base: string
  credit_account_code: string; is_system: boolean; is_active: boolean }
export interface PayrollRun { id: string; month: string; kind: RunKind
  supp_seq: number; parent_run_id: string | null
  final_employee_id: string | null; status: RunStatus
  employee_count: number; gross_total: string; unearned_total: string
  withholdings_total: string; advances_total: string; net_total: string
  prepared_by: string | null; approved_by: string | null
  posted_entry_id: string | null; paid_seq: number; created_by: string
  created_at: string | null }
export interface PayslipItem { code: string; name: string
  type: 'EARNING' | 'DEDUCTION'; amount: string; bucket: string
  note: string }
export interface Payslip { id: string; run_id: string; employee_id: string
  department_id: string; gross: string | null; unearned: string | null
  withholdings: string | null; advances: string | null
  penalties: string | null; net: string | null
  items_snapshot: PayslipItem[]; inputs_snapshot: Record<string, unknown>
  paid_entry_id: string | null; paid_at: string | null
  salary_masked: boolean }
export interface HrPolicy { day_count_mode: string; advance_max_pct: string
  workday_hours: string; ot_multiplier: string; late_deduct_daily: string
  penalty_credit_code: string; eos_enabled: boolean; eos_month_rate: string
  eos_credit_account_code: string }

const q = (o: Record<string, string>) => {
  const s = Object.entries(o).filter(([, v]) => v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&')
  return s ? '?' + s : s
}

export const hrApi = {
  // الهيكل
  departments: () => get<Department[]>('/api/hr/departments'),
  createDepartment: (b: unknown) =>
    post<{ id: string }>('/api/hr/departments', b),
  patchDepartment: (id: string, b: unknown) =>
    patch(`/api/hr/departments/${id}`, b),
  positions: (department_id = '') =>
    get<Position[]>('/api/hr/positions' + q({ department_id })),
  createPosition: (b: unknown) =>
    post<{ id: string }>('/api/hr/positions', b),
  // الموظفون
  employees: (o: Record<string, string> = {}) =>
    get<Employee[]>('/api/hr/employees' + q(o)),
  createEmployee: (b: unknown) =>
    post<{ id: string; emp_no: string }>('/api/hr/employees', b),
  suspendEmployee: (id: string, reason: string) =>
    post(`/api/hr/employees/${id}/suspend`, { reason }),
  terminateEmployee: (id: string, b: unknown) =>
    post(`/api/hr/employees/${id}/terminate`, b),
  changes: (employee_id = '') =>
    get<EmpChange[]>('/api/hr/changes' + q({ employee_id })),
  createChange: (b: unknown) =>
    post<{ id: string }>('/api/hr/changes', b),
  approveChange: (id: string) => post(`/api/hr/changes/${id}/approve`),
  rejectChange: (id: string, reason: string) =>
    post(`/api/hr/changes/${id}/reject`, { reason }),
  // الورديات والحضور
  shifts: () => get<Shift[]>('/api/hr/shifts'),
  createShift: (b: unknown) => post<{ id: string }>('/api/hr/shifts', b),
  roster: (month: string) => get<RosterRow[]>('/api/hr/roster' + q({ month })),
  setRoster: (rows: { employee_id: string; date: string; shift_id: string }[]) =>
    post<{ rows: number }>('/api/hr/roster', { rows }),
  attendance: (month: string, employee_id = '') =>
    get<AttRow[]>('/api/hr/attendance' + q({ month, employee_id })),
  upsertAttendance: (rows: unknown[]) => post('/api/hr/attendance', { rows }),
  approveAttendance: (ids: string[]) =>
    post('/api/hr/attendance/approve', { ids }),
  unapproveAttendance: (ids: string[]) =>
    post('/api/hr/attendance/unapprove', { ids }),
  // الإجازات
  leaveTypes: () => get<LeaveType[]>('/api/hr/leave-types'),
  createLeaveType: (b: unknown) => post('/api/hr/leave-types', b),
  accrueLeave: (month: string) =>
    post<{ month: string; accrued_rows: number }>('/api/hr/leave/accrue',
                                                  { month }),
  leaveRequests: (status = '') =>
    get<LeaveReq[]>('/api/hr/leave/requests' + q({ status })),
  createLeaveRequest: (b: unknown) =>
    post<{ id: string }>('/api/hr/leave/requests', b),
  approveLeave: (id: string) => post(`/api/hr/leave/requests/${id}/approve`),
  rejectLeave: (id: string, reason: string) =>
    post(`/api/hr/leave/requests/${id}/reject`, { reason }),
  leaveBalances: () => get<LeaveBal[]>('/api/hr/leave/balances'),
  // الجزاءات
  penalties: (month = '') => get<Penalty[]>('/api/hr/penalties' + q({ month })),
  createPenalty: (b: unknown) => post('/api/hr/penalties', b),
  approvePenalty: (id: string) => post(`/api/hr/penalties/${id}/approve`),
  // السلف
  advances: () => get<Advance[]>('/api/hr/advances'),
  createAdvance: (b: unknown) =>
    post<{ id: string; installment_amount: string }>('/api/hr/advances', b),
  approveAdvance: (id: string) => post(`/api/hr/advances/${id}/approve`),
  rejectAdvance: (id: string, reason: string) =>
    post(`/api/hr/advances/${id}/reject`, { reason }),
  disburseAdvance: (id: string, account_code = '1101') =>
    post<{ entry_id: string; remaining: string }>(
      `/api/hr/advances/${id}/disburse`, { account_code }),
  // بنود الرواتب
  payItems: () => get<PayItem[]>('/api/hr/pay-items'),
  createPayItem: (b: unknown) => post('/api/hr/pay-items', b),
  togglePayItem: (id: string, is_active: boolean) =>
    post(`/api/hr/pay-items/${id}/toggle`, { is_active }),
  // المسير
  runs: (month = '') => get<PayrollRun[]>('/api/hr/payroll/runs' + q({ month })),
  createRun: (b: unknown) => post<PayrollRun>('/api/hr/payroll/runs', b),
  recalcRun: (id: string, eos_amount?: string) =>
    post<PayrollRun>(`/api/hr/payroll/runs/${id}/recalc`,
                     { eos_amount: eos_amount ?? null }),
  prepareRun: (id: string) =>
    post<PayrollRun>(`/api/hr/payroll/runs/${id}/prepare`),
  approveRun: (id: string) =>
    post<PayrollRun>(`/api/hr/payroll/runs/${id}/approve`),
  postRun: (id: string) => post<PayrollRun>(`/api/hr/payroll/runs/${id}/post`),
  payRun: (id: string, b: unknown) =>
    post<PayrollRun>(`/api/hr/payroll/runs/${id}/pay`, b),
  cancelRun: (id: string, reason: string) =>
    post<PayrollRun>(`/api/hr/payroll/runs/${id}/cancel`, { reason }),
  runPayslips: (id: string) =>
    get<Payslip[]>(`/api/hr/payroll/runs/${id}/payslips`),
  employeeStatement: (empId: string) =>
    get<{ rows: { month: string; kind: string; supp_seq: number;
      run_status: string; payslip_id: string; gross: string; net: string;
      paid: boolean; items_snapshot: PayslipItem[] }[] }>(
      `/api/hr/payroll/statement/${empId}`),
  eosAccrue: (month: string) => post('/api/hr/payroll/eos-accrue', { month }),
  // التقارير
  register: (month: string) =>
    get<Record<string, unknown>>('/api/hr/reports/register' + q({ month })),
  compare: () => get<Record<string, unknown>[]>('/api/hr/reports/compare'),
  reportAdvances: () =>
    get<Record<string, unknown>[]>('/api/hr/reports/advances'),
  reportLeaveBal: () =>
    get<Record<string, unknown>[]>('/api/hr/reports/leave-balances'),
  turnover: () => get<Record<string, unknown>[]>('/api/hr/reports/turnover'),
  costVsRevenue: (month: string) =>
    get<Record<string, unknown>>(
      '/api/hr/reports/cost-vs-revenue' + q({ month })),
  policy: () => get<HrPolicy>('/api/hr/settings/policy'),
  putPolicy: (b: unknown) => put<HrPolicy>('/api/hr/settings/policy', b),
}

export const HR_STATUS_AR: Record<string, string> = {
  DRAFT: 'مسودة', REVIEWED: 'أُعدّ (HR)', APPROVED: 'معتمد',
  POSTED: 'مرحَّل', PAID: 'مدفوع', CANCELLED: 'ملغى',
  ACTIVE: 'نشط', SUSPENDED: 'موقوف', TERMINATED: 'منتهي',
  PENDING: 'معلق', REJECTED: 'مرفوض',
  REQUESTED: 'بطلب', SETTLED: 'مسوّى', CONVERTED: 'محوَّل',
}
export const RUN_KIND_AR: Record<string, string> = {
  NORMAL: 'شهري', SUPPLEMENTAL: 'تسوية', FINAL: 'نهائي',
}
export const CONTRACT_AR: Record<string, string> = {
  PERM: 'دائم', TEMP: 'مؤقت', PIECE: 'بالقطعة',
}
