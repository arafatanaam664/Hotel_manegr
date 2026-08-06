// وحدة «الغرف والأسعار» (ملف 03 §1.1–1.5 + ADR-0035 الأجنحة المركبة):
// الغرف/الأنواع/خطط الأسعار/تقويم الأسعار/الخدمات — إدارة كاملة موثقة.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { fmt, HttpError } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import {
  CalendarEntry, ExtraFull, getRack, getRoomTypes, hkNames, RatePlan,
  RoomRackItem, RoomType, roomsApi,
} from '../hotel'

type TabKey = 'rooms' | 'types' | 'plans' | 'calendar' | 'extras'
const TABS: { k: TabKey; label: string }[] = [
  { k: 'rooms', label: '🛏 الغرف' },
  { k: 'types', label: '🏷 أنواع الغرف' },
  { k: 'plans', label: '📋 خطط الأسعار' },
  { k: 'calendar', label: '📆 تقويم الأسعار' },
  { k: 'extras', label: '🧺 الخدمات الإضافية' },
]
const KIND_AR: Record<string, string> = { STANDARD: 'غرفة', SUITE_UNIT: 'جناح مركب' }
const DAY_TYPES = [
  { c: 'NORMAL', n: 'عادي' }, { c: 'WEEKEND', n: 'نهاية أسبوع' },
  { c: 'SEASON', n: 'موسم' }, { c: 'EVENT', n: 'مناسبة/عيد' },
  { c: 'LEAN', n: 'موسم منخفض' },
]

const input = 'border rounded-lg px-3 py-2 text-sm w-full bg-white'
const label = 'block text-xs text-slate-500 mb-1'

function Modal({ title, onClose, children }: {
  title: string; onClose: () => void; children: React.ReactNode
}) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
         onClick={onClose}>
      <div className="bg-white rounded-3xl p-6 w-full max-w-lg shadow-2xl max-h-[90vh] overflow-auto"
           onClick={(e) => e.stopPropagation()}>
        <h3 className="font-black text-lg mb-4">{title}</h3>
        {children}
      </div>
    </div>
  )
}

export default function HotelRoomsPage() {
  const { has } = useAuth()
  const canRooms = has('rooms.manage')
  const canRates = has('rates.manage')
  const canExtras = has('extras.manage')
  const [tab, setTab] = useState<TabKey>('rooms')
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  const [busy, setBusy] = useState(false)

  const [rooms, setRooms] = useState<RoomRackItem[]>([])
  const [types, setTypes] = useState<RoomType[]>([])
  const [plans, setPlans] = useState<RatePlan[]>([])
  const [extras, setExtras] = useState<ExtraFull[]>([])
  const [calRows, setCalRows] = useState<CalendarEntry[]>([])

  const load = useCallback(async () => {
    try {
      const [rack, t, p, x] = await Promise.all([
        getRack(), getRoomTypes(), roomsApi.plans(), roomsApi.extrasAll()])
      setRooms(rack.items); setTypes(t); setPlans(p); setExtras(x)
      setErr('')
    } catch (e) {
      setErr(e instanceof HttpError ? `${e.code}: ${e.message}` : 'تعذر الجلب')
    }
  }, [])
  useEffect(() => { load() }, [load])

  async function run(fn: () => Promise<unknown>, okMsg: string | ((r: unknown) => string)) {
    if (busy) return
    setBusy(true); setErr(''); setOk('')
    try {
      const r = await fn()
      setOk(typeof okMsg === 'function' ? okMsg(r) : okMsg)
      await load()
    } catch (e) {
      setErr(e instanceof HttpError ? `${e.code}: ${e.message}` : 'فشل التنفيذ')
    } finally { setBusy(false) }
  }

  return (
    <div className="space-y-4" dir="rtl">
      <div className="flex items-center gap-2 flex-wrap">
        <h2 className="text-xl font-black ml-4">🛏 الغرف والأسعار</h2>
        {TABS.map((t) => (
          <button key={t.k} onClick={() => setTab(t.k)}
                  className={`px-3 py-1.5 rounded-full text-sm border transition ${tab === t.k ? 'bg-atheer-600 text-white border-atheer-600' : 'bg-white hover:bg-slate-50'}`}>
            {t.label}
          </button>
        ))}
      </div>
      <ErrorNote msg={err} />
      <OkNote msg={ok} />

      {tab === 'rooms' && <RoomsTab rooms={rooms} types={types}
        canManage={canRooms} busy={busy} run={run} />}
      {tab === 'types' && <TypesTab types={types} canManage={canRooms}
        busy={busy} run={run} />}
      {tab === 'plans' && <PlansTab plans={plans} canManage={canRates}
        busy={busy} run={run} />}
      {tab === 'calendar' && <CalendarTab types={types} plans={plans}
        rows={calRows} setRows={setCalRows} canManage={canRates}
        busy={busy} run={run} />}
      {tab === 'extras' && <ExtrasTab extras={extras} canManage={canExtras}
        busy={busy} run={run} />}
    </div>
  )
}

