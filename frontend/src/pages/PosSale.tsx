// شاشة البيع اللمسية — ملف 04 §1: شبكة أصناف، تصنيفات ملونة، بحث F2،
// تسديد F9، بيعة نقدية ≤ 15 ثانية، وطابور محلي آمن يمنع فقدان فواتير
// عند انقطاع الشبكة (قبول #4) — إعادة الإرسال آمنة بـ client_uuid.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, fmt } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import type { Category, Invoice, Item, Modifier, OccupiedRoom, Outlet,
              PosOrder, Table } from '../pos'
import { posApi } from '../pos'
import type { SettlePayment } from '../pos'

interface CartLine {
  item: Item
  qty: number
  modifiers: Modifier[]
  notes: string
  discount: number
}

interface OutboxRec {
  client_uuid: string; outlet_id: string; type: string
  table_id?: string | null
  lines: { item_id: string; qty: number; modifiers: { id: string }[];
           notes: string; discount: number }[]
  payments: SettlePayment[]; invoice_discount: number
  discount_reason: string; approver_pin: string
  created_at: string
}

const OUTBOX_KEY = 'pos.outbox.v1'
const loadOutbox = (): OutboxRec[] => {
  try { return JSON.parse(localStorage.getItem(OUTBOX_KEY) || '[]') } catch { return [] }
}
const saveOutbox = (r: OutboxRec[]) => localStorage.setItem(OUTBOX_KEY, JSON.stringify(r))

