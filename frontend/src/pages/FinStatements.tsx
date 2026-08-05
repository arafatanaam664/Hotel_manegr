// القوائم المالية (02 §10): قائمة دخل USALI قسمية / ميزانية بقطع /
// تدفقات نقدية غير مباشرة بهوية Δ نقدية / أعمار ذمم FIFO — كلها من المرحَّل فقط
import { useCallback, useEffect, useState } from 'react'
import { fmt, todayISO } from '../api'
import { Badge, Btn, Card, ErrorNote, Spinner } from '../components/ui'
import type { Aging, BalanceSheet, CashFlow, IncomeStatement,
  MoneyRow } from '../fa'
import { finApi } from '../fa'

const TABS = ['قائمة الدخل USALI', 'الميزانية العمومية', 'التدفقات النقدية',
  'أعمار الذمم'] as const
const inp = 'border border-slate-300 rounded-lg px-2 py-1.5 text-sm'
const th = 'px-3 py-2 text-right text-xs text-slate-500 font-semibold'
const td = 'px-3 py-2 text-sm'

function Money({ v, bold = false, tone = '' }: { v: string | number;
  bold?: boolean; tone?: string }) {
  return <span className={`font-mono ${bold ? 'font-bold' : ''} ${tone}`}>
    {fmt(v)}</span>
}

function MoneyTable({ rows, total, totalLabel }: { rows: MoneyRow[];
  total: string; totalLabel: string }) {
  return (
    <table className='w-full'>
      <tbody>
        {rows.map((r) => (
          <tr key={r.code} className='border-b border-slate-50'>
            <td className={td}><span className='font-mono text-xs text-slate-400'>{r.code}</span> {r.name}</td>
            <td className={`${td} text-left w-32`}><Money v={r.amount} /></td>
          </tr>))}
        <tr className='font-bold bg-slate-50/60'>
          <td className={td}>{totalLabel}</td>
          <td className={`${td} text-left`}><Money v={total} bold /></td>
        </tr>
      </tbody>
    </table>)
}

