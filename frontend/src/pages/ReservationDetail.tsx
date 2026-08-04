import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, fmt, HttpError } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import { getExtras, getFolio, getReservation, rsvStatusAr,
         type Extra, type FolioDetail, type Reservation } from '../hotel'

type Panel = null | 'deposit' | 'charge' | 'payment' | 'discount' | 'transfer' | 'checkout' | 'cancel'

export default function ReservationDetail() {
  const { id } = useParams()
  const { has } = useAuth()
  const [rsv, setRsv] = useState<Reservation | null>(null)
  const [folio, setFolio] = useState<FolioDetail | null>(null)
  const [extras, setExtras] = useState<Extra[]>([])
  const [panel, setPanel] = useState<Panel>(null)
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [invoice, setInvoice] = useState<Record<string, unknown> | null>(null)

  async function refresh() {
    const r = await getReservation(id!)
    setRsv(r)
    const pf = r.folios?.find((f) => f.window === 1)
    if (pf) setFolio(await getFolio(pf.id))
  }
  useEffect(() => {
    refresh().catch((e) => setErr(e.message))
    getExtras().then(setExtras).catch(() => {})
  }, [id])

  async function act(path: string, body: Record<string, unknown> = {}) {
    setErr(null); setOk(null)
    try {
      const r = await api<Record<string, unknown>>(`/api/hotel/reservations/${id}/${path}`, {
        method: 'POST', body: JSON.stringify(body),
      })
      setPanel(null)
      await refresh()
      return r
    } catch (e) {
      setErr(e instanceof HttpError ? e.message : 'فشل الإجراء')
      return null
    }
  }

  if (!rsv) return err ? <ErrorNote msg={err} /> : <Spinner />

  const canCheckIn = rsv.status === 'CONFIRMED' || rsv.status === 'TENTATIVE'
  const isIn = rsv.status === 'CHECKED_IN'
  const canCancel = ['CONFIRMED', 'TENTATIVE'].includes(rsv.status)

  return (
    <div className="space-y-4 max-w-6xl">
      {/* الرأس */}
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-black num">{rsv.confirmation_no}</h1>
              <Badge tone={{ CONFIRMED: 'blue', CHECKED_IN: 'green', CANCELLED: 'red', NO_SHOW: 'amber', CHECKED_OUT: 'slate' }[rsv.status] as 'blue' | 'green' | 'red' | 'amber' | 'slate'}>
                {rsvStatusAr[rsv.status]}
              </Badge>
              <Badge tone="slate">{rsv.source}</Badge>
            </div>
            <div className="text-slate-500 mt-2 text-sm">
              {rsv.guest_name} {rsv.corporate && `— ${rsv.corporate}`} ·
              غرفة <span className="num font-bold">{rsv.room_no}</span> ({rsv.room_type}) ·
              <span className="num"> {rsv.arrival_date} ← {rsv.departure_date}</span> · {rsv.nights} ليالٍ
            </div>
          </div>
          {/* شريط الإجراءات */}
          <div className="flex flex-wrap gap-2">
            {canCheckIn && has('folio.pay') && parseFloat(rsv.deposit_balance) === 0 && (
              <Btn kind="ghost" onClick={() => setPanel('deposit')}>عربون</Btn>)}
            {canCheckIn && has('checkin.do') && (
              <Btn onClick={async () => { const r = await act('check-in'); r && setOk('تم التسكين — العربون طُبّق على الفوليو') }}>تسكين ✓</Btn>)}
            {canCheckIn && has('reservations.cancel') && (
              <>
                <Btn kind="danger" onClick={() => setPanel('cancel')}>إلغاء</Btn>
                {rsv.status === 'CONFIRMED' && (
                  <Btn kind="ghost" onClick={async () => { const r = await act('no-show'); r && setOk('سُجل عدم حضور') }}>عدم حضور</Btn>)}
              </>
            )}
            {isIn && has('checkout.do') && (
              <Btn kind="gold" onClick={() => setPanel('checkout')}>مغادرة (Check-out)</Btn>)}
          </div>
        </div>
        {/* خط سير */}
        <div className="flex items-center gap-1 mt-4 text-[11px]">
          {['CONFIRMED', 'CHECKED_IN', 'CHECKED_OUT'].map((s, i) => (
            <div key={s} className="flex items-center gap-1">
              <span className={`px-3 py-1 rounded-full border ${
                rsv.status === s || (i < ['CONFIRMED', 'CHECKED_IN', 'CHECKED_OUT'].indexOf(rsv.status))
                  ? 'bg-atheer-600 text-white border-atheer-600'
                  : 'bg-slate-50 text-slate-400 border-slate-200'}`}>
                {rsvStatusAr[s]}
              </span>
              {i < 2 && <span className="text-slate-300">←</span>}
            </div>
          ))}
        </div>
      </Card>

      <ErrorNote msg={err} />
      <OkNote msg={ok} />

      {/* الفوليو */}
      {folio && (
        <Card title={`الفوليو (نافذة ${folio.window}) — الرصيد من حساب 1110 لحظياً`}
              actions={
                isIn && (
                  <div className="flex gap-2">
                    {has('folio.charge') && <Btn kind="ghost" onClick={() => setPanel('charge')}>+ شحنة</Btn>}
                    {has('folio.pay') && <Btn kind="ghost" onClick={() => setPanel('payment')}>+ دفعة</Btn>}
                    {has('folio.discount') && <Btn kind="ghost" onClick={() => setPanel('discount')}>% خصم</Btn>}
                    {rsv.corporate_id && has('checkout.credit_transfer') && (
                      <Btn kind="ghost" onClick={() => setPanel('transfer')}>⇄ نقل لنافذة الشركة</Btn>)}
                  </div>
                )
              }>
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div className="bg-slate-50 rounded-xl p-3 text-center">
              <div className="text-xs text-slate-400">إجمالي الشحنات</div>
              <div className="num font-black text-lg">{fmt(folio.charges)}</div>
            </div>
            <div className="bg-slate-50 rounded-xl p-3 text-center">
              <div className="text-xs text-slate-400">المدفوعات</div>
              <div className="num font-black text-lg text-emerald-600">{fmt(folio.payments)}</div>
            </div>
            <div className={`rounded-xl p-3 text-center ${folio.high_balance ? 'bg-red-50 border border-red-300' : 'bg-atheer-50'}`}>
              <div className="text-xs text-slate-400">الرصيد المستحق</div>
              <div className="num font-black text-xl text-atheer-800">{fmt(folio.balance)}</div>
              {folio.high_balance && <Badge tone="red">فوق السقف الائتماني!</Badge>}
            </div>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 text-xs border-b">
                <th className="text-right py-2 font-medium">القيد</th>
                <th className="text-right font-medium">البيان</th>
                <th className="text-right font-medium">مدين (شحنة)</th>
                <th className="text-right font-medium">دائن (دفعة/تخفيض)</th>
                <th className="text-right font-medium">الرصيد</th>
              </tr>
            </thead>
            <tbody>
              {folio.lines.map((l, i) => (
                <tr key={i} className="border-b last:border-0">
                  <td className="py-2 num text-xs text-slate-400">{l.entry_no}</td>
                  <td>{l.narration}</td>
                  <td className="num">{parseFloat(l.debit) > 0 ? fmt(l.debit, 4) : ''}</td>
                  <td className="num">{parseFloat(l.credit) > 0 ? fmt(l.credit, 4) : ''}</td>
                  <td className="num font-medium">{fmt(l.running, 4)}</td>
                </tr>
              ))}
              {folio.lines.length === 0 && (
                <tr><td colSpan={5} className="text-center text-slate-400 py-6">لا حركات بعد</td></tr>)}
            </tbody>
          </table>
        </Card>
      )}

      {/* نافذة الشركة إن وجدت */}
      {rsv.folios?.filter((f) => f.window === 2).map((f) => (
        <Card key={f.id} title="نافذة الشركة (window 2)">
          <div className="num font-black text-xl">الرصيد: {fmt(f.balance)}</div>
          <div className="text-xs text-slate-400 mt-1">تُقفل عند المغادرة بنقلها إلى ذمة المدينة (1120)</div>
        </Card>
      ))}

      {/* اللوحات التفاعلية */}
      {panel === 'deposit' && (
        <ActionPanel title="استلام عربون حجز (#01: صندوق ← أمانات 2110)" onClose={() => setPanel(null)}>
          <DepositForm onSubmit={async (amount) => {
            const r = await act('deposit', { amount })
            if (r) setOk(`سُجل العربون — رصيد العربون الآن ${fmt(String((r as {deposit_balance:string}).deposit_balance))}`)
          }} />
        </ActionPanel>
      )}

      {panel === 'charge' && folio && (
        <ActionPanel title="شحنة خدمة على الفوليو (#05)" onClose={() => setPanel(null)}>
          <ChargeForm extras={extras} folioId={folio.folio_id} onDone={async (bal) => {
            setPanel(null); setOk(`رُحّلت الشحنة — الرصيد ${fmt(bal)}`); await refresh()
          }} />
        </ActionPanel>
      )}

      {panel === 'payment' && folio && (
        <ActionPanel title="دفعة على الفوليو (#07)" onClose={() => setPanel(null)}>
          <PaymentForm folioId={folio.folio_id} onDone={async (bal) => {
            setPanel(null); setOk(`سُجلت الدفعة — الرصيد ${fmt(bal)}`); await refresh()
          }} />
        </ActionPanel>
      )}

      {panel === 'discount' && folio && (
        <ActionPanel title="خصم معتمد (#06 — فوق 100 يتطلب مديراً)" onClose={() => setPanel(null)}>
          <DiscountForm folioId={folio.folio_id} onDone={async (bal) => {
            setPanel(null); setOk(`طُبّق الخصم — الرصيد ${fmt(bal)}`); await refresh()
          }} />
        </ActionPanel>
      )}

      {panel === 'transfer' && (
        <ActionPanel title="تحويل شحنة إلى نافذة الشركة" onClose={() => setPanel(null)}>
          <TransferForm onSubmit={async (amount, reason) => {
            const r = await act('transfer-to-corporate', { amount, reason })
            if (r) setOk('حُوّلت الشحنة إلى نافذة الشركة')
          }} />
        </ActionPanel>
      )}

      {panel === 'cancel' && (
        <ActionPanel title="إلغاء الحجز — غرامة اختيارية من العربون (#02)" onClose={() => setPanel(null)}>
          <CancelForm onSubmit={async (reason, fee) => {
            const r = await act('cancel', { reason, fee: fee || '0', refund: true })
            if (r) setOk(`أُلغي الحجز${parseFloat(fee) > 0 ? ` — غرامة ${fmt(fee)}` : ''}`)
          }} />
        </ActionPanel>
      )}

      {panel === 'checkout' && folio && (
        <ActionPanel title="مغادرة — فحوص إلزامية ثم فاتورة ضريبية نهائية" onClose={() => setPanel(null)} wide>
          <CheckoutForm balance={parseFloat(folio.balance)} hasCorporate={!!rsv.corporate_id}
                        onSubmit={async ({ lateFee, payments, corpTransfer }) => {
            const r = await act('checkout', {
              late_fee: lateFee || '0',
              payments: payments.filter((p) => parseFloat(p.amount) > 0),
              corporate_transfer: corpTransfer,
            })
            if (r) {
              setInvoice(r)
              setOk(`تمت المغادرة — فاتورة ${(r as {invoice_no:string}).invoice_no}`)
            }
          }} />
        </ActionPanel>
      )}

      {invoice && (
        <Card title="الفاتورة الضريبية النهائية (غير قابلة للتعديل)">
          <div className="border-2 border-dashed border-slate-300 rounded-2xl p-6 text-center space-y-2">
            <div className="text-xs text-slate-400">فاتورة رقم</div>
            <div className="text-2xl font-black num">{String((invoice as {invoice_no:string}).invoice_no)}</div>
            <div className="grid grid-cols-3 gap-4 pt-3 text-sm">
              <div>الشحنات<br /><b className="num">{fmt(String((invoice as {charges:string}).charges))}</b></div>
              <div>المدفوعات<br /><b className="num">{fmt(String((invoice as {payments:string}).payments))}</b></div>
              <div>التسوية<br /><Badge tone="green">صفر ✓</Badge></div>
            </div>
            <div className="text-xs text-slate-400 pt-2">إعادة فتح الفاتورة ممنوعة — التصحيح بإشعار دائن/قيد عكسي (ملف 02)</div>
            <Btn kind="ghost" onClick={() => window.print()} className="mt-2">طباعة</Btn>
          </div>
        </Card>
      )}
    </div>
  )
}