type Run = (fn: () => Promise<unknown>, ok: string | ((r: unknown) => string)) => Promise<void>

/* ──────────────────── تبويب الغرف ──────────────────── */
function RoomsTab({ rooms, types, canManage, busy, run }: {
  rooms: RoomRackItem[]; types: RoomType[]; canManage: boolean
  busy: boolean; run: Run
}) {
  const [form, setForm] = useState({
    room_no: '', floor: 1, room_type_code: types[0]?.code ?? '',
    kind: 'STANDARD', parent_room_no: '', features: '',
  })
  const [editFor, setEditFor] = useState<RoomRackItem | null>(null)
  const suites = rooms.filter((r) => r.is_suite)
  const typeOf = (r: RoomRackItem) => types.find((t) => t.code === r.type_code)

  return (<>
    {canManage && (
      <Card title="➕ إضافة غرفة أو جناح مركب">
        <form className="grid grid-cols-2 md:grid-cols-7 gap-2 items-end"
              onSubmit={(e) => { e.preventDefault(); run(() => roomsApi.createRoom({
                room_no: form.room_no.trim(), floor: Number(form.floor),
                room_type_code: form.room_type_code, kind: form.kind,
                parent_room_no: form.kind === 'STANDARD' && form.parent_room_no ? form.parent_room_no : null,
                features: form.features ? form.features.split(',').map((f) => f.trim()).filter(Boolean) : [],
              }), `أُنشئت الغرفة ${form.room_no} ✔`).then(() =>
                setForm({ ...form, room_no: '', parent_room_no: '' }))
              }}>
          <label className={label}>رقم الغرفة
            <input className={input} required value={form.room_no}
                   onChange={(e) => setForm({ ...form, room_no: e.target.value })}
                   placeholder="501" /></label>
          <label className={label}>الطابق
            <input className={input} type="number" min={0} max={50} value={form.floor}
                   onChange={(e) => setForm({ ...form, floor: Number(e.target.value) })} /></label>
          <label className={label}>النوع
            <select className={input} value={form.room_type_code}
                    onChange={(e) => setForm({ ...form, room_type_code: e.target.value })}>
              {types.map((t) => <option key={t.code} value={t.code}>{t.name_ar}</option>)}
            </select></label>
          <label className={label}>الفئة
            <select className={input} value={form.kind}
                    onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              <option value="STANDARD">غرفة عادية</option>
              <option value="SUITE_UNIT">جناح مركب (أب بيعي)</option>
            </select></label>
          {form.kind === 'STANDARD' ? (
            <label className={label}>جزء من جناح؟
              <select className={input} value={form.parent_room_no}
                      onChange={(e) => setForm({ ...form, parent_room_no: e.target.value })}>
                <option value="">— مستقلة —</option>
                {suites.map((s) => <option key={s.id} value={s.room_no}>
                  {s.room_no} ({s.type})</option>)}
              </select></label>
          ) : <div className="text-[11px] text-purple-700 pb-2">
            الجناح المركب: سعره من نوعه، وحجزه يقفل أبناءه تلقائياً</div>}
          <label className={label}>مميزات (فاصلة)
            <input className={input} value={form.features}
                   onChange={(e) => setForm({ ...form, features: e.target.value })}
                   placeholder="شرفة, إطلالة بحرية" /></label>
          <Btn disabled={busy} type="submit">إضافة</Btn>
        </form>
      </Card>
    )}
    <Card title={`سجل الغرف (${rooms.length})`}>
      <div className="overflow-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-right text-slate-400 text-xs border-b">
            <th className="py-2">الغرفة</th><th>النوع</th><th>البنية</th>
            <th>سعر النوع/ليلة</th><th>الحالة</th><th>فعّالة</th>
            <th>مميزات</th><th></th></tr></thead>
          <tbody>
            {rooms.map((r) => (
              <tr key={r.id} className="border-b hover:bg-slate-50">
                <td className="py-2 font-bold num">{r.room_no}
                  <span className="text-[10px] text-slate-400"> ط{r.floor}</span></td>
                <td>{r.type}</td>
                <td>{r.is_suite
                  ? <Badge tone="gold">🏰 جناح ← {r.components.join('، ') || 'بلا أبناء'}</Badge>
                  : r.parent_room_no
                    ? <Badge tone="slate">جزء من {r.parent_room_no}</Badge>
                    : <Badge>مستقلة</Badge>}
                  {r.suite_note && <div className="text-[10px] text-purple-700 mt-1">🔒 {r.suite_note}</div>}
                </td>
                <td className="num">{fmt(typeOf(r)?.base_rate ?? r.base_rate)}</td>
                <td><Badge tone={r.hk_status === 'CLEAN' || r.hk_status === 'INSPECTED' ? 'green' : 'amber'}>{hkNames[r.hk_status]}</Badge></td>
                <td>{r.is_active ? '✅' : '⛔'}</td>
                <td className="text-[11px] text-slate-500 max-w-[120px] truncate">{(r.features ?? []).join('، ')}</td>
                <td>{canManage && <Btn kind="ghost" onClick={() => setEditFor(r)}>تعديل</Btn>}</td>
              </tr>))}
          </tbody>
        </table>
      </div>
    </Card>
    {editFor && <RoomEditModal room={editFor} types={types}
      suites={suites} onClose={() => setEditFor(null)} run={run} busy={busy} />}
  </>)
}

