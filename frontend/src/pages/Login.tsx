import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { HttpError, loadSession } from '../api'
import { changeMyPassword } from '../org'

export default function Login() {
  const { login, logout } = useAuth()
  const nav = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // المدير أنشأ الحساب بكلمة مؤقتة ← أول دخول يفرض استبدالها فوراً (ADR-0037)
  const [forceChange, setForceChange] = useState(false)
  const [next1, setNext1] = useState('')
  const [next2, setNext2] = useState('')

  async function submit(e: FormEvent) {
    e.preventDefault()
    setErr(null); setOk(null)
    setBusy(true)
    try {
      await login(username.trim(), password)
      if (loadSession()?.user.must_change_password) {
        setForceChange(true) // لا تدخل على النظام قبل استبدال الكلمة المؤقتة
      } else {
        nav('/')
      }
    } catch (ex) {
      setErr(ex instanceof HttpError ? ex.message : 'تعذر الاتصال بالخادم')
    } finally {
      setBusy(false)
    }
  }

  async function submitChange(e: FormEvent) {
    e.preventDefault()
    setErr(null)
    if (next1 !== next2) { setErr('تأكيد الكلمة الجديدة غير مطابق'); return }
    setBusy(true)
    try {
      await changeMyPassword(password, next1)
      // الخادم أبطل كل الجلسات (بما فيها هذه) ← نظّف محلياً وأعد الدخول
      await logout()
      setForceChange(false); setPassword(''); setNext1(''); setNext2('')
      setOk('تم تعيين كلمة المرور الجديدة ✔ سجّل الدخول بها الآن.')
    } catch (ex) {
      setErr(ex instanceof HttpError ? `${ex.code}: ${ex.message}` : 'فشل التغيير')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-sijill-950 flex items-center justify-center p-4"
         style={{ backgroundImage: 'radial-gradient(circle at 20% 30%, #0a684955, transparent 45%), radial-gradient(circle at 80% 70%, #d4af3722, transparent 40%)' }}>
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="text-4xl font-black text-gold-400 tracking-wide">سِجِلّ النُّزُل</div>
          <div className="text-white/60 mt-2 text-sm">نظام إدارة الفنادق المتكامل — من تطوير منطق سوفت</div>
        </div>
        {forceChange ? (
          <form onSubmit={submitChange} className="bg-white rounded-3xl shadow-2xl p-8 space-y-5">
            <h1 className="text-xl font-bold text-slate-800 text-center">تعيين كلمة مرور جديدة</h1>
            <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-xl px-4 py-3 text-sm leading-6">
              أهلاً <b>{username}</b> — هذه أول مرة تدخل فيها. المدير أنشأ حسابك بكلمة
              مؤقتة، ويجب استبدالها الآن بكلمة خاصة بك (10 أحرف فأكثر) قبل استخدام النظام.
            </div>
            {err && (
              <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm text-center">
                {err}
              </div>
            )}
            <label className="block">
              <span className="text-sm text-slate-600 mb-1 block">كلمة المرور الجديدة</span>
              <input
                type="password" value={next1} minLength={10}
                onChange={(e) => setNext1(e.target.value)}
                className="w-full border border-slate-300 rounded-xl px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-sijill-500 focus:border-sijill-500"
                autoFocus required autoComplete="new-password"
              />
            </label>
            <label className="block">
              <span className="text-sm text-slate-600 mb-1 block">تأكيد الجديدة</span>
              <input
                type="password" value={next2} minLength={10}
                onChange={(e) => setNext2(e.target.value)}
                className="w-full border border-slate-300 rounded-xl px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-sijill-500 focus:border-sijill-500"
                required autoComplete="new-password"
              />
            </label>
            <button
              type="submit" disabled={busy}
              className="w-full bg-gold-500 hover:bg-gold-600 text-sijill-950 font-bold py-3 rounded-xl transition-colors disabled:opacity-60"
            >
              {busy ? 'جارٍ التعيين…' : 'تعيين ودخول'}
            </button>
            <div className="text-[11px] text-slate-400 text-center leading-5">
              بعد التعيين تُبطل كل الجلسات وتسجّل الدخول بالكلمة الجديدة.
            </div>
          </form>
        ) : (
        <form onSubmit={submit} className="bg-white rounded-3xl shadow-2xl p-8 space-y-5">
          <h1 className="text-xl font-bold text-slate-800 text-center">تسجيل الدخول</h1>
          {err && (
            <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm text-center">
              {err}
            </div>
          )}
          {ok && (
            <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-xl px-4 py-3 text-sm text-center">
              {ok}
            </div>
          )}
          <label className="block">
            <span className="text-sm text-slate-600 mb-1 block">اسم المستخدم</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full border border-slate-300 rounded-xl px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-sijill-500 focus:border-sijill-500"
              autoFocus required autoComplete="username"
            />
          </label>
          <label className="block">
            <span className="text-sm text-slate-600 mb-1 block">كلمة المرور</span>
            <input
              type="password" value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-slate-300 rounded-xl px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-sijill-500 focus:border-sijill-500"
              required autoComplete="current-password"
            />
          </label>
          <button
            type="submit" disabled={busy}
            className="w-full bg-sijill-600 hover:bg-sijill-700 text-white font-bold py-3 rounded-xl transition-colors disabled:opacity-60"
          >
            {busy ? 'جارٍ التحقق…' : 'دخول'}
          </button>
          <div className="text-[11px] text-slate-400 text-center leading-5">
            البيئة التجريبية: admin / admin123!Change
            <br />بعد 5 محاولات خاطئة يُقفل الحساب 10 دقائق (سياسة الأمان)
          </div>
        </form>
        )}
        <div className="text-center text-white/30 text-xs mt-6">
          Sijill Al-Nuzul Hotel ERP © 2026 — MantiqSoft منطق سوفت
        </div>
      </div>
    </div>
  )
}
