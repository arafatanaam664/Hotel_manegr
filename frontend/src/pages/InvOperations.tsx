// حركة المخزون: صرف للأقسام / تحويلات باستلام مزدوج / هالك / جرد دوري
// — ملف 05 §3 و§4 (الجرد: تجميد ⇐ عدّ ⇐ فروقات ⇐ اعتماد مزدوج ⇐ تسويات #19/#20)
import { useCallback, useEffect, useState } from 'react'
import { fmt } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import type { Count, InvCategory, InvItem, Issue, Transfer,
  Warehouse, Waste } from '../inv'
import { INV_STATUS_AR, invApi } from '../inv'

const TABS = ['صرف للأقسام', 'التحويلات', 'الهالك', 'الجرد الدوري'] as const

const inp = 'border border-slate-300 rounded-lg px-2 py-1.5 text-sm'
const th = 'px-3 py-2 text-right text-xs text-slate-500 font-semibold'
const td = 'px-3 py-2 text-sm'

function statusTone(s: string): 'green' | 'red' | 'amber' | 'slate' | 'blue' {
  if (['ISSUED', 'RECEIVED', 'POSTED', 'APPROVED'].includes(s)) return 'green'
  if (['REQUESTED', 'PENDING', 'IN_TRANSIT', 'FREEZE', 'COUNTED',
    'PENDING_L1', 'PENDING_L2'].includes(s)) return 'amber'
  if (['REJECTED', 'CANCELLED'].includes(s)) return 'red'
  return 'slate'
}

interface Line { item_id: string; qty: string; reason: string }

