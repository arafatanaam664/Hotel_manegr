// شاشة مركز المزامنة (ملف 09 §6): حالة القناة، الدفع الفوري، الرفع الأولي،
// صندوق التعارضات بحسم بشري موثق، USB المشفر، سحب التراخيص والنبض.
import { useCallback, useEffect, useState } from 'react'
import {
  ENTITY_AR, EVENT_STATE_AR, OP_AR, syncApi, SyncConflict, SyncEvent,
  SyncStatus,
} from '../sync'
import { useAuth } from '../auth'
import { HttpError } from '../api'

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ background: '#fff', borderRadius: 10, padding: 16,
      marginBottom: 14, boxShadow: '0 1px 4px rgba(0,0,0,.08)' }}>
      <h3 style={{ margin: '0 0 10px', fontSize: 15 }}>{title}</h3>
      {children}
    </section>
  )
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between',
      padding: '5px 0', borderBottom: '1px dashed #eee', fontSize: 13 }}>
      <span style={{ color: '#666' }}>{k}</span>
      <span style={{ fontWeight: 600 }}>{v}</span>
    </div>
  )
}

function Btn({ onClick, disabled, children, danger }: {
  onClick: () => void; disabled?: boolean; children: React.ReactNode
  danger?: boolean
}) {
  return (
    <button onClick={onClick} disabled={disabled} style={{
      background: danger ? '#c0392b' : '#0b5cab', color: '#fff',
      border: 0, borderRadius: 8, padding: '8px 14px', fontSize: 13,
      cursor: disabled ? 'not-allowed' : 'pointer',
      opacity: disabled ? .55 : 1, marginInlineEnd: 8, marginBottom: 6,
    }}>{children}</button>
  )
}

function fmt(ts: string): string {
  if (!ts || ts === 'None') return '—'
  try { return new Date(ts).toLocaleString('ar-YE-u-nu-latn') }
  catch { return ts }
}

