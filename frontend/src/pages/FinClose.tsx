// الفترات والإقفال: إغلاق لين ← صلب لكل شهر (02 §5) + معالج إقفال السنة
// بقائمة تحقق حية ثم قيد إقفال + افتتاحية آلية بأرصدة الأطراف
import { useCallback, useEffect, useState } from 'react'
import { fmt } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import type { ClosePrecheck, CloseResult, FiscalYearInfo } from '../fa'
import { PERIOD_STATUS_AR, finApi } from '../fa'

const th = 'px-3 py-2 text-right text-xs text-slate-500 font-semibold'
const td = 'px-3 py-2 text-sm'

export default function FinClose() {
  const { has } = useAuth()
  const canClose = has('periods.close')
  const [years, setYears] = useState<FiscalYearInfo[]>([])
  const [pre, setPre] = useState<ClosePrecheck | null>(null)
  const [result, setResult] = useState<CloseResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [selYear, setSelYear] = useState<number | null>(null)

  const refresh = useCallback(async () => {
    setYears(await finApi.years())
  }, [])
  useEffect(() => { refresh().catch((e) => setErr((e as Error).message)) },
             [refresh])

  useEffect(() => {
    const y = selYear ?? years.find((x) => x.status === 'OPEN')?.year_no
    if (y !== undefined && y !== null)
      finApi.precheck(y).then(setPre).catch(() => setPre(null))
  }, [selYear, years])

  const run = async (fn: () => Promise<void>, okMsg: string) => {
    setErr(null); setOk(null); setResult(null); setBusy(true)
    try { await fn(); setOk(okMsg); await refresh() }
    catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }

  const openYear = years.find((x) => x.status === 'OPEN')
  const targetYear = selYear ?? openYear?.year_no ?? null

  return (
    <div className='space-y-4'>
      <ErrorNote msg={err} />
      <OkNote msg={ok} />
      {busy && <Spinner />}

      <Card title='حالة الفترات المالية — إغلاق لين (يوقف العادي ويسمح بتسوية المدير المالي) ثم صلب (نهائي مطلقاً)'>
        {years.map((y) => (
          <div key={y.id} className='mb-4'>
            <div className='flex gap-2 items-center mb-2'>
              <b>السنة {y.year_no}</b>
              <Badge tone={y.status === 'OPEN' ? 'green' : 'slate'}>{y.status}</Badge>
              <span className='text-xs font-mono text-slate-500'>
                {y.start_date} → {y.end_date}</span>
              {targetYear !== y.year_no && y.status === 'OPEN' && (
                <Btn kind='ghost' className='!px-2 !py-1 text-xs'
                  onClick={() => setSelYear(y.year_no)}>تحديد للإقفال ⬇</Btn>)}
            </div>
            <div className='grid grid-cols-6 md:grid-cols-12 gap-1.5'>
              {y.periods.map((p) => (
                <div key={p.id}
                  className={`border rounded-lg p-1.5 text-center text-xs ${p.status === 'OPEN'
                    ? 'border-emerald-300 bg-emerald-50/50'
                    : p.status === 'HARD_CLOSED'
                      ? 'border-slate-300 bg-slate-100/60 opacity-70'
                      : 'border-amber-300 bg-amber-50/50'}`}>
                  <div className='font-bold'>شهر {p.no}</div>
                  <div className='text-[10px]'>{PERIOD_STATUS_AR[p.status] ?? p.status}</div>
                  {canClose && y.status === 'OPEN' && (
                    <div className='mt-1 space-y-0.5'>
                      {p.status === 'OPEN' && (
                        <button type='button'
                          className='block w-full text-[10px] text-sijill-700 hover:underline'
                          onClick={() => run(async () => {
                            await finApi.closePeriod(p.id)
                          }, `أُغلقت الفترة ${p.no} ليناً`)}>إغلاق لين</button>)}
                      {(p.status === 'SOFT_CLOSED' || p.status === 'CLOSED') && (
                        <button type='button'
                          className='block w-full text-[10px] text-red-700 hover:underline'
                          onClick={() => run(async () => {
                            await finApi.hardClosePeriod(p.id)
                          }, `خُتمت الفترة ${p.no} صلباً — نهائي`)}>ختم صلب</button>)}
                    </div>)}
                </div>))}
            </div>
          </div>))}
      </Card>

      {pre && targetYear !== null && (
        <div className='grid md:grid-cols-2 gap-4'>
          <Card title={`قائمة تحقق إقفال السنة ${targetYear} (02 §5)`}>
            <div className='space-y-2'>
              {pre.checks.map((c) => (
                <div key={c.key} className='flex gap-2 items-start'>
                  <Badge tone={c.ok ? 'green' : 'red'}>{c.ok ? '✓' : '✗'}</Badge>
                  <div>
                    <div className='text-sm'>{c.label}</div>
                    {c.rows && (
                      <div className='text-[11px] font-mono text-slate-500'>
                        {c.rows.map((r) => (
                          <span key={r.code} className='me-3'>
                            {r.code}: {fmt(r.balance)}{r.blocking ? '' : ' (إعلامي)'}
                          </span>))}
                      </div>)}
                  </div>
                </div>))}
            </div>
            {canClose && (
              <div className='mt-4'>
                <Btn kind={pre.ready ? 'gold' : 'ghost'} disabled={busy || !pre.ready}
                  onClick={() => run(async () => {
                    const r = await finApi.closeYear(targetYear)
                    setResult(r)
                    setOk(`أُقفلت السنة ${r.year_no} — قيدان مرحَّلان وسنة ${r.next_year_no} فُتحت بـ12 فترة`)
                  }, '')}>
                  تنفيذ إقفال السنة {targetYear} 🔒</Btn>
                {!pre.ready && (
                  <span className='text-xs text-slate-500 ms-2'>
                    أكمل بنود التحقق الحمراء أولاً</span>)}
              </div>)}
          </Card>
          <Card title='ماذا يحدث عند الإقفال؟ (ذريّ كله أو لا شيء)'>
            <ol className='text-sm space-y-1.5 list-decimal list-inside'>
              <li>قيد إقفال واحد متوازن: مدين كل الإيرادات / دائن 3202،
                ومدين 3202 / دائن كل المصروفات، ثم صافي الربح من 3202 إلى
                3201 الأرباح المبقاة.</li>
              <li>إنشاء السنة الجديدة بـ12 فترة مفتوحة إن لم توجد.</li>
              <li>قيد افتتاحي آلي بكل موازين الأصول/الخصوم/حقوق الملكية —
                <b> بأرصدة كل طرف</b> (نزيل/شركة/مورد/موظف) لتستمر الذمم
                لحظياً في السنة الجديدة.</li>
              <li>السنة القديمة بحالة CLOSED وكل فتراتها صلبة نهائياً —
                لا ترحيل فيها من أي طريق بعد اليوم.</li>
            </ol>
            {result && (
              <div className='mt-3 rounded-xl bg-emerald-50 border border-emerald-200 p-3'>
                <div className='font-bold text-emerald-800 mb-1'>تم الإقفال ✅</div>
                <div className='text-xs space-y-0.5 font-mono'>
                  <div>قيد الإقفال: {result.closing_entry_no}</div>
                  <div>إيرادات مغلقة: {fmt(result.revenue_closed)} · مصروفات: {fmt(result.expense_closed)}</div>
                  <div>صافي الربح: <b>{fmt(result.net_income)}</b> ← 3201</div>
                  {result.opening_entry_no &&
                    <div>الافتتاحية: {result.opening_entry_no} ({result.opening_lines} سطراً)</div>}
                  <div>السنة الجديدة: {result.next_year_no} من {result.next_year_start}</div>
                </div>
              </div>)}
          </Card>
        </div>)}
    </div>
  )
}
