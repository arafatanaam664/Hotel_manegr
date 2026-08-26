// تقارير المخزون: أرصدة قيمية تطابق الأستاذ يومياً / تنبيهات / حركة /
// مشتريات وأداء موردين وفروقات أسعار / هالك شهري واستهلاك نظري↔فعلي / سياسة
// — ملف 05 §6
import { useCallback, useEffect, useState } from 'react'
import { fmt, todayISO } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import type { Alerts, MoveRow, Policy, StockValueReport, Warehouse } from '../inv'
import { invApi, MOVE_REASON_AR } from '../inv'

const TABS = ['الأرصدة والمطابقة', 'التنبيهات', 'حركة المخزون',
  'المشتريات والموردون', 'الهالك والاستهلاك', 'السياسة'] as const

const inp = 'border border-slate-300 rounded-lg px-2 py-1.5 text-sm'
const th = 'px-3 py-2 text-right text-xs text-slate-500 font-semibold'
const td = 'px-3 py-2 text-sm'

export default function InvReports() {
  const { has } = useAuth()
  const canPolicy = has('inv.policy.manage')
  const [tab, setTab] = useState<string>(TABS[0])
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])

  const [whFilter, setWhFilter] = useState('')
  const [sv, setSv] = useState<StockValueReport | null>(null)
  const [alerts, setAlerts] = useState<Alerts | null>(null)
  const [moves, setMoves] = useState<MoveRow[] | null>(null)
  const [mvFilter, setMvFilter] = useState({ warehouse_id: '', reason: '', date_from: '', date_to: '' })
  const [pFrom, setPFrom] = useState(todayISO().slice(0, 8) + '01')
  const [pTo, setPTo] = useState(todayISO())
  const [purchases, setPurchases] = useState<Record<string, unknown>[] | null>(null)
  const [perf, setPerf] = useState<Record<string, unknown>[] | null>(null)
  const [ppv, setPpv] = useState<Record<string, unknown>[] | null>(null)
  const [wasteR, setWasteR] = useState<{ months: { month: string; moves: number; qty: string; value: string }[] } | null>(null)
  const [consume, setConsume] = useState<{ rows: Record<string, unknown>[]; note: string } | null>(null)
  const [policy, setPolicy] = useState<Policy | null>(null)
  const [policyForm, setPolicyForm] = useState<Record<string, string>>({})

  const run = async (fn: () => Promise<void>, okMsg = '') => {
    setErr(null); setOk(null); setBusy(true)
    try { await fn(); if (okMsg) setOk(okMsg) }
    catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }

  const loadTab = useCallback(async (t: string) => {
    setErr(null)
    try {
      if (t === TABS[0]) setSv(await invApi.stockValue(whFilter))
      else if (t === TABS[1]) setAlerts(await invApi.alerts())
      else if (t === TABS[2]) setMoves(await invApi.moves({}))
      else if (t === TABS[3]) {
        const [pu, pe, pp] = await Promise.all([
          invApi.purchases(pFrom, pTo), invApi.supplierPerf(), invApi.ppv(pFrom, pTo)])
        setPurchases(pu as never[]); setPerf(pe as never[]); setPpv(pp as never[])
      } else if (t === TABS[4]) {
        const [w, c] = await Promise.all([invApi.wasteReport(), invApi.consumption(pFrom, pTo)])
        setWasteR(w); setConsume(c as never)
      } else if (t === TABS[5]) {
        const p = await invApi.policy()
        setPolicy(p)
        setPolicyForm({
          po_l0_limit: p.po_l0_limit, po_l1_limit: p.po_l1_limit,
          price_tolerance_pct: p.price_tolerance_pct,
          qty_tolerance_pct: p.qty_tolerance_pct,
          num0: String(p.expiry_windows[0] ?? 30), num1: String(p.expiry_windows[1] ?? 15),
          num2: String(p.expiry_windows[2] ?? 7), num_stag: String(p.stagnant_days),
          num_cons: String(p.consumption_days),
        })
      }
    } catch (e) { setErr((e as Error).message) }
  }, [whFilter, pFrom, pTo])

  useEffect(() => {
    invApi.warehouses().then(setWarehouses).catch(() => {})
    loadTab(TABS[0])
  }, [loadTab])

  const switchTab = (t: string) => { setTab(t); setOk(null); loadTab(t) }

  return (
    <div className='space-y-4'>
      <div className='flex gap-2 flex-wrap'>
        {TABS.map((t) => (
          <Btn key={t} kind={tab === t ? 'primary' : 'ghost'}
            onClick={() => switchTab(t)} disabled={busy}>{t}</Btn>))}
      </div>
      <ErrorNote msg={err} />
      <OkNote msg={ok} />
      {busy && <Spinner />}

      {/* ==================== الأرصدة والمطابقة ==================== */}
      {tab === TABS[0] && sv && !busy && (
        <>
          <Card title='المطابقة اليومية: قيمة المخزون = أرصدة حسابات 12xx (قبول-2)'
            actions={
              <select className={inp} value={whFilter} onChange={(e) => { setWhFilter(e.target.value) }}>
                <option value=''>كل المستودعات</option>
                {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name_ar}</option>)}
              </select>
            }>
            <div className={`rounded-xl px-4 py-3 mb-4 text-sm font-bold border ${
              sv.all_matched
                ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                : 'bg-red-50 border-red-200 text-red-800'}`}>
              {sv.all_matched
                ? '✅ كل حسابات المخزون مطابقة لدفتر الأستاذ — المخزون المرصود يساوي المدون مالياً'
                : '⛔ يوجد فرق بين المخزون المرصود وحسابات الأستاذ — راجع سجل الحركات فوراً'}
            </div>
            <table className='w-full mb-4'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الحساب</th><th className={th}>قيمة الأرصدة</th>
                <th className={th}>رصيد الأستاذ</th><th className={th}>الفرق</th><th className={th}></th>
              </tr></thead>
              <tbody>
                {sv.accounts_match.map((a) => (
                  <tr key={a.account_code} className='border-b border-slate-50'>
                    <td className={`${td} font-mono font-bold`}>{a.account_code}</td>
                    <td className={`${td} font-mono`}>{fmt(a.stock_value)}</td>
                    <td className={`${td} font-mono`}>{fmt(a.ledger_balance)}</td>
                    <td className={`${td} font-mono ${parseFloat(a.diff) ? 'text-red-700 font-bold' : ''}`}>{fmt(a.diff, 4)}</td>
                    <td className={td}>{a.matched
                      ? <Badge tone='green'>مطابق</Badge> : <Badge tone='red'>فرق!</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>المستودع</th><th className={th}>الصنف</th><th className={th}>الكمية</th>
                <th className={th}>متوسط التكلفة</th><th className={th}>القيمة</th>
              </tr></thead>
              <tbody>
                {sv.rows.map((r) => (
                  <tr key={r.warehouse_id + r.item_id} className='border-b border-slate-50'>
                    <td className={td}>{r.warehouse} <span className='text-xs text-slate-400'>({r.account_code})</span></td>
                    <td className={td}>{r.item_code} — {r.item_name} <span className='text-xs text-slate-400'>{r.unit}</span></td>
                    <td className={`${td} font-mono`}>{fmt(r.qty, 0)}</td>
                    <td className={`${td} font-mono`}>{fmt(r.avg_cost, 4)}</td>
                    <td className={`${td} font-mono font-bold`}>{fmt(r.value)}</td>
                  </tr>
                ))}
                {!sv.rows.length && <tr><td className={td} colSpan={5}>لا أرصدة</td></tr>}
                <tr className='bg-sijill-50 font-bold'>
                  <td className={td} colSpan={4}>الإجمالي</td>
                  <td className={`${td} font-mono`}>
                    {fmt(sv.rows.reduce((s, r) => s + parseFloat(r.value), 0))}</td>
                </tr>
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ==================== التنبيهات ==================== */}
      {tab === TABS[1] && alerts && !busy && (
        <>
          {!alerts.ledger_ok && (
            <div className='bg-red-50 border border-red-200 text-red-800 rounded-xl px-4 py-3 text-sm font-bold'>
              ⛔ خلل مطابقة ليلي مكتشف — حسابات: {alerts.ledger_mismatch.map((m) => `${m.account_code} (فرق ${fmt(m.diff, 4)})`).join('، ')}
            </div>
          )}
          <Card title={`تحت حد إعادة الطلب (${alerts.reorder.length}) — اقتراح أمر شراء = العجز حتى الأمان + معدل استهلاك ${policy?.consumption_days ?? 30} يوم`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الصنف</th><th className={th}>المتاح</th><th className={th}>حد الطلب</th>
                <th className={th}>الأمان</th><th className={th}>متوسط يومي</th><th className={th}>المقترح</th>
              </tr></thead>
              <tbody>
                {alerts.reorder.map((r) => (
                  <tr key={r.item_id} className='border-b border-slate-50'>
                    <td className={td}>{r.code} — {r.name} <span className='text-xs text-slate-400'>{r.unit}</span></td>
                    <td className={`${td} font-mono font-bold text-red-700`}>{fmt(r.on_hand, 0)}</td>
                    <td className={`${td} font-mono`}>{fmt(r.reorder_level, 0)}</td>
                    <td className={`${td} font-mono`}>{fmt(r.safety_level, 0)}</td>
                    <td className={`${td} font-mono text-xs`}>{fmt(r.avg_daily_consumption, 2)}</td>
                    <td className={`${td} font-mono font-bold text-sijill-700`}>{fmt(r.suggested_qty, 0)}</td>
                  </tr>
                ))}
                {!alerts.reorder.length && <tr><td className={td} colSpan={6}>✅ لا أصناف تحت حد الطلب</td></tr>}
              </tbody>
            </table>
          </Card>
          <Card title={`تنبيهات الصلاحية (${alerts.expiry.length}) — نوافذ 30/15/7 يوم`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الصنف</th><th className={th}>المستودع</th><th className={th}>الدفعة</th>
                <th className={th}>الصلاحية</th><th className={th}>المتبقي</th><th className={th}>الكمية</th>
              </tr></thead>
              <tbody>
                {alerts.expiry.map((e, i) => (
                  <tr key={i} className='border-b border-slate-50'>
                    <td className={td}>{e.code} — {e.name}</td>
                    <td className={td}>{e.warehouse}</td>
                    <td className={`${td} font-mono`}>{e.batch_no || '—'}</td>
                    <td className={`${td} font-mono`}>{e.expiry_date}</td>
                    <td className={td}>
                      <Badge tone={e.days_left <= 7 ? 'red' : e.days_left <= 15 ? 'amber' : 'blue'}>
                        {e.days_left} يوم</Badge>
                    </td>
                    <td className={`${td} font-mono`}>{fmt(e.qty, 0)}</td>
                  </tr>
                ))}
                {!alerts.expiry.length && <tr><td className={td} colSpan={6}>✅ لا صلاحيات قريبة</td></tr>}
              </tbody>
            </table>
          </Card>
          <Card title={`أصناف راكدة (${alerts.stagnant.length}) — بلا حركة ≥ ${policy?.stagnant_days ?? 90} يوم`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الصنف</th><th className={th}>الكمية</th>
                <th className={th}>آخر حركة</th><th className={th}>أيام الركود</th>
              </tr></thead>
              <tbody>
                {alerts.stagnant.map((s) => (
                  <tr key={s.item_id} className='border-b border-slate-50'>
                    <td className={td}>{s.code} — {s.name}</td>
                    <td className={`${td} font-mono`}>{fmt(s.qty, 0)}</td>
                    <td className={`${td} font-mono text-xs`}>{s.last_move_date ?? 'بلا حركة إطلاقاً'}</td>
                    <td className={td}>{s.idle_days !== null
                      ? <Badge tone='amber'>{s.idle_days} يوم</Badge> : <Badge tone='red'>منذ البداية</Badge>}</td>
                  </tr>
                ))}
                {!alerts.stagnant.length && <tr><td className={td} colSpan={4}>✅ لا راكد</td></tr>}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ==================== حركة المخزون ==================== */}
      {tab === TABS[2] && !busy && (
        <Card title='سجل حركة المخزون (كمية × تكلفة لحظتها × مستند × دفعة)'
          actions={<Btn kind='ghost' onClick={() => run(async () =>
            setMoves(await invApi.moves(Object.fromEntries(
              Object.entries(mvFilter).filter(([, v]) => v)) as Record<string, string>)))}>تطبيق الفلتر</Btn>}>
          <div className='flex gap-2 flex-wrap mb-3'>
            <select className={inp} value={mvFilter.warehouse_id}
              onChange={(e) => setMvFilter((f) => ({ ...f, warehouse_id: e.target.value }))}>
              <option value=''>كل المستودعات</option>
              {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name_ar}</option>)}
            </select>
            <select className={inp} value={mvFilter.reason}
              onChange={(e) => setMvFilter((f) => ({ ...f, reason: e.target.value }))}>
              <option value=''>كل الأسباب</option>
              {Object.entries(MOVE_REASON_AR).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <input className={inp} type='date' value={mvFilter.date_from}
              onChange={(e) => setMvFilter((f) => ({ ...f, date_from: e.target.value }))} />
            <input className={inp} type='date' value={mvFilter.date_to}
              onChange={(e) => setMvFilter((f) => ({ ...f, date_to: e.target.value }))} />
          </div>
          <table className='w-full'>
            <thead><tr className='border-b border-slate-100'>
              <th className={th}>التاريخ</th><th className={th}>المستودع</th><th className={th}>الصنف</th>
              <th className={th}>الكمية</th><th className={th}>التكلفة</th><th className={th}>القيمة</th>
              <th className={th}>السبب</th><th className={th}>الدفعة/الصلاحية</th>
            </tr></thead>
            <tbody>
              {(moves ?? []).map((m) => (
                <tr key={m.id} className='border-b border-slate-50'>
                  <td className={`${td} font-mono text-xs`}>{m.business_date}</td>
                  <td className={td}>{m.warehouse}</td>
                  <td className={td}>{m.item_code} — {m.item_name}</td>
                  <td className={`${td} font-mono font-bold ${parseFloat(m.qty_delta) < 0 ? 'text-red-700' : 'text-emerald-700'}`}>
                    {parseFloat(m.qty_delta) > 0 ? '+' : ''}{fmt(m.qty_delta, 0)}</td>
                  <td className={`${td} font-mono text-xs`}>{fmt(m.unit_cost, 4)}</td>
                  <td className={`${td} font-mono`}>{fmt(m.value_delta)}</td>
                  <td className={td}><Badge tone='slate'>{MOVE_REASON_AR[m.reason] ?? m.reason}</Badge></td>
                  <td className={`${td} font-mono text-xs`}>{m.batch_no || '—'}{m.expiry_date ? ` / ${m.expiry_date}` : ''}</td>
                </tr>
              ))}
              {moves && !moves.length && <tr><td className={td} colSpan={8}>لا حركات بالنطاق</td></tr>}
            </tbody>
          </table>
        </Card>
      )}

      {/* ==================== المشتريات والموردون ==================== */}
      {tab === TABS[3] && !busy && (
        <>
          <Card title='مشتريات المورد خلال الفترة'
            actions={
              <div className='flex gap-2 items-center'>
                <input className={inp} type='date' value={pFrom} onChange={(e) => setPFrom(e.target.value)} />
                <input className={inp} type='date' value={pTo} onChange={(e) => setPTo(e.target.value)} />
                <Btn kind='ghost' onClick={() => loadTab(TABS[3])}>تحديث</Btn>
              </div>
            }>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>المورد</th><th className={th}>عدد الاستلامات</th>
                <th className={th}>نقدي</th><th className={th}>آجل</th><th className={th}>الإجمالي</th>
              </tr></thead>
              <tbody>
                {(purchases ?? []).map((p, i) => (
                  <tr key={i} className='border-b border-slate-50'>
                    <td className={td}>{String(p.supplier)}</td>
                    <td className={`${td} font-mono`}>{String(p.grn_count)}</td>
                    <td className={`${td} font-mono`}>{fmt(String(p.cash_total))}</td>
                    <td className={`${td} font-mono`}>{fmt(String(p.credit_total))}</td>
                    <td className={`${td} font-mono font-bold`}>{fmt(String(p.total))}</td>
                  </tr>
                ))}
                {purchases && !purchases.length && <tr><td className={td} colSpan={5}>لا مشتريات بالفترة</td></tr>}
              </tbody>
            </table>
          </Card>
          <Card title='تقييم أداء الموردين'>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>المورد</th><th className={th}>الالتزام</th><th className={th}>الجودة</th>
                <th className={th}>استلامات مرفوضة الجودة</th><th className={th}>إجمالي التعامل</th>
              </tr></thead>
              <tbody>
                {(perf ?? []).map((s, i) => (
                  <tr key={i} className='border-b border-slate-50'>
                    <td className={td}>{String(s.supplier ?? s.name ?? '')}</td>
                    <td className={td}><Badge tone={Number(s.rating_commitment ?? 0) >= 4 ? 'green' : Number(s.rating_commitment ?? 0) >= 3 ? 'amber' : 'red'}>{fmt(String(s.rating_commitment ?? 0), 1)}</Badge></td>
                    <td className={td}><Badge tone={Number(s.rating_quality ?? 0) >= 4 ? 'green' : Number(s.rating_quality ?? 0) >= 3 ? 'amber' : 'red'}>{fmt(String(s.rating_quality ?? 0), 1)}</Badge></td>
                    <td className={`${td} font-mono ${Number(s.rejected_qty ?? s.rejects ?? 0) > 0 ? 'text-red-700 font-bold' : ''}`}>
                      {fmt(String(s.rejected_qty ?? s.rejects ?? 0), 0)}</td>
                    <td className={`${td} font-mono`}>{fmt(String(s.total ?? s.total_purchases ?? 0))}</td>
                  </tr>
                ))}
                {perf && !perf.length && <tr><td className={td} colSpan={5}>لا بيانات</td></tr>}
              </tbody>
            </table>
          </Card>
          <Card title='فروقات أسعار الشراء (حساب 5120)'>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>التاريخ</th><th className={th}>المستند</th><th className={th}>الفرق</th>
              </tr></thead>
              <tbody>
                {(ppv ?? []).map((r, i) => (
                  <tr key={i} className='border-b border-slate-50'>
                    <td className={`${td} font-mono text-xs`}>{String(r.date ?? r.business_date ?? '')}</td>
                    <td className={td}>{String(r.ref ?? r.doc ?? r.entry_no ?? '')}</td>
                    <td className={`${td} font-mono font-bold ${Number(r.diff ?? r.amount ?? 0) > 0 ? 'text-red-700' : 'text-emerald-700'}`}>
                      {fmt(String(r.diff ?? r.amount ?? 0), 4)}</td>
                  </tr>
                ))}
                {ppv && !ppv.length && <tr><td className={td} colSpan={3}>لا فروقات بالفترة</td></tr>}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ==================== الهالك والاستهلاك ==================== */}
      {tab === TABS[4] && !busy && (
        <>
          <Card title='إحصائية الهالك الشهرية (#19)'>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الشهر</th><th className={th}>حركات</th>
                <th className={th}>كمية</th><th className={th}>قيمة</th>
              </tr></thead>
              <tbody>
                {(wasteR?.months ?? []).map((m) => (
                  <tr key={m.month} className='border-b border-slate-50'>
                    <td className={`${td} font-mono`}>{m.month}</td>
                    <td className={`${td} font-mono`}>{m.moves}</td>
                    <td className={`${td} font-mono`}>{fmt(m.qty, 0)}</td>
                    <td className={`${td} font-mono font-bold text-red-700`}>{fmt(m.value)}</td>
                  </tr>
                ))}
                {wasteR && !wasteR.months.length && <tr><td className={td} colSpan={4}>لا هالك مسجل</td></tr>}
              </tbody>
            </table>
          </Card>
          <Card title='الاستهلاك النظري (بالوصفات) مقابل الفعلي — مؤشر الهدر والتلاعب الرئيسي'
            actions={
              <div className='flex gap-2 items-center'>
                <input className={inp} type='date' value={pFrom} onChange={(e) => setPFrom(e.target.value)} />
                <input className={inp} type='date' value={pTo} onChange={(e) => setPTo(e.target.value)} />
                <Btn kind='ghost' onClick={() => loadTab(TABS[4])}>تحديث</Btn>
              </div>
            }>
            {consume?.note && <div className='text-xs text-slate-500 mb-2'>{consume.note}</div>}
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الصنف</th><th className={th}>نظري (وصفات)</th><th className={th}>فعلي (حركات)</th>
                <th className={th}>الفرق</th><th className={th}>موثق كهالك</th><th className={th}>النسبة</th>
              </tr></thead>
              <tbody>
                {((consume?.rows ?? []) as Record<string, string>[]).map((r) => (
                  <tr key={r.item_id} className='border-b border-slate-50'>
                    <td className={td}>{r.code} — {r.name} <span className='text-xs text-slate-400'>{r.unit}</span></td>
                    <td className={`${td} font-mono`}>{fmt(r.theoretical_qty, 2)}</td>
                    <td className={`${td} font-mono`}>{fmt(r.actual_qty, 2)}</td>
                    <td className={`${td} font-mono font-bold ${parseFloat(r.variance_qty) > 0 ? 'text-red-700' : 'text-emerald-700'}`}>
                      {fmt(r.variance_qty, 2)}</td>
                    <td className={`${td} font-mono text-xs`}>{fmt(r.waste_count_qty, 2)}</td>
                    <td className={td}>{r.variance_pct && r.variance_pct !== 'None'
                      ? <Badge tone={Math.abs(parseFloat(r.variance_pct)) > 5 ? 'red' : 'amber'}>{fmt(r.variance_pct, 1)}%</Badge>
                      : '—'}</td>
                  </tr>
                ))}
                {consume && !consume.rows.length && <tr><td className={td} colSpan={6}>لا مبيعات وصفية بالفترة</td></tr>}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ==================== السياسة ==================== */}
      {tab === TABS[5] && policy && !busy && (
        <Card title='سياسة المشتريات والمخزون (قابلة للضبط للمستأجر — ملف 14 §2: لا اعتماد ذاتي أبداً)'>
          <div className='grid md:grid-cols-3 gap-3'>
            <div>
              <label className='text-xs text-slate-500 block mb-1'>حد الأمين الذاتي (أمر شراء ≤)</label>
              <input className={inp + ' w-full'} type='number' value={policyForm.po_l0_limit ?? ''} disabled={!canPolicy}
                onChange={(e) => setPolicyForm((f) => ({ ...f, po_l0_limit: e.target.value }))} />
            </div>
            <div>
              <label className='text-xs text-slate-500 block mb-1'>حد الاعتماد الأول L1 (مدير قسم)</label>
              <input className={inp + ' w-full'} type='number' value={policyForm.po_l1_limit ?? ''} disabled={!canPolicy}
                onChange={(e) => setPolicyForm((f) => ({ ...f, po_l1_limit: e.target.value }))} />
            </div>
            <div>
              <label className='text-xs text-slate-500 block mb-1'>تسامح فرق السعر % (فوقه إيقاف تلقائي)</label>
              <input className={inp + ' w-full'} type='number' value={policyForm.price_tolerance_pct ?? ''} disabled={!canPolicy}
                onChange={(e) => setPolicyForm((f) => ({ ...f, price_tolerance_pct: e.target.value }))} />
            </div>
            <div>
              <label className='text-xs text-slate-500 block mb-1'>تسامح الكمية ↑ %</label>
              <input className={inp + ' w-full'} type='number' value={policyForm.qty_tolerance_pct ?? ''} disabled={!canPolicy}
                onChange={(e) => setPolicyForm((f) => ({ ...f, qty_tolerance_pct: e.target.value }))} />
            </div>
            <div>
              <label className='text-xs text-slate-500 block mb-1'>نوافذ الصلاحية (أيام)</label>
              <div className='flex gap-1'>
                {['num0', 'num1', 'num2'].map((k, i) => (
                  <input key={k} className={inp + ' w-16 text-center'} type='number'
                    value={policyForm[k] ?? ''} disabled={!canPolicy} title={`نافذة ${i + 1}`}
                    onChange={(e) => setPolicyForm((f) => ({ ...f, [k]: e.target.value }))} />))}
              </div>
            </div>
            <div>
              <label className='text-xs text-slate-500 block mb-1'>أيام الركود / نافذة الاستهلاك</label>
              <div className='flex gap-1'>
                <input className={inp + ' w-20 text-center'} type='number' value={policyForm.num_stag ?? ''}
                  disabled={!canPolicy} title='أيام الركود'
                  onChange={(e) => setPolicyForm((f) => ({ ...f, num_stag: e.target.value }))} />
                <input className={inp + ' w-20 text-center'} type='number' value={policyForm.num_cons ?? ''}
                  disabled={!canPolicy} title='نافذة الاستهلاك'
                  onChange={(e) => setPolicyForm((f) => ({ ...f, num_cons: e.target.value }))} />
              </div>
            </div>
          </div>
          {canPolicy ? (
            <div className='mt-4'>
              <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                await invApi.putPolicy({
                  po_l0_limit: parseFloat(policyForm.po_l0_limit),
                  po_l1_limit: parseFloat(policyForm.po_l1_limit),
                  price_tolerance_pct: parseFloat(policyForm.price_tolerance_pct),
                  qty_tolerance_pct: parseFloat(policyForm.qty_tolerance_pct),
                  expiry_windows: [parseInt(policyForm.num0), parseInt(policyForm.num1), parseInt(policyForm.num2)],
                  stagnant_days: parseInt(policyForm.num_stag),
                  consumption_days: parseInt(policyForm.num_cons),
                })
                setPolicy(await invApi.policy())
              }, 'حُدّثت السياسة ووُثّق التغيير في سجل التدقيق')}>حفظ السياسة 💾</Btn>
            </div>
          ) : (
            <div className='mt-4 text-xs text-slate-500'>لعرض السياسة فقط — التعديل يتطلب صلاحية إدارة السياسة (المالية).</div>
          )}
        </Card>
      )}
    </div>
  )
}
