import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmt, HttpError, todayISO } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import { getCorporates, getGuests, getReservations, getRoomTypes,
         rsvStatusAr, type Corporate, type Guest, type Reservation,
         type RoomType } from '../hotel'

function statusTone(s: string): 'green' | 'amber' | 'red' | 'blue' | 'slate' {
  return { CONFIRMED: 'blue', CHECKED_IN: 'green', CHECKED_OUT: 'slate',
           CANCELLED: 'red', NO_SHOW: 'amber', TENTATIVE: 'slate' }[s] as 'green' | 'amber' | 'red' | 'blue' | 'slate'
}

export default function Reservations() {
  const { has } = useAuth()
  const [items, setItems] = useState<Reservation[] | null>(null)
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [showNew, setShowNew] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)

  async function refresh() {
    const params: Record<string, string> = {}
    if (status) params.status = status
    if (q) params.q = q
    const r = await getReservations(params)
    setItems(r.items)
  }
  useEffect(() => { refresh().catch((e) => setErr(e.message)) }, [status])

  return (
    <div className="space-y-4">
      <ErrorNote msg={err} />
      <OkNote msg={ok} />
      <Card title="الحجوزات"
            actions={
              <div className="flex items-center gap-2">
                <input value={q} onChange={(e) => setQ(e.target.value)}
                       onKeyDown={(e) => e.key === 'Enter' && refresh()}
                       placeholder="بحث: اسم/تأكيد/غرفة…"
                       className="border border-slate-300 rounded-xl px-3 py-1.5 text-sm w-52" />
                <select value={status} onChange={(e) => setStatus(e.target.value)}
                        className="border border-slate-300 rounded-xl px-3 py-1.5 text-sm">
                  <option value="">كل الحالات</option>
                  {Object.entries(rsvStatusAr).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>))}
                </select>
                <Btn kind="ghost" onClick={refresh}>تحديث</Btn>
                {has('reservations.create') && (
                  <Btn onClick={() => setShowNew(true)}>+ حجز جديد</Btn>)}
              </div>
            }>
        {!items ? <Spinner /> : items.length === 0 ? (
          <div className="text-center text-slate-400 py-8">لا حجوزات — أنشئ أول حجز</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 text-xs border-b">
                <th className="text-right py-2 font-medium">التأكيد</th>
                <th className="text-right font-medium">النزيل</th>
                <th className="text-right font-medium">الغرفة</th>
                <th className="text-right font-medium">وصول ← مغادرة</th>
                <th className="text-right font-medium">الليالي</th>
                <th className="text-right font-medium">الإجمالي</th>
                <th className="text-right font-medium">الحالة</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} className="border-b last:border-0 hover:bg-slate-50">
                  <td className="py-2.5 num text-sijill-700 font-bold">
                    <Link to={`/reservations/${r.id}`}>{r.confirmation_no}</Link>
                  </td>
                  <td>{r.guest_name}{r.corporate && <span className="text-xs text-slate-400"> — {r.corporate}</span>}</td>
                  <td className="num">{r.room_no} <span className="text-xs text-slate-400">{r.room_type}</span></td>
                  <td className="num text-xs">{r.arrival_date} ← {r.departure_date}</td>
                  <td className="num">{r.nights}</td>
                  <td className="num">{fmt(r.est_total)}</td>
                  <td><Badge tone={statusTone(r.status)}>{rsvStatusAr[r.status]}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {showNew && (
        <NewReservationModal
          onClose={() => setShowNew(false)}
          onDone={async (msg) => { setShowNew(false); setOk(msg); await refresh() }}
        />
      )}
    </div>
  )
}

