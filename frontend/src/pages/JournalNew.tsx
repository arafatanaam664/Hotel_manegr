import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, fmt, todayISO } from '../api'
import { Btn, Card, ErrorNote } from '../components/ui'
import type { Account, Journal } from '../types'

interface LineDraft {
  account_code: string
  debit: string
  credit: string
  party_id: string
  description: string
}

const emptyLine = (): LineDraft => ({ account_code: '', debit: '', credit: '', party_id: '', description: '' })

export default function JournalNew() {
  const nav = useNavigate()
  const [accounts, setAccounts] = useState<Account[]>([])
  const [lines, setLines] = useState<LineDraft[]>([emptyLine(), emptyLine()])
  const [narration, setNarration] = useState('')
  const [entryDate, setEntryDate] = useState(todayISO())
  const [reference, setReference] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => { api<Account[]>('/api/accounts').then(setAccounts) }, [])
  const postable = useMemo(() => accounts.filter((a) => a.is_postable && a.is_active), [accounts])

  const sum = (k: 'debit' | 'credit') =>
    lines.reduce((t, l) => t + (parseFloat(l[k]) || 0), 0)
  const td = sum('debit')
  const tc = sum('credit')
  const balanced = td > 0 && td === tc

  function setLine(i: number, patch: Partial<LineDraft>) {
    setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)))
  }

  async function submit() {
    setErr(null)
    setBusy(true)
    try {
      const je = await api<Journal>('/api/journals/manual', {
        method: 'POST',
        body: JSON.stringify({
          entry_date: entryDate,
          branch_code: 'MAIN',
          narration: narration.trim(),
          reference: reference.trim() || null,
          lines: lines.map((l) => ({
            account_code: l.account_code,
            debit: l.debit || '0',
            credit: l.credit || '0',
            party_id: l.party_id.trim() || null,
            party_type: l.party_id.trim() ? 'GENERAL' : null,
            description: l.description.trim(),
          })),
        }),
      })
      nav(`/journals/${je.id}`)
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : 'فشل الترحيل')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4 max-w-5xl">
      <h1 className="text-xl font-black text-slate-800">قيد يومية يدوي جديد</h1>
      <ErrorNote msg={err} />
      <Card>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-5">
          <label className="block">
            <span className="text-sm text-slate-600 mb-1 block">تاريخ القيد</span>
            <input type="date" value={entryDate} onChange={(e) => setEntryDate(e.target.value)}
                   className="w-full border border-slate-300 rounded-xl px-3 py-2 num" />
          </label>
          <label className="block md:col-span-2">
            <span className="text-sm text-slate-600 mb-1 block">البيان</span>
            <input value={narration} onChange={(e) => setNarration(e.target.value)}
                   placeholder="وصف القيد المحاسبي…" required
                   className="w-full border border-slate-300 rounded-xl px-3 py-2" />
          </label>
        </div>
        <label className="block mb-5 md:w-1/3">
          <span className="text-sm text-slate-600 mb-1 block">مرجع (اختياري)</span>
          <input value={reference} onChange={(e) => setReference(e.target.value)}
                 className="w-full border border-slate-300 rounded-xl px-3 py-2 num" />
        </label>

        <table className="w-full text-sm">
          <thead>
            <tr className="text-slate-400 text-xs border-b">
              <th className="text-right py-2 font-medium w-1/4">الحساب</th>
              <th className="text-right font-medium">مدين</th>
              <th className="text-right font-medium">دائن</th>
              <th className="text-right font-medium">طرف (عند الحاجة)</th>
              <th className="text-right font-medium">وصف السطر</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => {
              const acc = postable.find((a) => a.code === l.account_code)
              return (
                <tr key={i} className="border-b last:border-0">
                  <td className="py-2 pl-2">
                    <select value={l.account_code}
                            onChange={(e) => setLine(i, { account_code: e.target.value })}
                            className="w-full border border-slate-300 rounded-xl px-2 py-1.5">
                      <option value="">— اختر حساباً —</option>
                      {postable.map((a) => (
                        <option key={a.id} value={a.code}>{a.code} — {a.name_ar}</option>
                      ))}
                    </select>
                  </td>
                  <td className="pl-2">
                    <input value={l.debit} inputMode="decimal" placeholder="0"
                           onChange={(e) => setLine(i, { debit: e.target.value, credit: e.target.value ? '' : l.credit })}
                           className="w-full border border-slate-300 rounded-xl px-2 py-1.5 num" />
                  </td>
                  <td className="pl-2">
                    <input value={l.credit} inputMode="decimal" placeholder="0"
                           onChange={(e) => setLine(i, { credit: e.target.value, debit: e.target.value ? '' : l.debit })}
                           className="w-full border border-slate-300 rounded-xl px-2 py-1.5 num" />
                  </td>
                  <td className="pl-2">
                    <input value={l.party_id}
                           onChange={(e) => setLine(i, { party_id: e.target.value })}
                           placeholder={acc?.party_required ? 'مطلوب!' : ''}
                           className={`w-full border rounded-xl px-2 py-1.5 text-xs ${acc?.party_required && !l.party_id ? 'border-amber-400 bg-amber-50' : 'border-slate-300'}`} />
                  </td>
                  <td className="pl-2">
                    <input value={l.description}
                           onChange={(e) => setLine(i, { description: e.target.value })}
                           className="w-full border border-slate-300 rounded-xl px-2 py-1.5" />
                  </td>
                  <td>
                    <button onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}
                            disabled={lines.length <= 2}
                            className="text-red-400 hover:text-red-600 disabled:opacity-30 px-2">
                      ✕
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-slate-300 font-bold">
              <td className="py-3">
                <Btn kind="ghost" onClick={() => setLines((ls) => [...ls, emptyLine()])}>+ سطر</Btn>
              </td>
              <td className={`num ${balanced ? 'text-emerald-600' : 'text-slate-700'}`}>{fmt(td)}</td>
              <td className={`num ${balanced ? 'text-emerald-600' : 'text-slate-700'}`}>{fmt(tc)}</td>
              <td colSpan={3}>
                {balanced
                  ? <span className="text-emerald-600 text-sm">متوازن ✓</span>
                  : <span className="text-amber-600 text-sm">الفرق: {fmt(Math.abs(td - tc))}</span>}
              </td>
            </tr>
          </tfoot>
        </table>

        <div className="flex justify-end mt-5">
          <Btn onClick={submit} disabled={!balanced || narration.trim().length < 3 || busy}>
            {busy ? 'جارٍ الترحيل…' : 'ترحيل القيد'}
          </Btn>
        </div>
      </Card>
    </div>
  )
}