function RoomEditModal({ room, types, suites, onClose, run, busy }: {
  room: RoomRackItem; types: RoomType[]; suites: RoomRackItem[]
  onClose: () => void; run: Run; busy: boolean
}) {
  const [f, setF] = useState({
    floor: room.floor, room_type_code: room.type_code, kind: room.kind,
    parent_room_no: room.parent_room_no ?? '',
    features: (room.features ?? []).join(', '),
    is_active: room.is_active,
  })
  return (
    <Modal title={`تعديل الغرفة ${room.room_no}`} onClose={onClose}>
      <div className="grid grid-cols-2 gap-3">
        <label className={label}>الطابق
          <input className={input} type="number" min={0} max={50} value={f.floor}
                 onChange={(e) => setF({ ...f, floor: Number(e.target.value) })} /></label>
        <label className={label}>النوع
          <select className={input} value={f.room_type_code}
                  onChange={(e) => setF({ ...f, room_type_code: e.target.value })}>
            {types.map((t) => <option key={t.code} value={t.code}>{t.name_ar}</option>)}
          </select></label>
        <label className={label}>الفئة
          <select className={input} value={f.kind}
                  onChange={(e) => setF({ ...f, kind: e.target.value })}>
            <option value="STANDARD">غرفة عادية</option>
            <option value="SUITE_UNIT">جناح مركب</option>
          </select></label>
        {f.kind === 'STANDARD' && (
          <label className={label}>جزء من جناح
            <select className={input} value={f.parent_room_no}
                    onChange={(e) => setF({ ...f, parent_room_no: e.target.value })}>
              <option value="">— فك الربط (مستقلة) —</option>
              {suites.filter((s) => s.id !== room.id).map((s) =>
                <option key={s.id} value={s.room_no}>{s.room_no} ({s.type})</option>)}
            </select></label>)}
        <label className={`${label} col-span-2`}>مميزات (فاصلة)
          <input className={input} value={f.features}
                 onChange={(e) => setF({ ...f, features: e.target.value })} /></label>
        <label className="flex items-center gap-2 text-sm col-span-2">
          <input type="checkbox" checked={f.is_active}
                 onChange={(e) => setF({ ...f, is_active: e.target.checked })} />
          غرفة فعّالة (إلغاء التفعيل يمنع أي بيع مستقبلي ويُحرس بحجوزاتها النشطة)</label>
      </div>
      <div className="flex gap-2 mt-5">
        <Btn disabled={busy} onClick={() => {
          const body: Record<string, unknown> = {
            floor: f.floor, room_type_code: f.room_type_code, kind: f.kind,
            features: f.features ? f.features.split(',').map((x) => x.trim()).filter(Boolean) : [],
            is_active: f.is_active,
          }
          if (f.kind === 'STANDARD' && f.parent_room_no !== (room.parent_room_no ?? '')) {
            body.set_parent = true
            body.parent_room_no = f.parent_room_no
          }
          run(() => roomsApi.updateRoom(room.id, body),
            `عُدّلت الغرفة ${room.room_no} ✔`).then(onClose)
        }}>حفظ</Btn>
        <Btn kind="ghost" onClick={onClose}>إلغاء</Btn>
      </div>
    </Modal>
  )
}