// ── لوحة إجراء عامة ────────────────────────────────────
function ActionPanel({ title, children, onClose, wide }: {
  title: string; children: React.ReactNode; onClose: () => void; wide?: boolean
}) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 overflow-y-auto py-8" onClick={onClose}>
      <div className={`bg-white rounded-3xl p-6 w-full ${wide ? 'max-w-2xl' : 'max-w-md'} shadow-2xl`}
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-black">{title}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

function DepositForm({ onSubmit }: { onSubmit: (amount: string) => Promise<void> }) {
  const [amount, setAmount] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <form onSubmit={async (e) => { e.preventDefault(); setBusy(true); await onSubmit(amount); setBusy(false) }}
          className="space-y-3">
      <label className="block">
        <span className="text-xs text-slate-500 block mb-1">مبلغ العربون</span>
        <input value={amount} inputMode="decimal" required autoFocus
               onChange={(e) => setAmount(e.target.value)}
               className="w-full border border-slate-300 rounded-xl px-3 py-2 num" />
      </label>
      <Btn type="submit" disabled={busy || !parseFloat(amount)} className="w-full">
        {busy ? '…' : 'تسجيل العربون'}
      </Btn>
    </form>
  )
}

function ChargeForm({ extras, folioId, onDone }: {
  extras: Extra[]; folioId: string
  onDone: (balance: string) => Promise<void>
}) {
  const [code, setCode] = useState(extras[0]?.code ?? '')
  const [qty, setQty] = useState(1)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const extra = extras.find((x) => x.code === code)
  return (
    <form className="space-y-3" onSubmit={async (e) => {
      e.preventDefault(); setBusy(true); setErr(null)
      try {
        const r = await api<{ balance: string }>(`/api/hotel/folios/${folioId}/charges`, {
          method: 'POST', body: JSON.stringify({ extra_code: code, qty }),
        })
        await onDone(r.balance)
      } catch (ex) { setErr(ex instanceof HttpError ? ex.message : 'فشل') }
      setBusy(false)
    }}>
      <Err msg={err} />
      <label className="block">
        <span className="text-xs text-slate-500 block mb-1">الخدمة</span>
        <select value={code} onChange={(e) => setCode(e.target.value)}
                className="w-full border border-slate-300 rounded-xl px-3 py-2">
          {extras.map((x) => <option key={x.code} value={x.code}>{x.name_ar} — {fmt(x.price)}</option>)}
        </select>
      </label>
      <label className="block">
        <span className="text-xs text-slate-500 block mb-1">الكمية</span>
        <input type="number" min={1} max={50} value={qty} onChange={(e) => setQty(parseInt(e.target.value) || 1)}
               className="w-full border border-slate-300 rounded-xl px-3 py-2 num" />
      </label>
      <div className="text-sm text-slate-500">الإجمالي: <b className="num">{fmt((parseFloat(extra?.price ?? '0') * qty).toFixed(4))}</b></div>
      <Btn type="submit" disabled={busy} className="w-full">{busy ? '…' : 'ترحيل الشحنة'}</Btn>
    </form>
  )
}

