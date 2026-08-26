import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmt } from '../api'
import { Btn, Card, Spinner, statusBadge, JTYPE_AR } from '../components/ui'
import type { Journal, Paged } from '../types'

export default function Journals() {
  const [data, setData] = useState<Paged<Journal> | null>(null)
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')

  useEffect(() => {
    const qs = new URLSearchParams({ page: String(page), page_size: '25' })
    if (status) qs.set('status', status)
    api<Paged<Journal>>(`/api/journals?${qs}`).then(setData)
  }, [page, status])

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1

  return (
    <Card title="القيود اليومية"
          actions={
            <select value={status}
                    onChange={(e) => { setPage(1); setStatus(e.target.value) }}
                    className="border border-slate-300 rounded-xl px-3 py-1.5 text-sm">
              <option value="">كل الحالات</option>
              <option value="POSTED">مرحَّل</option>
              <option value="REVERSED">معكوس</option>
              <option value="DRAFT">مسودة</option>
            </select>
          }>
      {!data ? <Spinner /> : data.items.length === 0 ? (
        <div className="text-center text-slate-400 py-10">لا قيود مطابقة</div>
      ) : (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 text-xs border-b">
                <th className="text-right py-2 font-medium">رقم القيد</th>
                <th className="text-right font-medium">التاريخ</th>
                <th className="text-right font-medium">النوع</th>
                <th className="text-right font-medium">البيان</th>
                <th className="text-right font-medium">مدين</th>
                <th className="text-right font-medium">دائن</th>
                <th className="text-right font-medium">الحالة</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((j) => (
                <tr key={j.id} className="border-b last:border-0 hover:bg-slate-50">
                  <td className="py-2.5 num text-sijill-700 font-medium">
                    <Link to={`/journals/${j.id}`}>{j.entry_no}</Link>
                  </td>
                  <td className="num">{j.entry_date}</td>
                  <td className="text-xs">{JTYPE_AR[j.journal_type] ?? j.journal_type}</td>
                  <td className="max-w-[320px] truncate">{j.narration}</td>
                  <td className="num">{fmt(j.total_debit)}</td>
                  <td className="num">{fmt(j.total_credit)}</td>
                  <td>{statusBadge(j.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex items-center justify-between mt-4 text-sm">
            <div className="text-slate-500">الإجمالي: {data.total} قيداً — صفحة {page} من {pages}</div>
            <div className="flex gap-2">
              <Btn kind="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>السابق</Btn>
              <Btn kind="ghost" disabled={page >= pages} onClick={() => setPage(page + 1)}>التالي</Btn>
            </div>
          </div>
        </>
      )}
    </Card>
  )
}