// ── نافذة إنشاء حجز ────────────────────────────────────
function NewReservationModal({ onClose, onDone }: {
  onClose: () => void
  onDone: (msg: string) => Promise<void>
}) {
  const [guests, setGuests] = useState<Guest[]>([])
  const [corporates, setCorporates] = useState<Corporate[]>([])
  const [types, setTypes] = useState<RoomType[]>([])
  const [guestId, setGuestId] = useState('')
  const [corporateId, setCorporateId] = useState('')
  const [typeCode, setTypeCode] = useState('')
  const [arrival, setArrival] = useState(todayISO())
  const [nights, setNights] = useState(2)
  const [source, setSource] = useState('DIRECT')
  const [adults, setAdults] = useState(1)
  const [deposit, setDeposit] = useState('')
  const [avail, setAvail] = useState<{ count: number; total: string; available_rooms: string[] } | null>(null)
  const [newGuest, setNewGuest] = useState('')
  const [newGuestPhone, setNewGuestPhone] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    Promise.all([getGuests(), getCorporates(), getRoomTypes()]).then(([g, c, t]) => {
      setGuests(g); setCorporates(c); setTypes(t)
      if (t.length) setTypeCode(t[0].code)
    })
  }, [])

  function plusDays(iso: string, n: number): string {
    const d = new Date(iso); d.setDate(d.getDate() + n)
    return d.toISOString().slice(0, 10)
  }

  async function checkAvailability() {
    setErr(null); setAvail(null)
    try {
      const r = await api<{ count: number; total: string; available_rooms: string[] }>(
        `/api/hotel/availability?room_type=${typeCode}&date_from=${arrival}&date_to=${plusDays(arrival, nights)}`)
      if (r.count === 0) setErr('لا يوجد توفر لهذا النوع في الفترة المختارة')
      else setAvail(r)
    } catch (e) { setErr(e instanceof HttpError ? e.message : 'خطأ') }
  }

  async function createGuestQuick(): Promise<string | null> {
    if (newGuest.trim().length < 2) return null
    const g = await api<{ id: string }>('/api/hotel/guests', {
      method: 'POST',
      body: JSON.stringify({ full_name: newGuest.trim(), phone: newGuestPhone.trim() }),
    })
    return g.id
  }

  async function submit(walkIn: boolean) {
    setBusy(true); setErr(null)
    try {
      let gid = guestId
      if (!gid && newGuest.trim()) gid = (await createGuestQuick()) ?? ''
      if (!gid) { setErr('اختر نزيلاً أو أدخل اسم نزيل جديد'); setBusy(false); return }
      const dep = plusDays(arrival, nights)
      const body = {
        guest_id: gid, room_type_code: typeCode,
        arrival_date: walkIn ? undefined : arrival,
        departure_date: dep,
        corporate_id: corporateId || null,
        adults, source: walkIn ? 'WALKIN' : source,
      }
      const r = walkIn
        ? await api<{ confirmation_no: string }>('/api/hotel/walk-in', {
            method: 'POST',
            body: JSON.stringify({ ...body, arrival_date: undefined }),
          })
        : await api<{ confirmation_no: string }>('/api/hotel/reservations', {
            method: 'POST', body: JSON.stringify(body),
          })
      if (deposit && !walkIn) {
        // العربون لاحقاً من ملف الحجز — هنا فقط إنشاء
      }
      await onDone(`أُنشئ ${walkIn ? 'تسكين مباشر' : 'الحجز'} ${r.confirmation_no} بنجاح`)
    } catch (e) {
      setErr(e instanceof HttpError ? e.message : 'فشل الإنشاء')
    } finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 overflow-y-auto py-8" onClick={onClose}>
      <div className="bg-white rounded-3xl p-6 w-full max-w-2xl shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-black text-lg mb-4">حجز جديد</h3>
        <ErrorNote msg={err} />
        <div className="grid grid-cols-2 gap-4">
          <label className="block col-span-2">
            <span className="text-xs text-slate-500 block mb-1">النزيل (اختر أو أدخل جديداً)</span>
            <select value={guestId} onChange={(e) => { setGuestId(e.target.value); setNewGuest('') }}
                    className="w-full border border-slate-300 rounded-xl px-3 py-2">
              <option value="">— نزيل جديد بالاسم أدناه —</option>
              {guests.map((g) => (
                <option key={g.id} value={g.id}>{g.full_name} {g.phone && `(${g.phone})`}</option>))}
            </select>
          </label>
          {!guestId && (
            <div className="col-span-2 grid grid-cols-3 gap-2">
              <input value={newGuest} onChange={(e) => setNewGuest(e.target.value)}
                     placeholder="اسم النزيل الجديد…"
                     className="col-span-2 border border-slate-300 rounded-xl px-3 py-2" />
              <input value={newGuestPhone} onChange={(e) => setNewGuestPhone(e.target.value)}
                     placeholder="هاتف (اختياري)"
                     className="border border-slate-300 rounded-xl px-3 py-2 num" />
            </div>
          )}
          <label className="block">
            <span className="text-xs text-slate-500 block mb-1">نوع الغرفة</span>
            <select value={typeCode} onChange={(e) => { setTypeCode(e.target.value); setAvail(null) }}
                    className="w-full border border-slate-300 rounded-xl px-3 py-2">
              {types.map((t) => (
                <option key={t.id} value={t.code}>{t.name_ar} — {fmt(t.base_rate)}</option>))}
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-slate-500 block mb-1">شركة (اختياري)</span>
            <select value={corporateId} onChange={(e) => setCorporateId(e.target.value)}
                    className="w-full border border-slate-300 rounded-xl px-3 py-2">
              <option value="">— بدون —</option>
              {corporates.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-slate-500 block mb-1">الوصول</span>
            <input type="date" value={arrival}
                   onChange={(e) => { setArrival(e.target.value); setAvail(null) }}
                   className="w-full border border-slate-300 rounded-xl px-3 py-2 num" />
          </label>
          <label className="block">
            <span className="text-xs text-slate-500 block mb-1">الليالي</span>
            <input type="number" min={1} max={60} value={nights}
                   onChange={(e) => { setNights(parseInt(e.target.value) || 1); setAvail(null) }}
                   className="w-full border border-slate-300 rounded-xl px-3 py-2 num" />
          </label>
          <label className="block">
            <span className="text-xs text-slate-500 block mb-1">المصدر</span>
            <select value={source} onChange={(e) => setSource(e.target.value)}
                    className="w-full border border-slate-300 rounded-xl px-3 py-2">
              <option value="DIRECT">مباشر</option><option value="PHONE">هاتف</option>
              <option value="CORPORATE">شركة</option><option value="OTA">منصة حجز</option>
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-slate-500 block mb-1">بالغين</span>
            <input type="number" min={1} max={8} value={adults}
                   onChange={(e) => setAdults(parseInt(e.target.value) || 1)}
                   className="w-full border border-slate-300 rounded-xl px-3 py-2 num" />
          </label>
        </div>

        {avail && (
          <div className="bg-emerald-50 border border-emerald-200 rounded-xl px-4 py-3 mt-4 text-sm">
            ✅ التوفر: {avail.count} غرفة ({avail.available_rooms.join('، ')}) —
            الإجمالي التقديري: <b className="num">{fmt(avail.total)}</b>
          </div>
        )}

        <div className="flex justify-between mt-6">
          <Btn kind="ghost" onClick={onClose}>إلغاء</Btn>
          <div className="flex gap-2">
            <Btn kind="ghost" onClick={checkAvailability} disabled={busy || !typeCode}>
              فحص التوفر
            </Btn>
            <Btn kind="gold" onClick={() => submit(true)} disabled={busy}>
              {busy ? '…' : 'تسكين مباشر (Walk-in)'}
            </Btn>
            <Btn onClick={() => submit(false)} disabled={busy}>
              {busy ? 'يُنشأ…' : 'إنشاء الحجز'}
            </Btn>
          </div>
        </div>
      </div>
    </div>
  )
}
