import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, fmt } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner, statusBadge, JTYPE_AR } from '../components/ui'
import type { Journal } from '../types'

export default function JournalDetail() {
  const { id } = useParams()
  const { has } = useAuth()
  const [je, setJe] = useState<Journal | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [showReverse, setShowReverse] = useState(false)
  const [busy, setBusy] = useState(false)

  async function load() {
    try {
      setJe(await api<Journal>(`/api/journals/${id}`))
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : 'تعذر الجلب')
    }
  }
  useEffect(() => { load() }, [id])

  async function doReverse() {
    setBusy(true); setErr(null)
    try {
      const rev = await api<Journal>(`/api/journals/${id}/reverse`, {
        method: 'POST',
        body: JSON.stringify({ reason: reason.trim() }),
      })
      setOk(`أُنشئ قيد العكس ${rev.entry_no} — أصبح هذا القيد «معكوساً»`)
      setShowReverse(false)
      await load()
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : 'فشل العكس')
    } finally {
      setBusy(false)
    }
  }

  if (err && !je) return <ErrorNote msg={err} />
  if (!je) return <Spinner />

  return (
    <div className="space-y-4 max-w-5xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-black text-slate-800 num">{je.entry_no}</h1>
          <div className="text-sm text-slate-500 mt-1">
            {JTYPE_AR[je.journal_type] ?? je.journal_type} — تاريخ القيد: <span className="num">{je.entry_date}</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {statusBadge(je.status)}
          {je.status === 'POSTED' && has('journals.reverse') && (
            <Btn kind="danger" onClick={() => setShowReverse(true)}>عكس القيد</Btn>
          )}
        </div>
      </div>

      <ErrorNote msg={err} />
      <OkNote msg={ok} />

      {showReverse && (
        <Card title="عكس القيد (الإجراء الوحيد للتصحيح — لا تعديل ولا حذف)">
          <p className="text-sm text-slate-500 mb-3 leading-6">
            سيُنشأ قيد جديد مطابق معكوس الأطراف بتاريخ اليوم، ويُوسم هذا القيد كـ«معكوس».
            العملية مسجلة في سجل التدقيق باسمك.
          </p>
          <input value={reason} onChange={(e) => setReason(e.target.value)}
                 placeholder="سبب العكس (إلزامي)…"
                 className="w-full border border-slate-300 rounded-xl px-3 py-2 mb-3" />
          <div className="flex gap-2">
            <Btn kind="danger" disabled={reason.trim().length < 3 || busy} onClick={doReverse}>
              {busy ? 'جارٍ العكس…' : 'تأكيد العكس'}
            </Btn>
            <Btn kind="ghost" onClick={() => setShowReverse(false)}>إلغاء</Btn>
          </div>
        </Card>
      )}

      <Card>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm mb-4">
          <div><span className="text-slate-400 block text-xs">البيان</span>{je.narration}</div>
          <div><span className="text-slate-400 block text-xs">العملة</span><span className="num">{je.currency_code}</span></div>
          <div><span className="text-slate-400 block text-xs">المصدر</span>{je.source_type ?? 'يدوي'}</div>
          <div><span className="text-slate-400 block text-xs">المرجع</span><span className="num">{je.reference ?? '—'}</span></div>
        </div>
        {je.reversal_of_entry_id && (
          <div className="text-xs bg-amber-50 border border-amber-200 text-amber-700 rounded-lg px-3 py-2 mb-3">
            هذا قيد عكس — <Link className="underline" to={`/journals/${je.reversal_of_entry_id}`}>القيد الأصلي</Link>
          </div>
        )}
        {je.reversed_entry_id && (
          <div className="text-xs bg-amber-50 border border-amber-200 text-amber-700 rounded-lg px-3 py-2 mb-3">
            عُكس بواسطة — <Link className="underline" to={`/journals/${je.reversed_entry_id}`}>قيد العكس</Link>
          </div>
        )}
        <table className="w-full text-sm">
          <thead>
            <tr className="text-slate-400 text-xs border-b">
              <th className="text-right py-2 font-medium">#</th>
              <th className="text-right font-medium">الحساب</th>
              <th className="text-right font-medium">مدين</th>
              <th className="text-right font-medium">دائن</th>
              <th className="text-right font-medium">الوصف</th>
            </tr>
          </thead>
          <tbody>
            {je.lines.map((l) => (
              <tr key={l.line_no} className="border-b last:border-0">
                <td className="py-2.5 num text-slate-400">{l.line_no}</td>
                <td><span className="num font-bold text-sijill-800">{l.account_code}</span> — {l.account_name}</td>
                <td className="num">{parseFloat(l.debit) > 0 ? fmt(l.debit) : ''}</td>
                <td className="num">{parseFloat(l.credit) > 0 ? fmt(l.credit) : ''}</td>
                <td className="text-slate-500">{l.description}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-slate-300 font-bold">
              <td colSpan={2} className="py-3">الإجماليات <Badge tone="green">متوازن ✓</Badge></td>
              <td className="num">{fmt(je.total_debit)}</td>
              <td className="num">{fmt(je.total_credit)}</td>
              <td />
            </tr>
          </tfoot>
        </table>
      </Card>
    </div>
  )
}