/* ──────────────────── تبويب الأنواع ──────────────────── */
function TypesTab({ types, canManage, busy, run }: {
  types: RoomType[]; canManage: boolean; busy: boolean; run: Run
}) {
  const [form, setForm] = useState({
    code: '', name_ar: '', base_rate: '', capacity_adults: 2,
    capacity_children: 1, beds: '', amenities: '', display_order: 0,
  })
  const [editFor, setEditFor] = useState<RoomType | null>(null)
  return (<>
    {canManage && (
      <Card title="➕ إضافة نوع غرفة (السعر = سعر الليلة الأساسي)">
        <form className="grid grid-cols-2 md:grid-cols-4 gap-2 items-end"
              onSubmit={(e) => { e.preventDefault(); run(() => roomsApi.createType({
                code: form.code.trim().toUpperCase(), name_ar: form.name_ar,
                base_rate: form.base_rate, capacity_adults: Number(form.capacity_adults),
                capacity_children: Number(form.capacity_children), beds: form.beds,
                amenities: form.amenities ? form.amenities.split(',').map((x) => x.trim()).filter(Boolean) : [],
                display_order: Number(form.display_order),
              }), `أُضيف النوع ${form.code} ✔`) }}>
          <label className={label}>الكود (إنجليزي)
            <input className={input} required pattern="[A-Z0-9-]+" value={form.code}
                   onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="DLX" /></label>
          <label className={label}>الاسم العربي
            <input className={input} required value={form.name_ar}
                   onChange={(e) => setForm({ ...form, name_ar: e.target.value })} placeholder="ديلوكس بإطلالة" /></label>
          <label className={label}>سعر الليلة الأساسي
            <input className={input} required type="number" min={0} step="0.01" value={form.base_rate}
                   onChange={(e) => setForm({ ...form, base_rate: e.target.value })} /></label>
          <label className={label}>أسرّة
            <input className={input} value={form.beds}
                   onChange={(e) => setForm({ ...form, beds: e.target.value })} placeholder="سريران + أريكة" /></label>
          <label className={label}>سعة بالغين
            <input className={input} type="number" min={1} max={10} value={form.capacity_adults}
                   onChange={(e) => setForm({ ...form, capacity_adults: Number(e.target.value) })} /></label>
          <label className={label}>أطفال
            <input className={input} type="number" min={0} max={8} value={form.capacity_children}
                   onChange={(e) => setForm({ ...form, capacity_children: Number(e.target.value) })} /></label>
          <label className={label}>مرافق (فاصلة)
            <input className={input} value={form.amenities}
                   onChange={(e) => setForm({ ...form, amenities: e.target.value })} placeholder="واي فاي, شرفة" /></label>
          <Btn disabled={busy} type="submit">إضافة</Btn>
        </form>
      </Card>
    )}
    <Card title={`أنواع الغرف (${types.length})`}>
      <div className="overflow-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-right text-slate-400 text-xs border-b">
            <th className="py-2">الكود</th><th>الاسم</th><th>السعة</th><th>الأسرّة</th>
            <th>المرافق</th><th>سعر الليلة</th><th>نشط</th><th></th></tr></thead>
          <tbody>
            {types.map((t) => (
              <tr key={t.id} className="border-b hover:bg-slate-50">
                <td className="py-2 font-mono font-bold">{t.code}</td>
                <td>{t.name_ar}</td>
                <td className="text-[12px]">{t.capacity_adults} بالغ / {t.capacity_children} طفل</td>
                <td className="text-[12px]">{t.beds || '—'}</td>
                <td className="text-[11px] text-slate-500 max-w-[140px] truncate">{(t.amenities ?? []).join('، ') || '—'}</td>
                <td className="num font-bold">{fmt(t.base_rate)}</td>
                <td>{t.is_active ? '✅' : '⛔'}</td>
                <td>{canManage && <Btn kind="ghost" onClick={() => setEditFor(t)}>تعديل</Btn>}</td>
              </tr>))}
          </tbody>
        </table>
      </div>
    </Card>
    {editFor && <TypeEditModal t={editFor} onClose={() => setEditFor(null)}
      run={run} busy={busy} />}
  </>)
}

