// تقارير POS — ملف 04 §5: مبيعات بالأبعاد الستة + هامش الأصناف + مؤشرات الرقابة
import { useCallback, useEffect, useState } from 'react'
import { fmt, todayISO } from '../api'
import { Btn, Card, ErrorNote } from '../components/ui'
import { posApi } from '../pos'

const GROUPS = [
  ['item', 'بالصنف (مع الهامش)'], ['category', 'بالتصنيف'], ['outlet', 'بالمنفذ'],
  ['hour', 'بالساعة (ذروة)'], ['payment', 'بطريقة الدفع'], ['user', 'بالموظف'],
] as const

export default function PosReports() {
  const [from, setFrom] = useState(todayISO())
  const [to, setTo] = useState(todayISO())
  const [groupBy, setGroupBy] = useState<string>('item')
  const [rows, setRows] = useState<{ group: string; net: string; cost: string; count: string; margin: string; margin_pct: number }[]>([])
  const [control, setControl] = useState<{ voids?: unknown[]; returns?: unknown[]; discounts?: unknown[] } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const run = useCallback(async () => {
    setBusy(true); setErr(null)
    try {
      setRows(await posApi.salesReport(from, to, groupBy))
      setControl(await posApi.controlReport(from, to) as typeof control)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }, [from, to, groupBy])

  useEffect(() => { run().catch(() => undefined) }, []) // eslint-disable-line

  const totals = rows.reduce((a, r) => ({
    net: a.net + parseFloat(r.net), cost: a.cost + parseFloat(r.cost),
    margin: a.margin + parseFloat(r.margin),
  }), { net: 0, cost: 0, margin: 0 })

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-xl font-black">تقارير نقاط البيع</h1>
      <div className="flex items-end gap-2 flex-wrap">
        <label className="text-xs">من
          <input type="date" className="border rounded-lg px-3 py-1.5 block" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="text-xs">إلى
          <input type="date" className="border rounded-lg px-3 py-1.5 block" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <select className="border rounded-lg px-3 py-1.5 text-sm" value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>
          {GROUPS.map(([v, ar]) => <option key={v} value={v}>{ar}</option>)}
        </select>
        <Btn onClick={run} disabled={busy}>{busy ? '…' : 'عرض'}</Btn>
      </div>
      <ErrorNote msg={err} />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2">
          <Card title={`مبيعات ${from === to ? from : `${from} ← ${to}`} — ${GROUPS.find(([g]) => g === groupBy)?.[1]}`}>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-500 text-xs border-b">
                  <th className="py-2 text-right">المجموعة</th>
                  <th className="text-right">{groupBy === 'item' ? 'الكمية' : 'العدد'}</th>
                  <th className="text-right">الصافي</th><th className="text-right">التكلفة</th>
                  <th className="text-right">الهامش</th><th className="text-right">الهامش %</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.group} className="border-b border-slate-100">
                    <td className="py-1.5 font-bold">{r.group}</td>
                    <td>{fmt(r.count, 0)}</td>
                    <td>{fmt(r.net)}</td>
                    <td>{fmt(r.cost)}</td>
                    <td className={parseFloat(r.margin) >= 0 ? 'text-emerald-700 font-bold' : 'text-red-600 font-bold'}>
                      {fmt(r.margin)}
                    </td>
                    <td>{r.margin_pct.toFixed(1)}%</td>
                  </tr>
                ))}
                <tr className="font-black bg-slate-50">
                  <td className="py-2">الإجمالي</td><td></td>
                  <td>{fmt(totals.net)}</td><td>{fmt(totals.cost)}</td>
                  <td>{fmt(totals.margin)}</td>
                  <td>{totals.net > 0 ? ((totals.margin / totals.net) * 100).toFixed(1) : '0.0'}%</td>
                </tr>
              </tbody>
            </table>
            {!rows.length && <div className="text-slate-400 text-sm py-6 text-center">لا مبيعات في الفترة</div>}
          </Card>
        </div>

        <Card title="مؤشرات الرقابة — إلغاءات/مرتجعات/خصومات بالمستخدم">
          <div className="space-y-3 text-xs max-h-[420px] overflow-y-auto">
            <div>
              <div className="font-black text-red-700 mb-1">إلغاءات البنود</div>
              {((control?.voids || []) as { user: string; voids: number; void_value: string; reasons: string[] }[]).map((v) => (
                <div key={v.user} className="border-b border-slate-100 py-1">
                  <b>{v.user}</b>: {v.voids} إلغاء بقيمة {fmt(v.void_value)}
                  <div className="text-slate-400">{v.reasons.slice(0, 3).join(' | ')}</div>
                </div>
              ))}
              {!control?.voids?.length && <div className="text-slate-400">لا إلغاءات ✓</div>}
            </div>
            <div>
              <div className="font-black text-red-700 mb-1">المرتجعات</div>
              {((control?.returns || []) as { user: string; returns: number; value: string; reasons: string[] }[]).map((v) => (
                <div key={v.user} className="border-b border-slate-100 py-1">
                  <b>{v.user}</b>: {v.returns} مرتجع بقيمة {fmt(v.value)}
                  <div className="text-slate-400">{v.reasons.slice(0, 3).join(' | ')}</div>
                </div>
              ))}
              {!control?.returns?.length && <div className="text-slate-400">لا مرتجعات ✓</div>}
            </div>
            <div>
              <div className="font-black text-amber-700 mb-1">الخصومات</div>
              {((control?.discounts || []) as { user: string; discounted_invoices: number; discount_value: string }[]).map((v) => (
                <div key={v.user} className="border-b border-slate-100 py-1">
                  <b>{v.user}</b>: {v.discounted_invoices} فاتورة مخفضة بإجمالي {fmt(v.discount_value)}
                </div>
              ))}
              {!control?.discounts?.length && <div className="text-slate-400">لا خصومات ✓</div>}
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