export default function SyncCenterPage() {
  const { has } = useAuth()
  const canManage = has('sync.manage')
  const [st, setSt] = useState<SyncStatus | null>(null)
  const [events, setEvents] = useState<SyncEvent[]>([])
  const [conflicts, setConflicts] = useState<SyncConflict[]>([])
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [showUsb, setShowUsb] = useState(false)
  const [usbPass, setUsbPass] = useState('')
  const [usbPacket, setUsbPacket] = useState('')

  const load = useCallback(async () => {
    try {
      const [s, ev, cf] = await Promise.all([
        syncApi.status(), syncApi.events(60), syncApi.conflicts()])
      setSt(s); setEvents(ev); setConflicts(cf); setErr('')
    } catch (e) {
      setErr(e instanceof HttpError ? `${e.code}: ${e.message}` : 'تعذر الجلب')
    }
  }, [])
  useEffect(() => { load() }, [load])
  // تحديث تلقائي كل 15 ثانية — لوحة مراقبة حية
  useEffect(() => {
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [load])

  async function run(fn: () => Promise<unknown>, ok: string) {
    if (busy) return
    setBusy(true); setMsg(''); setErr('')
    try { await fn(); setMsg(ok); await load() }
    catch (e) {
      setErr(e instanceof HttpError ? `${e.code}: ${e.message}` : 'فشل التنفيذ')
    } finally { setBusy(false) }
  }

  async function doPush() {
    setBusy(true); setMsg(''); setErr('')
    try {
      const r = await syncApi.pushNow()
      if (r.error) setErr(`لم يصل شيء بعد: ${r.error} — يبقى آمناً ويُعاد تلقائياً`)
      else setMsg(r.pushed > 0 ? `أُرسلت ${r.pushed} أحداث وأُكدت ✔`
                               : 'لا أحداث معلقة — القناة متزامنة ✔')
      await load()
    } catch (e) {
      setErr(e instanceof HttpError ? e.message : 'فشل الدفع')
    } finally { setBusy(false) }
  }

  async function doBackfill() {
    await run(async () => {
      const r = await syncApi.backfill(true)
      setMsg(`الرفع الأولي: وُلّد ${r.total} حدثاً (قيود: ` +
        `${r.created.JOURNAL ?? 0}، غرف: ${r.created.ROOM ?? 0}، أصناف: ` +
        `${r.created.INV_ITEM ?? 0})` +
        (r.push?.pushed ? ` ودُفع ${r.push.pushed} ✔` : ''))
    }, '')
  }

  async function doExportUsb() {
    if (usbPass.length < 6) { setErr('كلمة المرور 6 أحرف فأكثر'); return }
    setBusy(true); setErr('')
    try {
      const p = await syncApi.exportUsb(usbPass)
      setUsbPacket(JSON.stringify(p, null, 2))
      setShowUsb(false); setUsbPass('')
    } catch (e) {
      setErr(e instanceof HttpError ? e.message : 'فشل التصدير')
    } finally { setBusy(false) }
  }

  async function doResolve(c: SyncConflict, choice: 'LOCAL' | 'REMOTE') {
    await run(async () => {
      await syncApi.resolve(c.id, choice)
      setMsg(choice === 'LOCAL'
        ? 'حُسم التعارض: اعتُمدت القيمة المحلية ووُثق القرار ✔'
        : 'حُسم التعارض: اعتُمدت القيمة الواردة وطُبقت محلياً ووُثق القرار ✔')
    }, '')
  }

  const gaps = st?.gaps ?? []

  return (
    <div style={{ maxWidth: 980, margin: '0 auto' }} dir="rtl">
      <h2 style={{ margin: '0 0 12px' }}>🔄 مركز المزامنة</h2>

      {err && <div style={{ background: '#fdf1ef', border: '1px solid #e7b4ac',
        color: '#8e2f22', borderRadius: 8, padding: 10, marginBottom: 12,
        fontSize: 13 }}>{err}</div>}
      {msg && <div style={{ background: '#eef9f0', border: '1px solid #b6e2be',
        color: '#1a7a3c', borderRadius: 8, padding: 10, marginBottom: 12,
        fontSize: 13 }}>{msg}</div>}

      {gaps.length > 0 && (
        <div style={{ background: '#fff7e6', border: '1px solid #f0d28a',
          color: '#8a6d1a', borderRadius: 8, padding: 10, marginBottom: 12,
          fontSize: 13 }}>
          ⚠ فجوة تسلسل مكتشفة ({gaps.map(g =>
            g.from === g.to ? `#${g.from}` : `#${g.from}←#${g.to}`).join('، ')})
          — تُستدرك آلياً بالدفعة التالية (لا إسقاط صامت).
        </div>
      )}

      <Card title="حالة القناة">
        {st && <>
          <Row k="الاقتران السحابي" v={st.paired
            ? <span style={{ color: '#1a7a3c' }}>متصل ✓ ({st.cloud_url})</span>
            : <span style={{ color: '#b8860b' }}>وضع محلي — غير مقترن بعد</span>} />
          <Row k="معرّف الموقع" v={<span style={{ fontFamily: 'monospace',
            fontSize: 11 }}>{st.site_id}</span>} />
          <Row k="بانتظار الإرسال" v={<b style={{ color: st.pending > 0
            ? '#b8860b' : '#1a7a3c' }}>{st.pending}</b>} />
          <Row k="أُرسل بلا تأكيد بعد" v={st.sent_unacked} />
          <Row k="أحداث مؤكدة (أرشيف)" v={st.acked} />
          <Row k="آخر تسلسل مؤكد" v={st.last_ack_seq} />
          <Row k="آخر نجاح كامل" v={fmt(st.last_success_at)} />
          <Row k="آخر نبضة صحة للمورّد" v={fmt(st.last_heartbeat_at)} />
          <Row k="دورة المزامنة" v={`${st.cycle_seconds} ثانية`} />
          <Row k="وضع التوفير (شبكات ضعيفة)" v={st.lean_mode
            ? 'مفعّل ✓' : 'متوقف'} />
          {st.last_error && <Row k="آخر ملاحظة" v={
            <span style={{ color: '#8e2f22' }}>{st.last_error}</span>} />}
          <div style={{ fontSize: 11, color: '#777', marginTop: 8 }}>
            {st.latency_note}</div>
        </>}
      </Card>

      <Card title="أوامر المشغّل">
        <Btn onClick={doPush} disabled={!canManage || busy}>⬆ دفع فوري الآن</Btn>
        <Btn onClick={doBackfill} disabled={!canManage || busy}>
          📦 رفع أولي للبيانات السابقة + دفع</Btn>
        <Btn onClick={() => run(() => syncApi.lean(!(st?.lean_mode)),
          'بدّلنا وضع التوفير ✔')} disabled={!canManage || busy}>
          {st?.lean_mode ? 'إيقاف وضع التوفير' : 'تفعيل وضع التوفير'}</Btn>
        <Btn onClick={() => run(() => syncApi.pullLicenses(),
          'سُحبت التراخيص والإلغاءات من المورّد ✔')}
          disabled={!canManage || busy}>🔑 سحب التراخيص من المورّد</Btn>
        <Btn onClick={() => run(() => syncApi.heartbeat(),
          'أُرسلت نبضة الصحة للمورّد ✔')} disabled={!canManage || busy}>
          💓 نبضة صحة فورية</Btn>
        <Btn onClick={() => setShowUsb(true)} disabled={!canManage || busy}>
          💾 تصدير USB مشفر</Btn>
        {!canManage && <div style={{ fontSize: 12, color: '#888' }}>
          صلاحية مشاهدة فقط — الأوامر التشغيلية تحتاج sync.manage</div>}
      </Card>

      {showUsb && (
        <Card title="💾 تصدير ملف USB مشفر وموقَّع">
          <p style={{ fontSize: 12, color: '#555' }}>
            للفنادق شديدة العزلة: يُنسخ الملف إلى الطرف المقابل ويُستورد
            بكلمة المرور نفسها. العبث أو كلمة مرور خاطئة = رفض موثق.</p>
          <input type="password" value={usbPass}
            onChange={e => setUsbPass(e.target.value)}
            placeholder="كلمة مرور الملف (6+ أحرف)" style={{ padding: 8,
              borderRadius: 6, border: '1px solid #ccc', minWidth: 240,
              marginInlineEnd: 8 }} />
          <Btn onClick={doExportUsb} disabled={busy}>توليد الملف</Btn>
          <Btn onClick={() => { setShowUsb(false); setUsbPass('') }}
            danger>إلغاء</Btn>
        </Card>
      )}
      {usbPacket && (
        <Card title="ملف USB جاهز — انسخه كاملاً">
          <textarea readOnly value={usbPacket} rows={8} style={{ width: '100%',
            fontFamily: 'monospace', fontSize: 10, direction: 'ltr' }}
            onFocus={e => e.target.select()} />
          <Btn onClick={() => setUsbPacket('')} danger>إخفاء</Btn>
        </Card>
      )}

      <Card title={`صندوق التعارضات (${conflicts.length})`}>
        {conflicts.length === 0 && <div style={{ fontSize: 13, color: '#1a7a3c' }}>
          لا تعارضات مفتوحة — القرارات الحساسة لا تُحسم صامتاً أبداً.</div>}
        {conflicts.map(c => (
          <div key={c.id} style={{ border: '1px solid #e0d5b8', borderRadius: 8,
            padding: 10, marginBottom: 10 }}>
            <div style={{ fontSize: 13, marginBottom: 6 }}>
              <b>{ENTITY_AR[c.entity] ?? c.entity}</b>
              <span style={{ color: '#888', fontFamily: 'monospace',
                fontSize: 11 }}> ({c.entity_id.slice(0, 8)}…)</span>
              <div style={{ color: '#8a6d1a' }}>{c.reason}</div>
            </div>
            <div style={{ display: 'grid', gap: 8,
              gridTemplateColumns: '1fr 1fr' }}>
              <pre style={{ background: '#f7fbff', border: '1px solid #cfe2f5',
                borderRadius: 6, padding: 8, fontSize: 11, margin: 0,
                direction: 'ltr', textAlign: 'left', maxHeight: 150,
                overflow: 'auto' }}>{JSON.stringify(c.local_val, null, 1)}</pre>
              <pre style={{ background: '#fff9f5', border: '1px solid #f0d3c0',
                borderRadius: 6, padding: 8, fontSize: 11, margin: 0,
                direction: 'ltr', textAlign: 'left', maxHeight: 150,
                overflow: 'auto' }}>{JSON.stringify(c.remote_val, null, 1)}</pre>
            </div>
            <div style={{ marginTop: 8 }}>
              <Btn onClick={() => doResolve(c, 'LOCAL')}
                disabled={!canManage || busy}>اعتماد المحلي (يسار)</Btn>
              <Btn onClick={() => doResolve(c, 'REMOTE')}
                disabled={!canManage || busy}>اعتماد الوارد (يمين)</Btn>
            </div>
          </div>
        ))}
      </Card>

      <Card title="آخر أحداث المزامنة">
        <table style={{ width: '100%', borderCollapse: 'collapse',
          fontSize: 12 }}>
          <thead>
            <tr style={{ textAlign: 'right', color: '#777' }}>
              <th style={{ padding: 6 }}>تسلسل</th><th>الكيان</th>
              <th>العملية</th><th>نسخة</th><th>الحالة</th><th>وقت الحدوث</th>
            </tr>
          </thead>
          <tbody>
            {events.map(e => (
              <tr key={e.seq} style={{ borderTop: '1px solid #f0f0f0' }}>
                <td style={{ padding: 6, fontFamily: 'monospace' }}>{e.seq}</td>
                <td>{ENTITY_AR[e.entity] ?? e.entity}</td>
                <td>{OP_AR[e.op] ?? e.op}</td>
                <td style={{ fontFamily: 'monospace' }}>v{e.version}</td>
                <td style={{ color: e.state === 'ACKED' ? '#1a7a3c'
                  : e.state === 'SENT' ? '#b8860b' : '#0b5cab' }}>
                  {EVENT_STATE_AR[e.state] ?? e.state}</td>
                <td>{fmt(e.occurred_at)}</td>
              </tr>
            ))}
            {events.length === 0 && <tr><td colSpan={6} style={{
              padding: 12, color: '#999', textAlign: 'center' }}>
              لا أحداث بعد — كل عملية مالية أو تعديل رئيسي يُؤرشف هنا.</td></tr>}
          </tbody>
        </table>
      </Card>
    </div>
  )
}
