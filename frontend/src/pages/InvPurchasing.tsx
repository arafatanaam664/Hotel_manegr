// دورة المشتريات: طلبات ⇒ أوامر (سلم اعتماد) ⇒ استلام ⇒ مطابقة ثلاثية
// ⇒ سداد ومرتجعات — ملف 05 §2
import { Fragment, useCallback, useEffect, useState } from 'react'
import { fmt, todayISO } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote } from '../components/ui'
import type { GRN, InvItem, PO, PR, SInvoice, Supplier,
  Warehouse } from '../inv'
import { INV_STATUS_AR, invApi } from '../inv'

const TABS = ['طلبات الشراء', 'أوامر الشراء', 'الاستلامات GRN',
  'فواتير الموردين', 'السداد والمرتجعات'] as const

const inp = 'border border-slate-300 rounded-lg px-2 py-1.5 text-sm'
const th = 'px-3 py-2 text-right text-xs text-slate-500 font-semibold'
const td = 'px-3 py-2 text-sm'

function statusTone(s: string): 'green' | 'red' | 'amber' | 'slate' | 'blue' {
  if (['APPROVED', 'MATCHED', 'POSTED', 'RECEIVED', 'PAID', 'ISSUED'].includes(s)) return 'green'
  if (s.startsWith('PENDING') || ['PART_RECEIVED', 'VARIANCE_HOLD'].includes(s)) return 'amber'
  if (['REJECTED', 'CANCELLED'].includes(s)) return 'red'
  if (s === 'REVERSED') return 'blue'
  return 'slate'
}

interface LineDraft { item_id: string; qty: string; price: string; uom: string; factor: string }

