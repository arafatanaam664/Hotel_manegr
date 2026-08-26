import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import type { AuditItem, Paged } from '../types'

const MODULE_AR: Record<string, string> = {
  accounting: 'محاسبة', security: 'أمان', org: 'تنظيم',
}
const ACTION_AR: Record<string, string> = {
  'journal.post': 'ترحيل قيد', 'journal.reverse': 'عكس قيد',
  'period.close': 'إغلاق فترة', 'auth.login.success': 'دخول ناجح',
  'auth.login.failed': 'دخول فاشل', 'auth.refresh.reuse_detected': 'اشتباه سرقة رمز!',
  'auth.logout': 'خروج', 'auth.outside_shift': 'دخول خارج الدوام!',
  'auth.password_changed': 'تغيير كلمة مرور',
  'user.create': 'إنشاء مستخدم', 'user.update': 'تعديل مستخدم',
  'user.toggle_active': 'تفعيل/إيقاف مستخدم', 'user.reset_password': 'إعادة تعيين كلمة مرور',
  'user.unlock': 'فك قفل حساب', 'user.revoke_sessions': 'إبطال جلسات مستخدم',
  'role.create': 'إنشاء دور', 'role.update': 'تعديل دور', 'role.delete': 'حذف دور',
}

export default function Audit() {
  const [params] = useSearchParams()
  const actor = params.get('actor') ?? ''
  const [data, setData] = useState<(Paged<AuditItem> & { chain_records?: number }) | null>(null)
  const [page, setPage] = useState(1)
  const [verify, setVerify] = useState<string | null>(null)
  const [verifyOk, setVerifyOk] = useState<boolean | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const actorQ = actor ? `&actor=${encodeURIComponent(actor)}` : ''
    api<Paged<AuditItem> & { chain_records?: number }>(`/api/audit?page=${page}&page_size=50${actorQ}`)
      .then(setData)
  }, [page, actor])

  async function runVerify() {
    setBusy(true); setVerify(null); setErr(null)
    try {
      const r = await api<{ ok: boolean; checked: number; detail?: string }>('/api/audit/verify')
      setVerifyOk(r.ok)
      setVerify(r.ok
        ? `السلسلة سليمة بالكامل — فُحص ${r.checked} سجلاً بتجزئة SHA-256، لا عبث.`
        : `انكسار في السلسلة! ${r.detail ?? ''}`)
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : 'فشل الفحص')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card title="سجل التدقيق المقيَّد بالتجزئة (Append-Only)"
            actions={<Btn kind="gold" onClick={runVerify} disabled={busy}>
              {busy ? 'يفحص…' : 'فحص سلامة السلسلة'}</Btn>}>
        <p className="text-xs text-slate-400 leading-5 mb-1">
          كل حدث مرتبط بسابقه بتجزئة SHA-256 — أي تعديل أو حذف أو إدراج في التاريخ يكسر السلسلة ويكشفه الفاحص فوراً.
          الإجمالي المتراكم: <span className="num font-bold">{data?.chain_records ?? '—'}</span> حدثاً.
        </p>
        {verify && (verifyOk ? <OkNote msg={verify} /> : <ErrorNote msg={verify} />)}
        <ErrorNote msg={err} />
      </Card>

      {actor && (
        <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5 text-sm">
          <span>مرشَّح على المستخدم:</span>
          <span className="num font-bold">{actor}</span>
          <span className="text-xs text-slate-400">— «ماذا فعل هذا الموظف؟» بالكامل</span>
          <Link to="/audit" className="mr-auto text-xs text-sijill-700 hover:underline font-bold">
            ✕ إظهار الكل
          </Link>
        </div>
      )}

      <Card>
        {!data ? <Spinner /> : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-xs border-b">
                  <th className="text-right py-2 font-medium">الوقت (UTC)</th>
                  <th className="text-right font-medium">الفاعل</th>
                  <th className="text-right font-medium">الوحدة</th>
                  <th className="text-right font-medium">الإجراء</th>
                  <th className="text-right font-medium">التفاصيل</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((a) => (
                  <tr key={a.id} className="border-b last:border-0 hover:bg-slate-50">
                    <td className="py-2 num text-xs text-slate-500">{String(a.at).replace('T', ' ').slice(0, 19)}</td>
                    <td className="text-xs">
                      {a.actor}
                      {a.actor_type === 'system' && <Badge tone="slate">نظام</Badge>}
                    </td>
                    <td><Badge tone="blue">{MODULE_AR[a.module] ?? a.module}</Badge></td>
                    <td className="text-xs font-medium">
                      {ACTION_AR[a.action] ?? a.action}
                    </td>
                    <td className="text-xs text-slate-500 max-w-[280px] truncate num">
                      {a.after ? JSON.stringify(a.after) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex items-center justify-between mt-4 text-sm">
              <div className="text-slate-500">الإجمالي: {data.total} — صفحة {page}</div>
              <div className="flex gap-2">
                <Btn kind="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>السابق</Btn>
                <Btn kind="ghost" disabled={page * 50 >= data.total} onClick={() => setPage(page + 1)}>التالي</Btn>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  )
}
