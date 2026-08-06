// لوحة الطلبات المفتوحة + شاشة التحضير (KDS) + أرشيف الفواتير والمرتجعات
import { useCallback, useEffect, useState } from 'react'
import { fmt, todayISO } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import type { Invoice, Outlet, PosOrder } from '../pos'
import { posApi } from '../pos'

const TABS = ['الطلبات المفتوحة', 'شاشة التحضير', 'الفواتير', 'المرتجعات'] as const

export default function PosOrders() {
  const { has } = useAuth()
  const [tab, setTab] = useState<string>(TABS[0])
  const [outlets, setOutlets] = useState<Outlet[]>([])
  const [outletId, setOutletId] = useState('')
  const [orders, setOrders] = useState<PosOrder[]>([])
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [viewInv, setViewInv] = useState<Invoice | null>(null)
  const [returnFor, setReturnFor] = useState<Invoice | null>(null)
  const [returnReason, setReturnReason] = useState('')
  const [settleFor, setSettleFor] = useState<PosOrder | null>(null)
  const [settleAmt, setSettleAmt] = useState('')

  const refresh = useCallback(async () => {
    const os = await posApi.outlets()
    setOutlets(os)
    if (!outletId && os.length) setOutletId(os[0].id)
  }, [outletId])

  const refreshData = useCallback(async () => {
    setErr(null)
    try {
      const oo = await posApi.orders('', '')
      setOrders(oo.filter((o) => o.status !== 'CLOSED' && o.status !== 'CANCELLED'
        && (!outletId || o.outlet_id === outletId)))
      const iv = await posApi.invoices(outletId, '')
      setInvoices(iv)
    } catch (e) { setErr((e as Error).message) }
  }, [outletId])

  useEffect(() => { refresh().catch(() => undefined) }, []) // eslint-disable-line
  useEffect(() => {
    refreshData().catch(() => undefined)
    const t = setInterval(() => { refreshData().catch(() => undefined) }, 10000)
    return () => clearInterval(t)
  }, [refreshData])

  const act = async (fn: () => Promise<unknown>, id: string) => {
    setBusyId(id); setErr(null)
    try { await fn(); await refreshData() } catch (e) { setErr((e as Error).message) }
    finally { setBusyId(null) }
  }

  const voidLine = async (orderId: string, lineId: string) => {
    const reason = window.prompt('سبب إلغاء البند (إلزامي — مشرف):')
    if (!reason) return
    await act(() => posApi.voidLine(orderId, lineId, reason), orderId)
  }

  const cancelOrder = async (orderId: string) => {
    const reason = window.prompt('سبب إلغاء الطلب كاملاً (إلزامي — مشرف):')
    if (!reason) return
    await act(() => posApi.cancelOrder(orderId, reason), orderId)
  }

  const quickSettle = async () => {
    if (!settleFor) return
    const o = settleFor
    setBusyId(o.id); setErr(null)
    try {
      const total = parseFloat(settleAmt || o.total)
      const r = await posApi.settle(o.id, {
        client_uuid: crypto.randomUUID(),
        payments: [{ method: 'CASH', amount: total.toFixed(4) }],
      })
      setSettleFor(null)
      setOk(`سُددت الفاتورة ${r.invoice.invoice_no}`)
      await refreshData()
    } catch (e) { setErr((e as Error).message) } finally { setBusyId(null) }
  }

  const doReturn = async () => {
    if (!returnFor || returnReason.trim().length < 3) return
    setBusyId(returnFor.id); setErr(null)
    try {
      const r = await posApi.returnInvoice(returnFor.id, returnReason.trim())
      setOk(`أنشئت فاتورة المرتجع ${r.invoice_no} بقيد عكسي كامل`)
      setReturnFor(null); setReturnReason('')
      await refreshData()
    } catch (e) { setErr((e as Error).message) } finally { setBusyId(null) }
  }

  const kdsLines = orders.filter((o) => o.status === 'FIRED')
    .flatMap((o) => o.lines.filter((l) => l.status === 'NORMAL')
      .map((l) => ({ ...l, orderNo: o.id.slice(0, 8), at: o.fired_at, table: o.table_name })))
  const kdsByStation: Record<string, typeof kdsLines> = {}
  for (const l of kdsLines) (kdsByStation[l.station] = kdsByStation[l.station] || []).push(l)

  const salesInvoices = invoices.filter((i) => i.type === 'SALE')
  const returnInvoices = invoices.filter((i) => i.type === 'RETURN')

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-xl font-black">الطلبات والفواتير — نقاط البيع</h1>
        <select className="border rounded-lg px-3 py-1.5 text-sm" value={outletId}
          onChange={(e) => setOutletId(e.target.value)}>
          {outlets.map((o) => <option key={o.id} value={o.id}>{o.name_ar}</option>)}
        </select>
        <div className="flex gap-1 mr-auto">
          {TABS.map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-3 py-1.5 rounded-lg text-sm border ${tab === t ? 'bg-sijill-700 text-white border-sijill-700' : 'border-slate-300 text-slate-600'}`}>
              {t}
            </button>
          ))}
        </div>
      </div>
      <ErrorNote msg={err} />
      <OkNote msg={ok} />

      {tab === 'الطلبات المفتوحة' && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {!orders.length && <div className="text-slate-400 text-sm">لا طلبات مفتوحة على هذا المنفذ</div>}
          {orders.map((o) => (
            <Card key={o.id}
              title={`طلب ${o.id.slice(0, 8)} — ${o.outlet}${o.table_name ? ` (${o.table_name})` : ''}`}
              actions={<Badge tone={o.status === 'FIRED' ? 'green' : 'slate'}>{o.status === 'FIRED' ? 'قيد التحضير' : 'مسودة'}</Badge>}>
              <div className="text-xs space-y-1 max-h-40 overflow-y-auto">
                {o.lines.filter((l) => l.status === 'NORMAL').map((l) => (
                  <div key={l.id} className="flex justify-between items-center gap-2">
                    <span>{l.item_name} ×{fmt(l.qty, 0)}</span>
                    <span className="flex items-center gap-2">
                      <b>{fmt(parseFloat(l.line_total) - parseFloat(l.discount))}</b>
                      {has('pos.void') && (
                        <button onClick={() => voidLine(o.id, l.id)}
                          className="text-red-400 hover:text-red-600" title="إلغاء البند (مشرف)">×</button>
                      )}
                    </span>
                  </div>
                ))}
                {o.lines.filter((l) => l.status === 'VOID').map((l) => (
                  <div key={l.id} className="flex justify-between text-red-300 line-through">
                    <span>{l.item_name}</span><span className="no-underline text-[10px]">ملغى: {l.void_reason}</span>
                  </div>
                ))}
              </div>
              <div className="flex justify-between font-black mt-2 pt-2 border-t border-slate-100">
                <span>الإجمالي</span><span>{fmt(o.total)}</span>
              </div>
              <div className="flex gap-2 mt-2">
                {o.status === 'DRAFT' && (
                  <Btn kind="ghost" onClick={() => act(() => posApi.fire(o.id), o.id)} disabled={busyId === o.id}>
                    إرسال للتحضير
                  </Btn>
                )}
                <Btn onClick={() => { setSettleFor(o); setSettleAmt(o.total) }} disabled={busyId === o.id}>
                  تسديد نقدي كامل
                </Btn>
                {has('pos.void') && (
                  <Btn kind="ghost" onClick={() => cancelOrder(o.id)} disabled={busyId === o.id}>
                    إلغاء الطلب
                  </Btn>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {tab === 'شاشة التحضير' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {(['KITCHEN', 'BAR'] as const).map((st) => (
            <Card key={st} title={st === 'KITCHEN' ? '🔥 المطبخ' : '🍹 البار'}>
              {!kdsByStation[st]?.length && <div className="text-slate-400 text-sm">لا طلبات معلقة</div>}
              <div className="space-y-2">
                {(kdsByStation[st] || []).map((l) => (
                  <div key={l.id} className="border border-slate-200 rounded-xl p-2.5 flex justify-between items-center">
                    <div>
                      <div className="font-bold">{l.item_name} <span className="text-sijill-700">×{fmt(l.qty, 0)}</span></div>
                      {l.modifiers.length > 0 && (
                        <div className="text-[11px] text-amber-700">{l.modifiers.map((m) => m.name).join('، ')}</div>
                      )}
                      {l.notes && <div className="text-[11px] text-slate-500">📝 {l.notes}</div>}
                    </div>
                    <div className="text-left text-xs text-slate-400">
                      <div>{l.table || 'سفري'}</div>
                      <div>{l.at ? new Date(l.at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : ''}</div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          ))}
        </div>
      )}

      {(tab === 'الفواتير' || tab === 'المرتجعات') && (
        <Card title={tab === 'الفواتير' ? `فواتير البيع (${salesInvoices.length})` : `فواتير المرتجع (${returnInvoices.length})`}>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-500 text-xs border-b">
                <th className="py-2 text-right">الرقم</th><th className="text-right">التاريخ</th>
                <th className="text-right">المنفذ</th><th className="text-right">الإجمالي</th>
                <th className="text-right">الخصم</th><th></th>
              </tr>
            </thead>
            <tbody>
              {(tab === 'الفواتير' ? salesInvoices : returnInvoices).map((iv) => (
                <tr key={iv.id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-2 font-bold">{iv.invoice_no}</td>
                  <td>{iv.business_date}</td>
                  <td>{iv.outlet}</td>
                  <td className="font-bold">{fmt(iv.net_total)}</td>
                  <td>{fmt(iv.discount_total)}</td>
                  <td className="text-left">
                    <button className="text-sijill-700 text-xs underline ml-2"
                      onClick={async () => setViewInv(await posApi.invoice(iv.id))}>عرض</button>
                    {tab === 'الفواتير' && has('pos.return') && (
                      <button className="text-red-600 text-xs underline"
                        onClick={() => setReturnFor(iv)}>مرتجع</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* عرض فاتورة */}
      {viewInv && (
        <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center" onClick={() => setViewInv(null)}>
          <div className="bg-white rounded-2xl p-6 w-[420px] max-h-[85vh] overflow-y-auto shadow-2xl" onClick={(e) => e.stopPropagation()} dir="rtl">
            <div className="font-black text-lg mb-1">فاتورة {viewInv.invoice_no}</div>
            <div className="text-xs text-slate-500 mb-3">
              {viewInv.outlet} — {viewInv.business_date} — الكاشير: {viewInv.issued_by}
              {viewInv.entry_no && <> — القيد: <b>{viewInv.entry_no}</b></>}
            </div>
            <table className="w-full text-sm mb-2">
              <tbody>
                {(viewInv.lines || []).map((l, i) => (
                  <tr key={i} className="border-b border-slate-100">
                    <td className="py-1.5">{l.item} ×{l.qty}
                      {l.modifiers.length > 0 && <span className="text-[10px] text-slate-400"> ({l.modifiers.map((m) => m.name).join('، ')})</span>}
                    </td>
                    <td className="text-left font-bold">{fmt(parseFloat(l.total) - parseFloat(l.discount))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="space-y-1 text-sm border-t pt-2">
              <div className="flex justify-between"><span>الإجمالي قبل الخصم</span><span>{fmt(viewInv.gross_total)}</span></div>
              <div className="flex justify-between"><span>الخصم</span><span>{fmt(viewInv.discount_total)}</span></div>
              <div className="flex justify-between font-black"><span>الصافي</span><span>{fmt(viewInv.net_total)}</span></div>
            </div>
            <div className="mt-2 text-xs text-slate-500">
              {(viewInv.payments || []).map((p, i) => (
                <div key={i} className="flex justify-between">
                  <span>{{ CASH: 'نقد', CARD: 'بطاقة', EWALLET: 'محفظة', ROOM: `على الغرفة${p.room_no ? ` ${p.room_no}` : ''}`, CORPORATE: 'على شركة', HOUSE: 'مجاني مصرّح' }[p.method as string]}</span>
                  <span>{fmt(p.amount)}</span>
                </div>
              ))}
            </div>
            <Btn kind="ghost" onClick={() => setViewInv(null)} className="mt-4">إغلاق</Btn>
          </div>
        </div>
      )}

      {/* نافذة المرتجع */}
      {returnFor && (
        <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center" onClick={() => setReturnFor(null)}>
          <div className="bg-white rounded-2xl p-6 w-[420px] shadow-2xl" onClick={(e) => e.stopPropagation()} dir="rtl">
            <div className="font-black mb-2">مرتجع فاتورة {returnFor.invoice_no}</div>
            <div className="text-xs text-slate-500 mb-3">
              فاتورة مرتجع منفصلة بقيد عكسي كامل — الأصل يبقى للتاريخ (ملف 04 §3.4).
              الصافي المرتجع: <b>{fmt(returnFor.net_total)}</b>
            </div>
            <textarea className="border rounded-xl w-full p-3 text-sm" rows={3}
              placeholder="سبب المرتجع (إلزامي — يسجل في التدقيق باسمك)"
              value={returnReason} onChange={(e) => setReturnReason(e.target.value)} />
            <div className="flex gap-2 mt-3">
              <Btn kind="danger" onClick={doReturn} disabled={busyId === returnFor.id || returnReason.trim().length < 3}>
                تأكيد المرتجع الكامل
              </Btn>
              <Btn kind="ghost" onClick={() => setReturnFor(null)}>إلغاء</Btn>
            </div>
          </div>
        </div>
      )}

      {/* تسديد نقدي سريع للطلبات المفتوحة */}
      {settleFor && (
        <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center" onClick={() => setSettleFor(null)}>
          <div className="bg-white rounded-2xl p-6 w-[360px] shadow-2xl" onClick={(e) => e.stopPropagation()} dir="rtl">
            <div className="font-black mb-2">تسديد نقدي — طلب {settleFor.id.slice(0, 8)}</div>
            <div className="text-xs text-slate-500 mb-2">للتسديد بوسائل أخرى استخدم شاشة البيع</div>
            <input className="border rounded-xl w-full p-3 font-black text-xl" value={settleAmt}
              onChange={(e) => setSettleAmt(e.target.value)} inputMode="decimal" />
            <div className="flex gap-2 mt-3">
              <Btn onClick={quickSettle} disabled={busyId === settleFor.id}>تأكيد {fmt(settleAmt)}</Btn>
              <Btn kind="ghost" onClick={() => setSettleFor(null)}>إلغاء</Btn>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export function posToday(): string { return todayISO() }