function TypeEditModal({ t, onClose, run, busy }: {
  t: RoomType; onClose: () => void; run: Run; busy: boolean
}) {
  const [f, setF] = useState({
    name_ar: t.name_ar, base_rate: t.base_rate, beds: t.beds,
    capacity_adults: t.capacity_adults, capacity_children: t.capacity_children,
    amenities: (t.amenities ?? []).join(', '), is_active: t.is_active,
  })
  return (
    <Modal title={`تعديل النوع ${t.code}`} onClose={onClose}>
      <div className="grid grid-cols-2 gap-3">
        <label className={label}>الاسم
          <input className={input} value={f.name_ar}
                 onChange={(e) => setF({ ...f, name_ar: e.target.value })} /></label>
        <label className={label}>سعر الليلة الأساسي
          <input className={input} type="number" min={0} step="0.01" value={f.base_rate}
                 onChange={(e) => setF({ ...f, base_rate: e.target.value })} /></label>
        <label className={label}>الأسرّة
          <input className={input} value={f.beds}
                 onChange={(e) => setF({ ...f, beds: e.target.value })} /></label>
        <label className={label}>سعة بالغين/أطفال
          <div className="flex gap-1">
            <input className={input} type="number" min={1} value={f.capacity_adults}
                   onChange={(e) => setF({ ...f, capacity_adults: Number(e.target.value) })} />
            <input className={input} type="number" min={0} value={f.capacity_children}
                   onChange={(e) => setF({ ...f, capacity_children: Number(e.target.value) })} />
          </div></label>
        <label className={`${label} col-span-2`}>مرافق (فاصلة)
          <input className={input} value={f.amenities}
                 onChange={(e) => setF({ ...f, amenities: e.target.value })} /></label>
        <label className="flex items-center gap-2 text-sm col-span-2">
          <input type="checkbox" checked={f.is_active}
                 onChange={(e) => setF({ ...f, is_active: e.target.checked })} />
          نوع نشط في البيع (إيقافه يمنع حجوزاته الجديدة فقط — التاريخ محفوظ)</label>
      </div>
      <div className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2 mt-3">
        ⚠ تغيير سعر الأساس ينعكس على الحجوزات الجديدة فوراً — الليالي المحجوزة
        سابقاً تبقى بصورتها (Snapshot) لا تتغير أبداً، وكل تعديل يوثَّق بالتدقيق.
      </div>
      <div className="flex gap-2 mt-4">
        <Btn disabled={busy} onClick={() => run(() => roomsApi.updateType(t.id, {
          name_ar: f.name_ar, base_rate: f.base_rate, beds: f.beds,
          capacity_adults: Number(f.capacity_adults),
          capacity_children: Number(f.capacity_children),
          amenities: f.amenities ? f.amenities.split(',').map((x) => x.trim()).filter(Boolean) : [],
          is_active: f.is_active,
        }), `عُدّل النوع ${t.code} ✔`).then(onClose)}>حفظ</Btn>
        <Btn kind="ghost" onClick={onClose}>إلغاء</Btn>
      </div>
    </Modal>
  )
}

/* ──────────────────── تبويب خطط الأسعار ──────────────────── */
function PlansTab({ plans, canManage, busy, run }: {
  plans: RatePlan[]; canManage: boolean; busy: boolean; run: Run
}) {
  const [form, setForm] = useState({
    code: '', name_ar: '', ref_rate: '', includes_breakfast: false,
    cancel_policy: 'مرن', min_nights: 1, for_corporate: false,
  })
  const [editFor, setEditFor] = useState<RatePlan | null>(null)
  return (<>
    {canManage && (
      <Card title="➕ خطة سعر جديدة (سعر الليلة = أساس النوع + السعر المرجعي)">
        <form className="grid grid-cols-2 md:grid-cols-4 gap-2 items-end"
              onSubmit={(e) => { e.preventDefault(); run(() => roomsApi.createPlan({
                code: form.code.trim().toUpperCase(), name_ar: form.name_ar,
                ref_rate: form.ref_rate || null,
                includes_breakfast: form.includes_breakfast,
                cancel_policy: form.cancel_policy,
                min_nights: Number(form.min_nights),
                for_corporate: form.for_corporate,
              }), `أُضيفت الخطة ${form.code} ✔`) }}>
          <label className={label}>الكود
            <input className={input} required pattern="[A-Z0-9-]+" value={form.code}
                   onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="HB" /></label>
          <label className={label}>الاسم
            <input className={input} required value={form.name_ar}
                   onChange={(e) => setForm({ ...form, name_ar: e.target.value })} placeholder="نصف إقامة" /></label>
          <label className={label}>المرجع الإضافي/ليلة (اختياري)
            <input className={input} type="number" min={0} step="0.01" value={form.ref_rate}
                   onChange={(e) => setForm({ ...form, ref_rate: e.target.value })} /></label>
          <label className={label}>أدنى ليالٍ
            <input className={input} type="number" min={1} max={90} value={form.min_nights}
                   onChange={(e) => setForm({ ...form, min_nights: Number(e.target.value) })} /></label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.includes_breakfast}
                   onChange={(e) => setForm({ ...form, includes_breakfast: e.target.checked })} />
            يشمل الإفطار</label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.for_corporate}
                   onChange={(e) => setForm({ ...form, for_corporate: e.target.checked })} />
            للشركات فقط</label>
          <label className="col-span-2 text-xs text-slate-500">سياسة الإلغاء
            <input className={input} value={form.cancel_policy}
                   onChange={(e) => setForm({ ...form, cancel_policy: e.target.value })} /></label>
          <Btn disabled={busy} type="submit">إضافة</Btn>
        </form>
      </Card>
    )}
    <Card title={`خطط الأسعار (${plans.length})`}>
      <table className="w-full text-sm">
        <thead><tr className="text-right text-slate-400 text-xs border-b">
          <th className="py-2">الكود</th><th>الاسم</th><th>مرجع/ليلة</th>
          <th>إفطار</th><th>أدنى ليالٍ</th><th>سياسة الإلغاء</th><th>نشطة</th><th></th></tr></thead>
        <tbody>
          {plans.map((p) => (
            <tr key={p.id} className="border-b hover:bg-slate-50">
              <td className="py-2 font-mono font-bold">{p.code}</td>
              <td>{p.name_ar}{p.for_corporate && <Badge tone="gold"> شركات</Badge>}</td>
              <td className="num">{p.ref_rate ? `+${fmt(p.ref_rate)}` : 'أساس النوع'}</td>
              <td>{p.includes_breakfast ? '🍳' : '—'}</td>
              <td className="num">{p.min_nights}</td>
              <td className="text-[11px] max-w-[180px] truncate">{p.cancel_policy}</td>
              <td>{p.is_active ? '✅' : '⛔'}</td>
              <td>{canManage && <Btn kind="ghost" onClick={() => setEditFor(p)}>تعديل</Btn>}</td>
            </tr>))}
        </tbody>
      </table>
    </Card>
    {editFor && <PlanEditModal p={editFor} onClose={() => setEditFor(null)}
      run={run} busy={busy} />}
  </>)
}

