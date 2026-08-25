import { useEffect, useState } from 'react'
import { backupApi, Backup } from '../backups'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import { useAuth } from '../auth'

function size(bytes: number) {
  if (bytes < 1024) return `${bytes} بايت`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} كيلوبايت`
  return `${(bytes / 1024 / 1024).toFixed(1)} ميغابايت`
}

export default function Backups() {
  const { has } = useAuth()
  const [rows, setRows] = useState<Backup[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try { setRows(await backupApi.list()) }
    catch (e) { setError(e instanceof Error ? e.message : 'تعذر تحميل سجل النسخ') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])

  if (!has('settings.manage')) return <Card title="النسخ الاحتياطي"><p className="text-slate-600">هذه الشاشة متاحة لمدير النظام المخوّل فقط.</p></Card>
  if (loading) return <Spinner />

  const create = async () => {
    setBusy(true); setError(null); setOk(null)
    try { await backupApi.create(); setOk('أُنشئت نسخة احتياطية موثقة بنجاح.'); await load() }
    catch (e) { setError(e instanceof Error ? e.message : 'فشل إنشاء النسخة') }
    finally { setBusy(false) }
  }
  const verify = async (id: string) => {
    setBusy(true); setError(null); setOk(null)
    try { await backupApi.verify(id); setOk('بصمة النسخة سليمة ويمكن استخدامها في وضع الصيانة.'); await load() }
    catch (e) { setError(e instanceof Error ? e.message : 'فشل التحقق من النسخة') }
    finally { setBusy(false) }
  }

  return <div className="space-y-5 max-w-5xl">
    <div className="flex items-start justify-between gap-4">
      <div><h1 className="text-2xl font-black text-slate-800">النسخ الاحتياطي والاستعادة</h1><p className="text-slate-500 mt-1">أنشئ نسخة مشفرة محلياً وتحقق من سلامتها قبل أي ترقية.</p></div>
      <Btn disabled={busy} onClick={() => void create()}>{busy ? 'جارٍ التنفيذ…' : 'إنشاء نسخة الآن'}</Btn>
    </div>
    <ErrorNote msg={error} /><OkNote msg={ok} />
    <Card title="سجل النسخ">
      {rows.length === 0 ? <div className="rounded-xl bg-amber-50 border border-amber-200 text-amber-900 p-4">لا توجد نسخ مسجلة. إنشاء أول نسخة شرط قبل تشغيل عميل حقيقي.</div> : <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-right text-slate-500 border-b"><th className="p-3">الوقت</th><th className="p-3">الملف</th><th className="p-3">الحجم</th><th className="p-3">البصمة</th><th className="p-3">الحالة</th><th className="p-3">إجراء</th></tr></thead><tbody>{rows.map(row => <tr key={row.id} className="border-b last:border-0"><td className="p-3 whitespace-nowrap">{new Date(row.created_at).toLocaleString('ar-YE')}</td><td className="p-3 font-medium">{row.file_name}</td><td className="p-3">{size(row.size_bytes)}</td><td className="p-3 font-mono text-xs" dir="ltr">{row.sha256.slice(0, 16)}…</td><td className="p-3">{row.verified ? <Badge tone="green">سليمة</Badge> : <Badge tone="red">تحتاج تحقق</Badge>}</td><td className="p-3"><Btn kind="ghost" disabled={busy} onClick={() => void verify(row.id)}>تحقق</Btn></td></tr>)}</tbody></table></div>}
    </Card>
    <Card title="ملاحظة الاستعادة"><p className="text-sm text-slate-600">الاستعادة لا تُنفذ من طلب ويب في هذه النسخة؛ ستتم من وضع صيانة موثق بعد إيقاف الخدمة والتحقق من البصمة، لمنع استبدال قاعدة بيانات حية بالخطأ.</p></Card>
  </div>
}
