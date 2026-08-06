// تقارير التوظيف §5: كشف شهري بالقسم/البند/الموظف + مقارنة أشهر + تقادم
// السلف + أرصدة الإجازات + الدوران + تكلفة الموظف مقابل الإيراد (USALI)
import { useCallback, useEffect, useState } from 'react'
import { fmt, todayISO } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, Spinner } from '../components/ui'
import { hrApi } from '../hr'

const TABS = ['كشف شهري', 'مقارنة أشهر', 'أرصدة السلف', 'أرصدة الإجازات',
  'دوران الموظفين', 'تكلفة × إيراد'] as const
const inp = 'border border-slate-300 rounded-lg px-2 py-1.5 text-sm'
const th = 'px-3 py-2 text-right text-xs text-slate-500 font-semibold'
const td = 'px-3 py-2 text-sm'

interface RegisterDept { department_code: string; dept: string;
  employees: number; gross: string; deductions: string; net: string }
interface RegisterItem { code: string; name: string; type: string;
  amount: string }
interface RegisterRow { emp_no: string; name: string; department: string;
  kind: string; gross: string; net: string; run_seq: number; status: string }
interface RegisterRes { month: string; by_department: RegisterDept[];
  by_item: RegisterItem[]; rows: RegisterRow[] }
interface CompareRow { month: string; runs: number; gross: string;
  net: string }
interface AdvRow { advance_id: string; emp_no: string; employee: string;
  amount: string; remaining: string; status: string; installments: number;
  installment_amount: string; request_date: string;
  first_deduct_month: string; aging_months: number }
interface LbRow { emp_no: string; employee: string; leave_type: string;
  paid: boolean; entitled: string; used: string; remaining: string }
interface TurnRow { month: string; hires: number; terminations: number }
interface CvrRes { month: string; payroll_gross: string; revenue: string;
  payroll_to_revenue_pct: string | null }

