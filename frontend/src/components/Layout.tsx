// هيكل التطبيق: شريط جانبي RTL بهوية سِجِلّ النُّزُل + شريط علوي بالمستخدم
// + شريط حالة الترخيص الرحيم (ملف 07 §3: تنبيه أصفر بالمهلة، أحمر بالقيد)
import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { licApi, LicenseStatus } from '../license'
import ChangePasswordModal from './ChangePassword'

const NAV = [
  { to: '/', label: 'لوحة القيادة', icon: '◈', end: true },
  { to: '/front-desk', label: 'مكتب الاستقبال', icon: '🛎', perm: 'frontdesk.view' },
  { to: '/reservations', label: 'الحجوزات', icon: '📅', perm: 'reservations.view' },
  { to: '/guests', label: 'النزلاء والشركات', icon: '👤', perm: 'guests.view' },
  { to: '/night-audit', label: 'التدقيق الليلي', icon: '🌙', perm: 'frontdesk.view' },
  { to: '/rooms', label: 'الغرف والأسعار', icon: '🛏', perm: 'frontdesk.view' },
  { to: '/pos', label: 'شاشة البيع', icon: '🍽', perm: 'pos.sell' },
  { to: '/pos/orders', label: 'الطلبات والفواتير', icon: '🧾', perm: 'pos.view' },
  { to: '/pos/shifts', label: 'الورديات وZ', icon: '⏱', perm: 'pos.view' },
  { to: '/pos/catalog', label: 'كتالوج البيع', icon: '🗂', perm: 'pos.view' },
  { to: '/pos/reports', label: 'تقارير البيع', icon: '📈', perm: 'pos.reports' },
  { to: '/inv/catalog', label: 'كتالوج المخزون', icon: '📦', perm: 'inv.view' },
  { to: '/inv/purchasing', label: 'دورة المشتريات', icon: '🛒', perm: 'inv.view' },
  { to: '/inv/operations', label: 'حركة المخزون', icon: '🔄', perm: 'inv.view' },
  { to: '/inv/reports', label: 'تقارير المخزون', icon: '📊', perm: 'inv.reports' },
  { to: '/hr/people', label: 'شؤون الموظفين', icon: '👥', perm: 'hr.view' },
  { to: '/hr/time', label: 'الوقت والحضور', icon: '⏰', perm: 'hr.view' },
  { to: '/hr/payroll', label: 'الرواتب والمسيرات', icon: '💰', perm: 'hr.view' },
  { to: '/hr/reports', label: 'تقارير التوظيف', icon: '📈', perm: 'hr.reports' },
  { to: '/fin/assets', label: 'الأصول الثابتة', icon: '🏭', perm: 'fa.view' },
  { to: '/fin/statements', label: 'القوائم المالية', icon: '🧾', perm: 'reports.view' },
  { to: '/fin/close', label: 'الإقفال والفترات', icon: '🔐', perm: 'periods.close' },
  { to: '/accounts', label: 'دليل الحسابات', icon: '☷', perm: 'accounts.view' },
  { to: '/journals', label: 'القيود اليومية', icon: '✎', perm: 'journals.view' },
  { to: '/journals/new', label: 'قيد يدوي جديد', icon: '＋', perm: 'journals.manual' },
  { to: '/trial-balance', label: 'ميزان المراجعة', icon: '⚖', perm: 'reports.view' },
  { to: '/ledger', label: 'دفتر الأستاذ', icon: '📖', perm: 'reports.view' },
  { to: '/audit', label: 'سجل التدقيق', icon: '🛡', perm: 'audit.view' },
  { to: '/sync', label: 'مركز المزامنة', icon: '🔄', perm: 'sync.view' },
  { to: '/users', label: 'المستخدمون والصلاحيات', icon: '👥', perm: 'users.manage' },
  { to: '/license', label: 'حالة الترخيص', icon: '🔑' },
]

/** شريط تنبيه الترخيص: أصفر بالمهلة (كل شيء يعمل)، أحمر بالقيد/القفل —
 تُحدَّث كل 5 دقائق ولا تعرقل التقارير والتصدير أبداً (07 §3). */
