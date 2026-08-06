// الوقت والحضور: رصد واعتماد مشرف / ورديات وجداول Roster /
// إجازات بأرصدة واستحقاق شهري / جزاءات بمستند — ملف 06 §2
import { useCallback, useEffect, useState } from 'react'
import { fmt, todayISO } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import type { AttRow, Employee, LeaveBal, LeaveReq, LeaveType,
  Penalty, RosterRow, Shift } from '../hr'
import { HR_STATUS_AR, hrApi } from '../hr'

const TABS = ['الحضور', 'الورديات والجداول', 'الإجازات', 'الجزاءات'] as const
const inp = 'border border-slate-300 rounded-lg px-2 py-1.5 text-sm'
const th = 'px-3 py-2 text-right text-xs text-slate-500 font-semibold'
const td = 'px-3 py-2 text-sm'

const ATT_AR: Record<string, string> = {
  PRESENT: 'حضور', ABSENT: 'غياب', LEAVE: 'إجازة' }

export default function HrTime() {
  const { has } = useAuth()
  const canAtt = has('hr.attendance.manage')
  const canAttApprove = has('hr.attendance.approve')
  const canRoster = has('hr.roster.manage')
  const canLeave = has('hr.leave.manage')
  const canLeaveApprove = has('hr.leave.approve')
  const canPenalty = has('hr.penalty.manage')
  const canPenaltyApprove = has('hr.penalty.approve')

  const [tab, setTab] = useState<string>(TABS[0])
  const [month, setMonth] = useState(todayISO().slice(0, 7))
  const [emps, setEmps] = useState<Employee[]>([])
  const [att, setAtt] = useState<AttRow[]>([])
  const [shifts, setShifts] = useState<Shift[]>([])
  const [roster, setRoster] = useState<RosterRow[]>([])
  const [lts, setLts] = useState<LeaveType[]>([])
  const [reqs, setReqs] = useState<LeaveReq[]>([])
  const [bals, setBals] = useState<LeaveBal[]>([])
  const [pens, setPens] = useState<Penalty[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [showForm, setShowForm] = useState(false)

  const blankAtt = { employee_id: '', date: todayISO(), status: 'PRESENT',
    in_time: '07:00', out_time: '15:00', late_min: '0', overtime_hours: '0' }
  const [attRows, setAttRows] = useState([blankAtt])
  const [rosForm, setRosForm] = useState({ employee_id: '', shift_id: '' })
  const [rosDays, setRosDays] = useState<Set<string>>(new Set())
  const [shiftForm, setShiftForm] = useState({ name: '', from_time: '07:00',
    to_time: '15:00', overnight: false })
  const [leaveForm, setLeaveForm] = useState({ employee_id: '',
    leave_type_id: '', from_date: todayISO(), to_date: todayISO(),
    days: '1', reason: '' })
  const [penForm, setPenForm] = useState({ employee_id: '',
    pen_date: todayISO(), amount: '', reason: '', doc_ref: '' })

  const refresh = useCallback(async () => {
    const [es, ss, ts, bs, ps] = await Promise.all([
      hrApi.employees(), hrApi.shifts(), hrApi.leaveTypes(),
      hrApi.leaveBalances(), hrApi.penalties(month)])
    setEmps(es.filter((e) => e.status !== 'TERMINATED'))
    setShifts(ss); setLts(ts); setBals(bs); setPens(ps)
    setAtt(await hrApi.attendance(month))
    setRoster(await hrApi.roster(month))
    setReqs(await hrApi.leaveRequests())
  }, [month])

  useEffect(() => { refresh().catch((e) => setErr((e as Error).message)) },
             [refresh])

  const run = async (fn: () => Promise<void>, okMsg: string) => {
    setErr(null); setOk(null); setBusy(true)
    try { await fn(); setOk(okMsg); setShowForm(false); setSelected(new Set())
      await refresh() }
    catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }
  const ask = (t: string) => window.prompt(t)?.trim() ?? ''

  // المتاح: (الاستحقاق - المستخدم - المعلق) لنوع سنوي للموظف المختار
  const annBalanceFor = (empId: string, code: string) => {
    const b = bals.find((x) => x.employee_id === empId && x.leave_type === code)
    const pending = reqs.filter((r) => r.employee_id === empId &&
      r.leave_type === code && r.status === 'PENDING')
      .reduce((s, r) => s + parseFloat(r.days), 0)
    return b ? parseFloat(b.remaining) - pending : -pending
  }

  return (
    <div className='space-y-4'>
      <div className='flex gap-2 flex-wrap items-center'>
        {TABS.map((t) => (
          <Btn key={t} kind={tab === t ? 'primary' : 'ghost'}
            onClick={() => { setTab(t); setShowForm(false); setErr(null); setOk(null) }}>{t}</Btn>))}
        <span className='ms-4'>
          <input className={inp} type='month' value={month}
            onChange={(e) => setMonth(e.target.value)} />
        </span>
      </div>
      <ErrorNote msg={err} />
      <OkNote msg={ok} />
      {busy && <Spinner />}

      {/* ═══ الحضور ═══ */}
      {tab === TABS[0] && (
        <>
          {canAtt && (
            <Card title='رصد جماعي (يدوي باعتماد مشرف — §2)'
              actions={<Btn onClick={() => setShowForm(!showForm)}>+ إدخال</Btn>}>
              {showForm && (
                <div className='space-y-1.5'>
                  {attRows.map((r, i) => (
                    <div key={i} className='flex gap-1.5 flex-wrap'>
                      <select className={inp + ' min-w-44'} value={r.employee_id}
                        onChange={(e) => setAttRows(attRows.map((x, j) => j === i
                          ? { ...x, employee_id: e.target.value } : x))}>
                        <option value=''>الموظف…</option>
                        {emps.map((e) => <option key={e.id} value={e.id}>
                          {e.emp_no} — {e.full_name}</option>)}
                      </select>
                      <input className={inp} type='date' value={r.date}
                        onChange={(e) => setAttRows(attRows.map((x, j) => j === i
                          ? { ...x, date: e.target.value } : x))} />
                      <select className={inp} value={r.status}
                        onChange={(e) => setAttRows(attRows.map((x, j) => j === i
                          ? { ...x, status: e.target.value } : x))}>
                        {Object.entries(ATT_AR).map(([k, v]) =>
                          <option key={k} value={k}>{v}</option>)}
                      </select>
                      <input className={inp + ' w-16'} placeholder='تأخير/د' type='number'
                        value={r.late_min}
                        onChange={(e) => setAttRows(attRows.map((x, j) => j === i
                          ? { ...x, late_min: e.target.value } : x))} />
                      <input className={inp + ' w-16'} placeholder='إضافي/س' type='number'
                        value={r.overtime_hours}
                        onChange={(e) => setAttRows(attRows.map((x, j) => j === i
                          ? { ...x, overtime_hours: e.target.value } : x))} />
                      <Btn kind='ghost' disabled={attRows.length < 2}
                        onClick={() => setAttRows(attRows.filter((_, j) => j !== i))}>✖</Btn>
                    </div>
                  ))}
                  <div className='flex gap-2'>
                    <Btn kind='ghost' onClick={() =>
                      setAttRows([...attRows, { ...blankAtt }])}>+ سطر</Btn>
                    <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                      await hrApi.upsertAttendance(attRows
                        .filter((r) => r.employee_id && r.date)
                        .map((r) => ({ ...r, late_min: parseInt(r.late_min || '0'),
                          overtime_hours: parseFloat(r.overtime_hours || '0') })))
                    }, 'رُصد — أرسل للمشرف للاعتماد (غير المعتمد لا يدخل الرواتب)')}>
                      حفظ الرصد</Btn>
                  </div>
                </div>
              )}
              {!showForm && <div className='text-xs text-slate-500'>
                الصفوف غير المعتمدة تظهر كهرم — اعتماد المشرف يجعلها تُحتسب
                (غياب/تأخير/إضافي).</div>}
            </Card>
          )}
          <Card title={`سجل حضور ${month} (${att.length})`}
            actions={canAttApprove && selected.size > 0 && (
              <div className='flex gap-1'>
                <Btn onClick={() => run(async () =>
                  { await hrApi.approveAttendance([...selected]) },
                  `اعتُمد ${selected.size} سجلاً`)}>اعتماد المحدد ✅</Btn>
                <Btn kind='ghost' onClick={() => run(async () =>
                  { await hrApi.unapproveAttendance([...selected]) },
                  'أُلغي الاعتماد')}>إلغاء اعتماد</Btn>
              </div>)}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                {canAttApprove && <th className={th}></th>}
                <th className={th}>التاريخ</th><th className={th}>الموظف</th>
                <th className={th}>الحالة</th><th className={th}>الحضور/الانصراف</th>
                <th className={th}>تأخير</th><th className={th}>إضافي</th>
                <th className={th}>الاعتماد</th>
              </tr></thead>
              <tbody>
                {att.map((a) => (
                  <tr key={a.id} className={`border-b border-slate-50 ${a.approved_by ? '' : 'bg-amber-50/40'}`}>
                    {canAttApprove && (
                      <td className={td}>
                        <input type='checkbox' checked={selected.has(a.id)}
                          onChange={(e) => {
                            const s = new Set(selected)
                            if (e.target.checked) s.add(a.id); else s.delete(a.id)
                            setSelected(s)
                          }} />
                      </td>)}
                    <td className={`${td} font-mono text-xs`}>{a.date}</td>
                    <td className={td}>{a.emp_no}</td>
                    <td className={td}><Badge tone={a.status === 'ABSENT' ? 'red' : a.status === 'LEAVE' ? 'blue' : 'green'}>
                      {ATT_AR[a.status]}</Badge></td>
                    <td className={`${td} font-mono text-xs`}>{a.in_time || '—'}/{a.out_time || '—'}</td>
                    <td className={`${td} font-mono ${a.late_min > 0 ? 'text-amber-700 font-bold' : ''}`}>
                      {a.late_min > 0 ? `${a.late_min}د` : '—'}</td>
                    <td className={`${td} font-mono ${parseFloat(a.overtime_hours) > 0 ? 'text-emerald-700 font-bold' : ''}`}>
                      {parseFloat(a.overtime_hours) > 0 ? `${a.overtime_hours}س` : '—'}</td>
                    <td className={td}>{a.approved_by
                      ? <Badge tone='green'>معتمد ✓</Badge>
                      : <Badge tone='amber'>بانتظار مشرف</Badge>}</td>
                  </tr>
                ))}
                {!att.length && <tr><td className={td} colSpan={8}>لا رصد لهذا الشهر</td></tr>}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ═══ الورديات والجداول ═══ */}
      {tab === TABS[1] && (
        <>
          <div className='grid md:grid-cols-2 gap-4'>
            {canRoster && (
            <Card title='إسناد وردية لأيام محددة'>
              <div className='flex gap-2 flex-wrap'>
                <select className={inp} value={rosForm.employee_id}
                  onChange={(e) => setRosForm((f) => ({ ...f, employee_id: e.target.value }))}>
                  <option value=''>الموظف *</option>
                  {emps.map((e) => <option key={e.id} value={e.id}>{e.emp_no} — {e.full_name}</option>)}
                </select>
                <select className={inp} value={rosForm.shift_id}
                  onChange={(e) => setRosForm((f) => ({ ...f, shift_id: e.target.value }))}>
                  <option value=''>الوردية *</option>
                  {shifts.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </div>
              <div className='mt-2 flex gap-1 flex-wrap'>
                {Array.from({ length: 28 }, (_, i) => `${month}-${String(i + 1).padStart(2, '0')}`)
                  .map((d) => (
                    <button key={d} type='button'
                      onClick={() => { const s = new Set(rosDays)
                        if (s.has(d)) s.delete(d); else s.add(d); setRosDays(s) }}
                      className={`px-2 py-1 text-xs rounded-lg border font-mono ${rosDays.has(d)
                        ? 'bg-sijill-600 text-white border-sijill-600'
                        : 'bg-white border-slate-300'}`}>
                      {d.slice(8)}</button>))}
              </div>
              <div className='mt-3'>
                <Btn kind='gold' disabled={busy || !rosDays.size}
                  onClick={() => run(async () => {
                    await hrApi.setRoster([...rosDays].sort().map((d) => ({
                      employee_id: rosForm.employee_id,
                      shift_id: rosForm.shift_id, date: d })))
                  }, `أُسندت ${rosDays.size} يوماً`)}>
                  إسناد ({rosDays.size} يوماً)</Btn>
              </div>
            </Card>)}
            <Card title='الورديات المعرفة'>
              {canRoster && (
              <div className='flex gap-2 mb-3 flex-wrap'>
                <input className={inp} placeholder='اسم وردية' value={shiftForm.name}
                  onChange={(e) => setShiftForm((f) => ({ ...f, name: e.target.value }))} />
                <input className={inp + ' w-20'} value={shiftForm.from_time}
                  onChange={(e) => setShiftForm((f) => ({ ...f, from_time: e.target.value }))} />
                <input className={inp + ' w-20'} value={shiftForm.to_time}
                  onChange={(e) => setShiftForm((f) => ({ ...f, to_time: e.target.value }))} />
                <label className='text-sm flex items-center gap-1'>
                  <input type='checkbox' checked={shiftForm.overnight}
                    onChange={(e) => setShiftForm((f) => ({ ...f, overnight: e.target.checked }))} />
                  ليلية عابرة</label>
                <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                  await hrApi.createShift(shiftForm)
                }, 'أُضيفت الوردية')}>+</Btn>
              </div>)}
              <div className='flex gap-2 flex-wrap'>
                {shifts.map((s) => (
                  <Badge key={s.id} tone='blue'>{s.name}: {s.from_time}–{s.to_time}
                    {s.overnight ? ' 🌙' : ''}</Badge>))}
              </div>
            </Card>
          </div>
          <Card title={`جدول ${month} (آخر إسناد لكل يوم)`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>التاريخ</th><th className={th}>الموظف</th>
                <th className={th}>الوردية</th>
              </tr></thead>
              <tbody>
                {roster.map((r) => (
                  <tr key={r.id} className='border-b border-slate-50'>
                    <td className={`${td} font-mono text-xs`}>{r.date}</td>
                    <td className={td}>{r.emp_no} — {r.employee}</td>
                    <td className={td}><Badge tone='slate'>{r.shift}</Badge></td>
                  </tr>
                ))}
                {!roster.length && <tr><td className={td} colSpan={3}>لا إسنادات</td></tr>}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ═══ الإجازات ═══ */}
      {tab === TABS[2] && (
        <>
          <div className='grid md:grid-cols-2 gap-4'>
            {canLeave && (
            <Card title='طلب إجازة (يخصم من رصيد المدفوعة آلياً)'>
              <div className='flex gap-2 flex-wrap'>
                <select className={inp} value={leaveForm.employee_id}
                  onChange={(e) => setLeaveForm((f) => ({ ...f, employee_id: e.target.value }))}>
                  <option value=''>الموظف *</option>
                  {emps.map((e) => <option key={e.id} value={e.id}>{e.emp_no} — {e.full_name}</option>)}
                </select>
                <select className={inp} value={leaveForm.leave_type_id}
                  onChange={(e) => setLeaveForm((f) => ({ ...f, leave_type_id: e.target.value }))}>
                  <option value=''>النوع *</option>
                  {lts.map((t) => <option key={t.id} value={t.id}>
                    {t.name} {t.paid ? '' : '(بدون أجر)'}</option>)}
                </select>
                <input className={inp} type='date' value={leaveForm.from_date}
                  onChange={(e) => setLeaveForm((f) => ({ ...f, from_date: e.target.value }))} />
                <input className={inp} type='date' value={leaveForm.to_date}
                  onChange={(e) => setLeaveForm((f) => ({ ...f, to_date: e.target.value }))} />
                <input className={inp + ' w-20'} placeholder='الأيام' type='number'
                  value={leaveForm.days}
                  onChange={(e) => setLeaveForm((f) => ({ ...f, days: e.target.value }))} />
                <input className={inp} placeholder='السبب' value={leaveForm.reason}
                  onChange={(e) => setLeaveForm((f) => ({ ...f, reason: e.target.value }))} />
                <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                  await hrApi.createLeaveRequest({
                    ...leaveForm, days: parseFloat(leaveForm.days || '0') })
                }, 'قدّم الطلب — بانتظار اعتماد')}>تقديم</Btn>
              </div>
              {leaveForm.employee_id && leaveForm.leave_type_id &&
                lts.find((t) => t.id === leaveForm.leave_type_id)?.paid && (
                <div className='mt-2 text-xs text-slate-500'>
                  المتاح لـ{leaveForm.leave_type_id && lts.find((t) =>
                    t.id === leaveForm.leave_type_id)?.name}:{' '}
                  <b>{fmt(annBalanceFor(leaveForm.employee_id,
                    lts.find((t) => t.id === leaveForm.leave_type_id)!.code))} يوم</b>
                  {' '}(بعد حجز الطلبات المعلقة)
                </div>)}
            </Card>)}
            <Card title='أرصدة الإجازات (السنة الجارية)'
              actions={canLeave && (
                <Btn kind='ghost' onClick={() => run(async () => {
                  const res = await hrApi.accrueLeave(month)
                  setOk(`استحقاق ${month}: ${res.accrued_rows} رصيداً`)
                }, '')}>تسيير استحقاق الشهر ⏱</Btn>)}>
              <table className='w-full'>
                <thead><tr className='border-b border-slate-100'>
                  <th className={th}>الموظف</th><th className={th}>النوع</th>
                  <th className={th}>استحقاق</th><th className={th}>مستخدم</th>
                  <th className={th}>متبقٍ</th>
                </tr></thead>
                <tbody>
                  {bals.map((b, i) => (
                    <tr key={i} className='border-b border-slate-50'>
                      <td className={td}>{b.emp_no}</td>
                      <td className={td}><Badge tone='blue'>{b.leave_type}</Badge></td>
                      <td className={`${td} font-mono`}>{fmt(b.entitled)}</td>
                      <td className={`${td} font-mono`}>{fmt(b.used)}</td>
                      <td className={`${td} font-mono font-bold ${
                        parseFloat(b.remaining) <= 0 ? 'text-red-700' : 'text-emerald-700'}`}>
                        {fmt(b.remaining)}</td>
                    </tr>))}
                  {!bals.length && <tr><td className={td} colSpan={5}>لا أرصدة بعد — سيّر الاستحقاق</td></tr>}
                </tbody>
              </table>
            </Card>
          </div>
          <Card title={`طلبات الإجازة (${reqs.length})`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الموظف</th><th className={th}>النوع</th>
                <th className={th}>من ← إلى</th><th className={th}>أيام</th>
                <th className={th}>الحالة</th><th className={th}>إجراءات</th>
              </tr></thead>
              <tbody>
                {reqs.map((r) => (
                  <tr key={r.id} className='border-b border-slate-50'>
                    <td className={td}>{r.emp_no} — {r.employee}
                      {!r.paid && <Badge tone='amber'> بدون أجر</Badge>}</td>
                    <td className={td}>{r.leave_type}</td>
                    <td className={`${td} font-mono text-xs`}>{r.from_date} ← {r.to_date}</td>
                    <td className={`${td} font-mono`}>{fmt(r.days)}</td>
                    <td className={td}><Badge tone={r.status === 'APPROVED' ? 'green' : r.status === 'REJECTED' ? 'red' : 'amber'}>
                      {HR_STATUS_AR[r.status]}</Badge></td>
                    <td className={td}>
                      {r.status === 'PENDING' && canLeaveApprove && (
                        <div className='flex gap-1'>
                          <Btn className='!px-2 !py-1 text-xs' onClick={() => run(async () => {
                            await hrApi.approveLeave(r.id)
                          }, 'اعتُمدت وخُصم الرصيد')}>اعتماد ✅</Btn>
                          <Btn kind='danger' className='!px-2 !py-1 text-xs'
                            onClick={() => { const rs = ask('سبب الرفض:');
                              if (rs) run(async () => { await hrApi.rejectLeave(r.id, rs) }, 'رُفضت') }}>رفض</Btn>
                        </div>)}
                    </td>
                  </tr>
                ))}
                {!reqs.length && <tr><td className={td} colSpan={6}>لا طلبات</td></tr>}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ═══ الجزاءات ═══ */}
      {tab === TABS[3] && (
        <>
          {canPenalty && (
            <Card title='جزاء تأديبي بمستند — يُخصم في شهر التطبيق بعد الاعتماد'>
              <div className='flex gap-2 flex-wrap'>
                <select className={inp} value={penForm.employee_id}
                  onChange={(e) => setPenForm((f) => ({ ...f, employee_id: e.target.value }))}>
                  <option value=''>الموظف *</option>
                  {emps.map((e) => <option key={e.id} value={e.id}>{e.emp_no} — {e.full_name}</option>)}
                </select>
                <input className={inp} type='date' value={penForm.pen_date}
                  onChange={(e) => setPenForm((f) => ({ ...f, pen_date: e.target.value }))} />
                <input className={inp + ' w-24'} placeholder='المبلغ *' type='number'
                  value={penForm.amount}
                  onChange={(e) => setPenForm((f) => ({ ...f, amount: e.target.value }))} />
                <input className={inp} placeholder='السبب *' value={penForm.reason}
                  onChange={(e) => setPenForm((f) => ({ ...f, reason: e.target.value }))} />
                <input className={inp} placeholder='مرجع المستند' value={penForm.doc_ref}
                  onChange={(e) => setPenForm((f) => ({ ...f, doc_ref: e.target.value }))} />
                <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                  await hrApi.createPenalty({ ...penForm, apply_month: month,
                    amount: parseFloat(penForm.amount || '0') })
                }, `سُجل — سيخصم من رواتب ${month} بعد اعتماده`)}>تسجيل</Btn>
              </div>
            </Card>
          )}
          <Card title={`جزاءات ${month} (${pens.length})`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الموظف</th><th className={th}>المبلغ</th>
                <th className={th}>السبب/المستند</th><th className={th}>الحالة</th>
                <th className={th}>إجراءات</th>
              </tr></thead>
              <tbody>
                {pens.map((p) => (
                  <tr key={p.id} className='border-b border-slate-50'>
                    <td className={td}>{p.emp_no}</td>
                    <td className={`${td} font-mono font-bold text-red-700`}>{fmt(p.amount)}</td>
                    <td className={`${td} text-xs`}>{p.reason}
                      {p.doc_ref && <span className='text-slate-400'> ({p.doc_ref})</span>}</td>
                    <td className={td}>
                      {p.deducted_run_id
                        ? <Badge tone='green'>مخصوم ✓</Badge>
                        : p.approved_by ? <Badge tone='blue'>معتمد</Badge>
                        : <Badge tone='amber'>بانتظار اعتماد</Badge>}
                    </td>
                    <td className={td}>
                      {!p.approved_by && canPenaltyApprove && (
                        <Btn className='!px-2 !py-1 text-xs' onClick={() => run(async () => {
                          await hrApi.approvePenalty(p.id)
                        }, 'اعتُمد الجزاء')}>اعتماد ✅</Btn>)}
                    </td>
                  </tr>
                ))}
                {!pens.length && <tr><td className={td} colSpan={5}>لا جزاءات لهذا الشهر</td></tr>}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  )
}
