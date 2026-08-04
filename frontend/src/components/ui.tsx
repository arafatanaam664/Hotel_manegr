// مكوّنات واجهة صغيرة مشتركة
import type { ReactNode } from 'react'

export function Card({ title, children, actions }: {
  title?: string
  children: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
      {title && (
        <div className="px-5 py-3.5 border-b border-slate-100 flex items-center justify-between">
          <h3 className="font-bold text-slate-700">{title}</h3>
          {actions}
        </div>
      )}
      <div className="p-5">{children}</div>
    </div>
  )
}

export function Btn({ children, kind = 'primary', ...rest }: {
  children: ReactNode
  kind?: 'primary' | 'ghost' | 'danger' | 'gold'
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const cls = {
    primary: 'bg-atheer-600 hover:bg-atheer-700 text-white',
    gold: 'bg-gold-500 hover:bg-gold-600 text-atheer-950 font-bold',
    ghost: 'bg-slate-100 hover:bg-slate-200 text-slate-700',
    danger: 'bg-red-600 hover:bg-red-700 text-white',
  }[kind]
  return (
    <button
      {...rest}
      className={`px-4 py-2 rounded-xl text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${cls} ${rest.className ?? ''}`}
    >
      {children}
    </button>
  )
}

export function Badge({ children, tone = 'slate' }: {
  children: ReactNode
  tone?: 'green' | 'red' | 'amber' | 'slate' | 'blue'
}) {
  const cls = {
    green: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    red: 'bg-red-50 text-red-700 border-red-200',
    amber: 'bg-amber-50 text-amber-700 border-amber-200',
    slate: 'bg-slate-50 text-slate-600 border-slate-200',
    blue: 'bg-sky-50 text-sky-700 border-sky-200',
  }[tone]
  return (
    <span className={`inline-block px-2.5 py-0.5 text-xs rounded-full border ${cls}`}>
      {children}
    </span>
  )
}

export function Spinner() {
  return (
    <div className="flex items-center justify-center py-16 text-atheer-600">
      <svg className="animate-spin h-8 w-8" viewBox="0 0 24 24" fill="none">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-90" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
      </svg>
    </div>
  )
}

export function ErrorNote({ msg }: { msg: string | null }) {
  if (!msg) return null
  return (
    <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm my-3">
      {msg}
    </div>
  )
}

export function OkNote({ msg }: { msg: string | null }) {
  if (!msg) return null
  return (
    <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-xl px-4 py-3 text-sm my-3">
      {msg}
    </div>
  )
}

export function statusBadge(s: string) {
  if (s === 'POSTED') return <Badge tone="green">مرحَّل</Badge>
  if (s === 'REVERSED') return <Badge tone="amber">معكوس</Badge>
  if (s === 'DRAFT') return <Badge tone="slate">مسودة</Badge>
  if (s === 'OPEN') return <Badge tone="green">مفتوحة</Badge>
  if (s === 'CLOSED') return <Badge tone="red">مُقفلة</Badge>
  return <Badge>{s}</Badge>
}

export const JTYPE_AR: Record<string, string> = {
  MANUAL: 'يدوي',
  REVERSAL: 'عكس',
  OPENING: 'افتتاحي',
  CLOSING: 'إقفال',
  AUTO_ROOM: 'آلي — غرف',
  AUTO_POS: 'آلي — مبيعات',
  AUTO_PURCHASE: 'آلي — مشتريات',
  AUTO_PAYROLL: 'آلي — رواتب',
  AUTO_DEPRECIATION: 'آلي — إهلاك',
  AUTO_TAX: 'آلي — ضريبة',
}