function LicenseBanner() {
  const [st, setSt] = useState<LicenseStatus | null>(null)
  useEffect(() => {
    let alive = true
    const tick = () => licApi.status()
      .then(s => { if (alive) setSt(s) }).catch(() => {})
    tick()
    const t = setInterval(tick, 5 * 60 * 1000)
    return () => { alive = false; clearInterval(t) }
  }, [])
  if (!st) return null
  const days = st.days_to_expire
  if (st.state === 'GRACE') {
    return (
      <div className="bg-amber-100 border-b border-amber-300 text-amber-900 px-6 py-2 text-sm flex items-center justify-between">
        <span>⚠️ انتهى الاشتراك — أنت في مهلة التجديد (حتى {st.grace_until}).
          كل شيء يعمل الآن؛ جدّد لتفادي وضع القراءة فقط.</span>
        <Link to="/license" className="font-bold underline shrink-0">التجديد الآن</Link>
      </div>
    )
  }
  if (st.state === 'READ_ONLY' || st.state === 'REVOKED' || st.state === 'INVALID') {
    return (
      <div className="bg-red-100 border-b border-red-300 text-red-900 px-6 py-2 text-sm flex items-center justify-between">
        <span>🔒 النظام في وضع القراءة فقط — التقارير والطباعة والتصدير تعمل
          كاملة؛ إضافة العمليات موقوفة حتى التجديد.</span>
        <Link to="/license" className="font-bold underline shrink-0">تفاصيل الترخيص</Link>
      </div>
    )
  }
  if (st.state === 'SUSPENDED' || st.state === 'CLOCK_LOCK') {
    return (
      <div className="bg-red-800 text-white px-6 py-2 text-sm flex items-center justify-between">
        <span>⛔ {st.status_reason}</span>
        <Link to="/license" className="font-bold underline shrink-0">حالة الترخيص</Link>
      </div>
    )
  }
  if (st.state === 'TRIAL' && days !== null && days <= 14) {
    return (
      <div className="bg-sky-50 border-b border-sky-200 text-sky-900 px-6 py-2 text-sm flex items-center justify-between">
        <span>🧪 الفترة التجريبية تنتهي بعد {days} يوم.</span>
        <Link to="/license" className="font-bold underline shrink-0">تفعيل الترخيص</Link>
      </div>
    )
  }
  return null
}

export default function Layout() {
  const { session, logout, has } = useAuth()
  const nav = useNavigate()
  const [cpOpen, setCpOpen] = useState(false)
  return (
    <div className="min-h-screen bg-slate-100 flex">
      {/* الشريط الجانبي */}
      <aside className="w-64 shrink-0 bg-sijill-950 text-white flex flex-col min-h-screen sticky top-0">
        <div className="px-5 py-6 border-b border-white/10">
          <div className="text-2xl font-black tracking-wide text-gold-400">سِجِلّ النُّزُل</div>
          <div className="text-[11px] text-white/50 mt-1">إدارة الفنادق — محاسبة وتشغيل</div>
        </div>
        <nav className="flex-1 py-4 px-3 space-y-1">
          {NAV.filter((n) => !n.perm || has(n.perm)).map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm transition-colors ${
                  isActive
                    ? 'bg-sijill-700 text-white font-bold'
                    : 'text-white/70 hover:bg-white/5 hover:text-white'
                }`
              }
            >
              <span className="w-5 text-center opacity-80">{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-4 border-t border-white/10 text-[11px] text-white/40">
          إصدار 0.13.0 — منطق سوفت | بوابات G1..G10 ✅ + الغرف والأجنحة والمستخدمون
        </div>
      </aside>

      {/* المحتوى */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="bg-white border-b border-slate-200 px-6 py-3.5 flex items-center justify-between shadow-sm">
          <div className="text-sm text-slate-500">
            مرحباً <span className="font-bold text-slate-800">{session?.user.full_name}</span>
            <span className="mx-2 text-slate-300">|</span>
            <span className="text-xs bg-sijill-50 text-sijill-700 px-2 py-1 rounded-full border border-sijill-100">
              {session?.user.roles.join('، ') || '—'}
            </span>
          </div>
          <button
            onClick={() => setCpOpen(true)}
            className="text-sm text-sijill-700 hover:bg-sijill-50 px-3 py-1.5 rounded-lg transition-colors"
            title="تغيير كلمة المرور الخاصة بي"
          >
            🔑 كلمة المرور
          </button>
          <button
            onClick={async () => { await logout(); nav('/login') }}
            className="text-sm text-red-600 hover:bg-red-50 px-3 py-1.5 rounded-lg transition-colors"
          >
            تسجيل الخروج
          </button>
        </header>
        <LicenseBanner />
        <main className="flex-1 p-6 overflow-x-auto">
          <Outlet />
        </main>
      </div>
      {cpOpen && <ChangePasswordModal onClose={() => setCpOpen(false)}
        onDone={async () => { setCpOpen(false); await logout(); nav('/login') }} />}
    </div>
  )
}