export default function PosSale() {
  const { has } = useAuth()
  const [outlets, setOutlets] = useState<Outlet[]>([])
  const [outlet, setOutlet] = useState<Outlet | null>(null)
  const [shiftId, setShiftId] = useState<string | null>(null)
  const [floatInput, setFloatInput] = useState('50')
  const [cats, setCats] = useState<Category[]>([])
  const [items, setItems] = useState<Item[]>([])
  const [activeCat, setActiveCat] = useState('')
  const [search, setSearch] = useState('')
  const [cart, setCart] = useState<CartLine[]>([])
  const [orderType, setOrderType] = useState<'TAKEAWAY' | 'DINE_IN' | 'ROOM_SERVICE'>('TAKEAWAY')
  const [tables, setTables] = useState<Table[]>([])
  const [tableId, setTableId] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [modFor, setModFor] = useState<Item | null>(null)
  const [availMods, setAvailMods] = useState<Modifier[]>([])
  const [payOpen, setPayOpen] = useState(false)
  const [receipt, setReceipt] = useState<Invoice | null>(null)
  const [outbox, setOutbox] = useState<OutboxRec[]>(loadOutbox())
  const [online, setOnline] = useState(navigator.onLine)
  const [openOrders, setOpenOrders] = useState<PosOrder[]>([])
  const searchRef = useRef<HTMLInputElement>(null)

  const cartTotal = useMemo(
    () => cart.reduce((s, l) => s + (parseFloat(l.item.price) + l.modifiers.reduce((a, m) => a + parseFloat(m.price), 0)) * l.qty - l.discount, 0),
    [cart])

  const refreshBasics = useCallback(async () => {
    const os = await posApi.outlets()
    setOutlets(os)
    if (!outlet && os.length) setOutlet(os[0])
    const cs = await posApi.categories()
    setCats(cs)
  }, [outlet])

  const refreshItems = useCallback(async () => {
    const r = await posApi.items(search, activeCat, 400)
    setItems(r.items)
  }, [search, activeCat])

  const refreshShift = useCallback(async () => {
    if (!outlet) return
    const sh = await posApi.shifts(outlet.id, 'OPEN')
    setShiftId(sh.length ? sh[0].id : null)
    const tb = await posApi.tables(outlet.id).catch(() => [] as Table[])
    setTables(tb)
    const oo = await posApi.orders('', '').catch(() => [] as PosOrder[])
    setOpenOrders(oo.filter((o) => (o.status === 'DRAFT' || o.status === 'FIRED') && o.outlet_id === outlet.id))
  }, [outlet])

  useEffect(() => { refreshBasics().catch((e) => setErr(e.message)) }, []) // eslint-disable-line
  useEffect(() => { refreshItems().catch(() => undefined) }, [refreshItems])
  useEffect(() => { refreshShift().catch(() => undefined) }, [refreshShift])

  // مراقبة حالة الشبكة + المزامنة التلقائية للطابور المحلي (قبول #4)
  useEffect(() => {
    const up = () => setOnline(true)
    const down = () => setOnline(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    return () => { window.removeEventListener('online', up); window.removeEventListener('offline', down) }
  }, [])

  const syncOutbox = useCallback(async () => {
    const queue = loadOutbox()
    if (!queue.length || !navigator.onLine) return
    const remain: OutboxRec[] = []
    let synced = 0
    for (const rec of queue) {
      try {
        const o = await posApi.createOrder({ outlet_id: rec.outlet_id, type: rec.type, table_id: rec.table_id ?? null })
        for (const ln of rec.lines) {
          await posApi.addLine(o.id, { item_id: ln.item_id, qty: ln.qty, modifiers: ln.modifiers, notes: ln.notes, discount: ln.discount })
        }
        const r = await posApi.settle(o.id, {
          client_uuid: rec.client_uuid, payments: rec.payments,
          invoice_discount: rec.invoice_discount,
          discount_reason: rec.discount_reason, approver_pin: rec.approver_pin,
        })
        synced++
        void r
      } catch (e) {
        // خطأ شبكة: أبقه بالطابور؛ خطأ منطقي (رفض تحقق): أبقه أيضاً لمراجعة الكاشير
        remain.push(rec)
        void e
      }
    }
    saveOutbox(remain)
    setOutbox(remain)
    if (synced) setOk(`تمت مزامنة ${synced} فاتورة معلقة بنجاح — لا فقدان`)
  }, [])

  useEffect(() => {
    const t = setInterval(() => { syncOutbox().catch(() => undefined) }, 8000)
    return () => clearInterval(t)
  }, [syncOutbox])
  useEffect(() => { if (online) { syncOutbox().catch(() => undefined) } }, [online, syncOutbox])

  // لوحة المفاتيح: F2 بحث — F9 تسديد (§1: تعمل بلوحة مفاتيح بالكامل)
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'F2') { e.preventDefault(); searchRef.current?.focus() }
      if (e.key === 'F9') { e.preventDefault(); if (cart.length && shiftId) setPayOpen(true) }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [cart.length, shiftId])

  const addItem = async (it: Item) => {
    setErr(null)
    try {
      const mods = await posApi.itemModifiers(it.id)
      if (mods.length) {
        setModFor(it); setAvailMods(mods)
        return
      }
      pushLine(it, [])
    } catch { pushLine(it, []) }
  }

  const pushLine = (it: Item, mods: Modifier[]) => {
    setCart((c) => {
      const ix = c.findIndex((l) => l.item.id === it.id
        && JSON.stringify(l.modifiers.map((m) => m.id)) === JSON.stringify(mods.map((m) => m.id))
        && !l.notes && l.discount === 0)
      if (ix >= 0) {
        const n = [...c]; n[ix] = { ...n[ix], qty: n[ix].qty + 1 }; return n
      }
      return [...c, { item: it, qty: 1, modifiers: mods, notes: '', discount: 0 }]
    })
    setModFor(null)
  }

  const changeQty = (ix: number, d: number) =>
    setCart((c) => c.map((l, i) => i === ix ? { ...l, qty: Math.max(1, l.qty + d) } : l))
  const removeLine = (ix: number) => setCart((c) => c.filter((_, i) => i !== ix))

  // بحث الباركود: مطابقة كاملة تضيف فوراً (تدفق ماسحة الباركود)
  const onSearchKey = (e: React.KeyboardEvent) => {
    if (e.key !== 'Enter') return
    const exact = items.find((i) => i.barcode === search.trim())
    if (exact) { addItem(exact); setSearch('') }
  }

  const openShift = async () => {
    if (!outlet) return
    setBusy(true); setErr(null)
    try {
      await posApi.openShift(outlet.id, parseFloat(floatInput || '0'))
      await refreshShift()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  // تثبيت السلة على الخادم: طلب مسودة ← إضافة البنود
  const persistOrder = async (): Promise<string> => {
    if (!outlet) throw new Error('لا منفذ')
    const o = await posApi.createOrder({
      outlet_id: outlet.id, type: orderType,
      table_id: orderType === 'DINE_IN' ? tableId : null,
    })
    for (const l of cart) {
      await posApi.addLine(o.id, {
        item_id: l.item.id, qty: l.qty,
        modifiers: l.modifiers.map((m) => ({ id: m.id })),
        notes: l.notes, discount: l.discount,
      })
    }
    return o.id
  }

  const fireAndKeep = async () => {
    setBusy(true); setErr(null)
    try {
      const oid = await persistOrder()
      await posApi.fire(oid)
      setOk('أُرسل الطلب للتحضير — يظهر الآن في لوحة الطلبات')
      setCart([]); setTableId(null)
      await refreshShift()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  const queueOffline = (rec: OutboxRec) => {
    const n = [...loadOutbox(), rec]
    saveOutbox(n); setOutbox(n)
    setCart([]); setPayOpen(false)
    setOk(`انقطعت الشبكة — حُفظت الفاتورة محلياً بأمان وستُرحَّل تلقائياً فور عودة الاتصال (${rec.client_uuid.slice(0, 12)}…)`)
  }

  if (!outlets.length) return <Spinner />

  return (
    <div className="flex flex-col h-[calc(100vh-64px)]">
      {/* شريط الحالة العلوي */}
      <div className="flex items-center gap-3 px-4 py-2 bg-white border-b border-slate-200 flex-wrap">
        <select className="border rounded-lg px-3 py-1.5 text-sm"
          value={outlet?.id || ''}
          onChange={(e) => setOutlet(outlets.find((o) => o.id === e.target.value) || null)}>
          {outlets.map((o) => <option key={o.id} value={o.id}>{o.name_ar}</option>)}
        </select>
        <div className="flex gap-1">
          {(['TAKEAWAY', 'DINE_IN', 'ROOM_SERVICE'] as const).map((t) => (
            <button key={t} onClick={() => setOrderType(t)}
              className={`px-3 py-1.5 rounded-lg text-sm border ${orderType === t ? 'bg-sijill-700 text-white border-sijill-700' : 'border-slate-300 text-slate-600'}`}>
              {t === 'TAKEAWAY' ? 'سفري' : t === 'DINE_IN' ? 'صالة' : 'خدمة غرف'}
            </button>
          ))}
        </div>
        {shiftId
          ? <Badge tone="green">وردية مفتوحة</Badge>
          : <Badge tone="red">لا وردية — البيع متوقف</Badge>}
        {!online && <Badge tone="amber">وضع أوفلاين — البيع مستمر محلياً</Badge>}
        {outbox.length > 0 && (
          <button onClick={() => syncOutbox()} className="text-xs bg-amber-100 text-amber-800 border border-amber-300 rounded-full px-3 py-1">
            طابور معلق: {outbox.length} فاتورة — مزامنة الآن
          </button>
        )}
        <div className="mr-auto text-xs text-slate-400">F2 بحث • F9 تسديد</div>
      </div>

      {!shiftId && (
        <div className="p-4">
          <Card title="فتح وردية جديدة" actions={null}>
            <div className="flex items-end gap-3">
              <label className="text-sm">عهدة الافتتاح النقدية
                <input className="border rounded-lg px-3 py-2 mt-1 w-40" value={floatInput}
                  onChange={(e) => setFloatInput(e.target.value)} inputMode="decimal" />
              </label>
              <Btn onClick={openShift} disabled={busy}>{busy ? '…' : 'فتح الوردية'}</Btn>
            </div>
            <ErrorNote msg={err} />
          </Card>
        </div>
      )}

      {shiftId && (
        <div className="flex flex-1 min-h-0">
          {/* السلة + التسديد */}
          <div className="w-[380px] shrink-0 border-l border-slate-200 bg-white flex flex-col">
            {orderType === 'DINE_IN' && (
              <div className="p-3 border-b border-slate-100">
                <div className="text-xs text-slate-500 mb-1">الطاولة</div>
                <div className="flex flex-wrap gap-1.5">
                  {tables.map((t) => (
                    <button key={t.id} onClick={() => !t.occupied && setTableId(t.id)}
                      disabled={t.occupied}
                      className={`px-2.5 py-1 rounded-lg text-xs border ${tableId === t.id ? 'bg-sijill-700 text-white' : t.occupied ? 'bg-red-50 text-red-400 border-red-200 cursor-not-allowed' : 'border-slate-300'}`}>
                      {t.name}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {cart.length === 0 && (
                <div className="text-center text-slate-400 text-sm py-10">
                  السلة فارغة — اختر الأصناف من الشبكة
                </div>
              )}
              {cart.map((l, ix) => {
                const unit = parseFloat(l.item.price) + l.modifiers.reduce((a, m) => a + parseFloat(m.price), 0)
                return (
                  <div key={ix} className="border border-slate-200 rounded-xl p-2.5">
                    <div className="flex justify-between items-start">
                      <div className="font-bold text-sm">{l.item.name_ar}</div>
                      <button onClick={() => removeLine(ix)} className="text-red-400 hover:text-red-600 text-lg leading-none">×</button>
                    </div>
                    {l.modifiers.length > 0 && (
                      <div className="text-[11px] text-slate-500 mt-0.5">
                        {l.modifiers.map((m) => `${m.name_ar}${parseFloat(m.price) ? ` +${m.price}` : ''}`).join('، ')}
                      </div>
                    )}
                    <div className="flex items-center justify-between mt-1.5">
                      <div className="flex items-center gap-2">
                        <button onClick={() => changeQty(ix, -1)} className="w-7 h-7 rounded-lg bg-slate-100 hover:bg-slate-200 font-bold">−</button>
                        <span className="w-8 text-center font-bold">{l.qty}</span>
                        <button onClick={() => changeQty(ix, 1)} className="w-7 h-7 rounded-lg bg-slate-100 hover:bg-slate-200 font-bold">+</button>
                      </div>
                      <div className="font-bold text-sijill-800">{fmt(unit * l.qty - l.discount)}</div>
                    </div>
                  </div>
                )
              })}
            </div>
            <div className="border-t border-slate-200 p-3 space-y-2">
              <div className="flex justify-between text-lg font-black">
                <span>الإجمالي</span><span className="text-sijill-800">{fmt(cartTotal)}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Btn kind="ghost" onClick={fireAndKeep} disabled={busy || !cart.length || (orderType === 'DINE_IN' && !tableId)}>
                  إرسال للتحضير
                </Btn>
                <Btn onClick={() => setPayOpen(true)} disabled={busy || !cart.length}>
                  تسديد (F9)
                </Btn>
              </div>
              <ErrorNote msg={err} />
              <OkNote msg={ok} />
            </div>
          </div>

          {/* التصنيفات والأصناف */}
          <div className="flex-1 flex flex-col min-w-0">
            <div className="p-3 flex gap-2 items-center bg-white border-b border-slate-100">
              <input ref={searchRef} dir="rtl" placeholder="بحث بالاسم/الكود/الباركود… (F2)"
                className="border rounded-xl px-4 py-2 w-80 text-sm"
                value={search} onChange={(e) => setSearch(e.target.value)}
                onKeyDown={onSearchKey} />
              <button onClick={() => setActiveCat('')}
                className={`px-3 py-1.5 rounded-full text-xs border ${!activeCat ? 'bg-slate-800 text-white' : 'border-slate-300'}`}>
                الكل
              </button>
              <div className="flex gap-1.5 overflow-x-auto">
                {cats.map((c) => (
                  <button key={c.id} onClick={() => setActiveCat(activeCat === c.id ? '' : c.id)}
                    style={{ borderColor: c.color, background: activeCat === c.id ? c.color : 'transparent', color: activeCat === c.id ? 'white' : c.color }}
                    className="px-3 py-1.5 rounded-full text-xs border whitespace-nowrap">
                    {c.name_ar}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-3">
              <div className="grid grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2.5">
                {items.map((it) => {
                  const cat = cats.find((c) => c.id === it.category_id)
                  return (
                    <button key={it.id} onClick={() => addItem(it)}
                      className="bg-white border border-slate-200 rounded-2xl p-3 text-right hover:shadow-md hover:border-sijill-300 transition-all active:scale-95">
                      <div className="h-1.5 rounded-full mb-2" style={{ background: cat?.color || '#94a3b8' }} />
                      <div className="font-bold text-sm leading-5 min-h-10">{it.name_ar}</div>
                      <div className="flex items-center justify-between mt-2">
                        <span className="text-sijill-800 font-black">{fmt(it.price)}</span>
                        {it.item_type !== 'SERVICE' && (
                          <span className={`text-[10px] px-1.5 py-0.5 rounded ${it.item_type === 'STOCK' ? 'bg-sky-50 text-sky-700' : 'bg-violet-50 text-violet-700'}`}>
                            {it.item_type === 'STOCK' ? 'مخزوني' : 'مركّب'}
                          </span>
                        )}
                      </div>
                    </button>
                  )
                })}
              </div>
              {!items.length && <div className="text-center text-slate-400 py-10">لا أصناف مطابقة</div>}
            </div>
          </div>
        </div>
      )}

      {/* نافذة المعدلات */}
      {modFor && (
        <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center" onClick={() => setModFor(null)}>
          <div className="bg-white rounded-2xl p-5 w-96 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="font-black mb-1">{modFor.name_ar}</div>
            <div className="text-xs text-slate-500 mb-3">اختر الإضافات ثم أضِف</div>
            <div className="space-y-1.5 max-h-72 overflow-y-auto">
              {availMods.map((md) => (
                <button key={md.id}
                  onClick={() => pushLine(modFor, [md])}
                  className="w-full flex justify-between items-center border border-slate-200 rounded-xl px-3 py-2 hover:bg-sijill-50 text-sm">
                  <span>{md.name_ar}</span>
                  <span className="font-bold text-sijill-800">{parseFloat(md.price) ? fmt(md.price) : 'مجاناً'}</span>
                </button>
              ))}
            </div>
            <div className="flex gap-2 mt-4">
              <Btn kind="ghost" onClick={() => pushLine(modFor, [])}>بدون إضافات</Btn>
              <Btn kind="ghost" onClick={() => setModFor(null)}>إلغاء</Btn>
            </div>
          </div>
        </div>
      )}

      {/* نافذة التسديد */}
      {payOpen && outlet && (
        <SettleModal
          total={cartTotal}
          cartLines={cart.length}
          rawLines={cart.map((l) => ({
            item_id: l.item.id, qty: l.qty,
            modifiers: l.modifiers.map((m) => ({ id: m.id })),
            notes: l.notes, discount: l.discount,
          }))}
          orderType={orderType}
          tableId={tableId}
          onCancel={() => setPayOpen(false)}
          onDone={(inv) => { setPayOpen(false); setCart([]); setTableId(null); setReceipt(inv.invoice) }}
          outbox={(rec) => queueOffline(rec)}
          outlet={outlet}
          persistOrder={persistOrder}
          hasApprove={has('pos.approve')}
        />
      )}

      {/* إيصال حراري */}
      {receipt && (
        <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center" onClick={() => setReceipt(null)}>
          <div className="bg-white rounded-2xl p-6 w-[340px] shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div dir="rtl" className="receipt-print text-center text-xs font-mono">
              <div className="text-base font-black mb-1">{receipt.outlet}</div>
              <div className="border-t border-dashed border-slate-400 my-2" />
              <div>فاتورة {receipt.invoice_no} — {receipt.business_date}</div>
              <div>الكاشير: {receipt.issued_by}</div>
              <div className="border-t border-dashed border-slate-400 my-2" />
              {(receipt.lines || []).map((l, i) => (
                <div key={i} className="flex justify-between text-right py-0.5">
                  <span>{l.item} ×{l.qty}</span>
                  <span>{fmt(parseFloat(l.total) - parseFloat(l.discount))}</span>
                </div>
              ))}
              <div className="border-t border-dashed border-slate-400 my-2" />
              <div className="flex justify-between font-black text-sm">
                <span>الإجمالي</span><span>{fmt(receipt.net_total)}</span>
              </div>
              {(receipt.payments || []).map((p, i) => (
                <div key={i} className="flex justify-between">
                  <span>{{ CASH: 'نقد', CARD: 'بطاقة', EWALLET: 'محفظة', ROOM: 'على الغرفة', CORPORATE: 'شركة', HOUSE: 'ضيافة' }[p.method as string]}{p.room_no ? ` (${p.room_no})` : ''}</span>
                  <span>{fmt(p.amount)}</span>
                </div>
              ))}
              <div className="border-t border-dashed border-slate-400 my-2" />
              <div>شكراً لزيارتكم — سِجِلّ النُّزُل</div>
            </div>
            <div className="flex gap-2 mt-4 no-print">
              <Btn onClick={() => window.print()}>طباعة</Btn>
              <Btn kind="ghost" onClick={() => setReceipt(null)}>إغلاق</Btn>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── نافذة التسديد: Split بكل الوسائل + غرفة + شركة + مجاني مصرّح ──
function SettleModal({ total, cartLines, rawLines, orderType,
                       tableId, outlet, onCancel, onDone,
                       outbox, persistOrder, hasApprove }: {
  total: number; cartLines: number
  rawLines: OutboxRec['lines']; orderType: string; tableId: string | null
  outlet: Outlet
  onCancel: () => void
  onDone: (r: { invoice: Invoice; replayed: boolean }) => void
  outbox: (rec: OutboxRec) => void
  persistOrder: () => Promise<string>
  hasApprove: boolean
}) {
  const [pays, setPays] = useState<SettlePayment[]>([{ method: 'CASH', amount: total.toFixed(4) }])
  const [rooms, setRooms] = useState<OccupiedRoom[]>([])
  const [corporates, setCorporates] = useState<{ id: string; name: string }[]>([])
  const [disc, setDisc] = useState('0')
  const [discReason, setDiscReason] = useState('')
  const [pin, setPin] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const uuidRef = useRef<string>(crypto.randomUUID())

  const net = total - (parseFloat(disc) || 0)
  const paid = pays.reduce((s, p) => s + (parseFloat(String(p.amount)) || 0), 0)
  const remain = net - paid
  const overCap = (parseFloat(disc) || 0) > 50 && !hasApprove

  useEffect(() => {
    if (pays.some((p) => p.method === 'ROOM')) {
      posApi.occupiedRooms().then(setRooms).catch(() => setRooms([]))
    }
    if (pays.some((p) => p.method === 'CORPORATE')) {
      api<{ id: string; name: string }[]>('/api/hotel/corporates')
        .then((r) => setCorporates(r as unknown as { id: string; name: string }[]))
        .catch(() => setCorporates([]))
    }
  }, [pays.map((p) => p.method).join(',')]) // eslint-disable-line

  const setPay = (ix: number, k: string, v: unknown) =>
    setPays((ps) => ps.map((p, i) => i === ix ? { ...p, [k]: v } : p))

  const submit = async () => {
    setBusy(true); setErr(null)
    try {
      const oid = await persistOrder()
      const body = {
        client_uuid: uuidRef.current,
        payments: pays.map((p) => ({ ...p, amount: String(p.amount) })),
        invoice_discount: parseFloat(disc) || 0,
        discount_reason: discReason, approver_pin: pin,
      }
      const r = await posApi.settle(oid, body)
      onDone(r)
    } catch (e) {
      const msg = (e as Error).message
      // انقطاع شبكة حقيقي (فشل fetch نفسه — لا رد خادم): ادفع للطابور المحلي
      // بكل بنود السلة — لا تُفقد فاتورة واحدة بعد الاستعادة (قبول #4)
      if (!(e as { code?: string }).code) {
        outbox({
          client_uuid: uuidRef.current, outlet_id: outlet.id,
          type: orderType, table_id: orderType === 'DINE_IN' ? tableId : null,
          lines: rawLines, payments: pays,
          invoice_discount: parseFloat(disc) || 0,
          discount_reason: discReason, approver_pin: pin,
          created_at: new Date().toISOString(),
        })
        return
      }
      setErr(msg)
    } finally { setBusy(false) }
  }

  const METHODS = [
    ['CASH', 'نقد', '💵'], ['CARD', 'بطاقة', '💳'], ['EWALLET', 'محفظة', '📱'],
    ['ROOM', 'على الغرفة', '🛏'], ['CORPORATE', 'على شركة', '🏢'], ['HOUSE', 'مجاني مصرّح', '🎁'],
  ] as const

  return (
    <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center" onClick={onCancel}>
      <div className="bg-white rounded-2xl p-6 w-[560px] max-h-[90vh] overflow-y-auto shadow-2xl" onClick={(e) => e.stopPropagation()} dir="rtl">
        <div className="flex justify-between items-center mb-4">
          <div className="font-black text-lg">تسديد الفاتورة — {cartLines} بند</div>
          <div className="text-2xl font-black text-sijill-800">{fmt(net)}</div>
        </div>

        <div className="bg-slate-50 rounded-xl p-3 mb-3">
          <div className="text-xs text-slate-500 mb-1.5">خصم على الفاتورة (فوق 50 يتطلب اعتماد مدير بـ PIN)</div>
          <div className="flex gap-2">
            <input className="border rounded-lg px-3 py-1.5 w-28" value={disc}
              onChange={(e) => setDisc(e.target.value)} inputMode="decimal" placeholder="0" />
            <input className="border rounded-lg px-3 py-1.5 flex-1 text-sm" value={discReason}
              onChange={(e) => setDiscReason(e.target.value)} placeholder={parseFloat(disc) > 0 ? 'سبب الخصم (إلزامي)' : 'سبب الخصم'} />
            {(overCap || pays.some((p) => p.method === 'HOUSE')) && (
              <input className="border border-amber-400 rounded-lg px-3 py-1.5 w-28 text-sm" value={pin}
                type="password" onChange={(e) => setPin(e.target.value)} placeholder="PIN المدير" />
            )}
          </div>
        </div>

        {pays.map((p, ix) => (
          <div key={ix} className="border border-slate-200 rounded-xl p-3 mb-2">
            <div className="flex items-center gap-2 flex-wrap">
              <select className="border rounded-lg px-2 py-1.5 text-sm" value={p.method}
                onChange={(e) => setPay(ix, 'method', e.target.value)}>
                {METHODS.map(([v, ar, ic]) => <option key={v} value={v}>{ic} {ar}</option>)}
              </select>
              <input className="border rounded-lg px-3 py-1.5 w-32 font-bold" value={String(p.amount)}
                onChange={(e) => setPay(ix, 'amount', e.target.value)} inputMode="decimal" />
              {p.method === 'CASH' && remain > 0 && ix === pays.length - 1 && (
                <button className="text-xs text-sijill-700 underline"
                  onClick={() => setPay(ix, 'amount', (parseFloat(String(p.amount)) + remain).toFixed(4))}>
                  الباقي هنا {fmt(remain)}
                </button>
              )}
              {pays.length > 1 && (
                <button onClick={() => setPays((ps) => ps.filter((_, i) => i !== ix))}
                  className="text-red-400 mr-auto">حذف</button>
              )}
            </div>
            {p.method === 'ROOM' && (
              <select className="border rounded-lg px-2 py-1.5 mt-2 w-full text-sm"
                value={p.folio_id || ''}
                onChange={(e) => setPay(ix, 'folio_id', e.target.value || null)}>
                <option value="">— اختر غرفة مشغولة —</option>
                {rooms.map((r) => (
                  <option key={r.folio_id} value={r.folio_id}>
                    غرفة {r.room_no} — {r.guest_short} (رصيده: {fmt(r.balance)}{r.credit_limit ? ` / سقف ${fmt(r.credit_limit)}` : ''})
                  </option>
                ))}
              </select>
            )}
            {p.method === 'CORPORATE' && (
              <select className="border rounded-lg px-2 py-1.5 mt-2 w-full text-sm"
                value={p.corporate_id || ''}
                onChange={(e) => setPay(ix, 'corporate_id', e.target.value || null)}>
                <option value="">— اختر شركة —</option>
                {corporates.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            )}
            {p.method === 'HOUSE' && (
              <input className="border rounded-lg px-2 py-1.5 mt-2 w-full text-sm"
                value={p.reason || ''} onChange={(e) => setPay(ix, 'reason', e.target.value)}
                placeholder="سبب الضيافة/الاستخدام الداخلي (إلزامي)" />
            )}
          </div>
        ))}

        <div className="flex justify-between items-center text-sm mb-3">
          <button className="text-sijill-700 text-xs underline"
            onClick={() => setPays((ps) => [...ps, { method: 'CARD', amount: Math.max(0, remain).toFixed(4) }])}>
            + سند دفع آخر (Split)
          </button>
          <div className={remain !== 0 ? 'text-red-600 font-bold' : 'text-emerald-600 font-bold'}>
            {remain > 0 ? `ناقص ${fmt(remain)}` : remain < 0 ? `زيادة ${fmt(-remain)}` : 'مطابق ✓'}
          </div>
        </div>

        <ErrorNote msg={err} />
        <div className="flex gap-2">
          <Btn onClick={submit} disabled={busy || remain !== 0 || net <= 0}>
            {busy ? 'جارٍ التسديد…' : `تأكيد التسديد ${fmt(net)}`}
          </Btn>
          <Btn kind="ghost" onClick={onCancel}>رجوع</Btn>
        </div>
      </div>
    </div>
  )
}