function PaymentForm({ folioId, onDone }: { folioId: string; onDone: (b: string) => Promise<void> }) {
  const [amount, setAmount] = useState('')
  const [method, setMethod] = useState('CASH')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  return (
    <form className="space-y-3" onSubmit={async (e) => {
      e.preventDefault(); setBusy(true); setErr(null)
      try {
        const r = await api<{ balance: string }>(`/api/hotel/folios/${folioId}/payments`, {
          method: 'POST', body: JSON.stringify({ amount, method }),
        })
        await onDone(r.balance)
      } catch (ex) { setErr(ex instanceof HttpError ? ex.message : 'فشل') }
      setBusy(false)
    }}>
      <Err msg={err} />
      <label className="block">
        <span className="text-xs text-slate-500 block mb-1">المبلغ</span>
        <input value={amount} inputMode="decimal" required autoFocus
               onChange={(e) => setAmount(e.target.value)}
               className="w-full border border-slate-300 rounded-xl px-3 py-2 num" />
      </label>
      <label className="block">
        <span className="text-xs text-slate-500 block mb-1">الوسيلة</span>
        <select value={method} onChange={(e) => setMethod(e.target.value)}
                className="w-full border border-slate-300 rounded-xl px-3 py-2">
          <option value="CASH">نقد — الصندوق الرئيسي (1101)</option>
          <option value="CARD">بنك/بطاقة (1103)</option>
          <option value="EWALLET">محفظة إلكترونية (1104)</option>
        </select>
      </label>
      <Btn type="submit" disabled={busy || !parseFloat(amount)} className="w-full">
        {busy ? '…' : 'تسجيل الدفعة'}
      </Btn>
    </form>
  )
}

