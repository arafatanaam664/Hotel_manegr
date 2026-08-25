import { useEffect, useState } from 'react'
import { api, fmt, todayISO } from '../api'
import { Badge, Btn, Card, ErrorNote, Spinner } from '../components/ui'
import { useAuth } from '../auth'
import { hotelReportsApi, HotelDailyReport } from '../hotelReports'

type Branch = { id: string; code: string; name: string }

function Metric({ label, value, suffix = '' }: { label: string; value: string | number; suffix?: string }) {
  return <div className="rounded-2xl bg-slate-50 border border-slate-200 p-4"><div className="text-xs text-slate-500">{label}</div><div className="text-2xl font-black text-slate-800 mt-1">{value}{suffix}</div></div>
}

export default function HotelReports() {
  const { has } = useAuth()
  const [day, setDay] = useState(todayISO())
  const [from, setFrom] = useState(todayISO())
  const [to, setTo] = useState(todayISO())
  const [branch, setBranch] = useState('')
  const [branches, setBranches] = useState<Branch[]>([])
  const [report, setReport] = useState<HotelDailyReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void api<Branch[]>('/api/org/branches').then(setBranches).catch(() => setBranches([]))
  }, [])

  if (!has('reports.view')) return <Card title="تقارير الفندق"><p className="text-slate-600">لا تملك صلاحية عرض التقارير.</p></Card>

  const load = async () => {
    setLoading(true); setError(null)
    try { setReport(await hotelReportsApi.daily(day, branch || undefined)) }
    catch (e) { setError(e instanceof Error ? e.message : 'تعذر تحميل التقرير') }
    finally { setLoading(false) }
  }

  return <div className="space-y-5 max-w-6xl">
    <div><h1 className="text-2xl font-black text-slate-800">تقارير الفندق التشغيلية</h1><p className="text-slate-500 mt-1">قراءة يومية سريعة للمدير، مع مؤشرات تصلح للمقارنة الشهرية.</p></div>
    <Card title="فلاتر التقرير">
      <div className="grid md:grid-cols-4 gap-3 items-end">
        <label className="text-sm text-slate-600">اليوم<input type="date" value={day} onChange={e => setDay(e.target.value)} className="mt-1 w-full border rounded-xl px-3 py-2" /></label>
        <label className="text-sm text-slate-600">الفرع<select value={branch} onChange={e => setBranch(e.target.value)} className="mt-1 w-full border rounded-xl px-3 py-2 bg-white"><option value="">كل الفروع</option>{branches.map(b => <option key={b.id} value={b.id}>{b.name || b.code}</option>)}</select></label>
        <label className="text-sm text-slate-600">من<input type="date" value={from} onChange={e => setFrom(e.target.value)} className="mt-1 w-full border rounded-xl px-3 py-2" /></label>
        <label className="text-sm text-slate-600">إلى<input type="date" value={to} onChange={e => setTo(e.target.value)} className="mt-1 w-full border rounded-xl px-3 py-2" /></label>
      </div>
      <div className="flex gap-3 mt-4"><Btn disabled={loading} onClick={() => void load()}>{loading ? 'جارٍ التحميل…' : 'عرض التقرير اليومي'}</Btn><Btn kind="ghost" disabled={loading} onClick={() => { setDay(to); void load() }}>استخدام تاريخ النهاية</Btn></div>
    </Card>
    <ErrorNote msg={error} />
    {loading && <Spinner />}
    {report && <>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3"><Metric label="الإشغال" value={fmt(report.occupancy_pct, 2)} suffix="%" /><Metric label="ADR متوسط سعر الغرفة" value={fmt(report.adr, 2)} /><Metric label="RevPAR" value={fmt(report.revpar, 2)} /><Metric label="إيراد الغرف" value={fmt(report.room_revenue, 2)} /></div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3"><Metric label="الغرف المباعة" value={report.rooms_sold} /><Metric label="الغرف المتاحة" value={report.rooms_sellable} /><Metric label="الوصولات" value={report.arrivals} /><Metric label="المغادرات" value={report.departures} /><Metric label="No-show" value={report.no_shows} /></div>
      <Card title={`تفاصيل ${report.business_day}`}>
        <div className="grid md:grid-cols-2 gap-5"><div><h3 className="font-bold text-slate-700 mb-3">حالة التدبير الفندقي</h3><div className="flex flex-wrap gap-2">{Object.entries(report.housekeeping).map(([key, value]) => <Badge key={key} tone={key === 'CLEAN' || key === 'INSPECTED' ? 'green' : key === 'DIRTY' || key === 'CLEANING' ? 'amber' : 'red'}>{key}: {value}</Badge>)}</div></div><div><h3 className="font-bold text-slate-700 mb-3">الإيراد حسب المصدر</h3>{Object.keys(report.revenue_by_source).length === 0 ? <p className="text-sm text-slate-500">لا توجد ليالٍ مسعّرة في هذا اليوم.</p> : <div className="space-y-2">{Object.entries(report.revenue_by_source).map(([key, value]) => <div key={key} className="flex justify-between border-b pb-2 text-sm"><span>{key}</span><b>{fmt(value, 2)}</b></div>)}</div>}</div></div>
      </Card>
    </>}
  </div>
}