export default function FinStatements() {
  const [tab, setTab] = useState<string>(TABS[0])
  const [from, setFrom] = useState(todayISO().slice(0, 8) + '01')
  const [to, setTo] = useState(todayISO())
  const [agingAcc, setAgingAcc] = useState('1120')
  const [is_, setIS] = useState<IncomeStatement | null>(null)
  const [bs, setBS] = useState<BalanceSheet | null>(null)
  const [cf, setCF] = useState<CashFlow | null>(null)
  const [ag, setAG] = useState<Aging | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    setBusy(true); setErr(null)
    try {
      const [a, b, c, d] = await Promise.all([
        finApi.incomeStatement(from, to), finApi.balanceSheet(to),
        finApi.cashFlow(from, to), finApi.aging(agingAcc, to)])
      setIS(a); setBS(b); setCF(c); setAG(d)
    } catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }, [from, to, agingAcc])

  useEffect(() => { refresh() }, [refresh])

  const bucketNames = ['0-30', '31-60', '61-90', '+90']

  return (
    <div className='space-y-4'>
      <div className='flex gap-2 flex-wrap items-center'>
        {TABS.map((t) => (
          <Btn key={t} kind={tab === t ? 'primary' : 'ghost'}
            onClick={() => setTab(t)}>{t}</Btn>))}
        <span className='ms-4 flex gap-1.5 items-center text-sm'>
          من <input className={inp} type='date' value={from}
            onChange={(e) => setFrom(e.target.value)} />
          إلى <input className={inp} type='date' value={to}
            onChange={(e) => setTo(e.target.value)} />
        </span>
      </div>
      <ErrorNote msg={err} />
      {busy && <Spinner />}

      {/* ═══ قائمة الدخل USALI ═══ */}
      {tab === TABS[0] && is_ && (
        <>
          {is_.departments.map((d) => (
            <Card key={d.key} title={`${d.name} — دخل القسم`}
              actions={<Badge tone={parseFloat(d.dept_income) >= 0 ? 'green' : 'red'}>
                <Money v={d.dept_income} bold /></Badge>}>
              <div className='grid md:grid-cols-2 gap-4'>
                <div>
                  <div className='text-xs text-slate-500 mb-1'>إيرادات القسم</div>
                  {d.revenues.length
                    ? <MoneyTable rows={d.revenues} total={d.revenue_total}
                        totalLabel='إجمالي الإيراد' />
                    : <div className='text-sm text-slate-400'>لا إيرادات بالفترة</div>}
                </div>
                <div>
                  <div className='text-xs text-slate-500 mb-1'>مصروفاته المباشرة</div>
                  {d.expenses.length
                    ? <MoneyTable rows={d.expenses} total={d.expense_total}
                        totalLabel='إجمالي المباشر' />
                    : <div className='text-sm text-slate-400'>لا مصروفات مباشرة</div>}
                </div>
              </div>
            </Card>
          ))}
          <Card title='بعد دخل الأقسام — ملخص USALI'>
            <table className='w-full'>
              <tbody>
                <tr className='border-b border-slate-50'>
                  <td className={td}>إجمالي دخل الأقسام التشغيلية</td>
                  <td className={`${td} text-left w-40`}>
                    <Money v={is_.departments_income} bold /></td></tr>
                {is_.other_revenue.length > 0 && (
                  <tr className='border-b border-slate-50'>
                    <td className={td}>إيرادات أخرى (49xx)</td>
                    <td className={`${td} text-left`}>
                      <Money v={is_.other_revenue_total} /></td></tr>)}
                <tr className='border-b border-slate-50'>
                  <td className={td}>المصاريف غير الموزعة (إدارية/تسويق/طاقة/أخرى)</td>
                  <td className={`${td} text-left`}>
                    <Money v={is_.undistributed_total} tone='text-red-700' /></td></tr>
                <tr className='border-b border-slate-100 bg-atheer-50/70'>
                  <td className={`${td} font-bold`}>صافي الدخل التشغيلي GOP</td>
                  <td className={`${td} text-left`}><Money v={is_.gop} bold /></td></tr>
                <tr className='border-b border-slate-50'>
                  <td className={td}>بنود غير تشغيلية (إهلاك/تمويل/استثنائي)</td>
                  <td className={`${td} text-left`}>
                    <Money v={is_.non_operating_total} tone='text-red-700' /></td></tr>
                <tr className='bg-emerald-50/80'>
                  <td className={`${td} font-bold text-lg`}>صافي الدخل</td>
                  <td className={`${td} text-left`}>
                    <Money v={is_.net_income} bold
                      tone={parseFloat(is_.net_income) >= 0
                        ? 'text-emerald-700' : 'text-red-700'} /></td></tr>
              </tbody>
            </table>
            {is_.non_operating.length > 0 && (
              <details className='mt-2'>
                <summary className='text-xs text-slate-500 cursor-pointer'>تفصيل غير التشغيلية</summary>
                <div className='mt-1'>
                  {is_.non_operating.map((r) => (
                    <div key={r.code} className='flex justify-between text-sm border-b border-slate-50 py-1'>
                      <span>{r.code} — {r.name}</span><Money v={r.amount} /></div>))}
                </div>
              </details>)}
            <div className='mt-2 text-xs text-slate-400'>
              المنهج: USALI — إيراد كل قسم ناقص مصروفه المباشر، الفترة {is_.from}→{is_.to}، من القيود المرحَّلة فقط.</div>
          </Card>
        </>
      )}

      {/* ═══ الميزانية ═══ */}
      {tab === TABS[1] && bs && (
        <>
          <div className='flex gap-2 items-center'>
            <Badge tone={bs.balanced ? 'green' : 'red'}>
              {bs.balanced ? 'متوازنة: أصول = خصوم + حقوق ملكية ✓'
                : `غير متوازنة! فرق ${fmt(bs.diff)}`}</Badge>
            <span className='text-xs text-slate-500'>بتاريخ قطع {bs.as_of}</span>
          </div>
          <div className='grid md:grid-cols-2 gap-4'>
            <Card title='الأصول'>
              <div className='text-xs text-slate-500 mb-1'>متداولة</div>
              <MoneyTable rows={bs.current_assets}
                total={bs.current_assets.reduce((s, r) => s + parseFloat(r.amount), 0).toString()}
                totalLabel='مجموع المتداولة' />
              <div className='text-xs text-slate-500 mt-3 mb-1'>ثابتة (بعد مجمع الإهلاك)</div>
              <MoneyTable rows={bs.fixed_assets}
                total={bs.fixed_assets.reduce((s, r) => s + parseFloat(r.amount), 0).toString()}
                totalLabel='مجموع الثابتة' />
              {bs.system_accounts.length > 0 && (
                <>
                  <div className='text-xs text-slate-500 mt-3 mb-1'>حسابات نظام (يجب أن تتجه للصفر)</div>
                  <MoneyTable rows={bs.system_accounts}
                    total={bs.system_accounts.reduce((s, r) => s + parseFloat(r.amount), 0).toString()}
                    totalLabel='صافي حسابات النظام' />
                </>)}
              <div className='mt-3 pt-2 border-t border-slate-200 flex justify-between font-bold text-lg'>
                <span>إجمالي الأصول</span><Money v={bs.total_assets} bold /></div>
            </Card>
            <Card title='الخصوم وحقوق الملكية'>
              <div className='text-xs text-slate-500 mb-1'>الخصوم</div>
              <MoneyTable rows={bs.liabilities} total={bs.total_liabilities}
                totalLabel='إجمالي الخصوم' />
              <div className='text-xs text-slate-500 mt-3 mb-1'>حقوق الملكية</div>
              <table className='w-full'><tbody>
                {bs.equity.map((r) => (
                  <tr key={r.code} className='border-b border-slate-50'>
                    <td className={td}><span className='font-mono text-xs text-slate-400'>{r.code}</span> {r.name}</td>
                    <td className={`${td} text-left w-32`}><Money v={r.amount} /></td></tr>))}
                <tr className='border-b border-slate-50'>
                  <td className={td}>أرباح/خسائر العام حتى الإقفال</td>
                  <td className={`${td} text-left`}>
                    <Money v={bs.current_year_earnings}
                      tone={parseFloat(bs.current_year_earnings) >= 0
                        ? 'text-emerald-700' : 'text-red-700'} /></td></tr>
                <tr className='font-bold bg-slate-50/60'>
                  <td className={td}>إجمالي حقوق الملكية</td>
                  <td className={`${td} text-left`}><Money v={bs.total_equity} bold /></td></tr>
              </tbody></table>
              <div className='mt-3 pt-2 border-t border-slate-200 flex justify-between font-bold text-lg'>
                <span>إجمالي الخصوم + حقوق الملكية</span>
                <Money v={(parseFloat(bs.total_liabilities) + parseFloat(bs.total_equity)).toString()} bold /></div>
            </Card>
          </div>
        </>
      )}

      {/* ═══ التدفقات ═══ */}
      {tab === TABS[2] && cf && (
        <>
          <div className='flex gap-2 items-center'>
            <Badge tone={cf.identity_holds ? 'green' : 'red'}>
              {cf.identity_holds
                ? 'الهوية محققة: تشغيلي+استثماري+تمويلي = Δ النقدية ✓'
                : `فارق تسوية ${fmt(cf.reconciliation_diff)}`}</Badge>
            <span className='text-xs text-slate-500'>بالطريقة غير المباشرة — مشتقة من مستويين</span>
          </div>
          <Card title='قائمة التدفقات النقدية'>
            <table className='w-full'>
              <tbody>
                <tr className='border-b border-slate-50 font-semibold bg-slate-50/60'>
                  <td className={td} colSpan={2}>التشغيلية</td></tr>
                <tr className='border-b border-slate-50'>
                  <td className={td}>صافي الدخل للفترة</td>
                  <td className={`${td} text-left w-44`}><Money v={cf.net_income} /></td></tr>
                <tr className='border-b border-slate-50'>
                  <td className={td}>يُضاف: إهلاك الفترة (غير نقدي)</td>
                  <td className={`${td} text-left`}><Money v={cf.depreciation_addback} /></td></tr>
                <tr className='border-b border-slate-50'>
                  <td className={td}>التغير في الذمم والمخزون</td>
                  <td className={`${td} text-left`}>
                    <Money v={(parseFloat(cf.delta_receivables) + parseFloat(cf.delta_inventory)).toString()} /></td></tr>
                <tr className='border-b border-slate-50'>
                  <td className={td}>التغير في الخصوم التشغيلية</td>
                  <td className={`${td} text-left`}><Money v={cf.delta_operating_liabilities} /></td></tr>
                <tr className='border-b border-slate-100 font-bold'>
                  <td className={td}>صافي التشغيلية</td>
                  <td className={`${td} text-left`}><Money v={cf.operating} bold /></td></tr>
                <tr className='border-b border-slate-50 font-semibold bg-slate-50/60'>
                  <td className={td} colSpan={2}>الاستثمارية</td></tr>
                <tr className='border-b border-slate-50'>
                  <td className={td}>اقتناء/تغير الأصول الثابتة (إجمالي)</td>
                  <td className={`${td} text-left`}><Money v={cf.delta_fixed_assets_gross} /></td></tr>
                <tr className='border-b border-slate-100 font-bold'>
                  <td className={td}>صافي الاستثمارية</td>
                  <td className={`${td} text-left`}><Money v={cf.investing} bold /></td></tr>
                <tr className='border-b border-slate-50 font-semibold bg-slate-50/60'>
                  <td className={td} colSpan={2}>التمويلية</td></tr>
                <tr className='border-b border-slate-50'>
                  <td className={td}>قروض / جاري مالك / رأس مال</td>
                  <td className={`${td} text-left`}>
                    <Money v={(parseFloat(cf.delta_loans) + parseFloat(cf.delta_owner_current) + parseFloat(cf.delta_capital)).toString()} /></td></tr>
                <tr className='border-b border-slate-100 font-bold'>
                  <td className={td}>صافي التمويلية</td>
                  <td className={`${td} text-left`}><Money v={cf.financing} bold /></td></tr>
                <tr className='border-b border-slate-50 text-slate-500'>
                  <td className={td}>تحويلات إقفالات/نظام غير نقدية</td>
                  <td className={`${td} text-left`}><Money v={cf.equity_and_system_transfers} /></td></tr>
                <tr className='bg-emerald-50/80 font-bold text-lg'>
                  <td className={td}>التغير الفعلي في النقدية</td>
                  <td className={`${td} text-left`}><Money v={cf.cash_delta_actual} bold /></td></tr>
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ═══ أعمار الذمم ═══ */}
      {tab === TABS[3] && ag && (
        <Card title={`${ag.account} — ${ag.account_name} بتخصيص FIFO (${ag.method})`}
          actions={
            <div className='flex gap-2 items-center'>
              <select className={inp} value={agingAcc}
                onChange={(e) => setAgingAcc(e.target.value)}>
                <option value='1110'>1110 ذمم النزلاء</option>
                <option value='1120'>1120 ذمم المدينة — الشركات</option>
                <option value='2101'>2101 ذمم الموردين</option>
              </select>
              <Badge tone={ag.matches_gl ? 'green' : 'red'}>
                {ag.matches_gl ? 'مجموع الأعمار = الأستاذ ✓' : 'فرق عن الأستاذ!'}</Badge>
            </div>}>
          <table className='w-full'>
            <thead><tr className='border-b border-slate-100'>
              <th className={th}>الطرف</th><th className={th}>النوع</th>
              {bucketNames.map((b) => <th key={b} className={th}>{b}</th>)}
              <th className={th}>الإجمالي</th></tr></thead>
            <tbody>
              {ag.rows.map((r) => (
                <tr key={r.party} className='border-b border-slate-50'>
                  <td className={td}>{r.party_name}</td>
                  <td className={td}><Badge tone='slate'>{r.party_type}</Badge></td>
                  {bucketNames.map((b) => (
                    <td key={b} className={`${td} font-mono ${parseFloat(r.buckets[b] ?? '0') > 0 && b === '+90' ? 'text-red-700 font-bold' : ''}`}>
                      {fmt(r.buckets[b] ?? '0')}</td>))}
                  <td className={`${td} font-mono font-bold`}>{fmt(r.total)}</td>
                </tr>))}
              {!ag.rows.length && (
                <tr><td className={td} colSpan={7}>لا أرصدة مفتوحة على أطراف</td></tr>)}
            </tbody>
            <tfoot><tr className='border-t border-slate-200 font-bold'>
              <td className={td} colSpan={2}>الإجمالي</td>
              {bucketNames.map((b) => (
                <td key={b} className={`${td} font-mono`}>{fmt(ag.totals[b] ?? '0')}</td>))}
              <td className={`${td} font-mono`}>{fmt(ag.grand_total)}
                <span className='text-xs font-normal text-slate-500'>
                  {' '}≡ أستاذ {fmt(ag.gl_balance)}</span></td>
            </tr></tfoot>
          </table>
          <div className='mt-2 text-xs text-slate-500'>
            سدادات الطرف تُسقط أقدم فواتيره أولاً (FIFO)، والباقي يُعمّر بتاريخ
            فاتورته: 0-30 / 31-60 / 61-90 / +90 يوماً.</div>
        </Card>)}
    </div>
  )
}
