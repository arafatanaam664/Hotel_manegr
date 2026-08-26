import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, fmt, HttpError } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import { getRack, getReservations, hkNames, rsvStatusAr,
         type Reservation, type RoomRackItem } from '../hotel'

function rackColor(r: RoomRackItem): string {
  if (r.hk_status === 'OOO' || r.hk_status === 'OOS') return 'bg-red-100 border-red-400 text-red-800'
  if (r.occupied) return 'bg-sijill-100 border-sijill-600 text-sijill-900'
  if (r.hk_status === 'DIRTY' || r.hk_status === 'CLEANING') return 'bg-amber-100 border-amber-400 text-amber-800'
  return 'bg-emerald-50 border-emerald-400 text-emerald-800'
}

export default function FrontDesk() {
  const nav = useNavigate()
  const { has } = useAuth()
  const [bd, setBd] = useState<string | null>(null)
  const [rack, setRack] = useState<RoomRackItem[]>([])
  const [arrivals, setArrivals] = useState<Reservation[]>([])
  const [departures, setDepartures] = useState<Reservation[]>([])
  const [inHouse, setInHouse] = useState<Reservation[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [hkFor, setHkFor] = useState<RoomRackItem | null>(null)
  const [busyRoom, setBusyRoom] = useState<string | null>(null)

  async function refresh() {
    const rk = await getRack()
    setBd(rk.business_date)
    setRack(rk.items)
    const [arr, dep, inh] = await Promise.all([
      getReservations({ arrivals_on: rk.business_date, status: 'CONFIRMED' }),
      getReservations({ departures_on: rk.business_date, status: 'CHECKED_IN' }),
      getReservations({ status: 'CHECKED_IN' }),
    ])
    setArrivals(arr.items)
    setDepartures(dep.items)
    setInHouse(inh.items)
  }

  useEffect(() => { refresh().catch((e) => setErr(e.message)) }, [])

  const stats = useMemo(() => ({
    occupied: rack.filter((r) => r.occupied).length,
    vacantClean: rack.filter((r) => !r.occupied && (r.hk_status === 'CLEAN' || r.hk_status === 'INSPECTED')).length,
    dirty: rack.filter((r) => ['DIRTY', 'CLEANING'].includes(r.hk_status)).length,
    ooo: rack.filter((r) => ['OOO', 'OOS'].includes(r.hk_status)).length,
  }), [rack])

  async function quickHk(room: RoomRackItem, to: string) {
    setBusyRoom(room.id); setErr(null); setOk(null)
    try {
      await api(`/api/hotel/rooms/${room.id}/hk`, {
        method: 'POST',
        body: JSON.stringify({ new_status: to }),
      })
      setHkFor(null)
      await refresh()
    } catch (e) {
      setErr(e instanceof HttpError ? e.message : 'فشل تغيير الحالة')
    } finally { setBusyRoom(null) }
  }

  if (!bd) return <Spinner />

  return (
    <div className="space-y-5">
      {/* شريط تاريخ العمل */}
      <div className="bg-gradient-to-l from-sijill-800 to-sijill-950 text-white rounded-3xl px-6 py-4 flex flex-wrap items-center justify-between gap-3 shadow-lg">
        <div>
          <div className="text-xs text-gold-400">تاريخ العمل الفندقي</div>
          <div className="text-2xl font-black num">{bd}</div>
        </div>
        <div className="flex gap-4 text-center">
          <div><div className="text-2xl font-black">{stats.occupied}</div><div className="text-[11px] text-white/60">مشغولة</div></div>
          <div><div className="text-2xl font-black text-emerald-300">{stats.vacantClean}</div><div className="text-[11px] text-white/60">شاغرة نظيفة</div></div>
          <div><div className="text-2xl font-black text-amber-300">{stats.dirty}</div><div className="text-[11px] text-white/60">متسخة</div></div>
          <div><div className="text-2xl font-black text-red-300">{stats.ooo}</div><div className="text-[11px] text-white/60">معطلة</div></div>
        </div>
        <Link to="/night-audit"
              className="bg-gold-500 hover:bg-gold-600 text-sijill-950 font-bold px-4 py-2 rounded-xl text-sm transition-colors">
          التدقيق الليلي ←
        </Link>
      </div>

      <ErrorNote msg={err} />
      <OkNote msg={ok} />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* وصولات اليوم */}
        <Card title={`وصولات اليوم (${arrivals.length})`}>
          {arrivals.length === 0 && <div className="text-slate-400 text-sm text-center py-4">لا وصولات بانتظار التسكين</div>}
          {arrivals.map((r) => (
            <div key={r.id} className="flex items-center justify-between py-2.5 border-b last:border-0">
              <div>
                <div className="font-bold text-sm">{r.guest_name} <span className="text-xs text-slate-400 num">{r.confirmation_no}</span></div>
                <div className="text-xs text-slate-500">{r.room_type} — غرفة {r.room_no} — {r.nights} ليالٍ</div>
              </div>
              <Btn onClick={() => nav(`/reservations/${r.id}`)}>تسكين</Btn>
            </div>
          ))}
        </Card>

        {/* مغادرات اليوم */}
        <Card title={`مغادرات اليوم (${departures.length})`}>
          {departures.length === 0 && <div className="text-slate-400 text-sm text-center py-4">لا مغادرات اليوم</div>}
          {departures.map((r) => (
            <div key={r.id} className="flex items-center justify-between py-2.5 border-b last:border-0">
              <div>
                <div className="font-bold text-sm">{r.guest_name} — غرفة {r.room_no}</div>
                <div className="text-xs text-slate-500">الرصيد: <span className="num">{fmt(r.folios?.[0]?.balance ?? '0')}</span></div>
              </div>
              <Btn kind="danger" onClick={() => nav(`/reservations/${r.id}`)}>مغادرة</Btn>
            </div>
          ))}
        </Card>

        {/* المقيمون */}
        <Card title={`المقيمون حالياً (${inHouse.length})`}>
          {inHouse.length === 0 && <div className="text-slate-400 text-sm text-center py-4">لا نزلاء حالياً</div>}
          {inHouse.map((r) => (
            <div key={r.id} className="flex items-center justify-between py-2.5 border-b last:border-0">
              <div>
                <div className="font-bold text-sm">{r.guest_name} — {r.room_no}</div>
                <div className="text-xs text-slate-500">يغادر <span className="num">{r.departure_date}</span></div>
              </div>
              <Link to={`/reservations/${r.id}`} className="text-sijill-600 text-sm hover:underline">الفوليو</Link>
            </div>
          ))}
        </Card>
      </div>

      {/* الراك اللوني */}
      <Card title="لوحة الطوابق (الراك) — اضغط غرفة للهوسكيبينج">
        <div className="flex flex-wrap gap-2 mb-3 text-[11px]">
          <span className="px-2 py-1 rounded bg-emerald-50 border border-emerald-400">شاغرة نظيفة</span>
          <span className="px-2 py-1 rounded bg-sijill-100 border border-sijill-600">مشغولة</span>
          <span className="px-2 py-1 rounded bg-amber-100 border border-amber-400">متسخة/قيد التنظيف</span>
          <span className="px-2 py-1 rounded bg-red-100 border border-red-400">معطلة</span>
        </div>
        <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-11 gap-2">
          {rack.map((r) => (
            <button key={r.id} onClick={() => setHkFor(r)}
                    title={r.suite_note ?? (r.is_suite ? `جناح مركب: ${r.components.join('، ')}` : undefined)}
                    className={`border-2 rounded-xl py-2.5 px-1 text-center transition-transform hover:scale-105 ${rackColor(r)} ${r.suite_note ? 'opacity-80 ring-2 ring-purple-300' : ''}`}>
              <div className="font-black num">{r.is_suite ? '🏰 ' : ''}{r.room_no}</div>
              <div className="text-[10px]">{r.type_code}{r.parent_room_no ? ` ⊂${r.parent_room_no}` : ''}</div>
              <div className="text-[10px] mt-0.5">{hkNames[r.hk_status]}</div>
              {r.suite_note && <div className="text-[9px] mt-0.5 text-purple-700">🔒 مجدول ضمنياً</div>}
            </button>
          ))}
        </div>
      </Card>

      {/* نافذة هوسكيبينج */}
      {hkFor && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setHkFor(null)}>
          <div className="bg-white rounded-3xl p-6 w-full max-w-sm shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-black text-lg mb-1">غرفة {hkFor.room_no}</h3>
            <div className="text-sm text-slate-500 mb-4">
              الحالة: <Badge>{hkNames[hkFor.hk_status]}</Badge>
              {hkFor.occupied && <Badge tone="blue">مشغولة</Badge>}
            </div>
            <div className="space-y-2">
              {hkFor.hk_status === 'DIRTY' && (
                <Btn className="w-full" disabled={busyRoom === hkFor.id}
                     onClick={() => quickHk(hkFor, 'CLEANING')}>بدء التنظيف</Btn>
              )}
              {hkFor.hk_status === 'CLEANING' && (
                <Btn className="w-full" disabled={busyRoom === hkFor.id}
                     onClick={() => quickHk(hkFor, 'CLEAN')}>انتهاء التنظيف ✓</Btn>
              )}
              {hkFor.hk_status === 'CLEAN' && has('hk.manage') && (
                <Btn className="w-full" disabled={busyRoom === hkFor.id}
                     onClick={() => quickHk(hkFor, 'INSPECTED')}>فحص المشرف</Btn>
              )}
              {hkFor.hk_status === 'OOO' && has('hk.manage') && (
                <Btn className="w-full" disabled={busyRoom === hkFor.id}
                     onClick={() => quickHk(hkFor, 'DIRTY')}>إرجاع للخدمة (متسخة)</Btn>
              )}
              {hkFor.hk_status === 'OOS' && has('hk.manage') && (
                <Btn className="w-full" disabled={busyRoom === hkFor.id}
                     onClick={() => quickHk(hkFor, 'DIRTY')}>إرجاع للخدمة</Btn>
              )}
              {!has('hk.cleaning') && !has('hk.manage') && (
                <div className="text-xs text-slate-400 text-center">تتطلب التعديل صلاحية هوسكيبينج</div>
              )}
              {hkFor.current_rsv && (
                <Btn kind="ghost" className="w-full"
                     onClick={() => nav(`/reservations/${hkFor.current_rsv}`)}>ملف الحجز ←</Btn>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