export default function InvPurchasing() {
  const { has, session } = useAuth()
  const canPr = has('inv.pr.create')
  const canPo = has('inv.po.create')
  const canGrn = has('inv.grn.manage')
  const canInv = has('inv.invoice.create')
  const canPay = has('inv.pay')
  const canRet = has('inv.return.manage')
  const [tab, setTab] = useState<string>(TABS[1])
  const [items, setItems] = useState<InvItem[]>([])
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [prs, setPrs] = useState<PR[]>([])
  const [pos, setPos] = useState<PO[]>([])
  const [grns, setGrns] = useState<GRN[]>([])
  const [invs, setInvs] = useState<SInvoice[]>([])
  const [payments, setPayments] = useState<unknown[]>([])
  const [returns, setReturns] = useState<unknown[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const blankLine = (): LineDraft => ({ item_id: '', qty: '', price: '', uom: '', factor: '' })
  const [prForm, setPrForm] = useState({ department: '', notes: '' })
  const [prLines, setPrLines] = useState<LineDraft[]>([blankLine()])
  const [poForm, setPoForm] = useState({ supplier_id: '', expected_date: '', terms: '', tax_amount: '0', pr_id: '' })
  const [poLines, setPoLines] = useState<LineDraft[]>([blankLine()])
  const [grnForm, setGrnForm] = useState({ po_id: '', supplier_id: '', warehouse_id: '',
    purchase_type: 'CREDIT' as 'CASH' | 'CREDIT', supplier_invoice_no: '',
    payment_account_code: '1101', tax_amount: '0', note: '' })
  const [grnLines, setGrnLines] = useState<LineDraft[]>([blankLine()])
  const [siForm, setSiForm] = useState({ supplier_id: '', supplier_invoice_no: '',
    invoice_date: todayISO(), po_id: '', grn_id: '', tax_amount: '0' })
  const [siLines, setSiLines] = useState<LineDraft[]>([blankLine()])
  const [payForm, setPayForm] = useState({ supplier_id: '', amount: '', method: 'CASH', discount: '0', invoice_id: '' })
  const [retForm, setRetForm] = useState({ supplier_id: '', warehouse_id: '', reason: '', refund_to: 'CREDIT_AP' })
  const [retLines, setRetLines] = useState<LineDraft[]>([blankLine()])

  const refresh = useCallback(async () => {
    const [is, ss, ws] = await Promise.all([
      invApi.items(), invApi.suppliers(), invApi.warehouses()])
    setItems(is); setSuppliers(ss); setWarehouses(ws)
    const [pr1, po1, gr1, si1, py1, rt1] = await Promise.all([
      invApi.prs(), invApi.pos(), invApi.grns(), invApi.invoices(),
      invApi.payments(), invApi.returns()])
    setPrs(pr1); setPos(po1); setGrns(gr1); setInvs(si1)
    setPayments(py1 as never[]); setReturns(rt1 as never[])
  }, [])

  useEffect(() => { refresh().catch((e) => setErr((e as Error).message)) }, [refresh])

  const run = async (fn: () => Promise<void>, okMsg: string) => {
    setErr(null); setOk(null)
    try { await fn(); setOk(okMsg); await refresh() }
    catch (e) { setErr((e as Error).message) }
  }
  const linesOf = (rows: LineDraft[], withPrice = true) =>
    rows.filter((l) => l.item_id && l.qty).map((l) => ({
      item_id: l.item_id, qty: parseFloat(l.qty),
      ...(withPrice && l.price ? { unit_price: parseFloat(l.price) } : {}),
      ...(l.uom ? { uom: l.uom } : {}),
      ...(l.factor ? { factor: parseFloat(l.factor) } : {}),
    }))

  const LineEditor = ({ rows, setRows, withPrice = true }: {
    rows: LineDraft[]; setRows: (r: LineDraft[]) => void; withPrice?: boolean
  }) => (
    <div className="space-y-1.5">
      {rows.map((l, i) => (
        <div key={i} className="flex gap-1.5 flex-wrap">
          <select className={inp + ' flex-1 min-w-40'} value={l.item_id}
            onChange={(e) => setRows(rows.map((r, j) => j === i ? { ...r, item_id: e.target.value } : r))}>
            <option value="">الصنف…</option>
            {items.map((it) => <option key={it.id} value={it.id}>{it.code} — {it.name_ar}</option>)}
          </select>
          <input className={inp + ' w-20'} placeholder="الكمية" type="number" value={l.qty}
            onChange={(e) => setRows(rows.map((r, j) => j === i ? { ...r, qty: e.target.value } : r))} />
          {withPrice && (
            <input className={inp + ' w-20'} placeholder="السعر" type="number" value={l.price}
              onChange={(e) => setRows(rows.map((r, j) => j === i ? { ...r, price: e.target.value } : r))} />
          )}
          <input className={inp + ' w-20'} placeholder="الوحدة" value={l.uom}
            onChange={(e) => setRows(rows.map((r, j) => j === i ? { ...r, uom: e.target.value } : r))} />
          <input className={inp + ' w-20'} placeholder="المعامل" type="number" value={l.factor}
            onChange={(e) => setRows(rows.map((r, j) => j === i ? { ...r, factor: e.target.value } : r))} />
          <Btn kind="ghost" onClick={() => setRows(rows.filter((_, j) => j !== i))}>✕</Btn>
        </div>
      ))}
      <Btn kind="ghost" onClick={() => setRows([...rows, blankLine()])}>＋ بند</Btn>
    </div>
  )

  const askReason = (title: string) => window.prompt(title)?.trim() ?? ''

  // استلام سريع مقابل أمر معتمد
  const receiveAgainstPo = (po: PO) => {
    setGrnForm({
      po_id: po.id, supplier_id: po.supplier_id, warehouse_id: '',
      purchase_type: 'CREDIT', supplier_invoice_no: '',
      payment_account_code: '1101', tax_amount: '0', note: `مقابل ${po.po_no}`,
    })
    setGrnLines(po.lines.map((l) => ({
      item_id: l.item_id, qty: String(parseFloat(l.base_qty) - parseFloat(l.received_qty)),
      price: l.unit_price, uom: '', factor: '',
    })).filter((l) => parseFloat(l.qty) > 0))
    setTab('الاستلامات GRN')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const invoiceAgainst = (po: PO, grn?: GRN) => {
    setSiForm({ supplier_id: po.supplier_id, supplier_invoice_no: '',
      invoice_date: todayISO(), po_id: po.id, grn_id: grn?.id ?? '', tax_amount: '0' })
    setSiLines(po.lines.map((l) => ({ item_id: l.item_id,
      qty: l.received_qty, price: l.unit_price, uom: '', factor: '' })))
    setTab('فواتير الموردين')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-xl font-black text-sijill-950">دورة المشتريات</h2>
        <div className="flex gap-1 bg-white rounded-xl border border-slate-200 p-1 flex-wrap">
          {TABS.map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${tab === t ? 'bg-sijill-600 text-white font-bold' : 'text-slate-600 hover:bg-slate-100'}`}>
              {t}
            </button>
          ))}
        </div>
      </div>
      <ErrorNote msg={err} /><OkNote msg={ok} />

      {tab === 'طلبات الشراء' && (
        <div className="space-y-4">
          {canPr && (
            <Card title="طلب شراء داخلي جديد (§2.1 — اختياري من قسم)">
              <div className="grid md:grid-cols-3 gap-2 mb-3">
                <input className={inp} placeholder="القسم الطالب *" value={prForm.department}
                  onChange={(e) => setPrForm({ ...prForm, department: e.target.value })} />
                <input className={inp + ' md:col-span-2'} placeholder="ملاحظات" value={prForm.notes}
                  onChange={(e) => setPrForm({ ...prForm, notes: e.target.value })} />
              </div>
              <LineEditor rows={prLines} setRows={setPrLines} withPrice={false} />
              <div className="mt-3">
                <Btn onClick={() => run(async () => {
                  await invApi.createPr({ department: prForm.department, notes: prForm.notes,
                    lines: linesOf(prLines, false) })
                  setPrLines([blankLine()]); setPrForm({ department: '', notes: '' })
                }, 'أُنشئ الطلب') } disabled={!prForm.department}>إنشاء الطلب</Btn>
              </div>
            </Card>
          )}
          <Card title={`الطلبات (${prs.length})`}>
            <table className="w-full">
              <thead><tr className="border-b border-slate-100">
                <th className={th}>الرقم</th><th className={th}>القسم</th>
                <th className={th}>البنود</th><th className={th}>الحالة</th>
                <th className={th}>إجراءات</th>
              </tr></thead>
              <tbody>
                {prs.map((p) => (
                  <tr key={p.id} className="border-b border-slate-50">
                    <td className={`${td} font-mono font-bold text-sijill-700`}>{p.pr_no}</td>
                    <td className={td}>{p.department}</td>
                    <td className={`${td} text-xs`}>{p.lines.map((l) => `${l.item_code}×${fmt(l.qty, 0)}`).join('، ')}</td>
                    <td className={td}><Badge tone={statusTone(p.status)}>{INV_STATUS_AR[p.status] ?? p.status}</Badge></td>
                    <td className={td}>
                      <div className="flex gap-1">
                        {p.status === 'DRAFT' && <Btn kind="ghost" onClick={() => run(async () => { await invApi.submitPr(p.id) }, 'رفُع للاعتماد')}>رفع</Btn>}
                        {p.status === 'SUBMITTED' && has('inv.pr.approve') && <>
                          <Btn onClick={() => run(async () => { await invApi.approvePr(p.id, true) }, 'اعتُمد')}>اعتماد ✅</Btn>
                          <Btn kind="danger" onClick={() => { const r = askReason('سبب الرفض:'); if (r) run(async () => { await invApi.approvePr(p.id, false, r) }, 'رُفض') }}>رفض</Btn>
                        </>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      {tab === 'أوامر الشراء' && (
        <div className="space-y-4">
          {canPo && (
            <Card title="أمر شراء جديد — الاعتماد على سلم القيمة تلقائياً (ملف 14 §2)">
              <div className="grid md:grid-cols-4 gap-2 mb-3">
                <select className={inp} value={poForm.supplier_id}
                  onChange={(e) => setPoForm({ ...poForm, supplier_id: e.target.value })}>
                  <option value="">المورد *</option>
                  {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
                <input className={inp} type="date" title="تاريخ التوريد المتوقع" value={poForm.expected_date}
                  onChange={(e) => setPoForm({ ...poForm, expected_date: e.target.value })} />
                <input className={inp} placeholder="ضريبة إن وجدت" type="number" value={poForm.tax_amount}
                  onChange={(e) => setPoForm({ ...poForm, tax_amount: e.target.value })} />
                <input className={inp} placeholder="شروط" value={poForm.terms}
                  onChange={(e) => setPoForm({ ...poForm, terms: e.target.value })} />
              </div>
              <LineEditor rows={poLines} setRows={setPoLines} />
              <div className="mt-3">
                <Btn onClick={() => run(async () => {
                  await invApi.createPo({ supplier_id: poForm.supplier_id,
                    expected_date: poForm.expected_date || null,
                    tax_amount: parseFloat(poForm.tax_amount || '0'),
                    terms: poForm.terms, lines: linesOf(poLines) })
                  setPoLines([blankLine()])
                }, 'أُنشئ الأمر على سلّم الاعتماد')} disabled={!poForm.supplier_id}>إنشاء الأمر</Btn>
              </div>
            </Card>
          )}
          <Card title={`الأوامر (${pos.length})`}>
            <table className="w-full">
              <thead><tr className="border-b border-slate-100">
                <th className={th}>الرقم</th><th className={th}>المورد</th>
                <th className={th}>الإجمالي</th><th className={th}>الاعتماد</th>
                <th className={th}>الحالة</th><th className={th}>إجراءات</th>
              </tr></thead>
              <tbody>
                {pos.map((p) => (
                  <Fragment key={p.id}>
                    <tr key={p.id} className="border-b border-slate-50 hover:bg-slate-50/70">
                      <td className={`${td} font-mono font-bold text-sijill-700 cursor-pointer`}
                        onClick={() => setExpanded(expanded === p.id ? null : p.id)}>
                        {expanded === p.id ? '▾' : '▸'} {p.po_no}</td>
                      <td className={td}>{p.supplier}</td>
                      <td className={`${td} font-bold`}>{fmt(p.total)}</td>
                      <td className={`${td} text-xs`}>
                        {p.approve_level_required === 0 ? 'ذاتي (حد الأمين)'
                          : `سلم L${p.approve_level_required}`}
                        {p.approved1_by && <div title="اعتماد أول">✔ {p.approved1_by === 'system' ? 'نظام' : 'أول'}</div>}
                        {p.approved2_by && <div title="اعتماد ثانٍ">✔ ثانٍ</div>}
                      </td>
                      <td className={td}><Badge tone={statusTone(p.status)}>{INV_STATUS_AR[p.status] ?? p.status}</Badge></td>
                      <td className={td}>
                        <div className="flex gap-1 flex-wrap">
                          {p.status.startsWith('PENDING') && <>
                            <Btn onClick={() => run(async () => { await invApi.approvePo(p.id) },
                              'اعتُمد بزر موقّع')}>اعتماد ✅</Btn>
                            <Btn kind="danger" onClick={() => { const r = askReason('سبب الرفض:'); if (r) run(async () => { await invApi.rejectPo(p.id, r) }, 'رُفض') }}>رفض</Btn>
                          </>}
                          {['APPROVED', 'PART_RECEIVED'].includes(p.status) && canGrn &&
                            <Btn kind="gold" onClick={() => receiveAgainstPo(p)}>استلام 📦</Btn>}
                          {['APPROVED', 'PART_RECEIVED', 'RECEIVED'].includes(p.status) && canInv &&
                            <Btn kind="ghost" onClick={() => invoiceAgainst(p)}>فاتورة 🧾</Btn>}
                          {!['PART_RECEIVED', 'RECEIVED', 'CANCELLED', 'REJECTED'].includes(p.status) &&
                            <Btn kind="ghost" onClick={() => { const r = askReason('مسوغ الإلغاء:'); if (r) run(async () => { await invApi.cancelPo(p.id, r) }, 'أُلغي') }}>إلغاء</Btn>}
                        </div>
                      </td>
                    </tr>
                    {expanded === p.id && (
                      <tr key={p.id + '-x'} className="bg-slate-50/50">
                        <td colSpan={6} className="px-8 py-2">
                          <table className="w-full">
                            <thead><tr className="border-b border-slate-100">
                              <th className={th}>الصنف</th><th className={th}>الكمية</th>
                              <th className={th}>بالأساسية</th><th className={th}>السعر</th>
                              <th className={th}>الإجمالي</th><th className={th}>المستلم</th>
                            </tr></thead>
                            <tbody>
                              {p.lines.map((l) => (
                                <tr key={l.id} className="border-b border-slate-50">
                                  <td className={td}>{l.item_code} — {l.item_name}</td>
                                  <td className={td}>{fmt(l.qty, 0)} {l.uom}{l.uom !== 'حبة' && parseFloat(l.factor) !== 1 ? ` (×${l.factor})` : ''}</td>
                                  <td className={td}>{fmt(l.base_qty, 0)}</td>
                                  <td className={td}>{fmt(l.unit_price)}</td>
                                  <td className={td}>{fmt(l.line_total)}</td>
                                  <td className={`${td} font-bold ${parseFloat(l.received_qty) >= parseFloat(l.base_qty) ? 'text-emerald-700' : 'text-amber-700'}`}>
                                    {fmt(l.received_qty, 0)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      {tab === 'الاستلامات GRN' && (
        <div className="space-y-4">
          {canGrn && (
            <Card title="سند استلام بضاعة (§2.3) — مقابل أمر أو مباشر">
              <div className="grid md:grid-cols-4 gap-2 mb-3">
                <select className={inp} value={grnForm.supplier_id} disabled={!!grnForm.po_id}
                  onChange={(e) => setGrnForm({ ...grnForm, supplier_id: e.target.value })}>
                  <option value="">المورد *</option>
                  {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
                <select className={inp} value={grnForm.warehouse_id}
                  onChange={(e) => setGrnForm({ ...grnForm, warehouse_id: e.target.value })}>
                  <option value="">مستودع الاستلام *</option>
                  {warehouses.filter((w) => w.kind !== 'OUTLET').map((w) =>
                    <option key={w.id} value={w.id}>{w.name_ar}</option>)}
                </select>
                <select className={inp} value={grnForm.purchase_type}
                  onChange={(e) => setGrnForm({ ...grnForm, purchase_type: e.target.value as 'CASH' })}>
                  <option value="CREDIT">آجل (#15)</option><option value="CASH">نقدي (#14)</option>
                </select>
                <input className={inp} placeholder="رقم فاتورة المورد (إلزامي للآجل) *"
                  value={grnForm.supplier_invoice_no}
                  onChange={(e) => setGrnForm({ ...grnForm, supplier_invoice_no: e.target.value })} />
                {grnForm.purchase_type === 'CASH' && (
                  <select className={inp} value={grnForm.payment_account_code}
                    onChange={(e) => setGrnForm({ ...grnForm, payment_account_code: e.target.value })}>
                    <option value="1101">صندوق رئيسي 1101</option>
                    <option value="1103">بنك 1103</option>
                  </select>
                )}
                <input className={inp} placeholder="ضريبة مدخلات" type="number" value={grnForm.tax_amount}
                  onChange={(e) => setGrnForm({ ...grnForm, tax_amount: e.target.value })} />
                <input className={inp + ' md:col-span-2'} placeholder="ملاحظة" value={grnForm.note}
                  onChange={(e) => setGrnForm({ ...grnForm, note: e.target.value })} />
              </div>
              <LineEditor rows={grnLines} setRows={setGrnLines} withPrice={!grnForm.po_id} />
              <div className="mt-3">
                <Btn onClick={() => run(async () => {
                  await invApi.createGrn({ ...grnForm, po_id: grnForm.po_id || null,
                    tax_amount: parseFloat(grnForm.tax_amount || '0'),
                    lines: grnLines.filter((l) => l.item_id && l.qty).map((l) => ({
                      item_id: l.item_id, qty_received: parseFloat(l.qty),
                      ...(l.price ? { unit_price: parseFloat(l.price) } : {}),
                    })) })
                  setGrnLines([blankLine()])
                  setGrnForm({ po_id: '', supplier_id: '', warehouse_id: '',
                    purchase_type: 'CREDIT', supplier_invoice_no: '',
                    payment_account_code: '1101', tax_amount: '0', note: '' })
                }, 'أُنشئ السند — رحِّله ليدخل المخزون بالقيد')} disabled={!grnForm.supplier_id || !grnForm.warehouse_id}>
                  إنشاء السند</Btn>
              </div>
              <p className="text-xs text-slate-400 mt-2">السند المرحَّل غير قابل للتعديل إطلاقاً — التصحيح بعكس موثق + سند جديد (قبول §7.4)</p>
            </Card>
          )}
          <Card title={`سندات الاستلام (${grns.length})`}>
            <table className="w-full">
              <thead><tr className="border-b border-slate-100">
                <th className={th}>الرقم</th><th className={th}>المورد</th>
                <th className={th}>المستودع</th><th className={th}>النوع</th>
                <th className={th}>الإجمالي</th><th className={th}>الحالة</th>
                <th className={th}>إجراءات</th>
              </tr></thead>
              <tbody>
                {grns.map((g) => (
                  <Fragment key={g.id}>
                    <tr key={g.id} className="border-b border-slate-50 hover:bg-slate-50/70">
                      <td className={`${td} font-mono font-bold text-sijill-700 cursor-pointer`}
                        onClick={() => setExpanded(expanded === g.id ? null : g.id)}>
                        {expanded === g.id ? '▾' : '▸'} {g.grn_no}</td>
                      <td className={td}>{g.supplier}</td>
                      <td className={td}>{g.warehouse}</td>
                      <td className={td}><Badge tone={g.purchase_type === 'CREDIT' ? 'amber' : 'blue'}>{g.purchase_type === 'CREDIT' ? 'آجل' : 'نقدي'}</Badge></td>
                      <td className={`${td} font-bold`}>{fmt(g.total)}</td>
                      <td className={td}><Badge tone={statusTone(g.status)}>{INV_STATUS_AR[g.status] ?? g.status}</Badge></td>
                      <td className={td}>
                        <div className="flex gap-1">
                          {g.status === 'DRAFT' && canGrn &&
                            <Btn onClick={() => run(async () => { await invApi.postGrn(g.id) }, 'رُحِّل ودخل المخزون والقيد')}>ترحيل ✅</Btn>}
                          {g.status === 'POSTED' && has('inv.grn.reverse') &&
                            <Btn kind="danger" onClick={() => { const r = askReason('مسوغ العكس (إلزامي):'); if (r) run(async () => { await invApi.reverseGrn(g.id, r) }, 'عُكس بقيد عكسي') }}>عكس ↩</Btn>}
                        </div>
                      </td>
                    </tr>
                    {expanded === g.id && (
                      <tr key={g.id + '-x'} className="bg-slate-50/50">
                        <td colSpan={7} className="px-8 py-2">
                          <table className="w-full">
                            <thead><tr className="border-b border-slate-100">
                              <th className={th}>الصنف</th><th className={th}>مطلوب</th>
                              <th className={th}>مستلم</th><th className={th}>مرفوض</th>
                              <th className={th}>السعر</th><th className={th}>الإجمالي</th>
                              <th className={th}>دفعة/صلاحية</th>
                            </tr></thead>
                            <tbody>
                              {g.lines.map((l, i) => (
                                <tr key={i} className="border-b border-slate-50">
                                  <td className={td}>{l.item_code}</td>
                                  <td className={td}>{fmt(l.qty_ordered, 0)}</td>
                                  <td className={td}>{fmt(l.qty_received, 0)}</td>
                                  <td className={td}>
                                    {parseFloat(l.qty_rejected) > 0
                                      ? <span className="text-red-600" title={l.reject_reason ?? ''}>{fmt(l.qty_rejected, 0)} ⚠</span>
                                      : '—'}</td>
                                  <td className={td}>{fmt(l.unit_price)}</td>
                                  <td className={td}>{fmt(l.line_total)}</td>
                                  <td className={`${td} text-xs`}>{l.batch_no || '—'}{l.expiry_date ? ` (${l.expiry_date})` : ''}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      {tab === 'فواتير الموردين' && (
        <div className="space-y-4">
          {canInv && (
            <Card title="تسجيل فاتورة مورد — المطابقة الثلاثية تلقائية (§2.4)">
              <div className="grid md:grid-cols-4 gap-2 mb-3">
                <select className={inp} value={siForm.supplier_id} disabled={!!siForm.po_id}
                  onChange={(e) => setSiForm({ ...siForm, supplier_id: e.target.value })}>
                  <option value="">المورد *</option>
                  {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
                <input className={inp} placeholder="رقم فاتورة المورد *" value={siForm.supplier_invoice_no}
                  onChange={(e) => setSiForm({ ...siForm, supplier_invoice_no: e.target.value })} />
                <input className={inp} type="date" value={siForm.invoice_date}
                  onChange={(e) => setSiForm({ ...siForm, invoice_date: e.target.value })} />
                <input className={inp} placeholder="ضريبة" type="number" value={siForm.tax_amount}
                  onChange={(e) => setSiForm({ ...siForm, tax_amount: e.target.value })} />
                {(siForm.po_id || siForm.grn_id) && (
                  <div className="text-xs text-emerald-700 md:col-span-4">
                    سيطابَق ضد {siForm.po_id ? 'أمر الشراء' : ''}{siForm.po_id && siForm.grn_id ? ' ↔ ' : ''}{siForm.grn_id ? 'سند الاستلام' : ''} تلقائياً
                  </div>
                )}
              </div>
              <LineEditor rows={siLines} setRows={setSiLines} />
              <div className="mt-3">
                <Btn onClick={() => run(async () => {
                  await invApi.createInvoice({ ...siForm,
                    po_id: siForm.po_id || null, grn_id: siForm.grn_id || null,
                    tax_amount: parseFloat(siForm.tax_amount || '0'),
                    lines: linesOf(siLines) })
                  setSiLines([blankLine()])
                  setSiForm({ supplier_id: '', supplier_invoice_no: '',
                    invoice_date: todayISO(), po_id: '', grn_id: '', tax_amount: '0' })
                }, 'سُجِّلت — نتيجة المطابقة بجانبها') } disabled={!siForm.supplier_id || !siForm.supplier_invoice_no}>
                  تسجيل ومطابقة</Btn>
              </div>
            </Card>
          )}
          <Card title={`الفواتير (${invs.length})`}>
            <table className="w-full">
              <thead><tr className="border-b border-slate-100">
                <th className={th}>رقمنا</th><th className={th}>فاتورة المورد</th>
                <th className={th}>المورد</th><th className={th}>الإجمالي</th>
                <th className={th}>المتبقي</th><th className={th}>المطابقة</th>
                <th className={th}>إجراءات</th>
              </tr></thead>
              <tbody>
                {invs.map((si) => (
                  <Fragment key={si.id}>
                    <tr key={si.id} className="border-b border-slate-50 hover:bg-slate-50/70">
                      <td className={`${td} font-mono font-bold text-sijill-700 cursor-pointer`}
                        onClick={() => setExpanded(expanded === si.id ? null : si.id)}>
                        {expanded === si.id ? '▾' : '▸'} {si.sinv_no}</td>
                      <td className={td}>{si.supplier_invoice_no}</td>
                      <td className={td}>{si.supplier}</td>
                      <td className={`${td} font-bold`}>{fmt(si.total)}</td>
                      <td className={`${td} ${parseFloat(si.remaining) > 0 ? 'text-red-600 font-bold' : 'text-emerald-700'}`}>{fmt(si.remaining)}</td>
                      <td className={td}><Badge tone={statusTone(si.status)}>{INV_STATUS_AR[si.status] ?? si.status}</Badge></td>
                      <td className={td}>
                        <div className="flex gap-1 flex-wrap">
                          {si.status === 'MATCHED' && has('inv.invoice.approve') &&
                            <Btn onClick={() => run(async () => { await invApi.approveInvoice(si.id) }, 'اعتُمدت وأصبحت قابلة للسداد')}>اعتماد ✅</Btn>}
                          {si.status === 'VARIANCE_HOLD' && <>
                            {has('inv.variance.approve') &&
                              <Btn kind="gold" onClick={() => {
                                if (window.confirm('اعتماد فرق السعر وترحيله لحساب فروقات أسعار الشراء 5120؟'))
                                  run(async () => { await invApi.resolveVariance(si.id, { action: 'APPROVE_VARIANCE' }) }, 'اعتُمد الفرق برهن 5120')
                              }}>اعتماد الفرق لِـ 5120</Btn>}
                            {canInv &&
                              <Btn kind="ghost" onClick={() => {
                                const price = window.prompt('السعر المتفاوض عليه (يطبق على أول بند):')?.trim()
                                if (!price || !si.lines.length) return
                                run(async () => {
                                  await invApi.resolveVariance(si.id, {
                                    action: 'EDIT',
                                    corrected_lines: si.lines.map((l, i) => ({
                                      item_id: l.item_id, qty: parseFloat(l.qty),
                                      unit_price: i === 0 ? parseFloat(price) : parseFloat(l.unit_price),
                                    })),
                                  })
                                }, 'عُدِّلت وأُعيدت المطابقة')
                              }}>تفاوض ✎</Btn>}
                          </>}
                        </div>
                      </td>
                    </tr>
                    {expanded === si.id && (
                      <tr key={si.id + '-x'} className="bg-slate-50/50">
                        <td colSpan={7} className="px-8 py-2 space-y-2">
                          {si.match_report && si.match_report.issues.length > 0 && (
                            <div className="bg-amber-50 border border-amber-200 rounded-lg p-2 text-xs">
                              <b>فروقات المطابقة ({si.match_report.checked_at.slice(0, 16)}):</b>
                              {si.match_report.issues.map((i, k) => <div key={k}>• [{i.item}] {i.detail}</div>)}
                            </div>
                          )}
                          <table className="w-full">
                            <thead><tr className="border-b border-slate-100">
                              <th className={th}>الصنف</th><th className={th}>الكمية</th>
                              <th className={th}>السعر</th><th className={th}>الإجمالي</th>
                            </tr></thead>
                            <tbody>
                              {si.lines.map((l, i) => (
                                <tr key={i} className="border-b border-slate-50">
                                  <td className={td}>{l.item_code}</td>
                                  <td className={td}>{fmt(l.qty, 0)}</td>
                                  <td className={td}>{fmt(l.unit_price)}</td>
                                  <td className={td}>{fmt(l.line_total)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          {(si.status === 'APPROVED' || si.status === 'PAID') && canPay && (
                            <Btn kind="gold" onClick={() => {
                              setPayForm({ ...payForm, supplier_id: si.supplier_id,
                                amount: si.remaining, invoice_id: si.id })
                              setTab('السداد والمرتجعات')
                              window.scrollTo({ top: 0, behavior: 'smooth' })
                            }}>سداد المتبقي {fmt(si.remaining)} 💰</Btn>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      {tab === 'السداد والمرتجعات' && (
        <div className="grid lg:grid-cols-2 gap-4">
          <div className="space-y-4">
            {canPay && (
              <Card title="سداد مورد (#16) — خصم مكتسب يُقيد دائناً 4901">
                <div className="grid grid-cols-2 gap-2">
                  <select className={inp} value={payForm.supplier_id}
                    onChange={(e) => setPayForm({ ...payForm, supplier_id: e.target.value })}>
                    <option value="">المورد *</option>
                    {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name} (ذمة {fmt(s.balance)})</option>)}
                  </select>
                  <input className={inp} placeholder="المبلغ *" type="number" value={payForm.amount}
                    onChange={(e) => setPayForm({ ...payForm, amount: e.target.value })} />
                  <select className={inp} value={payForm.method}
                    onChange={(e) => setPayForm({ ...payForm, method: e.target.value })}>
                    <option value="CASH">نقداً (1101)</option>
                    <option value="BANK">بنك (1103)</option>
                    <option value="EWALLET">محفظة (1104)</option>
                  </select>
                  <input className={inp} placeholder="خصم مكتسب (دائن 4901)" type="number" value={payForm.discount}
                    onChange={(e) => setPayForm({ ...payForm, discount: e.target.value })} />
                  <select className={inp + ' col-span-2'} value={payForm.invoice_id}
                    onChange={(e) => setPayForm({ ...payForm, invoice_id: e.target.value })}>
                    <option value="">تخصيص لفاتورة (اختياري — وإلا فائض ذمة)</option>
                    {invs.filter((i) => i.status === 'APPROVED' && (!payForm.supplier_id || i.supplier_id === payForm.supplier_id)).map((i) =>
                      <option key={i.id} value={i.id}>{i.sinv_no} — متبقٍ {fmt(i.remaining)}</option>)}
                  </select>
                </div>
                <div className="mt-3">
                  <Btn onClick={() => run(async () => {
                    await invApi.createPayment({
                      supplier_id: payForm.supplier_id,
                      amount: parseFloat(payForm.amount || '0'),
                      method: payForm.method,
                      discount: parseFloat(payForm.discount || '0'),
                      allocations: payForm.invoice_id
                        ? [{ invoice_id: payForm.invoice_id, amount: parseFloat(payForm.amount || '0') }]
                        : [],
                    })
                    setPayForm({ supplier_id: '', amount: '', method: 'CASH', discount: '0', invoice_id: '' })
                  }, 'سُدد بقيد #16')} disabled={!payForm.supplier_id || !payForm.amount}>سداد 💰</Btn>
                </div>
              </Card>
            )}
            <Card title={`السدادات (${payments.length})`}>
              <table className="w-full">
                <thead><tr className="border-b border-slate-100">
                  <th className={th}>الرقم</th><th className={th}>المورد</th>
                  <th className={th}>التاريخ</th><th className={th}>المبلغ</th>
                  <th className={th}>خصم مكتسب</th>
                </tr></thead>
                <tbody>
                  {(payments as { id: string; pay_no: string; supplier: string
                    payment_date: string; amount: string; discount: string }[]).map((p) => (
                    <tr key={p.id} className="border-b border-slate-50">
                      <td className={`${td} font-mono font-bold`}>{p.pay_no}</td>
                      <td className={td}>{p.supplier}</td>
                      <td className={td}>{p.payment_date}</td>
                      <td className={`${td} font-bold`}>{fmt(p.amount)}</td>
                      <td className={td}>{parseFloat(p.discount) > 0 ? fmt(p.discount) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>
          <div className="space-y-4">
            {canRet && (
              <Card title="مرتجع مشتريات للمورد (#17) — مستند مستقل">
                <div className="grid grid-cols-2 gap-2 mb-2">
                  <select className={inp} value={retForm.supplier_id}
                    onChange={(e) => setRetForm({ ...retForm, supplier_id: e.target.value })}>
                    <option value="">المورد *</option>
                    {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                  <select className={inp} value={retForm.warehouse_id}
                    onChange={(e) => setRetForm({ ...retForm, warehouse_id: e.target.value })}>
                    <option value="">من مستودع *</option>
                    {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name_ar}</option>)}
                  </select>
                  <select className={inp} value={retForm.refund_to}
                    onChange={(e) => setRetForm({ ...retForm, refund_to: e.target.value })}>
                    <option value="CREDIT_AP">تخفيض ذمته (2101)</option>
                    <option value="CASH">استرداد نقدي (1101)</option>
                  </select>
                  <input className={inp} placeholder="المسوغ *" value={retForm.reason}
                    onChange={(e) => setRetForm({ ...retForm, reason: e.target.value })} />
                </div>
                <LineEditor rows={retLines} setRows={setRetLines} withPrice={false} />
                <div className="mt-3">
                  <Btn onClick={() => run(async () => {
                    const r = await invApi.createReturn({ ...retForm,
                      lines: linesOf(retLines, false) }) as { id: string }
                    await invApi.postReturn(r.id)
                    setRetLines([blankLine()])
                  }, 'أُنشئ ورُحِّل — نقص المخزون بالمتوسط وقيد #17 صدر')}
                    disabled={!retForm.supplier_id || !retForm.warehouse_id || retForm.reason.length < 3}>
                    إنشاء وترحيل ↩</Btn>
                </div>
              </Card>
            )}
            <Card title={`المرتجعات (${returns.length})`}>
              <table className="w-full">
                <thead><tr className="border-b border-slate-100">
                  <th className={th}>الرقم</th><th className={th}>المورد</th>
                  <th className={th}>المستودع</th><th className={th}>القيمة</th>
                  <th className={th}>الحالة</th>
                </tr></thead>
                <tbody>
                  {(returns as { id: string; srt_no: string; supplier: string
                    warehouse: string; total: string; status: string }[]).map((r) => (
                    <tr key={r.id} className="border-b border-slate-50">
                      <td className={`${td} font-mono font-bold`}>{r.srt_no}</td>
                      <td className={td}>{r.supplier}</td>
                      <td className={td}>{r.warehouse}</td>
                      <td className={`${td} font-bold`}>{fmt(r.total)}</td>
                      <td className={td}><Badge tone={statusTone(r.status)}>{INV_STATUS_AR[r.status] ?? r.status}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}