function PlanEditModal({ p, onClose, run, busy }: {
  p: RatePlan; onClose: () => void; run: Run; busy: boolean
}) {
  const [f, setF] = useState({
    name_ar: p.name_ar, ref_rate: p.ref_rate ?? '',
    includes_breakfast: p.includes_breakfast,
    cancel_policy: p.cancel_policy, min_nights: p.min_nights,
    for_corporate: p.for_corporate, is_active: p.is_active,
  })
  return (
    <Modal title={`تعديل الخطة ${p.code}`} onClose={onClose}>
      <div className="grid grid-cols-2 gap-3">
        <label className={label}>الاسم
          <input className={input} value={f.name_ar}
                 onChange={(e) => setF({ ...f, name_ar: e.target.value })} /></label>
        <label className={label}>المرجع الإضافي/ليلة
          <input className={input} type="number" min={0} step="0.01" value={f.ref_rate}
                 onChange={(e) => setF({ ...f, ref_rate: e.target.value })} /></label>
        <label className={label}>أدنى ليالٍ
          <input className={input} type="number" min={1} max={90} value={f.min_nights}
                 onChange={(e) => setF({ ...f, min_nights: Number(e.target.value) })} /></label>
        <label className={label}>سياسة الإلغاء
          <input className={input} value={f.cancel_policy}
                 onChange={(e) => setF({ ...f, cancel_policy: e.target.value })} /></label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.includes_breakfast}
                 onChange={(e) => setF({ ...f, includes_breakfast: e.target.checked })} />
          يشمل الإفطار</label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.is_active}
                 onChange={(e) => setF({ ...f, is_active: e.target.checked })} />
          خطة نشطة</label>
      </div>
      <div className="flex gap-2 mt-4">
        <Btn disabled={busy} onClick={() => run(() => roomsApi.updatePlan(p.id, {
          name_ar: f.name_ar, ref_rate: f.ref_rate || null,
          includes_breakfast: f.includes_breakfast,
          cancel_policy: f.cancel_policy, min_nights: Number(f.min_nights),
          for_corporate: f.for_corporate, is_active: f.is_active,
        }), `عُدّلت الخطة ${p.code} ✔`).then(onClose)}>حفظ</Btn>
        <Btn kind="ghost" onClick={onClose}>إلغاء</Btn>
      </div>
    </Modal>
  )
}

