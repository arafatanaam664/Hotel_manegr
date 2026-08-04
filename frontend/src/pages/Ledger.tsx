import { useEffect, useState } from 'react'
import { api, fmt } from '../api'
import { Btn, Card, ErrorNote, Spinner } from '../components/ui'
import type { Account, Ledger as LedgerT } from '../types'

function monthRange() {
  const d = new Date()
  const y = d.getFullYear(); const m = String(d.getMonth() + 1).padStart(2, '0')
  return [`${y}-${m}-01`, `${d.getFullYear()}-${m}-${String(d.getDate()).padStart(2, '0')}`]
}

export default function Ledger() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [code, setCode] = useState('')
  const [range, setRange] = useState(monthRange())
  const [led, setLed] = useState<LedgerT | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api<Account[]>('/api/accounts').then((a) => {
      const postable = a.filter((x) => x.is_postable)
      setAccounts(postable)
      if (postable.length && !code) setCode(postable[0].code)
    })
  }, [])

  async function load() {
    if (!code) return
    setBusy(true); setErr(null)
    try {
      setLed(await api<LedgerT>(`/api/reports/ledger?account_code=${code}&date_from=${range[0]}&date_to=${range[1]}`))
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : 'خطأ')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card title="دفتر الأستاذ">
        <div className="flex flex-wrap items-end gap-3">
          <label className="block grow max-w-md">
            <span className="text-xs text-slate-500 mb-1 block">الحساب</span>
            <select value={code} onChange={(e) => setCode(e.target.value)}
                    className="w-full border border-slate-300 rounded-xl px-3 py-2">
              {accounts.map((a) => (
                <option key={a.id} value={a.code}>{a.code} — {a.name_ar}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-slate-500 mb-1 block">من</span>
            <input type="date" value={range[0]} onChange={(e) => setRange([e.target.value, range[1]])}
                   className="border border-slate-300 rounded-xl px-3 py-2 num" />
          </label>
          <label className="block">
            <span className="text-xs text-slate-500 mb-1 block">إلى</span>
            <input type="date" value={range[1]} onChange={(e) => setRange([range[0], e.target.value])}
                   className="border border-slate-300 rounded-xl px-3 py-2 num" />
          </label>
          <Btn onClick={load} disabled={busy}>{busy ? '…' : 'عرض الحركات'}</Btn>
        </div>
      </Card>

      <ErrorNote msg={err} />

      {led && (
        <Card title={`${led.account_code} — ${led.account_name}`}>
          <div className="grid grid-cols-3 gap-4 mb-4 text-sm">
            <div className="bg-slate-50 rounded-xl p-3">
              <div className="text-xs text-slate-400">رصيد افتتاحي</div>
              <div className="num font-bold mt-1">{fmt(led.opening_balance)}</div>
            </div>
            <div className="bg-slate-50 rounded-xl p-3">
              <div className="text-xs text-slate-400">عدد الحركات</div>
              <div className="num font-bold mt-1">{led.rows.length}</div>
            </div>
            <div className="bg-atheer-50 rounded-xl p-3">
              <div className="text-xs text-slate-400">رصيد ختامي</div>
              <div className="num font-bold mt-1 text-atheer-800">{fmt(led.closing_balance)}</div>
            </div>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 text-xs border-b">
                <th className="text-right py-2 font-medium">القيد</th>
                <th className="text-right font-medium">التاريخ</th>
                <th className="text-right font-medium">البيان</th>
                <th className="text-right font-medium">مدين</th>
                <th className="text-right font-medium">دائن</th>
                <th className="text-right font-medium">الرصيد المتحرك</th>
              </tr>
            </thead>
            <tbody>
              {led.rows.map((r, i) => (
                <tr key={i} className="border-b last:border-0 hover:bg-slate-50">
                  <td className="py-2 num text-atheer-700">{r.entry_no}</td>
                  <td className="num">{r.entry_date}</td>
                  <td className="max-w-[280px] truncate">{r.narration}</td>
                  <td className="num">{parseFloat(r.debit) > 0 ? fmt(r.debit) : ''}</td>
                  <td className="num">{parseFloat(r.credit) > 0 ? fmt(r.credit) : ''}</td>
                  <td className="num font-medium">{fmt(r.running_balance)}</td>
                </tr>
              ))}
              {led.rows.length === 0 && (
                <tr><td colSpan={6} className="text-center text-slate-400 py-8">لا حركات في هذه الفترة</td></tr>
              )}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