export default function HrReports() {
  const { has } = useAuth()
  const canSalary = has('hr.salary.view')
  const [tab, setTab] = useState<string>(TABS[0])
  const [month, setMonth] = useState(todayISO().slice(0, 7))
  const [reg, setReg] = useState<RegisterRes | null>(null)
  const [cmp, setCmp] = useState<CompareRow[]>([])
  const [advs, setAdvs] = useState<AdvRow[]>([])
  const [lbs, setLbs] = useState<LbRow[]>([])
  const [turn, setTurn] = useState<TurnRow[]>([])
  const [cvr, setCvr] = useState<CvrRes | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    setBusy(true); setErr(null)
    try {
      const [rg, cp, av, lb, tn, cv] = await Promise.all([
        hrApi.register(month), hrApi.compare(), hrApi.reportAdvances(),
        hrApi.reportLeaveBal(), hrApi.turnover(), hrApi.costVsRevenue(month)])
      setReg(rg as unknown as RegisterRes)
      setCmp(cp as unknown as CompareRow[])
      setAdvs(av as unknown as AdvRow[])
      setLbs(lb as unknown as LbRow[])
      setTurn(tn as unknown as TurnRow[])
      setCvr(cv as unknown as CvrRes)
    } catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }, [month])

  useEffect(() => { refresh() }, [refresh])

  const maxCmp = Math.max(...cmp.map((c) => parseFloat(c.net)), 1)
  const totLb = lbs.reduce((s, b) =>
    s + (b.paid ? parseFloat(b.remaining) : 0), 0)

  return (
    <div className='space-y-4'>
      <div className='flex gap-2 flex-wrap items-center'>
        {TABS.map((t) => (
          <Btn key={t} kind={tab === t ? 'primary' : 'ghost'}
            onClick={() => setTab(t)}>{t}</Btn>))}
        <span className='ms-4'>
          <input className={inp} type='month' value={month}
            onChange={(e) => setMonth(e.target.value)} /></span>
      </div>
      <ErrorNote msg={err} />
      {busy && <Spinner />}

      {/* ═══ كشف شهري ═══ */}
      {tab === TABS[0] && reg && (
        <>
          <div className='grid md:grid-cols-2 gap-4'>
            <Card title={`حسب القسم — ${reg.month} (توزيع قيد #21)`}>
              <table className='w-full'>
                <thead><tr className='border-b border-slate-100'>
                  <th className={th}>القسم</th><th className={th}>موظفون</th>
                  <th className={th}>إجمالي</th><th className={th}>خصوم</th>
                  <th className={th}>صافٍ</th></tr></thead>
                <tbody>
                  {reg.by_department.map((d) => (
                    <tr key={d.department_code} className='border-b border-slate-50'>
                      <td className={td}><Badge tone='blue'>{d.department_code}</Badge>
                        {' '}{d.dept}</td>
                      <td className={`${td} font-mono`}>{d.employees}</td>
                      <td className={`${td} font-mono`}>{fmt(d.gross)}</td>
                      <td className={`${td} font-mono text-red-700`}>{fmt(d.deductions)}</td>
                      <td className={`${td} font-mono font-bold`}>{fmt(d.net)}</td>
                    </tr>))}
                  {!reg.by_department.length && <tr><td className={td} colSpan={5}>
                    لا مسيرات مرحَّلة لهذا الشهر</td></tr>}
                </tbody>
              </table>
            </Card>
            <Card title='حسب بند الرواتب'>
              <table className='w-full'>
                <thead><tr className='border-b border-slate-100'>
                  <th className={th}>البند</th><th className={th}>النوع</th>
                  <th className={th}>المبلغ</th></tr></thead>
                <tbody>
                  {reg.by_item.map((it) => (
                    <tr key={it.code} className='border-b border-slate-50'>
                      <td className={td}>{it.code} — {it.name}</td>
                      <td className={td}><Badge tone={it.type === 'EARNING' ? 'green' : 'red'}>
                        {it.type === 'EARNING' ? 'استحقاق' : 'استقطاع'}</Badge></td>
                      <td className={`${td} font-mono font-bold ${it.type === 'EARNING' ? 'text-emerald-700' : 'text-red-700'}`}>
                        {fmt(it.amount)}</td>
                    </tr>))}
                  {!reg.by_item.length && <tr><td className={td} colSpan={3}>—</td></tr>}
                </tbody>
              </table>
            </Card>
          </div>
          <Card title={`التفصيل لكل موظف ${canSalary ? '' : '— يتطلب صلاحية الاطلاع على الرواتب (§6)'}`}>
            {reg.rows.length ? (
              <table className='w-full'>
                <thead><tr className='border-b border-slate-100'>
                  <th className={th}>الرقم</th><th className={th}>الاسم</th>
                  <th className={th}>القسم</th><th className={th}>المسير</th>
                  <th className={th}>إجمالي</th><th className={th}>صافٍ</th>
                </tr></thead>
                <tbody>
                  {reg.rows.map((r, i) => (
                    <tr key={i} className='border-b border-slate-50'>
                      <td className={`${td} font-mono`}>{r.emp_no}</td>
                      <td className={td}>{r.name}</td>
                      <td className={td}><Badge tone='slate'>{r.department}</Badge></td>
                      <td className={td}><Badge tone={r.kind === 'SUPPLEMENTAL' ? 'amber' : 'blue'}>
                        {r.kind === 'SUPPLEMENTAL' ? `تسوية #${r.run_seq}` : r.kind === 'FINAL' ? 'نهائي' : 'شهري'}</Badge></td>
                      <td className={`${td} font-mono`}>{fmt(r.gross)}</td>
                      <td className={`${td} font-mono font-bold`}>{fmt(r.net)}</td>
                    </tr>))}
                </tbody>
              </table>
            ) : <div className='text-sm text-slate-500'>
              {canSalary ? 'لا صفوف' : 'التفصيل مخفي وفق الخصوصية الصفية — الإجماليات أعلاه متاحة.'}</div>}
          </Card>
        </>
      )}

      {/* ═══ مقارنة أشهر ═══ */}
      {tab === TABS[1] && (
        <Card title='إجمالي الرواتب المرحَّلة عبر الأشهر (§5)'>
          <table className='w-full'>
            <thead><tr className='border-b border-slate-100'>
              <th className={th}>الشهر</th><th className={th}>مسيرات</th>
              <th className={th}>إجمالي</th><th className={th}>صافٍ</th>
              <th className={th}></th></tr></thead>
            <tbody>
              {cmp.map((c) => (
                <tr key={c.month} className='border-b border-slate-50'>
                  <td className={`${td} font-mono`}>{c.month}</td>
                  <td className={`${td} font-mono`}>{c.runs}</td>
                  <td className={`${td} font-mono`}>{fmt(c.gross)}</td>
                  <td className={`${td} font-mono font-bold`}>{fmt(c.net)}</td>
                  <td className={td}>
                    <div className='h-2 rounded bg-sijill-200'
                      style={{ width: `${Math.max(4,
                        parseFloat(c.net) / maxCmp * 100)}%` }} />
                  </td>
                </tr>))}
              {!cmp.length && <tr><td className={td} colSpan={5}>
                لا مسيرات مرحَّلة بعد</td></tr>}
            </tbody>
          </table>
        </Card>)}

      {/* ═══ أرصدة السلف ═══ */}
      {tab === TABS[2] && (
        <Card title='سلف قائمة ومتسوّاة مع تقادم عمري بالأشهر (كشف 1130 – §3/§5)'>
          <table className='w-full'>
            <thead><tr className='border-b border-slate-100'>
              <th className={th}>الموظف</th><th className={th}>المبلغ</th>
              <th className={th}>القسط</th><th className={th}>المتبقي</th>
              <th className={th}>منذ</th><th className={th}>العمر</th>
              <th className={th}>الحالة</th></tr></thead>
            <tbody>
              {advs.map((a) => (
                <tr key={a.advance_id} className='border-b border-slate-50'>
                  <td className={td}>{a.emp_no} — {a.employee}</td>
                  <td className={`${td} font-mono`}>{fmt(a.amount)}</td>
                  <td className={`${td} font-mono text-xs`}>
                    {fmt(a.installment_amount)}×{a.installments}</td>
                  <td className={`${td} font-mono font-bold ${parseFloat(a.remaining) > 0 ? 'text-amber-700' : 'text-emerald-700'}`}>
                    {fmt(a.remaining)}</td>
                  <td className={`${td} font-mono text-xs`}>{a.request_date}</td>
                  <td className={td}><Badge tone={a.aging_months > 6 ? 'red' : a.aging_months > 3 ? 'amber' : 'slate'}>
                    {a.aging_months} شهر</Badge></td>
                  <td className={td}>{parseFloat(a.remaining) > 0
                    ? <Badge tone='amber'>يُخصم آلياً</Badge>
                    : <Badge tone='green'>مسوّى ✓</Badge>}</td>
                </tr>))}
              {!advs.length && <tr><td className={td} colSpan={7}>لا سلف مصروفة</td></tr>}
            </tbody>
          </table>
        </Card>)}

      {/* ═══ أرصدة الإجازات ═══ */}
      {tab === TABS[3] && (
        <Card title={`أرصدة الإجازات المستحقة — إجمالي المتبقي المدفوع: ${fmt(totLb)} يوماً (§5)`}>
          <table className='w-full'>
            <thead><tr className='border-b border-slate-100'>
              <th className={th}>الموظف</th><th className={th}>النوع</th>
              <th className={th}>استحقاق</th><th className={th}>مستخدم</th>
              <th className={th}>متبقٍ</th></tr></thead>
            <tbody>
              {lbs.map((b, i) => (
                <tr key={i} className='border-b border-slate-50'>
                  <td className={td}>{b.emp_no} — {b.employee}</td>
                  <td className={td}><Badge tone={b.paid ? 'blue' : 'amber'}>
                    {b.leave_type}{b.paid ? '' : ' (بدون أجر)'}</Badge></td>
                  <td className={`${td} font-mono`}>{fmt(b.entitled)}</td>
                  <td className={`${td} font-mono`}>{fmt(b.used)}</td>
                  <td className={`${td} font-mono font-bold ${parseFloat(b.remaining) <= 0 ? 'text-red-700' : 'text-emerald-700'}`}>
                    {fmt(b.remaining)}</td>
                </tr>))}
              {!lbs.length && <tr><td className={td} colSpan={5}>لا أرصدة</td></tr>}
            </tbody>
          </table>
        </Card>)}

      {/* ═══ دوران الموظفين ═══ */}
      {tab === TABS[4] && (
        <Card title='تعيينات مقابل إنهاءات شهرياً (§5)'>
          <table className='w-full'>
            <thead><tr className='border-b border-slate-100'>
              <th className={th}>الشهر</th><th className={th}>تعيينات ➕</th>
              <th className={th}>إنهاءات ➖</th><th className={th}>صافي الحركة</th>
            </tr></thead>
            <tbody>
              {turn.map((t) => (
                <tr key={t.month}
                  className={`border-b border-slate-50 ${t.hires + t.terminations === 0 ? 'opacity-40' : ''}`}>
                  <td className={`${td} font-mono`}>{t.month}</td>
                  <td className={`${td} font-mono text-emerald-700 font-bold`}>{t.hires || '—'}</td>
                  <td className={`${td} font-mono text-red-700 font-bold`}>{t.terminations || '—'}</td>
                  <td className={`${td} font-mono font-bold`}>
                    {t.hires - t.terminations > 0 ? '+' : ''}{t.hires - t.terminations}</td>
                </tr>))}
            </tbody>
          </table>
        </Card>)}

      {/* ═══ تكلفة × إيراد ═══ */}
      {tab === TABS[5] && cvr && (
        <Card title={`التكلفة الكاملة للموظفين مقابل إيراد ${cvr.month} — مؤشر USALI استرشادي (§5)`}>
          <div className='grid md:grid-cols-3 gap-4 text-center'>
            <div className='rounded-xl bg-slate-50 p-4'>
              <div className='text-xs text-slate-500'>إجمالي كلفة الرواتب</div>
              <div className='text-2xl font-bold font-mono'>{fmt(cvr.payroll_gross)}</div>
            </div>
            <div className='rounded-xl bg-slate-50 p-4'>
              <div className='text-xs text-slate-500'>إيراد الشهر (حسابات الإيراد)</div>
              <div className='text-2xl font-bold font-mono text-emerald-700'>{fmt(cvr.revenue)}</div>
            </div>
            <div className='rounded-xl bg-slate-50 p-4'>
              <div className='text-xs text-slate-500'>نسبة الرواتب إلى الإيراد</div>
              <div className={`text-2xl font-bold font-mono ${
                cvr.payroll_to_revenue_pct === null ? 'text-slate-400'
                : parseFloat(cvr.payroll_to_revenue_pct) > 40 ? 'text-red-700'
                : 'text-sijill-700'}`}>
                {cvr.payroll_to_revenue_pct === null ? '—'
                  : `${fmt(cvr.payroll_to_revenue_pct)}%`}</div>
              {cvr.payroll_to_revenue_pct !== null &&
                parseFloat(cvr.payroll_to_revenue_pct) > 40 && (
                <div className='text-[11px] text-red-600 mt-1'>
                  أعلى من الحد الاسترشادي 40%</div>)}
            </div>
          </div>
          <div className='mt-3 text-xs text-slate-500'>
            يُحتسب من المسيرات المرحَّلة (POSTED/PAID) مقابل صافي حركة حسابات
            الإيراد للشهر — لا بد من ترحيل #21 وإقفال الإيرادات لدقة المؤشر.</div>
        </Card>)}
    </div>
  )
}