function DiscountForm({ folioId, onDone }: { folioId: string; onDone: (b: string) => Promise<void> }) {
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const needsApproval = parseFloat(amount) > 100
  return (
    <form className="space-y-3" onSubmit={async (e) => {
      e.preventDefault(); setBusy(true); setErr(null)
      try {
        const r = await api<{ balance: string }>(`/api/hotel/folios/${folioId}/discount`, {
          method: 'POST', body: JSON.stringify({ amount, reason }),
        })
        await onDone(r.balance)
      } catch (ex) { setErr(ex instanceof HttpError ? ex.message : 'فشل') }
      setBusy(false)
    }}>
      <Err msg={err} />
      {needsApproval && (
        <div className="bg-amber-50 border border-amber-300 text-amber-800 rounded-xl px-3 py-2 text-xs">
          ⚠ يتجاوز 100 — سيطلب النظام اعتماد مدير (discounts.approve) أو يرفض
        </div>
      )}
      <label className="block">
        <span className="text-xs text-slate-500 block mb-1">مبلغ الخصم</span>
        <input value={amount} inputMode="decimal" required autoFocus
               onChange={(e) => setAmount(e.target.value)}
               className="w-full border border-slate-300 rounded-xl px-3 py-2 num" />
      </label>
      <label className="block">
        <span className="text-xs text-slate-500 block mb-1">السبب (إلزامي)</span>
        <input value={reason} required
               onChange={(e) => setReason(e.target.value)}
               className="w-full border border-slate-300 rounded-xl px-3 py-2" />
      </label>
      <Btn type="submit" disabled={busy || !parseFloat(amount) || reason.trim().length < 3} className="w-full">
        {busy ? '…' : 'تطبيق الخصم'}
      </Btn>
    </form>
  )
}

