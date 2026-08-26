// الأصول الثابتة: سجل + إعدام + تشغيلات إهلاك شهرية #24 + مطابقة الأستاذ
import { Fragment, useCallback, useEffect, useState } from 'react'
import { fmt, todayISO } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import type { FaAsset, FaRegister, FaRun } from '../fa'
import { FA_METHOD_AR, finApi } from '../fa'

const TABS = ['السجل', 'تشغيلات الإهلاك'] as const
const inp = 'border border-slate-300 rounded-lg px-2 py-1.5 text-sm'
const th = 'px-3 py-2 text-right text-xs text-slate-500 font-semibold'
const td = 'px-3 py-2 text-sm'

export default function FinAssets() {
  const { has } = useAuth()
  const canManage = has('fa.manage')
  const [tab, setTab] = useState<string>(TABS[0])
  const [month, setMonth] = useState(todayISO().slice(0, 7))
  const [reg, setReg] = useState<FaRegister | null>(null)
  const [runs, setRuns] = useState<FaRun[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ name: '', category: '',
    purchase_date: todayISO(), cost: '', salvage: '0', life: '60',
    method: 'STRAIGHT', asset_account_code: '1520' })
  const [schedFor, setSchedFor] = useState<string | null>(null)
  const [sched, setSched] = useState<{ month: string; charge: string;
    acc_dep: string; nbv: string }[]>([])

  const refresh = useCallback(async () => {
    const [rg, rs] = await Promise.all([finApi.register(), finApi.runs()])
    setReg(rg); setRuns(rs)
  }, [])
  useEffect(() => { refresh().catch((e) => setErr((e as Error).message)) },
             [refresh])

  const run = async (fn: () => Promise<void>, okMsg: string) => {
    setErr(null); setOk(null); setBusy(true)
    try { await fn(); setOk(okMsg); await refresh() }
    catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }
  const loadSched = async (a: FaAsset) => {
    if (schedFor === a.id) { setSchedFor(null); return }
    setSchedFor(a.id)
    try {
      const r = await finApi.schedule(a.id, month)
      setSched(r.schedule)
    } catch (e) { setErr((e as Error).message) }
  }

  return (
    <div className='space-y-4'>
      <div className='flex gap-2 flex-wrap items-center'>
        {TABS.map((t) => (
          <Btn key={t} kind={tab === t ? 'primary' : 'ghost'}
            onClick={() => { setTab(t); setErr(null); setOk(null) }}>{t}</Btn>))}
        <span className='ms-4'>
          <input className={inp} type='month' value={month}
            onChange={(e) => setMonth(e.target.value)} /></span>
      </div>
      <ErrorNote msg={err} />
      <OkNote msg={ok} />
      {busy && <Spinner />}

      {tab === TABS[0] && (
        <>
          {canManage && (
            <Card title='تسجيل أصل — الإهلاك يبدأ من الشهر التالي للشراء ويتوقف عند الخردة (قيد الشراء نفسه يومي يدوي)'>
              <div className='flex gap-2 flex-wrap items-center'>
                <input className={inp} placeholder='اسم الأصل *' value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
                <input className={inp + ' w-28'} placeholder='الفئة' value={form.category}
                  onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))} />
                <input className={inp} type='date' value={form.purchase_date}
                  onChange={(e) => setForm((f) => ({ ...f, purchase_date: e.target.value }))} />
                <input className={inp + ' w-24'} placeholder='التكلفة *' type='number'
                  value={form.cost}
                  onChange={(e) => setForm((f) => ({ ...f, cost: e.target.value }))} />
                <input className={inp + ' w-20'} placeholder='الخردة' type='number'
                  value={form.salvage}
                  onChange={(e) => setForm((f) => ({ ...f, salvage: e.target.value }))} />
                <input className={inp + ' w-20'} placeholder='العمر/شهر' type='number'
                  value={form.life}
                  onChange={(e) => setForm((f) => ({ ...f, life: e.target.value }))} />
                <select className={inp} value={form.method}
                  onChange={(e) => setForm((f) => ({ ...f, method: e.target.value }))}>
                  {Object.entries(FA_METHOD_AR).map(([k, v]) =>
                    <option key={k} value={k}>{v}</option>)}
                </select>
                <select className={inp} value={form.asset_account_code}
                  title='حساب الأصل'
                  onChange={(e) => setForm((f) => ({ ...f,
                    asset_account_code: e.target.value }))}>
                  <option value='1510'>1510 أراضٍ ومباني</option>
                  <option value='1520'>1520 أثاث وتجهيزات</option>
                  <option value='1530'>1530 أجهزة ومعدات</option>
                  <option value='1540'>1540 وسائل نقل</option>
                </select>
                <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                  await finApi.createAsset({
                    ...form, cost: parseFloat(form.cost || '0'),
                    salvage: parseFloat(form.salvage || '0'),
                    useful_life_months: parseInt(form.life || '1') })
                }, 'سُجل الأصل — سيدخل تشغيلة الشهر المستحق')}>تسجيل</Btn>
              </div>
            </Card>)}
          <Card title={`سجل الأصول (${reg?.rows.length ?? 0})`}
            actions={reg && (
              <Badge tone={reg.matches_gl ? 'green' : 'amber'}>
                {reg.matches_gl
                  ? 'صافي السجل = الأستاذ ✓'
                  : 'السجل ≠ الأستاذ — قيود شراء ناقصة'}</Badge>)}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الرمز</th><th className={th}>الأصل</th>
                <th className={th}>الشراء</th><th className={th}>التكلفة</th>
                <th className={th}>المجمع</th><th className={th}>الدفترية</th>
                <th className={th}>الطريقة/العمر</th><th className={th}>آخر شهر</th>
                <th className={th}>إجراءات</th></tr></thead>
              <tbody>
                {(reg?.rows ?? []).map((a) => (
                  <Fragment key={a.id}>
                    <tr className={`border-b border-slate-50 ${a.status === 'DISPOSED' ? 'opacity-50' : ''}`}>
                      <td className={`${td} font-mono`}>{a.code}</td>
                      <td className={td}>{a.name}
                        {a.status === 'DISPOSED' &&
                          <Badge tone='red'> مُعدَم {a.disposed_at}</Badge>}</td>
                      <td className={`${td} font-mono text-xs`}>{a.purchase_date}</td>
                      <td className={`${td} font-mono`}>{fmt(a.cost)}</td>
                      <td className={`${td} font-mono text-red-700`}>({fmt(a.depreciated_total)})</td>
                      <td className={`${td} font-mono font-bold`}>{fmt(a.nbv)}</td>
                      <td className={`${td} text-xs`}>{FA_METHOD_AR[a.method]} / {a.life_months}ش</td>
                      <td className={`${td} font-mono text-xs`}>{a.last_run_month ?? '—'}</td>
                      <td className={td}>
                        <div className='flex gap-1'>
                          <Btn kind='ghost' className='!px-2 !py-1 text-xs'
                            onClick={() => loadSched(a)}>جدولة 📅</Btn>
                          {a.status === 'ACTIVE' && canManage && (
                            <Btn kind='danger' className='!px-2 !py-1 text-xs'
                              onClick={() => {
                                const reason = window.prompt('سبب الإعدام (موثق):')?.trim()
                                if (reason) run(async () => {
                                  await finApi.disposeAsset(a.id, {
                                    disposed_at: todayISO(), reason })
                                }, 'أُعدم — توقف إهلاكه (إخراجه من الدفاتر قيد يدوي)')
                              }}>إعدام</Btn>)}
                        </div>
                      </td>
                    </tr>
                    {schedFor === a.id && (
                      <tr className='bg-slate-50/60'>
                        <td colSpan={9} className='px-4 py-2'>
                          <div className='text-xs text-slate-500 mb-1'>
                            إسقاط 12 شهراً من {month} (استشرافي — لا يُرحَّل):</div>
                          <div className='flex gap-1.5 flex-wrap'>
                            {sched.map((s) => (
                              <div key={s.month}
                                className='border border-slate-200 rounded-lg px-2 py-1 text-center'>
                                <div className='text-[10px] font-mono text-slate-400'>{s.month}</div>
                                <div className='text-xs font-mono font-bold'>{fmt(s.charge)}</div>
                                <div className='text-[10px] font-mono text-slate-500'>
                                  دفترية {fmt(s.nbv)}</div>
                              </div>))}
                          </div>
                        </td>
                      </tr>)}
                  </Fragment>))}
                {reg && !reg.rows.length && (
                  <tr><td className={td} colSpan={9}>لا أصول بعد</td></tr>)}
              </tbody>
              {reg && reg.rows.length > 0 && (
                <tfoot><tr className='border-t border-slate-200 font-bold'>
                  <td className={td} colSpan={3}>الإجمالي (فعّالة)</td>
                  <td className={`${td} font-mono`}>{fmt(reg.totals.cost)}</td>
                  <td className={`${td} font-mono text-red-700`}>({fmt(reg.totals.depreciated)})</td>
                  <td className={`${td} font-mono`}>{fmt(reg.totals.nbv)}</td>
                  <td colSpan={3} className={`${td} text-xs font-normal text-slate-500`}>
                    الأستاذ: {fmt(reg.gl.asset_accounts_cost)} − {fmt(reg.gl.accum_depreciation)} = {fmt(reg.gl.nbv)}</td>
                </tr></tfoot>)}
            </table>
            <div className='mt-2 text-xs text-slate-500'>{reg?.note}</div>
          </Card>
        </>
      )}

      {tab === TABS[1] && (
        <>
          {canManage && (
            <Card title='تشغيلة إهلاك شهرية — قيد #24 (7101/1590) ذري من المحرك؛ كل شهر يُشغَّل مرة واحدة فقط'>
              <div className='flex gap-2 items-center flex-wrap'>
                <span className='text-sm'>تشغيل إهلاك شهر</span>
                <b className='font-mono'>{month}</b>
                <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                  const r = await finApi.runMonth(month)
                  setOk(`#24 لـ${month}: ${fmt(r.total)} لـ${r.asset_count} أصلاً — قيد مرحَّل`)
                }, '')}>تشغيل ▶</Btn>
                <span className='text-xs text-slate-500'>
                  إعادة التشغيل لنفس الشهر تُرفض (قيد فريد + آخر شهر محفوظ لكل أصل).</span>
              </div>
            </Card>)}
          <Card title={`التشغيلات (${runs.length})`}>
            {runs.map((r) => (
              <details key={r.id} className='border border-slate-100 rounded-lg mb-2'>
                <summary className='px-3 py-2 cursor-pointer flex gap-3 items-center'>
                  <Badge tone='blue'>{r.month}</Badge>
                  <span className='font-mono text-sm'>{r.asset_count} أصلاً</span>
                  <b className='font-mono text-emerald-700'>{fmt(r.total)}</b>
                  {r.posted_entry_id && <span className='text-emerald-700 text-xs'>#24✓ مرحَّل</span>}
                </summary>
                <div className='px-3 pb-2'>
                  <table className='w-full'>
                    <thead><tr className='border-b border-slate-100'>
                      <th className={th}>الأصل</th><th className={th}>الطريقة</th>
                      <th className={th}>دفترية قبل</th><th className={th}>القسط</th>
                      <th className={th}>دفترية بعد</th></tr></thead>
                    <tbody>
                      {r.lines.map((l, i) => (
                        <tr key={i} className='border-b border-slate-50'>
                          <td className={td}>{l.code} — {l.name}</td>
                          <td className={`${td} text-xs`}>{FA_METHOD_AR[l.method]}</td>
                          <td className={`${td} font-mono`}>{fmt(l.nbv_before)}</td>
                          <td className={`${td} font-mono font-bold text-red-700`}>{fmt(l.charge)}</td>
                          <td className={`${td} font-mono`}>{fmt(l.nbv_after)}</td>
                        </tr>))}
                    </tbody>
                  </table>
                </div>
              </details>
            ))}
            {!runs.length && <div className='text-sm text-slate-500'>
              لا تشغيلات بعد — سيّر أول تشغيلة من الأعلى</div>}
          </Card>
        </>
      )}
    </div>
  )
}
