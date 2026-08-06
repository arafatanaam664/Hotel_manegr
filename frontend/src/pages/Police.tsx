// شاشة «المعلومية اليومية» (البحث الجنائي — طلب المالك، ADR-0038):
// معاينة نزلاء اليوم بلا أرقام صريحة → تنزيل Excel طبق الأصل من القالب
// المعتمد → أرشيف «ما أُرسل فعلاً» ببصمته قابل لإعادة التنزيل الحرفية.
import { useCallback, useEffect, useState } from 'react'
import { HttpError, todayISO } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import { downloadFile, policeApi, type PolicePreview, type PoliceRow, type PoliceRun } from '../hotel'

const input = 'border rounded-lg px-3 py-2 text-sm bg-white'

export default function Police() {
  const { has } = useAuth()
  const [day, setDay] = useState(todayISO())
  const [pv, setPv] = useState<PolicePreview | null>(null)
  const [runs, setRuns] = useState<PoliceRun[]>([])
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  const [busy, setBusy] = useState(false)
  const [hdr, setHdr] = useState({ address: '', district: '', office_label: '' })

  const load = useCallback(async (d: string) => {
    try {
      const [p, r] = await Promise.all([policeApi.preview(d), policeApi.runs()])
      setPv(p); setRuns(r); setErr('')
      setHdr({
        address: p.header.address, district: p.header.district,
        office_label: p.header.office,
      })
    } catch (e) {
      setErr(e instanceof HttpError ? `${e.code}: ${e.message}` : 'تعذر الجلب')
    }
  }, [])
  useEffect(() => { load(day) }, [day, load])

  async function download(d: string, path?: string) {
    setBusy(true); setErr(''); setOk('')
    try {
      const name = await downloadFile(
        path ?? `/api/hotel/police-report/download?date=${d}`,
        `police-${d}.xlsx`)
      setOk(`نُزّل الملف: ${name} — وأُرشف ببصمته وفاعله`)
      await load(d)
    } catch (e) {
      setErr(e instanceof HttpError ? `${e.code}: ${e.message}` : 'فشل التنزيل')
    } finally { setBusy(false) }
  }

  const mainRows = pv?.rows.filter((r) => r.kind === 'main') ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-xl font-black">🛂 المعلومية اليومية — إرسال البحث الجنائي</h2>
        <input type="date" className={input} value={day} max={todayISO()}
               onChange={(e) => setDay(e.target.value)} />
        <Btn kind="ghost" onClick={() => load(day)}>تحديث</Btn>
        {pv && pv.rows_count > 0 && (
          <Btn kind="gold" disabled={busy}
               onClick={() => download(day)}>
            {busy ? 'يُولَّد…' : `⬇ تنزيل ملف اليوم (${pv.rows_count} اسماً)`}
          </Btn>
        )}
      </div>
      <ErrorNote msg={err} /><OkNote msg={ok} />

      {has('settings.manage') && pv && (
        <Card title="⚙ ترويسة الملف الرسمية (تُطبع أعلى معلومية كل يوم)">
          <div className="grid md:grid-cols-4 gap-2 items-end">
            <label className="text-xs text-slate-500">فندق
              <div className="font-bold text-sm mt-1">{pv.header.hotel}</div></label>
            <label className="text-xs text-slate-500">العنوان
              <input className={input + ' w-full'} value={hdr.address}
                     placeholder="التحرير الأسفل"
                     onChange={(e) => setHdr({ ...hdr, address: e.target.value })} /></label>
            <label className="text-xs text-slate-500">المديرية
              <input className={input + ' w-full'} value={hdr.district}
                     placeholder="القاهرة"
                     onChange={(e) => setHdr({ ...hdr, district: e.target.value })} /></label>
            <label className="text-xs text-slate-500">المكتب (م / …)
              <input className={input + ' w-full'} value={hdr.office_label}
                     placeholder="م / تعز"
                     onChange={(e) => setHdr({ ...hdr, office_label: e.target.value })} /></label>
          </div>
          <Btn kind="ghost" className="mt-2" onClick={async () => {
            try {
              await policeApi.saveHeader(hdr)
              setOk('حُفظت الترويسة — ستلتزم بها الملفات القادمة')
              await load(day)
            } catch (e) {
              setErr(e instanceof HttpError ? `${e.code}: ${e.message}` : 'فشل الحفظ')
            }
          }}>حفظ الترويسة</Btn>
        </Card>
      )}

      {!pv ? <Spinner /> : pv.rows_count === 0 ? (
        <Card>
          <div className="text-center text-slate-400 py-10">
            لا نزلاء «لامسوا الفندق» في هذا اليوم — الملغي وعدم الحضور لا يظهران
            أبداً في التبليغ.
          </div>
        </Card>
      ) : (
        <Card
          title={`معلومية النزلاء ليوم ${pv.header.weekday} ${pv.header.date} — ${pv.stays_count} غرفة / ${pv.rows_count} اسماً`}
          actions={<Badge tone="blue">يشمل من غادر اليوم نفسه</Badge>}>
          {pv.warnings.length > 0 && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-3 mb-3 text-sm">
              <b className="text-red-700">⚠ نواقص تظهر فارغة في التبليغ (صحّحها قبل الإرسال):</b>
              <ul className="list-disc pr-5 mt-1 text-red-600 text-xs space-y-0.5">
                {pv.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
          )}
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 text-xs border-b">
                <th className="py-2 text-right">م</th><th className="text-right">الغرفة</th>
                <th className="text-right">الاسم (الرئيسي ثم مرافقوه)</th>
                <th className="text-right">الغرض</th><th className="text-right">الجهة</th>
                <th className="text-right">الهوية</th><th className="text-right">التلفون</th>
                <th className="text-right">وقت النزول</th><th className="text-right">ملاحظات</th>
              </tr>
            </thead>
            <tbody>
              {pv.rows.map((r: PoliceRow, i: number) => (
                <tr key={i}
                    className={`border-b last:border-0 ${r.kind === 'companion' ? 'bg-slate-50/60' : ''}`}>
                  <td className="py-2 num">{r.serial}</td>
                  <td className="num font-bold">{r.room_no}</td>
                  <td className={r.kind === 'companion' ? 'pr-6' : 'font-bold'}>
                    {r.kind === 'companion' ? '↳ ' : ''}{r.name}
                  </td>
                  <td>{r.purpose || <span className="text-red-500">—</span>}</td>
                  <td className="text-xs">{[r.origin_gov, r.origin_district].filter(Boolean).join(' / ') || '—'}</td>
                  <td>
                    {r.has_id
                      ? <Badge tone="green">{r.id_type || '✔'} ✔</Badge>
                      : <Badge tone="red">بلا رقم!</Badge>}
                  </td>
                  <td className="num text-xs">{r.phone || '—'}</td>
                  <td className="num text-xs">{r.in_time || '—'}</td>
                  <td className="text-xs text-slate-500">{r.notes || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[11px] text-slate-400 mt-2">
            أرقام الهوية لا تُعرض هنا أبداً (سياسة التشفير) — تظهر صريحة داخل الملف
            الرسمي نفسه فقط، وكل تنزيل يُوثَّق باسم من قام به.
          </p>
          {mainRows.length > 0 && (
            <div className="text-xs text-slate-400 mt-1">
              الغرف: {mainRows.map((r) => r.room_no).filter(Boolean).join('، ')}
            </div>
          )}
        </Card>
      )}

      <Card title="🗄 أرشيف «ما أُرسل فعلاً» — إثبات قانوني أمام الجهة">
        {runs.length === 0 ? (
          <div className="text-slate-400 text-sm py-4 text-center">
            لم يُنزَّل أي ملف بعد — أول تنزيل يبدأ الأرشيف.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 text-xs border-b">
                <th className="py-2 text-right">معلومية يوم</th>
                <th className="text-right">نزّلها</th>
                <th className="text-right">وقت التنزيل (UTC)</th>
                <th className="text-right">الأسماء</th>
                <th className="text-right">البصمة</th><th></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="border-b last:border-0">
                  <td className="py-2 num font-bold">{r.report_date}</td>
                  <td className="num">{r.generated_by}</td>
                  <td className="num text-xs">{String(r.generated_at).replace('T', ' ').slice(0, 19)}</td>
                  <td className="num">{r.rows_count}
                    <span className="text-xs text-slate-400"> ({r.stays_count} غرفة)</span></td>
                  <td className="num text-[10px] text-slate-400 font-mono">{r.sha256.slice(0, 12)}…</td>
                  <td>
                    <Btn kind="ghost" disabled={busy}
                         onClick={() => download(r.report_date,
                           `/api/hotel/police-report/runs/${r.id}/download`)}>
                      إعادة تنزيل كما أُرسل
                    </Btn>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="text-[11px] text-slate-400 mt-2">
          إعادة التنزيل تعيد نفس الملف حرفياً حتى لو صُحّحت بيانات نزيل لاحقاً —
          فالأرشيف يحفظ الحمولة وبصمتها SHA-256 لحظة الإرسال.
        </p>
      </Card>
    </div>
  )
}
