import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmt, HttpError } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import type { AuditPrecheck } from '../hotel'

interface AuditRun {
  id: string
  business_date: string
  status: string
  totals: Record<string, string | number>
  completed_at: string | null
}

interface AuditHome {
  precheck: AuditPrecheck
  recent_runs: AuditRun[]
}

export default function NightAudit() {
  const { has } = useAuth()
  const [home, setHome] = useState<AuditHome | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [lastRun, setLastRun] = useState<Record<string, unknown> | null>(null)

  async function refresh() {
    setHome(await api<AuditHome>('/api/hotel/night-audit'))
  }
  useEffect(() => { refresh().catch((e) => setErr(e.message)) }, [])

  async function run() {
    setBusy(true); setErr(null); setOk(null)
    try {
      const r = await api<Record<string, unknown>>('/api/hotel/night-audit/run', { method: 'POST' })
      setLastRun(r)
      setOk(`أُقفل يوم ${r.business_date} — الليالٍ المرحلة: ${(r.totals as {nights_posted:number})?.nights_posted ?? '—'}`)
      await refresh()
    } catch (e) {
      setErr(e instanceof HttpError ? e.message : 'فشل التدقيق')
    } finally { setBusy(false) }
  }

  if (!home) return <Spinner />
  const p = home.precheck

  return (
    <div className="space-y-4 max-w-5xl">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-xs text-slate-400">تاريخ العمل القابل للإقفال</div>
            <div className="text-3xl font-black num">{p.business_date}</div>
            <div className="text-sm text-slate-500 mt-1">
              يتقدم التاريخ يوماً واحداً فقط عند نجاح الإقفال — الرجوع ممنوع إلا بإجراء مزدوج موثق
            </div>
          </div>
          {has('nightaudit.run') ? (
            <Btn kind="gold" onClick={run} disabled={busy || !p.can_run} className="text-lg px-6 py-3">
              {busy ? 'يُرحّل الليالٍ ويُقفل…' : p.can_run ? `إقفال يوم ${p.business_date}` : 'محجوب — عالج المعلقات'}
            </Btn>
          ) : (
            <Badge tone="amber">يتطلب صلاحية nightaudit.run</Badge>
          )}
        </div>
      </Card>

      <ErrorNote msg={err} />
      <OkNote msg={ok} />

      {/* فحوص الإجراء */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card title={`وصولات بلا حسم (${p.pending_arrivals.length})`}>
          {p.pending_arrivals.length === 0
            ? <Badge tone="green">واضحة ✓</Badge>
            : p.pending_arrivals.map((r) => (
                <div key={r.id} className="py-2 border-b last:border-0 text-sm flex justify-between items-center">
                  <span className="num">{r.conf} — وصول {r.arrival}</span>
                  <Link to={`/reservations/${r.id}`} className="text-sijill-600 hover:underline text-xs">حسم ←</Link>
                </div>
              ))}
        </Card>
        <Card title={`مغادرات بلا حسم (${p.pending_departures.length})`}>
          {p.pending_departures.length === 0
            ? <Badge tone="green">واضحة ✓</Badge>
            : p.pending_departures.map((r) => (
                <div key={r.id} className="py-2 border-b last:border-0 text-sm flex justify-between items-center">
                  <span className="num">{r.conf} — مغادرة {r.departure}</span>
                  <Link to={`/reservations/${r.id}`} className="text-sijill-600 hover:underline text-xs">حسم ←</Link>
                </div>
              ))}
        </Card>
        <Card title="ليالٍ سترحّل">
          <div className="text-3xl font-black num text-center my-2">{p.in_house_expect_nights}</div>
          <div className="text-xs text-slate-400 text-center">ليالِ إقامة ستُرحّل (حدث #04 لكل غرفة — ذرياً: الكل أو لا شيء)</div>
        </Card>
      </div>

      {/* نتيجة آخر إقفال */}
      {lastRun && (
        <Card title={`نتيجة إقفال ${String(lastRun.business_date)}`}>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {Object.entries((lastRun.snapshot as Record<string, string>) ?? {})
              .filter(([k]) => ['occupancy_pct', 'adr', 'revpar', 'room_revenue'].includes(k))
              .map(([k, v]) => (
                <div key={k} className="bg-slate-50 rounded-xl p-3 text-center">
                  <div className="text-xs text-slate-400">{{ occupancy_pct: 'الإشغال %', adr: 'ADR', revpar: 'RevPAR', room_revenue: 'إيراد الغرف' }[k]}</div>
                  <div className="num font-black text-lg">{v}</div>
                </div>
              ))}
          </div>
          <div className="text-xs text-slate-400 mt-3">
            Snapshot موقّع غير قابل للتعديل — أرشيفه في سجل التدقيق
          </div>
        </Card>
      )}

      {/* السجل */}
      <Card title="آخر عمليات الإقفال">
        {home.recent_runs.length === 0 ? (
          <div className="text-slate-400 text-sm text-center py-4">لم يُقفل أي يوم بعد</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 text-xs border-b">
                <th className="text-right py-2 font-medium">يوم العمل</th>
                <th className="text-right font-medium">الليالٍ</th>
                <th className="text-right font-medium">الإيراد</th>
                <th className="text-right font-medium">الإتمام</th>
                <th className="text-right font-medium">الحالة</th>
              </tr>
            </thead>
            <tbody>
              {home.recent_runs.map((r) => (
                <tr key={r.id} className="border-b last:border-0">
                  <td className="py-2 num">{r.business_date}</td>
                  <td className="num">{String(r.totals?.nights_posted ?? 0)}</td>
                  <td className="num">{fmt(String(r.totals?.revenue ?? 0))}</td>
                  <td className="num text-xs text-slate-400">{r.completed_at ? String(r.completed_at).slice(0, 19).replace('T', ' ') : '—'}</td>
                  <td><Badge tone="green">{r.status}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}