/* ──────────────────── تبويب تقويم الأسعار ──────────────────── */
function CalendarTab({ types, plans, rows, setRows, canManage, busy, run }: {
  types: RoomType[]; plans: RatePlan[]; rows: CalendarEntry[]
  setRows: (r: CalendarEntry[]) => void
  canManage: boolean; busy: boolean; run: Run
}) {
  const today = new Date().toISOString().slice(0, 10)
  const [q, setQ] = useState({ room_type: types[0]?.code ?? '', from: today,
    to: new Date(Date.now() + 30 * 864e5).toISOString().slice(0, 10) })
  const [f, setF] = useState({ room_type: types[0]?.code ?? '', rate_plan: '',
    from: today, to: today, price: '', day_type: 'NORMAL' })

  async function refresh() {
    setRows(await roomsApi.calendar(q.room_type, q.from, q.to))
  }
  useEffect(() => { refresh().catch(() => {}) }, [q.room_type, q.from, q.to]) // eslint-disable-line

  return (<>
    {canManage && (
      <Card title="➕ تعبئة سعر مدى (نفس المفتاح يُحدَّث بلا تكرار — Upsert)">
        <form className="grid grid-cols-2 md:grid-cols-6 gap-2 items-end"
              onSubmit={(e) => { e.preventDefault(); run(async () => {
                const r = await roomsApi.calendarBulk({
                  room_type_code: f.room_type, rate_plan_code: f.rate_plan || null,
                  date_from: f.from, date_to: f.to, price: f.price,
                  day_type: f.day_type,
                })
                await refresh()
                return r
              }, (r) => {
                const x = r as { days: number; created: number; updated: number }
                return `غُطي ${x.days} يوماً (${x.created} جديد + ${x.updated} تحديث) ✔`
              }) }}>
            <label className={label}>نوع الغرفة
              <select className={input} value={f.room_type}
                      onChange={(e) => setF({ ...f, room_type: e.target.value })}>
                {types.map((t) => <option key={t.code} value={t.code}>{t.name_ar}</option>)}
              </select></label>
            <label className={label}>خطة السعر
              <select className={input} value={f.rate_plan}
                      onChange={(e) => setF({ ...f, rate_plan: e.target.value })}>
                <option value="">الافتراضي (بدون خطة)</option>
                {plans.map((p) => <option key={p.code} value={p.code}>{p.name_ar}</option>)}
              </select></label>
            <label className={label}>من
              <input className={input} type="date" value={f.from}
                     onChange={(e) => setF({ ...f, from: e.target.value })} /></label>
            <label className={label}>إلى
              <input className={input} type="date" value={f.to}
                     onChange={(e) => setF({ ...f, to: e.target.value })} /></label>
            <label className={label}>سعر الليلة
              <input className={input} required type="number" min="0.01" step="0.01"
                     value={f.price}
                     onChange={(e) => setF({ ...f, price: e.target.value })} /></label>
            <label className={label}>نوع اليوم
              <select className={input} value={f.day_type}
                      onChange={(e) => setF({ ...f, day_type: e.target.value })}>
                {DAY_TYPES.map((d) => <option key={d.c} value={d.c}>{d.n}</option>)}
              </select></label>
            <Btn disabled={busy} type="submit">تعبئة ≤ 92 يوماً</Btn>
          </form>
      </Card>
    )}
    <Card title="استعراض التقويم">
      <div className="grid grid-cols-3 gap-2 mb-3">
        <label className={label}>النوع
          <select className={input} value={q.room_type}
                  onChange={(e) => setQ({ ...q, room_type: e.target.value })}>
            {types.map((t) => <option key={t.code} value={t.code}>{t.name_ar}</option>)}
          </select></label>
        <label className={label}>من
          <input className={input} type="date" value={q.from}
                 onChange={(e) => setQ({ ...q, from: e.target.value })} /></label>
        <label className={label}>إلى
          <input className={input} type="date" value={q.to}
                 onChange={(e) => setQ({ ...q, to: e.target.value })} /></label>
      </div>
      {rows.length === 0
        ? <div className="text-sm text-slate-400 py-6 text-center">
            لا أسعار مخصصة بهذا المدى — يسري سعر الأساس/الخطة تلقائياً</div>
        : <table className="w-full text-sm">
            <thead><tr className="text-right text-slate-400 text-xs border-b">
              <th className="py-2">اليوم</th><th>السعر</th><th>النوع</th>
              <th>الخطة</th><th></th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b hover:bg-slate-50">
                  <td className="py-1.5 num">{r.day}</td>
                  <td className="num font-bold">{fmt(r.price)}</td>
                  <td><Badge tone="slate">{DAY_TYPES.find((d) => d.c === r.day_type)?.n ?? r.day_type}</Badge></td>
                  <td>{r.rate_plan ?? <span className="text-slate-400">افتراضي</span>}</td>
                  <td>{canManage &&
                    <Btn kind="danger" onClick={() =>
                      run(async () => {
                        await roomsApi.deleteCalendar(r.id); await refresh() },
                        'حُذف قيد التقويم ✔')}>حذف</Btn>}</td>
                </tr>))}
            </tbody>
          </table>}
    </Card>
  </>)
}

