// هيكل التطبيق: شريط جانبي RTL بهوية أثير + شريط علوي بالمستخدم
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'

const NAV = [
  { to: '/', label: 'لوحة القيادة', icon: '◈', end: true },
  { to: '/accounts', label: 'دليل الحسابات', icon: '☷', perm: 'accounts.view' },
  { to: '/journals', label: 'القيود اليومية', icon: '✎', perm: 'journals.view' },
  { to: '/journals/new', label: 'قيد يدوي جديد', icon: '＋', perm: 'journals.manual' },
  { to: '/trial-balance', label: 'ميزان المراجعة', icon: '⚖', perm: 'reports.view' },
  { to: '/ledger', label: 'دفتر الأستاذ', icon: '📖', perm: 'reports.view' },
  { to: '/audit', label: 'سجل التدقيق', icon: '🛡', perm: 'audit.view' },
]

export default function Layout() {
  const { session, logout, has } = useAuth()
  const nav = useNavigate()
  return (
    <div className="min-h-screen bg-slate-100 flex">
      {/* الشريط الجانبي */}
      <aside className="w-64 shrink-0 bg-atheer-950 text-white flex flex-col min-h-screen sticky top-0">
        <div className="px-5 py-6 border-b border-white/10">
          <div className="text-2xl font-black tracking-wide text-gold-400">أثـيــر</div>
          <div className="text-[11px] text-white/50 mt-1">نظام محاسبة الضيافة — النواة</div>
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
                    ? 'bg-atheer-700 text-white font-bold'
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
          قيد الإصدار 0.1.0 — بوابة G1 ✅
        </div>
      </aside>

      {/* المحتوى */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="bg-white border-b border-slate-200 px-6 py-3.5 flex items-center justify-between shadow-sm">
          <div className="text-sm text-slate-500">
            مرحباً <span className="font-bold text-slate-800">{session?.user.full_name}</span>
            <span className="mx-2 text-slate-300">|</span>
            <span className="text-xs bg-atheer-50 text-atheer-700 px-2 py-1 rounded-full border border-atheer-100">
              {session?.user.roles.join('، ') || '—'}
            </span>
          </div>
          <button
            onClick={async () => { await logout(); nav('/login') }}
            className="text-sm text-red-600 hover:bg-red-50 px-3 py-1.5 rounded-lg transition-colors"
          >
            تسجيل الخروج
          </button>
        </header>
        <main className="flex-1 p-6 overflow-x-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
