// الورديات وتقارير Z الأرشيفية + تعيين PIN الاعتماد — ملف 04 §3.5/§5
import { useCallback, useEffect, useState } from 'react'
import { fmt } from '../api'
import { Badge, Btn, Card, ErrorNote, OkNote } from '../components/ui'
import type { Outlet, Shift } from '../pos'
import { posApi } from '../pos'

export default function PosShifts() {
  const [outlets, setOutlets] = useState<Outlet[]>([])
  const [outletId, setOutletId] = useState('')
  const [shifts, setShifts] = useState<Shift[]>([])
  const [pin, setPin] = useState({ pw: '', pin: '', done: false })
  const [closeFor, setCloseFor] = useState<Shift | null>(null)
  const [actualCash, setActualCash] = useState('')
  const [live, setLive] = useState<Record<string, unknown> | null>(null)
  const [zview, setZview] = useState<Record<string, unknown> | null>(null)
  const [archive, setArchive] = useState<{ shift_id: string; zreport: Record<string, unknown> }[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [floatBy, setFloatBy] = useState('50')

  const refresh = useCallback(async () => {
    const os = await posApi.outlets()
    setOutlets(os)
    if (!outletId && os.length) setOutletId(os[0].id)
  }, [outletId])

  const refreshData = useCallback(async () => {
    if (!outletId) return
    try {
      setShifts(await posApi.shifts(outletId, ''))
      setArchive(await posApi.zReports(outletId))
    } catch (e) { setErr((e as Error).message) }
  }, [outletId])

  useEffect(() => { refresh().catch(() => undefined) }, []) // eslint-disable-line
  useEffect(() => { refreshData().catch(() => undefined) }, [refreshData])

  const openShift = async () => {
    setErr(null); setOk(null)
    try {
      await posApi.openShift(outletId, parseFloat(floatBy || '0'))
      setOk('فُتحت الوردية')
      await refreshData()
    } catch (e) { setErr((e as Error).message) }
  }

  const openClose = async (sh: Shift) => {
    setCloseFor(sh); setActualCash('')
    try {
      const z = await posApi.zreport(sh.id)
      setLive(z.live_summary || null)
    } catch { setLive(null) }
  }

  const doClose = async () => {
    if (!closeFor) return
    setErr(null)
    try {
      const z = await posApi.closeShift(closeFor.id, parseFloat(actualCash || '0'))
      setZview(z as Record<string, unknown>)
      setCloseFor(null)
      setOk('أُقفلت الوردية ووُقّع تقرير Z — أصبح أرشيفاً غير قابل للتعديل')
      await refreshData()
    } catch (e) { setErr((e as Error).message) }
  }

  const submitPin = async () => {
    setErr(null); setOk(null)
    try {
      await posApi.setPin(pin.pw, pin.pin)
      setPin({ pw: '', pin: '', done: true })
      setOk('عُيّن رقم PIN الاعتماد الفوري بنجاح — احفظه سراً')
    } catch (e) { setErr((e as Error).message) }
  }

  const expected = live ? parseFloat(String((live as { expected_cash?: string }).expected_cash ?? 'NaN')) : NaN
  const variance = closeFor && actualCash !== '' && !Number.isNaN(expected)
    ? parseFloat(actualCash) - expected : null

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-xl font-black">الورديات وتقارير Z</h1>
        <select className="border rounded-lg px-3 py-1.5 text-sm" value={outletId}
          onChange={(e) => setOutletId(e.target.value)}>
          {outlets.map((o) => <option key={o.id} value={o.id}>{o.name_ar}</option>)}
        </select>
        <div className="flex items-center gap-2 mr-auto">
          <input className="border rounded-lg px-3 py-1.5 w-32 text-sm" value={floatBy}
            onChange={(e) => setFloatBy(e.target.value)} placeholder="عهدة الافتتاح" inputMode="decimal" />
          <Btn onClick={openShift}>فتح وردية</Btn>
        </div>
      </div>
      <ErrorNote msg={err} />
      <OkNote msg={ok} />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2 space-y-3">
          <Card title={`ورديات المنفذ (${shifts.length})`}>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-500 text-xs border-b">
                  <th className="py-2 text-right">الحالة</th><th className="text-right">فتح بواسطة</th>
                  <th className="text-right">الافتتاح</th><th className="text-right">العهدة</th>
                  <th className="text-right">متوقع</th><th className="text-right">فعلي</th>
                  <th className="text-right">الفرق</th><th></th>
                </tr>
              </thead>
              <tbody>
                {shifts.map((sh) => (
                  <tr key={sh.id} className="border-b border-slate-100">
                    <td className="py-2"><Badge tone={sh.status === 'OPEN' ? 'green' : 'red'}>{sh.status === 'OPEN' ? 'مفتوحة' : 'مقفلة'}</Badge></td>
                    <td>{sh.opened_by}</td>
                    <td className="text-xs">{new Date(sh.opened_at).toLocaleString('en-GB')}</td>
                    <td>{fmt(sh.opening_float)}</td>
                    <td>{sh.expected_cash != null ? fmt(sh.expected_cash) : '—'}</td>
                    <td>{sh.actual_cash != null ? fmt(sh.actual_cash) : '—'}</td>
                    <td className={sh.cash_variance && parseFloat(sh.cash_variance) !== 0 ? 'text-amber-600 font-bold' : ''}>
                      {sh.cash_variance != null ? fmt(sh.cash_variance) : '—'}
                    </td>
                    <td className="text-left">
                      {sh.status === 'OPEN'
                        ? <button className="text-red-600 text-xs underline" onClick={() => openClose(sh)}>إقفال + Z</button>
                        : <button className="text-atheer-700 text-xs underline"
                            onClick={async () => setZview(((await posApi.zreport(sh.id)).zreport) || null)}>Z-Report</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <Card title={`أرشيف تقارير Z (${archive.length}) — قراءة فقط، أرشيف غير قابل للتعديل`}>
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {archive.map((a) => (
                <button key={a.shift_id} onClick={() => setZview(a.zreport)}
                  className="w-full flex justify-between items-center border border-slate-200 rounded-xl px-3 py-2 hover:bg-atheer-50 text-sm">
                  <span>وردية {String(a.zreport.outlet)} — {String(a.zreport.business_date)}</span>
                  <span className="text-xs text-slate-500">التوقيع: {String(a.zreport.signature)}</span>
                </button>
              ))}
              {!archive.length && <div className="text-slate-400 text-sm">لا تقارير مقفلة بعد</div>}
            </div>
          </Card>
        </div>

        <Card title="رقم PIN للاعتماد الفوري" actions={pin.done ? <Badge tone="green">مُعيَّن</Badge> : null}>
          <div className="text-xs text-slate-500 mb-3 leading-5">
            يستخدمه المشرف/المدير لاعتماد: الخصومات فوق حد الدور، والمجاني المصرّح
            (House Use) — 4 إلى 8 أرقام، يُخزَّن مجزأً (argon2).
          </div>
          <input type="password" className="border rounded-lg w-full px-3 py-2 text-sm mb-2"
            placeholder="كلمة مرورك الحالية"
            value={pin.pw} onChange={(e) => setPin((p) => ({ ...p, pw: e.target.value }))} />
          <input type="password" className="border rounded-lg w-full px-3 py-2 text-sm mb-3"
            placeholder="PIN الجديد (4-8 أرقام)" inputMode="numeric"
            value={pin.pin} onChange={(e) => setPin((p) => ({ ...p, pin: e.target.value }))} />
          <Btn onClick={submitPin} disabled={!pin.pw || !/^\d{4,8}$/.test(pin.pin)}>تعيين PIN</Btn>
        </Card>
      </div>

      {/* نافذة الإقفال */}
      {closeFor && (
        <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center" onClick={() => setCloseFor(null)}>
          <div className="bg-white rounded-2xl p-6 w-[420px] shadow-2xl" onClick={(e) => e.stopPropagation()} dir="rtl">
            <div className="font-black text-lg mb-3">إقفال الوردية — عدّ النقد الفعلي</div>
            {live && (
              <div className="bg-slate-50 rounded-xl p-3 text-sm space-y-1 mb-3">
                <div className="flex justify-between"><span>عهدة الافتتاح</span><b>{fmt(String(live.expected_cash).replace(/[\d.+-]+$/, '') || '0') || fmt(closeFor.opening_float)}</b></div>
                <div className="flex justify-between"><span>مبيعات نقدية</span><b>{fmt(String(live.cash_sales ?? '0'))}</b></div>
                <div className="flex justify-between"><span>مرتجعات نقدية</span><b>{fmt(String(live.cash_refunds ?? '0'))}</b></div>
                <div className="flex justify-between border-t pt-1"><span>المتوقع بالصندوق</span><b className="text-atheer-800">{fmt(String(live.expected_cash ?? '0'))}</b></div>
                <div className="flex justify-between"><span>فواتير بيع / مرتجع</span><span>{String(live.invoices_sales ?? 0)} / {String(live.invoices_returns ?? 0)}</span></div>
              </div>
            )}
            <input className="border rounded-xl w-full p-3 font-black text-xl mb-1" value={actualCash}
              onChange={(e) => setActualCash(e.target.value)} inputMode="decimal"
              placeholder="العدّ الفعلي بالصندوق" />
            {variance !== null && (
              <div className={`text-sm font-bold mb-2 ${variance === 0 ? 'text-emerald-600' : Math.abs(variance) <= 10 ? 'text-amber-600' : 'text-red-600'}`}>
                {variance === 0 ? 'مطابق تماماً ✓' : `فرق العهدة: ${fmt(variance)} ${Math.abs(variance) <= 10 ? '(ضمن التسامح — سيُقيد لفرق الصندوق)' : '(خارج التسامح — سيُرفض الإقفال)'}`}
              </div>
            )}
            <div className="flex gap-2">
              <Btn kind="danger" onClick={doClose} disabled={actualCash === ''}>إقفال وتوقيع Z</Btn>
              <Btn kind="ghost" onClick={() => setCloseFor(null)}>رجوع</Btn>
            </div>
          </div>
        </div>
      )}

      {/* عرض Z-Report */}
      {zview && (
        <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center" onClick={() => setZview(null)}>
          <div className="bg-white rounded-2xl p-6 w-[400px] max-h-[85vh] overflow-y-auto shadow-2xl" onClick={(e) => e.stopPropagation()} dir="rtl">
            <div className="receipt-print font-mono text-xs">
              <div className="text-center font-black text-sm mb-1">تقرير Z — {String(zview.outlet_name)}</div>
              <div className="text-center mb-2">يوم عمل {String(zview.business_date)} — أرشيف مقفل 🔒</div>
              <div className="border-t border-dashed border-slate-400 my-2" />
              <div>فُتحت: {new Date(String(zview.opened_at)).toLocaleString('en-GB')} — {String(zview.opened_by)}</div>
              <div>أُقفلت: {new Date(String(zview.closed_at)).toLocaleString('en-GB')} — {String(zview.closed_by)}</div>
              <div className="border-t border-dashed border-slate-400 my-2" />
              <div className="flex justify-between"><span>عهدة الافتتاح</span><b>{fmt(String(zview.opening_float))}</b></div>
              <div className="flex justify-between"><span>مبيعات نقدية</span><b>{fmt(String(zview.cash_sales))}</b></div>
              <div className="flex justify-between"><span>مرتجعات نقدية</span><b>{fmt(String(zview.cash_refunds))}</b></div>
              <div className="flex justify-between"><span>فواتير بيع / مرتجع</span><span>{String(zview.invoices_sales)} / {String(zview.invoices_returns)}</span></div>
              <div className="flex justify-between"><span>إجمالي المبيعات</span><b>{fmt(String(zview.sales_total))}</b></div>
              {Object.entries((zview.by_method as Record<string, string>) || {}).map(([mth, amt]) => (
                <div key={mth} className="flex justify-between"><span>تحصيل {mth}</span><span>{fmt(amt)}</span></div>
              ))}
              <div className="flex justify-between"><span>الخصومات</span><span>{fmt(String(zview.discounts_total))}</span></div>
              <div className="border-t border-dashed border-slate-400 my-2" />
              <div className="flex justify-between"><span>المتوقع</span><b>{fmt(String(zview.expected_cash))}</b></div>
              <div className="flex justify-between"><span>الفعلي</span><b>{fmt(String(zview.actual_cash))}</b></div>
              <div className="flex justify-between font-black">
                <span>الفرق</span>
                <span className={parseFloat(String(zview.variance)) !== 0 ? 'text-amber-700' : ''}>{fmt(String(zview.variance))}</span>
              </div>
              {zview.variance_entry ? <div>قيد الفرق: {String(zview.variance_entry)}</div> : null}
              <div className="border-t border-dashed border-slate-400 my-2" />
              <div className="text-center">التوقيع: {String(zview.signature)}</div>
            </div>
            <div className="flex gap-2 mt-4 no-print">
              <Btn onClick={() => window.print()}>طباعة</Btn>
              <Btn kind="ghost" onClick={() => setZview(null)}>إغلاق</Btn>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
