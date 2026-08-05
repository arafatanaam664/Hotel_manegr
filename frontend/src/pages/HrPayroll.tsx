// الرواتب والمسيرات: معالج شهري باعتماد مزدوج وترحيل #21 وصرف #22 / قسائم
// وأرشيف لكل موظف / سلف بجدولة آلية #23 / بنود وسياسة — ملف 06 §3/§4
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { fmt, todayISO } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import type { Advance, Employee, HrPolicy, Payslip, PayslipItem,
  PayrollRun, PayItem } from '../hr'
import { HR_STATUS_AR, RUN_KIND_AR, hrApi } from '../hr'

const TABS = ['المسيرات', 'القسائم', 'السلف', 'بنود الرواتب',
  'السياسة'] as const
const inp = 'border border-slate-300 rounded-lg px-2 py-1.5 text-sm'
const th = 'px-3 py-2 text-right text-xs text-slate-500 font-semibold'
const td = 'px-3 py-2 text-sm'

const RUN_TONE: Record<string, 'slate' | 'amber' | 'blue' | 'green' | 'red'> = {
  DRAFT: 'slate', REVIEWED: 'amber', APPROVED: 'blue', POSTED: 'blue',
  PAID: 'green', CANCELLED: 'red' }

export default function HrPayroll() {
  const { has } = useAuth()
  const canPrepare = has('hr.payroll.prepare')
  const canApprove = has('hr.payroll.approve')
  const canPay = has('hr.pay')
  const canAdvReq = has('hr.advance.request')
  const canAdvAppr = has('hr.advance.approve')
  const canSalary = has('hr.salary.view')
  const canPolicy = has('hr.policy.manage')

  const [tab, setTab] = useState<string>(TABS[0])
  const [month, setMonth] = useState(todayISO().slice(0, 7))
  const [runs, setRuns] = useState<PayrollRun[]>([])
  const [emps, setEmps] = useState<Employee[]>([])
  const [advs, setAdvs] = useState<Advance[]>([])
  const [items, setItems] = useState<PayItem[]>([])
  const [pol, setPol] = useState<HrPolicy | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // نماذج
  const [newRun, setNewRun] = useState({ kind: 'NORMAL', parent_run_id: '',
    employee_id: '', eos_amount: '' })
  const [suppLines, setSuppLines] = useState([{ code: 'ADJ', name: '',
    type: 'EARNING', amount: '', credit: '2310', note: '' }])
  const [advForm, setAdvForm] = useState({ employee_id: '', amount: '',
    installments: '1', first_deduct_month: month, reason: '' })
  const [itemForm, setItemForm] = useState({ code: '', name: '',
    item_type: 'DEDUCTION', calc: 'PCT_BASE', pct_base: '',
    credit_account_code: '2220' })
  const [polForm, setPolForm] = useState({ day_count_mode: 'FIXED30',
    advance_max_pct: '', workday_hours: '', ot_multiplier: '',
    late_deduct_daily: '', penalty_credit_code: '2220',
    eos_enabled: false, eos_month_rate: '', eos_credit_account_code: '2320' })
  // القسائم
  const [slipRunId, setSlipRunId] = useState('')
  const [slips, setSlips] = useState<Payslip[]>([])
  const [openSlip, setOpenSlip] = useState<string | null>(null)
  const [stmtEmp, setStmtEmp] = useState('')
  const [stmt, setStmt] = useState<{ month: string; kind: string;
    supp_seq: number; run_status: string; payslip_id: string; gross: string;
    net: string; paid: boolean; items_snapshot: PayslipItem[] }[]>([])
  // صرف جزئي
  const [paySel, setPaySel] = useState<Set<string>>(new Set())

  const refresh = useCallback(async () => {
    const [rs, es, as, is_, p] = await Promise.all([
      hrApi.runs(month), hrApi.employees(), hrApi.advances(),
      hrApi.payItems(), hrApi.policy()])
    setRuns(rs); setEmps(es); setAdvs(as); setItems(is_); setPol(p)
    setPolForm({ day_count_mode: p.day_count_mode,
      advance_max_pct: p.advance_max_pct, workday_hours: p.workday_hours,
      ot_multiplier: p.ot_multiplier, late_deduct_daily: p.late_deduct_daily,
      penalty_credit_code: p.penalty_credit_code,
      eos_enabled: p.eos_enabled, eos_month_rate: p.eos_month_rate,
      eos_credit_account_code: p.eos_credit_account_code })
    if (canSalary && slipRunId)
      setSlips(await hrApi.runPayslips(slipRunId))
  }, [month, canSalary, slipRunId])

  useEffect(() => { refresh().catch((e) => setErr((e as Error).message)) },
             [refresh])

  const run = async (fn: () => Promise<void>, okMsg: string) => {
    setErr(null); setOk(null); setBusy(true)
    try { await fn(); setOk(okMsg); setPaySel(new Set()); await refresh() }
    catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }
  const ask = (t: string) => window.prompt(t)?.trim() ?? ''

  const postedParents = useMemo(() => runs.filter((r) =>
    r.kind === 'NORMAL' && ['POSTED', 'PAID'].includes(r.status)), [runs])
  const terminated = useMemo(() => emps.filter((e) =>
    e.status === 'TERMINATED'), [emps])
  const advCapFor = (empId: string) => {
    const e = emps.find((x) => x.id === empId)
    if (!e || e.base_salary === null || !pol) return null
    return parseFloat(e.base_salary) * parseFloat(pol.advance_max_pct) / 100
  }

  const loadSlips = async (runId: string) => {
    setSlipRunId(runId); setOpenSlip(null); setPaySel(new Set())
    try { setSlips(await hrApi.runPayslips(runId)) }
    catch (e) { setSlips([]); setErr((e as Error).message) }
  }
  const loadStmt = async (empId: string) => {
    setStmtEmp(empId); setStmt([])
    if (!empId) return
    try { const r = await hrApi.employeeStatement(empId); setStmt(r.rows) }
    catch (e) { setErr((e as Error).message) }
  }

  const itmRows = (its: PayslipItem[]) => (
    <table className='w-full mt-1'>
      <thead><tr className='border-b border-slate-100'>
        <th className={th}>البند</th><th className={th}>النوع</th>
        <th className={th}>المبلغ</th><th className={th}>ملاحظة</th>
      </tr></thead>
      <tbody>
        {its.map((x, i) => (
          <tr key={i} className='border-b border-slate-50'>
            <td className={td}>{x.code} — {x.name}</td>
            <td className={td}><Badge tone={x.type === 'EARNING' ? 'green' : 'red'}>
              {x.type === 'EARNING' ? 'استحقاق' : 'استقطاع'}</Badge></td>
            <td className={`${td} font-mono font-bold ${x.type === 'EARNING' ? 'text-emerald-700' : 'text-red-700'}`}>
              {fmt(x.amount)}</td>
            <td className={`${td} text-xs text-slate-500`}>{x.note || '—'}</td>
          </tr>))}
        {!its.length && <tr><td className={td} colSpan={4}>لا بنود</td></tr>}
      </tbody>
    </table>)

  return (
    <div className='space-y-4'>
      <div className='flex gap-2 flex-wrap items-center'>
        {TABS.map((t) => (
          <Btn key={t} kind={tab === t ? 'primary' : 'ghost'}
            onClick={() => { setTab(t); setErr(null); setOk(null) }}>{t}</Btn>))}
        <span className='ms-4'>
          <input className={inp} type='month' value={month}
            onChange={(e) => setMonth(e.target.value)} />
        </span>
        {tab === TABS[0] && canApprove && pol?.eos_enabled && (
          <Btn kind='ghost' onClick={() => run(async () => {
            const r = await hrApi.eosAccrue(month) as { total: string;
              posted: number }
            setOk(`مخصص نهاية الخدمة ${month}: ${fmt(r.total)} لـ${r.posted} موظفاً (قيد #يوثَّق)`)
          }, '')}>تسيير مخصص نهاية الخدمة ⏳</Btn>)}
      </div>
      <ErrorNote msg={err} />
      <OkNote msg={ok} />
      {busy && <Spinner />}

      {/* ═══════════ المسيرات ═══════════ */}
      {tab === TABS[0] && (
        <>
          {canPrepare && (
            <Card title='إنشاء مسير — لا قيد قبل اعتماد المالية (§4.2)'>
              <div className='flex gap-2 flex-wrap items-center'>
                <select className={inp} value={newRun.kind}
                  onChange={(e) => setNewRun((f) => ({ ...f,
                    kind: e.target.value, parent_run_id: '', employee_id: '' }))}>
                  {Object.entries(RUN_KIND_AR).map(([k, v]) =>
                    <option key={k} value={k}>{v}</option>)}
                </select>
                {newRun.kind === 'SUPPLEMENTAL' && (
                  <>
                    <select className={inp} value={newRun.parent_run_id}
                      onChange={(e) => setNewRun((f) => ({ ...f,
                        parent_run_id: e.target.value }))}>
                      <option value=''>المسير الأصل المرحَّل *</option>
                      {postedParents.map((r) => <option key={r.id} value={r.id}>
                        {r.month} — {HR_STATUS_AR[r.status]} ({fmt(r.net_total)})</option>)}
                    </select>
                    <select className={inp} value={newRun.employee_id}
                      onChange={(e) => setNewRun((f) => ({ ...f,
                        employee_id: e.target.value }))}>
                      <option value=''>الموظف المستهدف *</option>
                      {emps.map((e) => <option key={e.id} value={e.id}>
                        {e.emp_no} — {e.full_name}</option>)}
                    </select>
                  </>)}
                {newRun.kind === 'FINAL' && (
                  <>
                    <select className={inp} value={newRun.employee_id}
                      onChange={(e) => setNewRun((f) => ({ ...f,
                        employee_id: e.target.value }))}>
                      <option value=''>الموظف المنتهي *</option>
                      {terminated.map((e) => <option key={e.id} value={e.id}>
                        {e.emp_no} — {e.full_name} ({e.termination_date})</option>)}
                    </select>
                    <input className={inp + ' w-32'} placeholder='مكافأة نهاية خدمة'
                      type='number' value={newRun.eos_amount}
                      onChange={(e) => setNewRun((f) => ({ ...f,
                        eos_amount: e.target.value }))} />
                  </>)}
                <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                  const body: Record<string, unknown> = {
                    month, kind: newRun.kind }
                  if (newRun.kind === 'SUPPLEMENTAL') {
                    body.parent_run_id = newRun.parent_run_id
                    body.manual_lines = { [newRun.employee_id]: suppLines
                      .filter((x) => x.name && parseFloat(x.amount || '0') > 0)
                      .map((x) => ({ ...x, amount: parseFloat(x.amount) })) }
                  }
                  if (newRun.kind === 'FINAL') {
                    body.employee_id = newRun.employee_id
                    if (newRun.eos_amount)
                      body.eos_amount = parseFloat(newRun.eos_amount)
                  }
                  await hrApi.createRun(body)
                }, 'أُنشئ مسودة — راجع القسائم ثم جهّز للاعتماد')}>
                  إنشاء مسودة {month}</Btn>
              </div>
              {newRun.kind === 'SUPPLEMENTAL' && newRun.employee_id && (
                <div className='mt-2 space-y-1.5'>
                  <div className='text-xs text-slate-500'>
                    أسطر التسوية (تظهر سطراً جديداً مستقلاً في كشف الموظف §7):</div>
                  {suppLines.map((x, i) => (
                    <div key={i} className='flex gap-1.5 flex-wrap'>
                      <input className={inp + ' w-28'} placeholder='الاسم *' value={x.name}
                        onChange={(e) => setSuppLines(suppLines.map((y, j) => j === i
                          ? { ...y, name: e.target.value } : y))} />
                      <select className={inp} value={x.type}
                        onChange={(e) => setSuppLines(suppLines.map((y, j) => j === i
                          ? { ...y, type: e.target.value } : y))}>
                        <option value='EARNING'>استحقاق +</option>
                        <option value='DEDUCTION'>استقطاع −</option>
                      </select>
                      <input className={inp + ' w-24'} placeholder='المبلغ' type='number'
                        value={x.amount}
                        onChange={(e) => setSuppLines(suppLines.map((y, j) => j === i
                          ? { ...y, amount: e.target.value } : y))} />
                      <input className={inp} placeholder='ملاحظة' value={x.note}
                        onChange={(e) => setSuppLines(suppLines.map((y, j) => j === i
                          ? { ...y, note: e.target.value } : y))} />
                      <Btn kind='ghost' disabled={suppLines.length < 2}
                        onClick={() => setSuppLines(suppLines.filter((_, j) => j !== i))}>✖</Btn>
                    </div>))}
                  <Btn kind='ghost' onClick={() => setSuppLines([...suppLines,
                    { code: 'ADJ', name: '', type: 'EARNING', amount: '',
                      credit: '2310', note: '' }])}>+ سطر</Btn>
                </div>)}
              {newRun.kind === 'NORMAL' && (
                <div className='mt-2 text-xs text-slate-500'>
                  مسير واحد نشط لكل شهر — التصحيح لاحقاً عبر «تسوية» موثقة
                  (لا حذف للأرقام).</div>)}
            </Card>)}

          <Card title={`مسيرات ${month} (${runs.length})`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الشهر/النوع</th><th className={th}>الموظفون</th>
                <th className={th}>الإجمالي</th><th className={th}>الصافي</th>
                <th className={th}>الحالة</th><th className={th}>إجراءات</th>
              </tr></thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className='border-b border-slate-50'>
                    <td className={td}>
                      <Badge tone={r.kind === 'NORMAL' ? 'blue' : r.kind === 'FINAL' ? 'red' : 'amber'}>
                        {RUN_KIND_AR[r.kind]}</Badge>
                      {' '}{r.month}{r.kind === 'SUPPLEMENTAL' ? ` #${r.supp_seq}` : ''}
                    </td>
                    <td className={`${td} font-mono`}>{r.employee_count}</td>
                    <td className={`${td} font-mono`}>{fmt(r.gross_total)}</td>
                    <td className={`${td} font-mono font-bold`}>{fmt(r.net_total)}</td>
                    <td className={td}><Badge tone={RUN_TONE[r.status]}>
                      {r.status === 'APPROVED' ? 'معتمد (مالية)'
                        : HR_STATUS_AR[r.status]}</Badge>
                      {r.posted_entry_id && <span className='text-emerald-700'> #21✓</span>}
                      {r.status === 'PAID' && <span className='text-emerald-700'> #22✓</span>}
                    </td>
                    <td className={td}>
                      <div className='flex gap-1 flex-wrap'>
                        {r.status === 'DRAFT' && canPrepare && (<>
                          <Btn className='!px-2 !py-1 text-xs' kind='ghost'
                            onClick={() => run(async () => { await hrApi.recalcRun(r.id) },
                              'أُعيد الاحتساب من مدخلات معتمدة')}>احتساب ⟳</Btn>
                          <Btn className='!px-2 !py-1 text-xs'
                            onClick={() => run(async () => { await hrApi.prepareRun(r.id) },
                              'جُهّز — بانتظار اعتماد المالية (اعتماد مزدوج)')}>تجهيز ➜</Btn>
                        </>)}
                        {r.status === 'REVIEWED' && canApprove && (
                          <Btn className='!px-2 !py-1 text-xs'
                            onClick={() => run(async () => { await hrApi.approveRun(r.id) },
                              'اعتُمد من المالية — جاهز للترحيل')}>اعتماد مالية ✅</Btn>)}
                        {r.status === 'APPROVED' && canApprove && (
                          <Btn className='!px-2 !py-1 text-xs' kind='gold'
                            onClick={() => run(async () => { await hrApi.postRun(r.id) },
                              'رُحّل قيد الاستحقاق #21 — متوازن لكل قسم')}>ترحيل #21 📒</Btn>)}
                        {r.status === 'POSTED' && canPay && (
                          <Btn className='!px-2 !py-1 text-xs' kind='gold'
                            onClick={() => {
                              const note = ask('مرجع/ملاحظة إثبات الصرف:')
                              if (note === null as unknown as string) return
                              run(async () => {
                                await hrApi.payRun(r.id, { receipt_note: note })
                              }, 'صُرف قيد #22 — 2310 ← 1101')
                            }}>صرف #22 💵</Btn>)}
                        {['DRAFT', 'REVIEWED', 'APPROVED'].includes(r.status)
                          && canPrepare && (
                          <Btn className='!px-2 !py-1 text-xs' kind='danger'
                            onClick={() => { const rs = ask('سبب الإلغاء (يوثَّق):')
                              if (rs) run(async () => { await hrApi.cancelRun(r.id, rs) },
                                'أُلغي — الرقم محجوز لا يُعاد') }}>إلغاء</Btn>)}
                        {canSalary && ['DRAFT', 'REVIEWED', 'APPROVED', 'POSTED', 'PAID']
                          .includes(r.status) && (
                          <Btn className='!px-2 !py-1 text-xs' kind='ghost'
                            onClick={() => { setTab(TABS[1]); loadSlips(r.id) }}>
                            القسائم</Btn>)}
                        {r.status === 'APPROVED' && (
                          <span className='text-[11px] text-slate-400 self-center'>
                            معتمد — لا تعديل من أي طريق (§7)</span>)}
                      </div>
                    </td>
                  </tr>))}
                {!runs.length && <tr><td className={td} colSpan={6}>
                  لا مسيرات لهذا الشهر — أنشئ مسودة</td></tr>}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ═══════════ القسائم ═══════════ */}
      {tab === TABS[1] && (
        <>
          <div className='grid md:grid-cols-2 gap-4'>
            <Card title='قسائم مسير'>
              <select className={inp + ' mb-2 w-full'} value={slipRunId}
                disabled={!canSalary}
                onChange={(e) => loadSlips(e.target.value)}>
                <option value=''>اختر المسير…</option>
                {runs.map((r) => <option key={r.id} value={r.id}>
                  {RUN_KIND_AR[r.kind]} {r.month}{r.kind === 'SUPPLEMENTAL'
                    ? ` #${r.supp_seq}` : ''} — {HR_STATUS_AR[r.status]}</option>)}
              </select>
              {!canSalary && <div className='text-xs text-amber-700'>
                عرض القسائم يتطلب صلاحية «الاطلاع على الرواتب» — ملف 06 §6
                (الخصوصية الصفية).</div>}
              {slipRunId && canSalary && (
              <table className='w-full'>
                <thead><tr className='border-b border-slate-100'>
                  {paySel.size > 0 && <th className={th}></th>}
                  <th className={th}>الموظف</th><th className={th}>إجمالي</th>
                  <th className={th}>خصوم</th><th className={th}>صافٍ</th>
                  <th className={th}>الصرف</th>
                </tr></thead>
                <tbody>
                  {slips.map((s) => {
                    const e = emps.find((x) => x.id === s.employee_id)
                    const ded = (parseFloat(s.unearned ?? '0')
                      + parseFloat(s.withholdings ?? '0')
                      + parseFloat(s.advances ?? '0')
                      + parseFloat(s.penalties ?? '0'))
                    return (
                    <Fragment key={s.id}>
                      <tr className='border-b border-slate-50 cursor-pointer hover:bg-slate-50'
                        onClick={() => setOpenSlip(openSlip === s.id ? null : s.id)}>
                        {paySel.size > 0 && (
                          <td className={td} onClick={(ev) => ev.stopPropagation()}>
                            {!s.paid_entry_id && (
                              <input type='checkbox' checked={paySel.has(s.id)}
                                onChange={(ev) => { const st = new Set(paySel)
                                  if (ev.target.checked) st.add(s.id); else st.delete(s.id)
                                  setPaySel(st) }} />)}
                          </td>)}
                        <td className={td}>{e?.emp_no ?? ''} — {e?.full_name ?? s.employee_id}
                          {e?.department_confidential && ' 🔒'}</td>
                        <td className={`${td} font-mono`}>
                          {s.gross === null ? '•••' : fmt(s.gross)}</td>
                        <td className={`${td} font-mono text-red-700`}>
                          {s.gross === null ? '•••' : fmt(ded)}</td>
                        <td className={`${td} font-mono font-bold text-emerald-700`}>
                          {s.net === null ? '•••' : fmt(s.net)}</td>
                        <td className={td}>{s.paid_entry_id
                          ? <Badge tone='green'>مدفوعة ✓</Badge>
                          : <Badge tone='amber'>غير مدفوعة</Badge>}</td>
                      </tr>
                      {openSlip === s.id && (
                        <tr className='bg-slate-50/60'><td colSpan={6} className='px-4 py-2'>
                          <div className='text-xs text-slate-500 mb-1'>
                            لقطة صندوقة عند الاحتساب (Snapshot §4.2-2) — مشاهدة موثقة بالتدقيق:</div>
                          {itmRows(s.items_snapshot)}
                          <div className='flex gap-2 flex-wrap mt-2'>
                            {Object.entries(s.inputs_snapshot).map(([k, v]) => (
                              <Badge key={k} tone='slate'>{k}: {String(v)}</Badge>))}
                          </div>
                        </td></tr>)}
                    </Fragment>)
                  })}
                  {!slips.length && <tr><td className={td} colSpan={6}>
                    اختر مسيراً لعرض قسائمه</td></tr>}
                </tbody>
              </table>)}
              {paySel.size > 0 && slipRunId && canPay && (
                <div className='mt-2'>
                  <Btn kind='gold' disabled={busy} onClick={() => {
                    const note = ask(`إثبات صرف ${paySel.size} قسيمة فردية:`) ?? ''
                    run(async () => {
                      const r = runs.find((x) => x.id === slipRunId)
                      if (r) await hrApi.payRun(slipRunId,
                        { payslip_ids: [...paySel], receipt_note: note })
                    }, `صُرفت ${paySel.size} قسيمة`)
                  }}>صرف المحددة ({paySel.size}) 💵</Btn>
                </div>)}
            </Card>
            <Card title='كشف أرشيف موظف (قسائم متسلسلة §5)'>
              <select className={inp + ' mb-2 w-full'} value={stmtEmp}
                disabled={!canSalary}
                onChange={(e) => loadStmt(e.target.value)}>
                <option value=''>اختر الموظف…</option>
                {emps.map((e) => <option key={e.id} value={e.id}>
                  {e.emp_no} — {e.full_name}{e.department_confidential ? ' 🔒' : ''}</option>)}
              </select>
              {stmt.map((row, i) => (
                <details key={i} className='border border-slate-100 rounded-lg mb-1.5'>
                  <summary className='px-3 py-2 text-sm cursor-pointer flex gap-3 items-center'>
                    <Badge tone={row.kind === 'SUPPLEMENTAL' ? 'amber' : row.kind === 'FINAL' ? 'red' : 'blue'}>
                      {RUN_KIND_AR[row.kind]}{row.kind === 'SUPPLEMENTAL' ? ` #${row.supp_seq}` : ''}</Badge>
                    <span className='font-mono text-xs'>{row.month}</span>
                    <span className='font-mono'>إجمالي {fmt(row.gross)}</span>
                    <b className='font-mono text-emerald-700'>صافٍ {fmt(row.net)}</b>
                    {row.paid ? <Badge tone='green'>مدفوعة</Badge>
                      : <Badge tone='amber'>{HR_STATUS_AR[row.run_status]}</Badge>}
                  </summary>
                  <div className='px-3 pb-2'>{itmRows(row.items_snapshot)}</div>
                </details>))}
              {stmtEmp && !stmt.length && <div className='text-sm text-slate-500'>
                لا قسائم بعد لهذا الموظف</div>}
            </Card>
          </div>
        </>
      )}

      {/* ═══════════ السلف ═══════════ */}
      {tab === TABS[2] && (
        <>
          {canAdvReq && (
            <Card title={`طلب سلفة — سقف ${pol?.advance_max_pct ?? '—'}% من الراتب (§3) وجدولة إقساط آلية من أول راتب`}>
              <div className='flex gap-2 flex-wrap items-center'>
                <select className={inp} value={advForm.employee_id}
                  onChange={(e) => setAdvForm((f) => ({ ...f,
                    employee_id: e.target.value }))}>
                  <option value=''>الموظف *</option>
                  {emps.filter((e) => e.status === 'ACTIVE').map((e) =>
                    <option key={e.id} value={e.id}>{e.emp_no} — {e.full_name}</option>)}
                </select>
                <input className={inp + ' w-28'} placeholder='المبلغ *' type='number'
                  value={advForm.amount}
                  onChange={(e) => setAdvForm((f) => ({ ...f, amount: e.target.value }))} />
                <input className={inp + ' w-20'} placeholder='الأقساط' type='number'
                  min={1} max={36} value={advForm.installments}
                  onChange={(e) => setAdvForm((f) => ({ ...f,
                    installments: e.target.value }))} />
                <input className={inp} type='month' value={advForm.first_deduct_month}
                  title='أول شهر خصم'
                  onChange={(e) => setAdvForm((f) => ({ ...f,
                    first_deduct_month: e.target.value }))} />
                <input className={inp} placeholder='السبب' value={advForm.reason}
                  onChange={(e) => setAdvForm((f) => ({ ...f, reason: e.target.value }))} />
                <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                  const r = await hrApi.createAdvance({
                    ...advForm, amount: parseFloat(advForm.amount || '0'),
                    installments: parseInt(advForm.installments || '1') })
                  setOk(`قدّم الطلب — قسط شهري ${fmt(r.installment_amount)} بانتظار الاعتماد`)
                }, '')}>تقديم الطلب</Btn>
              </div>
              {advForm.employee_id && advCapFor(advForm.employee_id) !== null && (
                <div className='mt-1 text-xs text-slate-500'>
                  سقف هذا الموظف: <b>{fmt(advCapFor(advForm.employee_id)!)}</b>
                  {' '}(يتحقق النظام آلياً عند الإنشاء)</div>)}
            </Card>)}
          <Card title={`السلف (${advs.length}) — الرصيد يخصم آلياً حتى لا يتجاوز المتبقي (§7-3)`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الموظف</th><th className={th}>المبلغ</th>
                <th className={th}>القسط × العدد</th><th className={th}>المتبقي</th>
                <th className={th}>أول خصم</th><th className={th}>الحالة</th>
                <th className={th}>إجراءات</th>
              </tr></thead>
              <tbody>
                {advs.map((a) => (
                  <tr key={a.id} className='border-b border-slate-50'>
                    <td className={td}>{a.emp_no} — {a.employee}</td>
                    <td className={`${td} font-mono`}>{fmt(a.amount)}</td>
                    <td className={`${td} font-mono text-xs`}>
                      {fmt(a.installment_amount)} × {a.installments}</td>
                    <td className={`${td} font-mono font-bold ${parseFloat(a.remaining) > 0 ? 'text-amber-700' : 'text-emerald-700'}`}>
                      {fmt(a.remaining)}</td>
                    <td className={`${td} font-mono text-xs`}>{a.first_deduct_month}</td>
                    <td className={td}><Badge tone={
                      a.status === 'SETTLED' ? 'green'
                      : a.status === 'REJECTED' ? 'red'
                      : a.status === 'PAID' ? 'blue' : 'amber'}>
                      {HR_STATUS_AR[a.status] ?? a.status}
                      {a.paid_entry_id ? ' #23✓' : ''}</Badge></td>
                    <td className={td}>
                      <div className='flex gap-1 flex-wrap'>
                        {a.status === 'REQUESTED' && canAdvAppr && (<>
                          <Btn className='!px-2 !py-1 text-xs'
                            onClick={() => run(async () => { await hrApi.approveAdvance(a.id) },
                              'اعتُمدت — جاهزة للصرف')}>اعتماد ✅</Btn>
                          <Btn className='!px-2 !py-1 text-xs' kind='danger'
                            onClick={() => { const rs = ask('سبب الرفض:')
                              if (rs) run(async () => { await hrApi.rejectAdvance(a.id, rs) }, 'رُفضت') }}>رفض</Btn>
                        </>)}
                        {a.status === 'APPROVED' && canPay && (
                          <Btn className='!px-2 !py-1 text-xs' kind='gold'
                            onClick={() => run(async () => {
                              const r = await hrApi.disburseAdvance(a.id)
                              setOk(`صُرفت نقداً — قيد #23 ثابت (${r.entry_id.slice(0, 8)}…)`)
                            }, '')}>صرف نقداً #23 💵</Btn>)}
                      </div>
                    </td>
                  </tr>))}
                {!advs.length && <tr><td className={td} colSpan={7}>لا سلف</td></tr>}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ═══════════ بنود الرواتب ═══════════ */}
      {tab === TABS[3] && (
        <>
          {canPolicy && (
            <Card title='بند رواتب جديد — ثابت أو نسبة من الأساسي (§4.1؛ الاستحقاقات القانونية شرائح تُضبط لاحقاً لكل بلد)'>
              <div className='flex gap-2 flex-wrap items-center'>
                <input className={inp + ' w-24'} placeholder='الرمز *' value={itemForm.code}
                  onChange={(e) => setItemForm((f) => ({ ...f, code: e.target.value.toUpperCase() }))} />
                <input className={inp} placeholder='الاسم *' value={itemForm.name}
                  onChange={(e) => setItemForm((f) => ({ ...f, name: e.target.value }))} />
                <select className={inp} value={itemForm.item_type}
                  onChange={(e) => setItemForm((f) => ({ ...f, item_type: e.target.value }))}>
                  <option value='EARNING'>استحقاق</option>
                  <option value='DEDUCTION'>استقطاع</option>
                </select>
                <select className={inp} value={itemForm.calc}
                  onChange={(e) => setItemForm((f) => ({ ...f, calc: e.target.value }))}>
                  <option value='PCT_BASE'>% من الأساسي</option>
                  <option value='FIXED'>ثابت (من بدلات الملف)</option>
                </select>
                {itemForm.calc === 'PCT_BASE' && (
                  <input className={inp + ' w-20'} placeholder='% *' type='number'
                    value={itemForm.pct_base}
                    onChange={(e) => setItemForm((f) => ({ ...f, pct_base: e.target.value }))} />)}
                {itemForm.item_type === 'DEDUCTION' && (
                  <input className={inp + ' w-24'} placeholder='حساب دائن' value={itemForm.credit_account_code}
                    title='مثال 2220 استقطاعات للجهات'
                    onChange={(e) => setItemForm((f) => ({ ...f,
                      credit_account_code: e.target.value }))} />)}
                <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                  await hrApi.createPayItem({
                    ...itemForm, pct_base: parseFloat(itemForm.pct_base || '0') })
                }, 'أُنشئ البند — فعّله ليدخل المسير')}>إضافة</Btn>
              </div>
            </Card>)}
          <Card title={`البنود (${items.length})`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الرمز</th><th className={th}>الاسم</th>
                <th className={th}>النوع</th><th className={th}>الاحتساب</th>
                <th className={th}>الدائن</th><th className={th}>الحالة</th>
                {canPolicy && <th className={th}></th>}
              </tr></thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.id} className='border-b border-slate-50'>
                    <td className={`${td} font-mono`}>{it.code}
                      {it.is_system && <Badge tone='slate'> نظامي</Badge>}</td>
                    <td className={td}>{it.name}</td>
                    <td className={td}><Badge tone={it.item_type === 'EARNING' ? 'green' : 'red'}>
                      {it.item_type === 'EARNING' ? 'استحقاق' : 'استقطاع'}</Badge></td>
                    <td className={`${td} font-mono text-xs`}>
                      {it.calc === 'PCT_BASE' ? `${it.pct_base}% من الأساسي` : 'ثابت'}</td>
                    <td className={`${td} font-mono text-xs`}>
                      {it.item_type === 'DEDUCTION' ? it.credit_account_code : '—'}</td>
                    <td className={td}>{it.is_active
                      ? <Badge tone='green'>فعّال</Badge>
                      : <Badge tone='slate'>معطّل</Badge>}</td>
                    {canPolicy && (
                      <td className={td}>{!it.is_system && (
                        <Btn className='!px-2 !py-1 text-xs' kind='ghost'
                          onClick={() => run(async () => {
                            await hrApi.togglePayItem(it.id, !it.is_active)
                          }, it.is_active ? 'عُطّل — لن يدخل المسيرات الجديدة' : 'فُعّل')}>
                          {it.is_active ? 'تعطيل' : 'تفعيل'}</Btn>)}</td>)}
                  </tr>))}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ═══════════ السياسة ═══════════ */}
      {tab === TABS[4] && pol && (
        <Card title='سياسة الرواتب (المحاسب يضبطها لكل بلد/منشأة — §4.1). التغيير موثَّق'
          actions={canPolicy && (
            <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
              await hrApi.putPolicy({
                day_count_mode: polForm.day_count_mode,
                advance_max_pct: parseFloat(polForm.advance_max_pct || '0'),
                workday_hours: parseFloat(polForm.workday_hours || '0'),
                ot_multiplier: parseFloat(polForm.ot_multiplier || '0'),
                late_deduct_daily: parseFloat(polForm.late_deduct_daily || '0'),
                penalty_credit_code: polForm.penalty_credit_code,
                eos_enabled: polForm.eos_enabled,
                eos_month_rate: polForm.eos_enabled
                  ? parseFloat(polForm.eos_month_rate || '0') : null,
                eos_credit_account_code: polForm.eos_credit_account_code })
            }, 'حُفظت السياسة — تسري على المسيرات القادمة')}>
              حفظ السياسة</Btn>)}>
          <div className='grid md:grid-cols-3 gap-3'>
            <label className='text-sm'>أيام احتساب الشهر
              <select className={inp + ' w-full mt-1'} value={polForm.day_count_mode}
                disabled={!canPolicy}
                onChange={(e) => setPolForm((f) => ({ ...f,
                  day_count_mode: e.target.value }))}>
                <option value='FIXED30'>30 ثابتة</option>
                <option value='CALENDAR'>تقويمية فعلية</option>
              </select></label>
            <label className='text-sm'>سقف السلفة % من الأساسي
              <input className={inp + ' w-full mt-1'} type='number' disabled={!canPolicy}
                value={polForm.advance_max_pct}
                onChange={(e) => setPolForm((f) => ({ ...f, advance_max_pct: e.target.value }))} /></label>
            <label className='text-sm'>ساعات دوام اليوم
              <input className={inp + ' w-full mt-1'} type='number' disabled={!canPolicy}
                value={polForm.workday_hours}
                onChange={(e) => setPolForm((f) => ({ ...f, workday_hours: e.target.value }))} /></label>
            <label className='text-sm'>مضاعف الإضافي ×
              <input className={inp + ' w-full mt-1'} type='number' step='0.1' disabled={!canPolicy}
                value={polForm.ot_multiplier}
                onChange={(e) => setPolForm((f) => ({ ...f, ot_multiplier: e.target.value }))} /></label>
            <label className='text-sm'>خصم التأخير (يومي لكل 60د)
              <input className={inp + ' w-full mt-1'} type='number' disabled={!canPolicy}
                value={polForm.late_deduct_daily}
                onChange={(e) => setPolForm((f) => ({ ...f, late_deduct_daily: e.target.value }))} /></label>
            <label className='text-sm'>دائن الجزاءات
              <select className={inp + ' w-full mt-1'} value={polForm.penalty_credit_code}
                disabled={!canPolicy}
                onChange={(e) => setPolForm((f) => ({ ...f, penalty_credit_code: e.target.value }))}>
                <option value='2220'>2220 — استقطاعات للجهات</option>
                <option value='4901'>4901 — إيرادات أخرى</option>
              </select></label>
            <label className='text-sm flex items-center gap-2 mt-5'>
              <input type='checkbox' checked={polForm.eos_enabled} disabled={!canPolicy}
                onChange={(e) => setPolForm((f) => ({ ...f, eos_enabled: e.target.checked }))} />
              مخصص نهاية خدمة شهري</label>
            <label className='text-sm'>معدل المخصص الشهري (مثال 0.0833)
              <input className={inp + ' w-full mt-1'} type='number' step='0.0001'
                disabled={!canPolicy || !polForm.eos_enabled}
                value={polForm.eos_month_rate}
                onChange={(e) => setPolForm((f) => ({ ...f, eos_month_rate: e.target.value }))} /></label>
            <label className='text-sm'>حساب دائن المخصص
              <input className={inp + ' w-full mt-1'}
                disabled={!canPolicy || !polForm.eos_enabled}
                value={polForm.eos_credit_account_code}
                onChange={(e) => setPolForm((f) => ({ ...f,
                  eos_credit_account_code: e.target.value }))} /></label>
          </div>
          {!canPolicy && <div className='mt-2 text-xs text-slate-500'>
            التعديل يتطلب صلاحية «إدارة سياسة الرواتب» (المالية).</div>}
        </Card>)}
    </div>
  )
}