function TransferForm({ onSubmit }: { onSubmit: (amount: string, reason: string) => Promise<void> }) {
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <form className="space-y-3" onSubmit={async (e) => { e.preventDefault(); setBusy(true); await onSubmit(amount, reason); setBusy(false) }}>
      <label className="block">
        <span className="text-xs text-slate-500 block mb-1">المبلغ المحوَّل</span>
        <input value={amount} inputMode="decimal" required autoFocus
               onChange={(e) => setAmount(e.target.value)}
               className="w-full border border-slate-300 rounded-xl px-3 py-2 num" />
      </label>
      <label className="block">
        <span className="text-xs text-slate-500 block mb-1">السبب</span>
        <input value={reason} onChange={(e) => setReason(e.target.value)}
               className="w-full border border-slate-300 rounded-xl px-3 py-2" />
      </label>
      <Btn type="submit" disabled={busy || !parseFloat(amount)} className="w-full">
        {busy ? '…' : 'تحويل'}
      </Btn>
    </form>
  )
}

function CancelForm({ onSubmit }: { onSubmit: (reason: string, fee: string) => Promise<void> }) {
  const [reason, setReason] = useState('')
  const [fee, setFee] = useState('0')
  const [busy, setBusy] = useState(false)
  return (
    <form className="space-y-3" onSubmit={async (e) => { e.preventDefault(); setBusy(true); await onSubmit(reason, fee); setBusy(false) }}>
      <label className="block">
        <span className="text-xs text-slate-500 block mb-1">سبب الإلغاء (إلزامي)</span>
        <input value={reason} required autoFocus
               onChange={(e) => setReason(e.target.value)}
               className="w-full border border-slate-300 rounded-xl px-3 py-2" />
      </label>
      <label className="block">
        <span className="text-xs text-slate-500 block mb-1">غرامة الإلغاء (من العربون — 0 بدون)</span>
        <input value={fee} inputMode="decimal"
               onChange={(e) => setFee(e.target.value)}
               className="w-full border border-slate-300 rounded-xl px-3 py-2 num" />
      </label>
      <Btn kind="danger" type="submit" disabled={busy || reason.trim().length < 3} className="w-full">
        {busy ? '…' : 'تأكيد الإلغاء'}
      </Btn>
    </form>
  )
}