/* ──────────────────── تبويب الخدمات ──────────────────── */
function ExtrasTab({ extras, canManage, busy, run }: {
  extras: ExtraFull[]; canManage: boolean; busy: boolean; run: Run
}) {
  const [form, setForm] = useState({
    code: '', name_ar: '', price: '', revenue_account_code: '4901',
  })
  const [editFor, setEditFor] = useState<ExtraFull | null>(null)
  return (<>
    {canManage && (
      <Card title="➕ خدمة إضافية (تُشحن على الفوليو لحساب إيرادها)">
        <form className="grid grid-cols-2 md:grid-cols-5 gap-2 items-end"
              onSubmit={(e) => { e.preventDefault(); run(() => roomsApi.createExtra({
                code: form.code.trim().toUpperCase(), name_ar: form.name_ar,
                price: form.price, revenue_account_code: form.revenue_account_code,
              }), `أُضيفت الخدمة ${form.code} ✔`) }}>
          <label className={label}>الكود
            <input className={input} required pattern="[A-Z0-9_-]+" value={form.code}
                   onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="MASSAGE" /></label>
          <label className={label}>الاسم
            <input className={input} required value={form.name_ar}
                   onChange={(e) => setForm({ ...form, name_ar: e.target.value })} placeholder="مساج" /></label>
          <label className={label}>السعر
            <input className={input} required type="number" min="0" step="0.01"
                   value={form.price}
                   onChange={(e) => setForm({ ...form, price: e.target.value })} /></label>
          <label className={label}>حساب الإيراد
            <input className={input} required value={form.revenue_account_code}
                   onChange={(e) => setForm({ ...form, revenue_account_code: e.target.value })} /></label>
          <Btn disabled={busy} type="submit">إضافة</Btn>
        </form>
      </Card>
    )}
    <Card title={`الخدمات الإضافية (${extras.length})`}>
      <table className="w-full text-sm">
        <thead><tr className="text-right text-slate-400 text-xs border-b">
          <th className="py-2">الكود</th><th>الاسم</th><th>السعر</th>
          <th>حساب الإيراد</th><th>نشطة</th><th></th></tr></thead>
        <tbody>
          {extras.map((x) => (
            <tr key={x.id} className="border-b hover:bg-slate-50">
              <td className="py-2 font-mono font-bold">{x.code}</td>
              <td>{x.name_ar}</td>
              <td className="num font-bold">{fmt(x.price)}</td>
              <td className="num">{x.revenue_account_code}</td>
              <td>{x.is_active ? '✅' : '⛔'}</td>
              <td>{canManage && <Btn kind="ghost" onClick={() => setEditFor(x)}>تعديل</Btn>}</td>
            </tr>))}
        </tbody>
      </table>
    </Card>
    {editFor && <ExtraEditModal x={editFor} onClose={() => setEditFor(null)}
      run={run} busy={busy} />}
  </>)
}

function ExtraEditModal({ x, onClose, run, busy }: {
  x: ExtraFull; onClose: () => void; run: Run; busy: boolean
}) {
  const [f, setF] = useState({
    name_ar: x.name_ar, price: x.price,
    revenue_account_code: x.revenue_account_code, is_active: x.is_active,
  })
  return (
    <Modal title={`تعديل الخدمة ${x.code}`} onClose={onClose}>
      <div className="grid grid-cols-2 gap-3">
        <label className={label}>الاسم
          <input className={input} value={f.name_ar}
                 onChange={(e) => setF({ ...f, name_ar: e.target.value })} /></label>
        <label className={label}>السعر
          <input className={input} type="number" min="0" step="0.01" value={f.price}
                 onChange={(e) => setF({ ...f, price: e.target.value })} /></label>
        <label className={label}>حساب الإيراد
          <input className={input} value={f.revenue_account_code}
                 onChange={(e) => setF({ ...f, revenue_account_code: e.target.value })} /></label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.is_active}
                 onChange={(e) => setF({ ...f, is_active: e.target.checked })} />
          خدمة نشطة</label>
      </div>
      <div className="flex gap-2 mt-4">
        <Btn disabled={busy} onClick={() => run(() => roomsApi.updateExtra(x.id, {
          name_ar: f.name_ar, price: f.price,
          revenue_account_code: f.revenue_account_code, is_active: f.is_active,
        }), `عُدّلت الخدمة ${x.code} ✔`).then(onClose)}>حفظ</Btn>
        <Btn kind="ghost" onClick={onClose}>إلغاء</Btn>
      </div>
    </Modal>
  )
}
