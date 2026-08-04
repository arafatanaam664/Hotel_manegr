import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Badge, Card, Spinner } from '../components/ui'
import type { Account } from '../types'

const TYPE_AR: Record<string, string> = {
  ASSET: 'أصول', LIABILITY: 'خصوم', EQUITY: 'حقوق ملكية',
  REVENUE: 'إيرادات', COGS: 'تكلفة مبيعات', EXPENSE: 'مصروفات', SYSTEM: 'نظام',
}

export default function Accounts() {
  const [accounts, setAccounts] = useState<Account[] | null>(null)
  const [q, setQ] = useState('')

  useEffect(() => { api<Account[]>('/api/accounts').then(setAccounts) }, [])

  const filtered = useMemo(() => {
    if (!accounts) return []
    const s = q.trim()
    if (!s) return accounts
    return accounts.filter((a) => a.code.includes(s) || a.name_ar.includes(s))
  }, [accounts, q])

  if (!accounts) return <Spinner />

  return (
    <Card title={`دليل الحسابات (${filtered.length})`}
          actions={
            <input
              value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="بحث بالكود أو الاسم…"
              className="border border-slate-300 rounded-xl px-3 py-1.5 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-atheer-500"
            />
          }>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-slate-400 text-xs border-b">
            <th className="text-right py-2 font-medium">الكود</th>
            <th className="text-right font-medium">الاسم</th>
            <th className="text-right font-medium">النوع</th>
            <th className="text-right font-medium">الطبيعة</th>
            <th className="text-right font-medium">خصائص</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((a) => (
            <tr key={a.id} className={`border-b last:border-0 hover:bg-slate-50 ${a.is_postable ? '' : 'bg-slate-50/60'}`}>
              <td className="py-2 num font-bold text-atheer-800">{a.code}</td>
              <td>
                <span style={{ paddingRight: `${(a.level - 1) * 22}px` }}
                      className={a.is_postable ? '' : 'font-bold text-slate-600'}>
                  {a.name_ar}
                </span>
              </td>
              <td><Badge tone="blue">{TYPE_AR[a.type] ?? a.type}</Badge></td>
              <td className="text-xs text-slate-500">{a.nature === 'DEBIT' ? 'مدين' : 'دائن'}</td>
              <td className="space-x-1 space-x-reverse">
                {!a.is_postable && <Badge tone="slate">تجميعي</Badge>}
                {a.is_postable && <Badge tone="green">ترحيل</Badge>}
                {a.party_required && <Badge tone="amber">يتطلب طرفاً</Badge>}
                {a.is_system && <Badge>نظام</Badge>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}
