import { useEffect, useState } from 'react'
import { api, fmt, todayISO } from '../api'
import { Badge, Btn, Card, Spinner } from '../components/ui'
import type { TrialBalance as TB } from '../types'

export default function TrialBalance() {
  const [asOf, setAsOf] = useState(todayISO())
  const [tb, setTb] = useState<TB | null>(null)
  const [busy, setBusy] = useState(false)

  async function load() {
    setBusy(true)
    try {
      setTb(await api<TB>(`/api/reports/trial-balance?as_of=${asOf}`))
    } finally {
      setBusy(false)
    }
  }
  useEffect(() => { load() }, [])

  const visible = tb?.rows.filter((r) => parseFloat(r.debit_sum) > 0 || parseFloat(r.credit_sum) > 0 || !r.account_code) ?? []

  return (
    <Card title="ميزان المراجعة"
          actions={
            <div className="flex items-center gap-2">
              <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)}
                     className="border border-slate-300 rounded-xl px-3 py-1.5 text-sm num" />
              <Btn kind="ghost" onClick={load} disabled={busy}>{busy ? '…' : 'عرض'}</Btn>
            </div>
          }>
      {!tb ? <Spinner /> : (
        <>
          <div className="flex items-center gap-3 mb-4">
            {tb.balanced ? <Badge tone="green">متوازن: مدين = دائن ✓</Badge> : <Badge tone="red">غير متوازن!</Badge>}
            {tb.net_balance_zero && <Badge tone="green">الصافي صفري تماماً ✓</Badge>}
            <span className="text-xs text-slate-400">حتى <span className="num">{tb.as_of}</span> — الأرصدة الصفرية مخفية</span>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 text-xs border-b">
                <th className="text-right py-2 font-medium">الكود</th>
                <th className="text-right font-medium">الحساب</th>
                <th className="text-right font-medium">مجموع مدين</th>
                <th className="text-right font-medium">مجموع دائن</th>
                <th className="text-right font-medium">الرصيد</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => {
                const bal = parseFloat(r.balance)
                return (
                  <tr key={r.account_code}
                      className={`border-b last:border-0 hover:bg-slate-50 ${r.level <= 2 ? 'font-bold bg-slate-50/50' : ''}`}>
                    <td className="py-2 num font-bold text-atheer-800">{r.account_code}</td>
                    <td>
                      <span style={{ paddingRight: `${(r.level - 1) * 22}px` }}>{r.account_name}</span>
                    </td>
                    <td className="num">{fmt(r.debit_sum)}</td>
                    <td className="num">{fmt(r.credit_sum)}</td>
                    <td className={`num ${bal > 0 ? '' : bal < 0 ? 'text-red-600' : ''}`}>
                      {fmt(Math.abs(bal))} {bal > 0 ? 'مدين' : bal < 0 ? 'دائن' : ''}
                    </td>
                  </tr>
                )
              })}
              {visible.length === 0 && (
                <tr><td colSpan={5} className="text-center text-slate-400 py-10">
                  لا حركات حتى هذا التاريخ — شغّل «الشهر الفندقي التجريبي» من لوحة القيادة
                </td></tr>
              )}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-slate-400 font-black bg-atheer-50">
                <td colSpan={2} className="py-3">الإجماليات (الحسابات الورقية)</td>
                <td className="num text-atheer-800">{fmt(tb.total_debit)}</td>
                <td className="num text-atheer-800">{fmt(tb.total_credit)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </>
      )}
    </Card>
  )
}