function CheckoutForm({ balance, hasCorporate, onSubmit }: {
  balance: number; hasCorporate: boolean
  onSubmit: (v: { lateFee: string; payments: { amount: string; method: string }[]; corpTransfer: boolean }) => Promise<void>
}) {
  const [lateFee, setLateFee] = useState('0')
  const [pay1, setPay1] = useState(balance > 0 ? balance.toFixed(4) : '')
  const [method, setMethod] = useState('CASH')
  const [corpTransfer, setCorpTransfer] = useState(false)
  const [busy, setBusy] = useState(false)
  const total = balance + (parseFloat(lateFee) || 0)
  return (
    <form className="space-y-4" onSubmit={async (e) => {
      e.preventDefault(); setBusy(true)
      await onSubmit({
        lateFee,
        payments: corpTransfer ? [] : [{ amount: pay1, method }],
        corpTransfer,
      })
      setBusy(false)
    }}>
      <div className="bg-slate-50 rounded-xl p-4 grid grid-cols-2 gap-3 text-sm">
        <div>رصيد الفوليو الحالي: <b className="num">{fmt(balance.toFixed(4))}</b></div>
        <div>الإجمالي بعد رسوم التأخير: <b className="num">{fmt(total.toFixed(4))}</b></div>
      </div>
      <label className="block">
        <span className="text-xs text-slate-500 block mb-1">رسوم مغادرة متأخرة (4103 — 0 بدون)</span>
        <input value={lateFee} inputMode="decimal" onChange={(e) => setLateFee(e.target.value)}
               className="w-full border border-slate-300 rounded-xl px-3 py-2 num" />
      </label>
      {hasCorporate && (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={corpTransfer} onChange={(e) => setCorpTransfer(e.target.checked)} />
          نقل الرصيد المتبقي إلى ذمة الشركة (1120 — بصلاحية)
        </label>
      )}
      {!corpTransfer && total > 0 && (
        <div className="grid grid-cols-3 gap-2">
          <label className="block col-span-2">
            <span className="text-xs text-slate-500 block mb-1">سداد نهائي</span>
            <input value={pay1} inputMode="decimal" onChange={(e) => setPay1(e.target.value)}
                   className="w-full border border-slate-300 rounded-xl px-3 py-2 num" />
          </label>
          <label className="block">
            <span className="text-xs text-slate-500 block mb-1">الوسيلة</span>
            <select value={method} onChange={(e) => setMethod(e.target.value)}
                    className="w-full border border-slate-300 rounded-xl px-3 py-2">
              <option value="CASH">نقد</option><option value="CARD">بنك</option>
              <option value="EWALLET">محفظة</option>
            </select>
          </label>
        </div>
      )}
      {total < 0 && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl px-3 py-2 text-xs">
          فائض مدفوع {fmt(Math.abs(total).toFixed(4))} — سيُرد نقداً للنزيل تلقائياً
        </div>
      )}
      <Btn kind="gold" type="submit" disabled={busy} className="w-full">
        {busy ? 'يُقفل…' : 'تأكيد المغادرة وإصدار الفاتورة'}
      </Btn>
    </form>
  )
}

function Err({ msg }: { msg: string | null }) {
  return msg ? <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-3 py-2 text-xs">{msg}</div> : null
}
