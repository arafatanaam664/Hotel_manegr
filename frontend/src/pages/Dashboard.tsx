import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmt, todayISO } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner, statusBadge } from '../components/ui'
import type { DemoResult, Journal, Paged, Period, TenantInfo, TrialBalance } from '../types'

export default function Dashboard() {
  const { has } = useAuth()
  const [tenant, setTenant] = useState<TenantInfo | null>(null)
  const [tb, setTb] = useState<TrialBalance | null>(null)
  const [journals, setJournals] = useState<Paged<Journal> | null>(null)
  const [periods, setPeriods] = useState<Period[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [demoBusy, setDemoBusy] = useState(false)
  const [demoMsg, setDemoMsg] = useState<string | null>(null)

  async function refresh() {
    try {
      const [t, b, j, p] = await Promise.all([
        api<TenantInfo>('/api/org/tenant'),
        api<TrialBalance>('/api/reports/trial-balance'),
        api<Paged<Journal>>('/api/journals?page=1&page_size=6'),
        api<Period[]>('/api/periods'),
      ])
      setTenant(t); setTb(b); setJournals(j); setPeriods(p)
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : 'خطأ غير متوقع')
    }
  }

  useEffect(() => { refresh() }, [])

  async function runDemo() {
    setDemoBusy(true); setDemoMsg(null); setErr(null)
    try {
      const r = await api<DemoResult>('/api/demo/run-month', { method: 'POST' })
      setDemoMsg(
        `اكتمل شهر ${r.month}/${r.year}: ${r.entries_posted} قيداً مرحلاً — كل الأيام متوازنة ${r.daily_balance_ok ? '✓' : '✗'} — الميزان: مدين ${fmt(r.total_debit)} = دائن ${fmt(r.total_credit)}`,
      )
      await refresh()
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : 'فشل تشغيل السيناريو')
    } finally {
      setDemoBusy(false)
    }
  }

  if (err && !tenant) return <ErrorNote msg={err} />
  if (!tenant) return <Spinner />

  const today = todayISO()
  const currentPeriod = periods.find((p) => p.start_date <= today && today <= p.end_date)

  return (
    <div className="space-y-6">
      {/* بطاقة الجهة */}
      <div className="bg-gradient-to-l from-atheer-800 to-atheer-950 text-white rounded-3xl p-6 shadow-lg flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black">{tenant.trade_name || tenant.legal_name}</h1>
          <div className="text-white/70 text-sm mt-1">
            العملة الأساسية: {tenant.base_currency} — المنطقة الزمنية: {tenant.timezone}
            — الفروع: {tenant.branches.map((b) => b.name).join('، ')}
          </div>
        </div>
        <div className="text-left">
          <div className="text-[11px] text-white/50 mb-1">الفترة الحالية</div>
          {currentPeriod ? statusBadge(currentPeriod.status) : <Badge>—</Badge>}
          <div className="text-xs text-white/70 mt-1 num">
            {currentPeriod && `${currentPeriod.start_date} ← ${currentPeriod.end_date}`}
          </div>
        </div>
      </div>

      <ErrorNote msg={err} />
      <OkNote msg={demoMsg} />

      {/* مؤشرات */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <div className="text-sm text-slate-500">إجمالي القيود المرحَّلة</div>
          <div className="text-3xl font-black text-atheer-700 mt-2 num">{journals?.total ?? '—'}</div>
        </Card>
        <Card>
          <div className="text-sm text-slate-500">ميزان اليوم (مدين = دائن)</div>
          <div className="text-xl font-black mt-2 num text-slate-800">
            {tb ? fmt(tb.total_debit) : '—'}
          </div>
          <div className="mt-1">
            {tb && (tb.balanced && tb.net_balance_zero
              ? <Badge tone="green">متوازن تماماً ✓</Badge>
              : <Badge tone="red">خلل!</Badge>)}
          </div>
        </Card>
        <Card>
          <div className="text-sm text-slate-500">إثبات بوابة G1 — شهر فندقي كامل</div>
          {has('*') ? (
            <>
              <p className="text-xs text-slate-400 mt-1 mb-3 leading-5">
                يولّد الشهر التجريبي كاملاً عبر محرك الترحيل: إشغال غرف، مبيعات، مشتريات، رواتب، إهلاك — بمفاتيح منع تكرار (آمن لإعادة التشغيل).
              </p>
              <Btn kind="gold" onClick={runDemo} disabled={demoBusy}>
                {demoBusy ? 'يُرحّل الشهر…' : 'تشغيل الشهر الفندقي التجريبي'}
              </Btn>
            </>
          ) : (
            <div className="text-xs text-slate-400 mt-2">متاح لصاحب الصلاحية الكاملة (OWNER) فقط</div>
          )}
        </Card>
      </div>

      {/* أحدث القيود */}
      <Card title="أحدث القيود"
            actions={<Link to="/journals" className="text-sm text-atheer-600 hover:underline">كل القيود ←</Link>}>
        {!journals ? <Spinner /> : journals.items.length === 0 ? (
          <div className="text-center text-slate-400 py-6">
            لا قيود بعد — جرّب «تشغيل الشهر الفندقي التجريبي» أو أنشئ قيداً يدوياً
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 text-xs border-b">
                <th className="text-right py-2 font-medium">الرقم</th>
                <th className="text-right font-medium">التاريخ</th>
                <th className="text-right font-medium">النوع</th>
                <th className="text-right font-medium">البيان</th>
                <th className="text-right font-medium">المبلغ</th>
                <th className="text-right font-medium">الحالة</th>
              </tr>
            </thead>
            <tbody>
              {journals.items.map((j) => (
                <tr key={j.id} className="border-b last:border-0 hover:bg-slate-50">
                  <td className="py-2.5 num text-atheer-700 font-medium">
                    <Link to={`/journals/${j.id}`}>{j.entry_no}</Link>
                  </td>
                  <td className="num">{j.entry_date}</td>
                  <td>{j.journal_type}</td>
                  <td className="max-w-[300px] truncate">{j.narration}</td>
                  <td className="num font-medium">{fmt(j.total_debit)}</td>
                  <td>{statusBadge(j.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}