export default function InvOperations() {
  const { has } = useAuth()
  const canIssueCreate = has('inv.issue.create')
  const canIssueApprove = has('inv.issue.approve')
  const canTransfer = has('inv.transfer.manage')
  const canWasteCreate = has('inv.waste.create')
  const canWasteApprove = has('inv.waste.approve')
  const canCount = has('inv.count.manage')
  const canCountL1 = has('inv.count.approve.l1')
  const canCountL2 = has('inv.count.approve.l2')

  const [tab, setTab] = useState<string>(TABS[0])
  const [items, setItems] = useState<InvItem[]>([])
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [cats, setCats] = useState<InvCategory[]>([])
  const [issues, setIssues] = useState<Issue[]>([])
  const [transfers, setTransfers] = useState<Transfer[]>([])
  const [wastes, setWastes] = useState<Waste[]>([])
  const [counts, setCounts] = useState<Count[]>([])
  const [countDetail, setCountDetail] = useState<Count | null>(null)
  const [counted, setCounted] = useState<Record<string, string>>({})
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  const blank = (): Line => ({ item_id: '', qty: '', reason: '' })
  const [issForm, setIssForm] = useState({ from_warehouse_id: '', to_warehouse_id: '', department: '', reason: '' })
  const [issLines, setIssLines] = useState<Line[]>([blank()])
  const [trfForm, setTrfForm] = useState({ from_warehouse_id: '', to_warehouse_id: '', reason: '', requires_receive: true })
  const [trfLines, setTrfLines] = useState<Line[]>([blank()])
  const [wstForm, setWstForm] = useState({ warehouse_id: '', reason: '', photo_ref: '' })
  const [wstLines, setWstLines] = useState<Line[]>([blank()])
  const [cntForm, setCntForm] = useState({ warehouse_id: '', category_id: '' })

  const refresh = useCallback(async () => {
    const [is, ws, cs, i1, t1, w1, c1] = await Promise.all([
      invApi.items(), invApi.warehouses(), invApi.categories(),
      invApi.issues(), invApi.transfers(), invApi.waste(), invApi.counts()])
    setItems(is); setWarehouses(ws); setCats(cs)
    setIssues(i1); setTransfers(t1); setWastes(w1); setCounts(c1)
    if (countDetail) setCountDetail(await invApi.count(countDetail.id))
  }, [countDetail])

  useEffect(() => {
    refresh().catch((e) => setErr((e as Error).message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const run = async (fn: () => Promise<void>, okMsg: string) => {
    setErr(null); setOk(null); setBusy(true)
    try { await fn(); setOk(okMsg); setShowForm(false); await refresh() }
    catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }
  const askReason = (title: string) => window.prompt(title)?.trim() ?? ''
  const linesOf = (rows: Line[], withReason = false) =>
    rows.filter((l) => l.item_id && l.qty).map((l) => ({
      item_id: l.item_id, qty: parseFloat(l.qty),
      ...(withReason ? { reason: l.reason } : {}),
    }))

  const openCount = async (c: Count) => {
    const d = await invApi.count(c.id)
    setCountDetail(d)
    const init: Record<string, string> = {}
    for (const l of d.lines ?? []) if (l.counted_qty !== null) init[l.item_id] = l.counted_qty
    setCounted(init)
  }

  const whSel = (v: string, set: (s: string) => void, exclude?: string) => (
    <select className={inp} value={v} onChange={(e) => set(e.target.value)}>
      <option value=''>المستودع…</option>
      {warehouses.filter((w) => w.id !== exclude).map((w) => (
        <option key={w.id} value={w.id}>{w.name_ar} ({w.code})</option>))}
    </select>
  )

  const LinesEditor = ({ rows, setRows, withReason = false }: {
    rows: Line[]; setRows: (r: Line[]) => void; withReason?: boolean
  }) => (
    <div className='space-y-1.5'>
      {rows.map((l, i) => (
        <div key={i} className='flex gap-1.5 flex-wrap'>
          <select className={inp + ' flex-1 min-w-40'} value={l.item_id}
            onChange={(e) => setRows(rows.map((r, j) => j === i ? { ...r, item_id: e.target.value } : r))}>
            <option value=''>الصنف…</option>
            {items.map((it) => <option key={it.id} value={it.id}>{it.code} — {it.name_ar}</option>)}
          </select>
          <input className={inp + ' w-24'} placeholder='الكمية (أساسية)' type='number' value={l.qty}
            onChange={(e) => setRows(rows.map((r, j) => j === i ? { ...r, qty: e.target.value } : r))} />
          {withReason && (
            <input className={inp + ' w-40'} placeholder='سبب السطر (اختياري)' value={l.reason}
              onChange={(e) => setRows(rows.map((r, j) => j === i ? { ...r, reason: e.target.value } : r))} />
          )}
          <Btn kind='ghost' onClick={() => setRows(rows.filter((_, j) => j !== i))} disabled={rows.length < 2}>✖</Btn>
        </div>
      ))}
      <Btn kind='ghost' onClick={() => setRows([...rows, blank()])}>+ سطر</Btn>
    </div>
  )

  const nameOf = (list: { id: string; name_ar: string }[], id: string) =>
    list.find((w) => w.id === id)?.name_ar ?? '…'

  if (!items.length && !err) return <Spinner />

  return (
    <div className='space-y-4'>
      <div className='flex gap-2 flex-wrap'>
        {TABS.map((t) => (
          <Btn key={t} kind={tab === t ? 'primary' : 'ghost'}
            onClick={() => { setTab(t); setShowForm(false); setErr(null); setOk(null) }}>{t}</Btn>))}
      </div>
      <ErrorNote msg={err} />
      <OkNote msg={ok} />

      {/* ==================== صرف للأقسام ==================== */}
      {tab === TABS[0] && (
        <>
          {canIssueCreate && (
            <Card title='طلب صرف جديد لقسم (#18: بلا أثر دخل — تكلفة))'>
              {!showForm ? (
                <Btn onClick={() => setShowForm(true)}>+ طلب صرف جديد</Btn>
              ) : (
                <div className='space-y-3'>
                  <div className='grid md:grid-cols-2 gap-2'>
                    <div>
                      <label className='text-xs text-slate-500 block mb-1'>من مستودع</label>
                      {whSel(issForm.from_warehouse_id,
                        (v) => setIssForm((f) => ({ ...f, from_warehouse_id: v })), issForm.to_warehouse_id)}
                    </div>
                    <div>
                      <label className='text-xs text-slate-500 block mb-1'>إلى مستودع/قسم (لا يُقبل مستودع POS)</label>
                      {whSel(issForm.to_warehouse_id,
                        (v) => setIssForm((f) => ({ ...f, to_warehouse_id: v })), issForm.from_warehouse_id)}
                    </div>
                    <div>
                      <label className='text-xs text-slate-500 block mb-1'>القسم الطالب *</label>
                      <input className={inp + ' w-full'} value={issForm.department}
                        onChange={(e) => setIssForm((f) => ({ ...f, department: e.target.value }))} />
                    </div>
                    <div>
                      <label className='text-xs text-slate-500 block mb-1'>المسوغ</label>
                      <input className={inp + ' w-full'} value={issForm.reason}
                        onChange={(e) => setIssForm((f) => ({ ...f, reason: e.target.value }))} />
                    </div>
                  </div>
                  <LinesEditor rows={issLines} setRows={setIssLines} />
                  <div className='flex gap-2'>
                    <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                      await invApi.createIssue({ ...issForm, lines: linesOf(issLines) })
                    }, `أُنشئ طلب الصرف — بانتظار اعتماد ${canIssueApprove ? 'الأمين' : 'المعتمد'}`)}>حفظ الطلب</Btn>
                    <Btn kind='ghost' onClick={() => setShowForm(false)}>تراجع</Btn>
                  </div>
                </div>
              )}
            </Card>
          )}
          <Card title={`طلبات الصرف (${issues.length})`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الرقم</th><th className={th}>من</th><th className={th}>إلى</th>
                <th className={th}>القسم</th><th className={th}>الحالة</th><th className={th}>إجراءات</th>
              </tr></thead>
              <tbody>
                {issues.map((i) => (
                  <tr key={i.id} className='border-b border-slate-50'>
                    <td className={`${td} font-mono font-bold text-atheer-700 cursor-pointer`}
                      onClick={() => setExpanded(expanded === i.id ? null : i.id)}>{i.iss_no}</td>
                    <td className={td}>{i.from_warehouse}</td>
                    <td className={td}>{i.to_warehouse}</td>
                    <td className={td}>{i.department}</td>
                    <td className={td}><Badge tone={statusTone(i.status)}>{INV_STATUS_AR[i.status] ?? i.status}</Badge></td>
                    <td className={td}>
                      <div className='flex gap-1'>
                        {i.status === 'REQUESTED' && canIssueApprove && (<>
                          <Btn onClick={() => run(async () => { await invApi.approveIssue(i.id) }, 'اعتُمد — جاهز للصرف')}>اعتماد ✅</Btn>
                          <Btn kind='danger' onClick={() => { const r = askReason('سبب الرفض:'); if (r) run(async () => { await invApi.rejectIssue(i.id, r) }, 'رُفض') }}>رفض</Btn>
                        </>)}
                        {i.status === 'APPROVED' && canIssueApprove &&
                          <Btn kind='gold' onClick={() => run(async () => { await invApi.executeIssue(i.id) }, 'صُرف ووُثّقت التكلفة والقيد')}>تنفيذ الصرف 📤</Btn>}
                      </div>
                    </td>
                  </tr>
                ))}
                {!issues.length && <tr><td className={td} colSpan={6}>لا طلبات</td></tr>}
                {issues.filter((i) => expanded === i.id).map((i) => (
                  <tr key={i.id + '-x'} className='bg-slate-50/50'>
                    <td colSpan={6} className='px-8 py-2 text-xs text-slate-600'>
                      {i.lines.map((l) => (
                        <span key={l.item_id} className='inline-block ms-4'>
                          {l.item_code}: {fmt(l.qty, 0)}
                          {l.unit_cost && <> × {fmt(l.unit_cost, 4)} = <b>{fmt(l.line_value)}</b></>}
                        </span>))}
                      {i.entry_id && <span className='ms-4 text-emerald-700'>قيد #{i.entry_id.slice(0, 8)}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ==================== التحويلات ==================== */}
      {tab === TABS[1] && (
        <>
          {canTransfer && (
            <Card title='تحويل بين مستودعات (مسوغ إلزامي + استلام مزدوج)'>
              {!showForm ? (
                <Btn onClick={() => setShowForm(true)}>+ تحويل جديد</Btn>
              ) : (
                <div className='space-y-3'>
                  <div className='flex gap-2 flex-wrap items-end'>
                    <div>
                      <label className='text-xs text-slate-500 block mb-1'>من</label>
                      {whSel(trfForm.from_warehouse_id,
                        (v) => setTrfForm((f) => ({ ...f, from_warehouse_id: v })), trfForm.to_warehouse_id)}
                    </div>
                    <div>
                      <label className='text-xs text-slate-500 block mb-1'>إلى</label>
                      {whSel(trfForm.to_warehouse_id,
                        (v) => setTrfForm((f) => ({ ...f, to_warehouse_id: v })), trfForm.from_warehouse_id)}
                    </div>
                    <input className={inp} placeholder='المسوغ *' value={trfForm.reason}
                      onChange={(e) => setTrfForm((f) => ({ ...f, reason: e.target.value }))} />
                    <label className='text-sm flex items-center gap-1'>
                      <input type='checkbox' checked={trfForm.requires_receive}
                        onChange={(e) => setTrfForm((f) => ({ ...f, requires_receive: e.target.checked }))} />
                      يتطلب استلاماً (على الطريق)
                    </label>
                  </div>
                  <LinesEditor rows={trfLines} setRows={setTrfLines} />
                  <div className='flex gap-2'>
                    <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                      await invApi.createTransfer({ ...trfForm, lines: linesOf(trfLines) })
                    }, 'أُنشئ التحويل')}>حفظ</Btn>
                    <Btn kind='ghost' onClick={() => setShowForm(false)}>تراجع</Btn>
                  </div>
                </div>
              )}
            </Card>
          )}
          <Card title={`التحويلات (${transfers.length})`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الرقم</th><th className={th}>من</th><th className={th}>إلى</th>
                <th className={th}>الحالة</th><th className={th}>المسؤولون</th><th className={th}>إجراءات</th>
              </tr></thead>
              <tbody>
                {transfers.map((t) => (
                  <tr key={t.id} className='border-b border-slate-50'>
                    <td className={`${td} font-mono font-bold`}>{t.trf_no}</td>
                    <td className={td}>{t.from_warehouse}</td>
                    <td className={td}>{t.to_warehouse}</td>
                    <td className={td}><Badge tone={statusTone(t.status)}>{INV_STATUS_AR[t.status] ?? t.status}</Badge></td>
                    <td className={`${td} text-xs text-slate-500`}>
                      {t.dispatched_by && <div>إرسال: {t.dispatched_by}</div>}
                      {t.received_by && <div>استلام: {t.received_by}</div>}
                    </td>
                    <td className={td}>
                      {canTransfer && (
                        <div className='flex gap-1'>
                          {t.status === 'DRAFT' &&
                            <Btn onClick={() => run(async () => { await invApi.dispatchTransfer(t.id) }, t.requires_receive ? 'أُرسل — أصبح على الطريق' : 'نُفّذ التحويل المباشر')}>إرسال 🚚</Btn>}
                          {t.status === 'IN_TRANSIT' &&
                            <Btn kind='gold' onClick={() => run(async () => { await invApi.receiveTransfer(t.id) }, 'استُلم — تُمنع الاستلام الذاتي: المستلم ≠ المرسل')}>استلام 📥</Btn>}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
                {!transfers.length && <tr><td className={td} colSpan={6}>لا تحويلات</td></tr>}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ==================== الهالك ==================== */}
      {tab === TABS[2] && (
        <>
          {canWasteCreate && (
            <Card title='مستند هالك (#19: مستند + سبب + اعتماد — Dr 7104)'>
              {!showForm ? (
                <Btn onClick={() => setShowForm(true)}>+ مستند هالك جديد</Btn>
              ) : (
                <div className='space-y-3'>
                  <div className='flex gap-2 flex-wrap items-end'>
                    <div>
                      <label className='text-xs text-slate-500 block mb-1'>المستودع</label>
                      {whSel(wstForm.warehouse_id, (v) => setWstForm((f) => ({ ...f, warehouse_id: v })))}
                    </div>
                    <input className={inp} placeholder='السبب (≥3 أحرف) *' value={wstForm.reason}
                      onChange={(e) => setWstForm((f) => ({ ...f, reason: e.target.value }))} />
                    <input className={inp} placeholder='مرجع الصورة/المرفق' value={wstForm.photo_ref}
                      onChange={(e) => setWstForm((f) => ({ ...f, photo_ref: e.target.value }))} />
                  </div>
                  <LinesEditor rows={wstLines} setRows={setWstLines} withReason />
                  <div className='flex gap-2'>
                    <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                      await invApi.createWaste({ ...wstForm, lines: linesOf(wstLines, true) })
                    }, 'حُفظت مسودة الهالك — أرفعها للاعتماد')}>حفظ مسودة</Btn>
                    <Btn kind='ghost' onClick={() => setShowForm(false)}>تراجع</Btn>
                  </div>
                </div>
              )}
            </Card>
          )}
          <Card title={`مستندات الهالك (${wastes.length})`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الرقم</th><th className={th}>المستودع</th><th className={th}>القيمة</th>
                <th className={th}>السبب</th><th className={th}>الحالة</th><th className={th}>إجراءات</th>
              </tr></thead>
              <tbody>
                {wastes.map((w) => (
                  <tr key={w.id} className='border-b border-slate-50'>
                    <td className={`${td} font-mono font-bold`}>{w.wst_no}</td>
                    <td className={td}>{w.warehouse}</td>
                    <td className={`${td} font-bold text-red-700`}>{w.status === 'POSTED' ? fmt(w.total_value) : '—'}</td>
                    <td className={`${td} text-xs`}>{w.reason}{w.reject_reason && <div className='text-red-600'>رفض: {w.reject_reason}</div>}</td>
                    <td className={td}><Badge tone={statusTone(w.status)}>{INV_STATUS_AR[w.status] ?? w.status}</Badge></td>
                    <td className={td}>
                      <div className='flex gap-1'>
                        {w.status === 'DRAFT' && canWasteCreate &&
                          <Btn onClick={() => run(async () => { await invApi.submitWaste(w.id) }, 'رُفع للاعتماد')}>رفع 📨</Btn>}
                        {w.status === 'PENDING' && canWasteApprove && (<>
                          <Btn onClick={() => run(async () => { await invApi.approveWaste(w.id) }, 'اعتُمد ورُحّل — قيد #19 Dr 7104')}>اعتماد ✅</Btn>
                          <Btn kind='danger' onClick={() => { const r = askReason('سبب الرفض:'); if (r) run(async () => { await invApi.rejectWaste(w.id, r) }, 'رُفض') }}>رفض</Btn>
                        </>)}
                      </div>
                    </td>
                  </tr>
                ))}
                {!wastes.length && <tr><td className={td} colSpan={6}>لا مستندات</td></tr>}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ==================== الجرد الدوري ==================== */}
      {tab === TABS[3] && (
        <>
          {!countDetail ? (
            <>
              {canCount && (
                <Card title='بدء جرد (يُجمّد نطاق المستودع فوراً — تُمنع كل حركة عليه)'>
                  <div className='flex gap-2 flex-wrap items-end'>
                    <div>
                      <label className='text-xs text-slate-500 block mb-1'>المستودع *</label>
                      {whSel(cntForm.warehouse_id, (v) => setCntForm((f) => ({ ...f, warehouse_id: v })))}
                    </div>
                    <div>
                      <label className='text-xs text-slate-500 block mb-1'>التصنيف (اختياري — جرد جزئي)</label>
                      <select className={inp} value={cntForm.category_id}
                        onChange={(e) => setCntForm((f) => ({ ...f, category_id: e.target.value }))}>
                        <option value=''>كل التصنيفات — جرد شامل</option>
                        {cats.map((c) => <option key={c.id} value={c.id}>{c.name_ar}</option>)}
                      </select>
                    </div>
                    <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                      await invApi.createCount({
                        warehouse_id: cntForm.warehouse_id,
                        category_id: cntForm.category_id || null,
                      })
                    }, 'بُدئ الجرد وجُمّد المستودع — ابدأ العدّ من القائمة')}>بدء الجرد وتجميد ❄️</Btn>
                  </div>
                </Card>
              )}
              <Card title={`الجردات (${counts.length})`}>
                <table className='w-full'>
                  <thead><tr className='border-b border-slate-100'>
                    <th className={th}>الرقم</th><th className={th}>المستودع</th><th className={th}>الحالة</th>
                    <th className={th}>عجز #19</th><th className={th}>زيادة #20</th><th className={th}>الاعتمادات</th>
                  </tr></thead>
                  <tbody>
                    {counts.map((c) => (
                      <tr key={c.id} className='border-b border-slate-50 hover:bg-slate-50/70 cursor-pointer'
                        onClick={() => openCount(c).catch((e) => setErr((e as Error).message))}>
                        <td className={`${td} font-mono font-bold text-atheer-700`}>{c.cnt_no}</td>
                        <td className={td}>{c.warehouse}</td>
                        <td className={td}><Badge tone={statusTone(c.status)}>{INV_STATUS_AR[c.status] ?? c.status}</Badge></td>
                        <td className={`${td} text-red-700`}>{c.status === 'POSTED' ? fmt(c.short_value) : '—'}</td>
                        <td className={`${td} text-emerald-700`}>{c.status === 'POSTED' ? fmt(c.over_value) : '—'}</td>
                        <td className={`${td} text-xs`}>
                          {c.approved1_by && <span className='text-emerald-700'>✔ أول </span>}
                          {c.approved2_by && <span className='text-emerald-700'>✔ ثانٍ </span>}
                          {!c.approved1_by && !c.approved2_by && '—'}
                        </td>
                      </tr>
                    ))}
                    {!counts.length && <tr><td className={td} colSpan={6}>لا جردات — الجرد الشامل إلزامي قبل الإقفال السنوي</td></tr>}
                  </tbody>
                </table>
              </Card>
            </>
          ) : (
            <Card title={`جرد ${countDetail.cnt_no} — ${countDetail.warehouse}`}
              actions={<Btn kind='ghost' onClick={() => setCountDetail(null)}>عودة للقائمة ←</Btn>}>
              <div className='mb-3 flex items-center gap-3 flex-wrap'>
                <Badge tone={statusTone(countDetail.status)}>{INV_STATUS_AR[countDetail.status] ?? countDetail.status}</Badge>
                <span className='text-xs text-slate-500'>
                  أنشأه {countDetail.created_by} — العدّ: {countDetail.counted_by ?? 'لم يبدأ'}
                  {countDetail.status === 'FREEZE' && ' — المستودع مجمّد حتى ترحيل التسويات أو الإلغاء'}
                </span>
              </div>
              <table className='w-full'>
                <thead><tr className='border-b border-slate-100'>
                  <th className={th}>الصنف</th><th className={th}>النظامي</th>
                  <th className={th}>المعدود</th><th className={th}>الفرق</th><th className={th}>قيمة الفرق</th>
                </tr></thead>
                <tbody>
                  {(countDetail.lines ?? []).map((l) => (
                    <tr key={l.item_id} className='border-b border-slate-50'>
                      <td className={td}>{l.item_code} — {l.item_name}</td>
                      <td className={`${td} font-mono`}>{fmt(l.system_qty, 0)}</td>
                      <td className={td}>
                        {['FREEZE', 'COUNTED'].includes(countDetail.status) ? (
                          <input className={inp + ' w-24'} type='number' value={counted[l.item_id] ?? ''}
                            onChange={(e) => setCounted((c) => ({ ...c, [l.item_id]: e.target.value }))} />
                        ) : <span className='font-mono'>{l.counted_qty === null ? '—' : fmt(l.counted_qty, 0)}</span>}
                      </td>
                      <td className={`${td} font-mono ${l.variance_qty && parseFloat(l.variance_qty) < 0 ? 'text-red-700 font-bold' : l.variance_qty && parseFloat(l.variance_qty) > 0 ? 'text-emerald-700 font-bold' : ''}`}>
                        {l.variance_qty === null ? '—' : fmt(l.variance_qty, 0)}</td>
                      <td className={`${td} font-mono text-xs`}>{l.variance_value === null ? '—' : fmt(l.variance_value, 4)} بالهللة</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className='mt-4 flex gap-2 flex-wrap'>
                {['FREEZE', 'COUNTED'].includes(countDetail.status) && canCount && (<>
                  <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                    const payload = Object.entries(counted)
                      .filter(([, v]) => v !== '')
                      .map(([item_id, v]) => ({ item_id, counted_qty: parseFloat(v) }))
                    await invApi.enterCount(countDetail.id, payload)
                  }, 'حُفظ العدّ')}>حفظ العدّ 📝</Btn>
                  <Btn disabled={busy} onClick={() => run(async () => {
                    await invApi.finishCount(countDetail.id)
                  }, 'أُقفل العدّ وحُسبت الفروقات — بانتظار الاعتماد المزدوج')}>إقفال العدّ وحساب الفروقات 🧮</Btn>
                </>)}
                {countDetail.status === 'PENDING_L1' && canCountL1 &&
                  <Btn onClick={() => run(async () => { await invApi.approveCount(countDetail.id, 1) }, 'اعتمد أول — بانتظار الاعتماد الثاني')}>اعتماد أول ✅ (أمين+مالية)</Btn>}
                {countDetail.status === 'PENDING_L2' && canCountL2 &&
                  <Btn onClick={() => run(async () => { await invApi.approveCount(countDetail.id, 2) }, 'اعتمد ثانٍ ورُحّلت التسويات #19/#20 بالهللة')}>اعتماد ثانٍ ✅✅ (مدير عام)</Btn>}
                {!['POSTED', 'CANCELLED'].includes(countDetail.status) && canCount && (
                  <Btn kind='danger' onClick={() => {
                    const r = askReason('مسوغ الإلغاء (سيفك التجميد):')
                    if (r) run(async () => { await invApi.cancelCount(countDetail.id, r); setCountDetail(null) }, 'أُلغي الجرد وفُك التجميد')
                  }}>إلغاء الجرد</Btn>
                )}
              </div>
            </Card>
          )}
        </>
      )}

      <div className='text-xs text-slate-400'>
        ملاحظة: إنشاء الصرف يتطلب صلاحية إنشاء صرف (مدير عام) والاعتماد/التنفيذ
        صلاحية أمين — فصل مهام مطبَّق من الخادم.
      </div>
    </div>
  )
}
