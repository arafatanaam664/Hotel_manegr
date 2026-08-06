import { useEffect, useState } from 'react'
import { api, HttpError } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import { getCorporates, getGuests, type Corporate, type Guest } from '../hotel'

export default function Guests() {
  const { has } = useAuth()
  const [tab, setTab] = useState<'guests' | 'corporates'>('guests')
  const [guests, setGuests] = useState<Guest[] | null>(null)
  const [corporates, setCorporates] = useState<Corporate[]>([])
  const [q, setQ] = useState('')
  const [show, setShow] = useState(false)
  const [editFor, setEditFor] = useState<Guest | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)

  async function refresh() {
    const [g, c] = await Promise.all([getGuests(q), getCorporates()])
    setGuests(g); setCorporates(c)
  }
  useEffect(() => { refresh().catch((e) => setErr(e.message)) }, [])

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <Btn kind={tab === 'guests' ? 'primary' : 'ghost'} onClick={() => setTab('guests')}>النزلاء</Btn>
        <Btn kind={tab === 'corporates' ? 'primary' : 'ghost'} onClick={() => setTab('corporates')}>الشركات</Btn>
      </div>
      <ErrorNote msg={err} />
      <OkNote msg={ok} />
      {tab === 'guests' && (
        <Card title="سجل النزلاء (الهوية مشفرة — تُعرض مقنّعة فقط)"
              actions={
                <div className="flex gap-2">
                  <input value={q} onChange={(e) => setQ(e.target.value)}
                         onKeyDown={(e) => e.key === 'Enter' && refresh()}
                         placeholder="بحث بالاسم/الهاتف…"
                         className="border border-slate-300 rounded-xl px-3 py-1.5 text-sm w-56" />
                  <Btn kind="ghost" onClick={refresh}>بحث</Btn>
                  {has('guests.manage') && <Btn onClick={() => setShow(true)}>+ نزيل</Btn>}
                </div>
              }>
          {!guests ? <Spinner /> : guests.length === 0 ? (
            <div className="text-center text-slate-400 py-8">لا نزلاء مسجلين</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-xs border-b">
                  <th className="text-right py-2 font-medium">الاسم</th>
                  <th className="text-right font-medium">الهاتف</th>
                  <th className="text-right font-medium">الهوية (نوعها/إصدارها)</th>
                  <th className="text-right font-medium">الجنسية</th>
                  <th className="text-right font-medium">وسوم</th>
                  <th className="text-right font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {guests.map((g) => (
                  <tr key={g.id} className="border-b last:border-0">
                    <td className="py-2.5 font-bold">{g.full_name}</td>
                    <td className="num">{g.phone || '—'}</td>
                    <td className="text-xs">
                      {g.has_id
                        ? <span>{g.id_type || 'هوية'} <span className="num text-slate-400">{g.id_masked}</span>
                            <div className="text-[10px] text-slate-400">
                              {g.id_issue_place && `إصدار ${g.id_issue_place}`}
                              {g.id_issue_date && ` — ${g.id_issue_date}`}
                            </div></span>
                        : <Badge tone="red">بلا هوية — ناقص معلومية</Badge>}
                    </td>
                    <td>{g.nationality || '—'}</td>
                    <td className="space-x-1 space-x-reverse">
                      {g.vip && <Badge tone="amber">VIP</Badge>}
                      {g.blacklist && <Badge tone="red">قائمة سوداء</Badge>}
                    </td>
                    <td>{has('guests.manage') &&
                      <Btn kind="ghost" onClick={() => setEditFor(g)}>تعديل</Btn>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
      {tab === 'corporates' && (
        <Card title="الشركات وجهات الحجز (ذمة المدينة 1120)"
              actions={has('corporates.manage') ? (
                <Btn onClick={async () => {
                  const name = prompt('اسم الشركة:')
                  if (name && name.length >= 2) {
                    try {
                      await api('/api/hotel/corporates', {
                        method: 'POST',
                        body: JSON.stringify({ name, contact_person: '', phone: '' }),
                      })
                      setOk('أُضيفت الشركة')
                      await refresh()
                    } catch (e) { setErr(e instanceof HttpError ? e.message : 'فشل') }
                  }
                }}>+ شركة</Btn>
              ) : undefined}>
          {corporates.length === 0 ? (
            <div className="text-center text-slate-400 py-8">لا شركات مسجلة</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-xs border-b">
                  <th className="text-right py-2 font-medium">الشركة</th>
                  <th className="text-right font-medium">الاتصال</th>
                  <th className="text-right font-medium">سقف الائتمان</th>
                  <th className="text-right font-medium">خصم تعاقدي</th>
                  <th className="text-right font-medium">التسوية</th>
                </tr>
              </thead>
              <tbody>
                {corporates.map((c) => (
                  <tr key={c.id} className="border-b last:border-0">
                    <td className="py-2.5 font-bold">{c.name}</td>
                    <td>{c.contact_person || '—'} <span className="num text-xs text-slate-400">{c.phone}</span></td>
                    <td className="num">{c.credit_limit ?? '—'}</td>
                    <td className="num">{c.discount_pct}%</td>
                    <td>{c.settlement_period === 'MONTHLY' ? 'شهري' : 'أسبوعي'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
      {show && <NewGuestModal onClose={() => setShow(false)} onDone={async () => { setShow(false); setOk('أُضيف النزيل'); await refresh() }} />}
      {editFor && <EditGuestModal guest={editFor} onClose={() => setEditFor(null)}
        onDone={async () => { setEditFor(null); setOk('حُدّث ملف النزيل'); await refresh() }} />}
    </div>
  )
}

function NewGuestModal({ onClose, onDone }: { onClose: () => void; onDone: () => Promise<void> }) {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [idType, setIdType] = useState('')
  const [idNumber, setIdNumber] = useState('')
  const [idPlace, setIdPlace] = useState('')
  const [idDate, setIdDate] = useState('')
  const [nationality, setNationality] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-3xl p-6 w-full max-w-md shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-black text-lg mb-4">نزيل جديد</h3>
        {err && <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-3 py-2 text-xs mb-3">{err}</div>}
        <form className="space-y-3" onSubmit={async (e) => {
          e.preventDefault(); setBusy(true); setErr(null)
          try {
            await api('/api/hotel/guests', {
              method: 'POST',
              body: JSON.stringify({
                full_name: name.trim(), phone: phone.trim(),
                id_number: idNumber.trim(), nationality: nationality.trim(),
                id_type: idType, id_issue_place: idPlace.trim(),
                id_issue_date: idDate || null,
              }),
            })
            await onDone()
          } catch (ex) { setErr(ex instanceof HttpError ? ex.message : 'فشل') }
          setBusy(false)
        }}>
          <input value={name} required autoFocus placeholder="الاسم الكامل…"
                 onChange={(e) => setName(e.target.value)}
                 className="w-full border border-slate-300 rounded-xl px-3 py-2" />
          <input value={phone} placeholder="الهاتف…"
                 onChange={(e) => setPhone(e.target.value)}
                 className="w-full border border-slate-300 rounded-xl px-3 py-2 num" />
          <div className="grid grid-cols-3 gap-2">
            <select value={idType} onChange={(e) => setIdType(e.target.value)}
                    className="border border-slate-300 rounded-xl px-2 py-2 text-sm">
              <option value="">نوع الهوية…</option>
              <option value="شخصية">شخصية</option><option value="جواز">جواز</option>
              <option value="عسكرية">عسكرية</option><option value="إقامة">إقامة</option>
              <option value="أخرى">أخرى</option>
            </select>
            <input value={idNumber} placeholder="رقمها (يُشفَّر ساكناً)…"
                   onChange={(e) => setIdNumber(e.target.value)}
                   className="col-span-2 border border-slate-300 rounded-xl px-3 py-2 num" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <input value={idPlace} placeholder="مكان الإصدار (للمعلومية)…"
                   onChange={(e) => setIdPlace(e.target.value)}
                   className="border border-slate-300 rounded-xl px-3 py-2" />
            <input type="date" value={idDate} title="تاريخ إصدار الهوية"
                   onChange={(e) => setIdDate(e.target.value)}
                   className="border border-slate-300 rounded-xl px-3 py-2 num" />
          </div>
          <input value={nationality} placeholder="الجنسية…"
                 onChange={(e) => setNationality(e.target.value)}
                 className="w-full border border-slate-300 rounded-xl px-3 py-2" />
          <div className="flex justify-end gap-2 pt-2">
            <Btn kind="ghost" type="button" onClick={onClose}>إلغاء</Btn>
            <Btn type="submit" disabled={busy || name.trim().length < 2}>{busy ? '…' : 'حفظ النزيل'}</Btn>
          </div>
        </form>
      </div>
    </div>
  )
}

function EditGuestModal({ guest, onClose, onDone }: {
  guest: Guest; onClose: () => void; onDone: () => Promise<void>
}) {
  const [f, setF] = useState({
    full_name: guest.full_name, phone: guest.phone,
    id_type: guest.id_type ?? '', id_number: '',
    id_issue_place: guest.id_issue_place ?? '',
    id_issue_date: guest.id_issue_date ?? '',
    nationality: guest.nationality ?? '',
  })
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const inp = 'w-full border border-slate-300 rounded-xl px-3 py-2 text-sm'
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
         onClick={onClose}>
      <div className="bg-white rounded-3xl p-6 w-full max-w-md shadow-2xl max-h-[92vh] overflow-auto"
           onClick={(e) => e.stopPropagation()}>
        <h3 className="font-black text-lg mb-1">تعديل ملف النزيل</h3>
        <p className="text-[11px] text-slate-400 mb-3">
          حقول المعلومية اليومية: نوع الهوية + رقمها + مكان إصدارها وتاريخه.
          أدخل الرقم الجديد فقط إن أردت استبداله — اتركه فارغاً ليبقى الحالي {guest.id_masked}.
        </p>
        {err && <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-3 py-2 text-xs mb-3">{err}</div>}
        <form className="space-y-2.5" onSubmit={async (e) => {
          e.preventDefault(); setBusy(true); setErr(null)
          try {
            await api(`/api/hotel/guests/${guest.id}`, {
              method: 'PATCH',
              body: JSON.stringify({
                full_name: f.full_name.trim(), phone: f.phone.trim(),
                nationality: f.nationality.trim(), id_type: f.id_type,
                id_issue_place: f.id_issue_place.trim(),
                id_issue_date: f.id_issue_date || null,
                ...(f.id_number.trim() ? { id_number: f.id_number.trim() } : {}),
              }),
            })
            await onDone()
          } catch (ex) { setErr(ex instanceof HttpError ? ex.message : 'فشل') }
          setBusy(false)
        }}>
          <input className={inp} required value={f.full_name} placeholder="الاسم رباعياً مع اللقب"
                 onChange={(e) => setF({ ...f, full_name: e.target.value })} />
          <input className={inp + ' num'} value={f.phone} placeholder="الهاتف"
                 onChange={(e) => setF({ ...f, phone: e.target.value })} />
          <div className="grid grid-cols-3 gap-2">
            <select className={inp} value={f.id_type}
                    onChange={(e) => setF({ ...f, id_type: e.target.value })}>
              <option value="">نوع الهوية…</option>
              <option value="شخصية">شخصية</option><option value="جواز">جواز</option>
              <option value="عسكرية">عسكرية</option><option value="إقامة">إقامة</option>
              <option value="أخرى">أخرى</option>
            </select>
            <input className={inp + ' num col-span-2'} value={f.id_number}
                   placeholder={guest.has_id ? `رقم جديد يستبدل ${guest.id_masked}` : 'رقم الهوية…'}
                   onChange={(e) => setF({ ...f, id_number: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <input className={inp} value={f.id_issue_place} placeholder="مكان الإصدار…"
                   onChange={(e) => setF({ ...f, id_issue_place: e.target.value })} />
            <input className={inp + ' num'} type="date" value={f.id_issue_date ?? ''}
                   title="تاريخ إصدار الهوية"
                   onChange={(e) => setF({ ...f, id_issue_date: e.target.value })} />
          </div>
          <input className={inp} value={f.nationality} placeholder="الجنسية…"
                 onChange={(e) => setF({ ...f, nationality: e.target.value })} />
          <div className="flex justify-end gap-2 pt-1">
            <Btn kind="ghost" type="button" onClick={onClose}>إلغاء</Btn>
            <Btn type="submit" disabled={busy || f.full_name.trim().length < 2}>
              {busy ? '…' : 'حفظ'}</Btn>
          </div>
        </form>
      </div>
    </div>
  )
}
