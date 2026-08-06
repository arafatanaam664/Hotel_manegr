// نافذة «تغيير كلمة المرور» الذاتية — بعد النجاح تموت كل الجلسات
// ويُعاد الدخول بالكلمة الجديدة (ADR-0037).
import { useState, type FormEvent } from 'react'
import { HttpError } from '../api'
import { changeMyPassword } from '../org'
import { Btn, ErrorNote } from './ui'

const input = 'border rounded-lg px-3 py-2 text-sm w-full bg-white'
const label = 'block text-xs text-slate-500 mb-1'

export default function ChangePasswordModal({ onClose, onDone }: {
  onClose: () => void
  onDone: () => void  // بعد النجاح: الخادم أبطل كل الجلسات ← أعد الدخول
}) {
  const [f, setF] = useState({ cur: '', next: '', again: '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setErr('')
    if (f.next !== f.again) { setErr('تأكيد الكلمة الجديدة غير مطابق'); return }
    setBusy(true)
    try {
      await changeMyPassword(f.cur, f.next)
      alert('غيّرت كلمة المرور بنجاح ✔\nكل الجلسات أُبطلت — سجّل الدخول بالكلمة الجديدة.')
      onDone()
    } catch (ex) {
      setErr(ex instanceof HttpError ? `${ex.code}: ${ex.message}` : 'فشل التغيير')
    } finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
         onClick={onClose}>
      <div className="bg-white rounded-3xl p-6 w-full max-w-md shadow-2xl"
           onClick={(e) => e.stopPropagation()}>
        <h3 className="font-black text-lg mb-4">🔑 تغيير كلمة المرور الخاصة بي</h3>
        <div className="text-[12px] bg-amber-50 border border-amber-200 rounded-lg p-2 mb-3">
          بعد التغيير تُبطل كل الجلسات النشطة (هذا الجهاز والأجهزة الأخرى) ويُطلب
          الدخول من جديد بالكلمة الجديدة.</div>
        <ErrorNote msg={err} />
        <form onSubmit={submit} className="space-y-3 mt-2">
          <label className={label}>كلمة المرور الحالية
            <input className={input} type="password" required value={f.cur}
                   onChange={(e) => setF({ ...f, cur: e.target.value })} /></label>
          <label className={label}>الجديدة (10 أحرف فأكثر)
            <input className={input} type="password" required minLength={10}
                   value={f.next}
                   onChange={(e) => setF({ ...f, next: e.target.value })} /></label>
          <label className={label}>تأكيد الجديدة
            <input className={input} type="password" required minLength={10}
                   value={f.again}
                   onChange={(e) => setF({ ...f, again: e.target.value })} /></label>
          <div className="flex gap-2 pt-1">
            <Btn type="submit" disabled={busy}>تغيير</Btn>
            <Btn kind="ghost" onClick={onClose}>إلغاء</Btn>
          </div>
        </form>
      </div>
    </div>
  )
}
