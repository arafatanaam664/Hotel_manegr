// شاشة حالة الترخيص (ملف 07): الحالة، الحدود، البصمة، التثبيت/التجديد،
// التفعيل المعزول، قوائم الإلغاء — «صارم على الترخيص، رحيم بالتشغيل».
import { useCallback, useEffect, useState } from 'react'
import { licApi, LicenseStatus, STATE_AR, STATE_COLOR, MODULE_AR, PACKAGE_AR }
  from '../license'
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

function Meter({ used, max, label }: { used: number; max: number; label: string }) {
  const pct = Math.min(100, Math.round((used / Math.max(1, max)) * 100))
  return (
    <div style={{ margin: '8px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between',
        fontSize: 12, marginBottom: 3 }}>
        <span>{label}</span>
        <b>{used} / {max}</b>
      </div>
      <div style={{ background: '#eee', borderRadius: 6, height: 8 }}>
        <div style={{ width: `${pct}%`, height: 8, borderRadius: 6,
          background: pct >= 100 ? '#c0392b' : pct >= 80 ? '#b8860b' : '#1a7a3c',
          transition: 'width .3s' }} />
      </div>
    </div>
  )
}

export default function LicenseStatusPage() {
  const { has } = useAuth()
  const canManage = has('license.manage')
  const [st, setSt] = useState<LicenseStatus | null>(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [licenseText, setLicenseText] = useState('')
  const [revokeText, setRevokeText] = useState('')
  const [showInstall, setShowInstall] = useState(false)
  const [showRevoke, setShowRevoke] = useState(false)

  const load = useCallback(async () => {
    try { setSt(await licApi.status()); setErr('') }
    catch (e) { setErr(e instanceof HttpError ? `${e.code}: ${e.message}` : 'تعذر الجلب') }
  }, [])
  useEffect(() => { load() }, [load])

  async function doEvaluate() {
    setBusy(true); setMsg('')
    try { setSt(await licApi.evaluate()); setMsg('تم الفحص الفوري الكامل ✔') }
    catch (e) { setErr(e instanceof HttpError ? e.message : 'فشل الفحص') }
    finally { setBusy(false) }
  }

  async function doInstall() {
    setBusy(true); setErr(''); setMsg('')
    try {
      const payload = JSON.parse(licenseText)
      const out = await licApi.install(payload)
      setSt(out.status)
      setMsg(out.already ? 'هذا الملف مثبّت مسبقاً — لا تغيير'
                         : 'تم تثبيت/تجديد الترخيص بنجاح ✔')
      setLicenseText(''); setShowInstall(false)
    } catch (e) {
      setErr(e instanceof SyntaxError ? 'ملف JSON غير صالح'
        : e instanceof HttpError ? `[${e.code}] ${e.message}` : 'فشل التثبيت')
    } finally { setBusy(false) }
  }

  async function doRevoke() {
    setBusy(true); setErr(''); setMsg('')
    try {
      const payload = JSON.parse(revokeText)
      const out = await licApi.importRevocations(payload)
      setSt(out.status)
      setMsg(`تم استيراد قائمة الإلغاء (تسلسل ${out.revocation_serial}) ✔`)
      setRevokeText(''); setShowRevoke(false)
    } catch (e) {
      setErr(e instanceof SyntaxError ? 'ملف JSON غير صالح'
        : e instanceof HttpError ? `[${e.code}] ${e.message}` : 'فشل الاستيراد')
    } finally { setBusy(false) }
  }

  async function doActivationRequest() {
    setBusy(true); setErr('')
    try {
      const req = await licApi.activationRequest()
      const blob = new Blob([JSON.stringify(req, null, 2)],
        { type: 'application/json' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `activation-request-${req.date}.json`
      a.click()
      setMsg('نُزّل ملف طلب التفعيل — أرسله للشركة لتوقيع ملف مفعَّل ✔')
    } catch (e) { setErr(e instanceof HttpError ? e.message : 'فشل التوليد') }
    finally { setBusy(false) }
  }

  if (!st) return <main style={{ padding: 20 }}>
    {err ? <p style={{ color: '#c0392b' }}>{err}</p> : <p>…يحمّل حالة الترخيص</p>}
  </main>

  const color = STATE_COLOR[st.state] ?? '#333'
  return (
    <main style={{ padding: 16, maxWidth: 900 }}>
      <h2 style={{ margin: '0 0 12px' }}>🔑 حالة الترخيص</h2>
      {msg && <p style={{ background: '#eaf7ee', color: '#1a7a3c',
        padding: 10, borderRadius: 8 }}>{msg}</p>}
      {err && <p style={{ background: '#fdecea', color: '#c0392b',
        padding: 10, borderRadius: 8 }}>{err}</p>}

      <Card title="الحالة الحالية">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10,
          marginBottom: 8 }}>
          <span style={{ background: color, color: '#fff', borderRadius: 20,
            padding: '6px 18px', fontWeight: 700 }}>
            {STATE_AR[st.state] ?? st.state}
          </span>
          <span style={{ color: '#666', fontSize: 13 }}>{st.status_reason}</span>
        </div>
        <Row k="الباقة" v={PACKAGE_AR[st.package] ?? st.package} />
        <Row k="الاسم القانوني" v={st.legal_name || '— (وضع تجريبي)'} />
        <Row k="رقم الترخيص" v={st.license_id || '—'} />
        <Row k="مستوى الدعم" v={st.support_level} />
        <Row k="صدر في" v={st.issued_at?.slice(0, 10) ?? '—'} />
        <Row k="ساري حتى" v={st.valid_until ?? '—'} />
        <Row k="مهلة التجديد حتى" v={st.grace_until ?? '—'} />
        <Row k="الأيام المتبقية"
             v={st.days_to_expire === null ? '—'
               : st.days_to_expire >= 0 ? `${st.days_to_expire} يوم`
               : `منتهٍ منذ ${-st.days_to_expire} يوم`} />
        <Row k="آخر فحص" v={st.last_check?.slice(0, 16).replace('T', ' ') ?? '—'} />
        <Row k="مرساة الساعة" v={st.clock_anchor_date ?? '—'} />
      </Card>

      <Card title="الحدود الصلبة (07 §5)">
        <Meter used={st.limits.used_users} max={st.limits.max_users}
               label="المستخدمون النشطون" />
        <Meter used={st.limits.used_branches} max={st.limits.max_branches}
               label="الفروع النشطة" />
      </Card>

      <Card title="الوحدات">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {Object.keys(MODULE_AR).slice(0, 6).map(code => {
            const on = st.modules_enabled.includes(code)
            return <span key={code} style={{ padding: '4px 12px',
              borderRadius: 14, fontSize: 12, fontWeight: 600,
              background: on ? '#eaf7ee' : '#f4f4f4',
              color: on ? '#1a7a3c' : '#999',
              border: `1px solid ${on ? '#bfe6cc' : '#ddd'}` }}>
              {on ? '✔ ' : '✖ '}{MODULE_AR[code]}
            </span>
          })}
        </div>
      </Card>

      <Card title="بصمة الجهاز (محلي/هجين — 07 §2)">
        <Row k="مربوطة بجهاز" v={st.fingerprint.bound ? 'نعم' : 'لا'} />
        <Row k="تطابق المكونات (من 3)"
             v={`${st.fingerprint.match_components}/3 ${st.fingerprint.passing ? '✔' : '✖'}`} />
        <Row k="بصمة هذا الجهاز" v={st.fingerprint.hash} />
        <Row k="قائمة الإلغاء المستوردة (تسلسل)" v={st.revocation_serial} />
      </Card>

      {canManage && (
        <Card title="إجراءات الإدارة">
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button onClick={() => setShowInstall(v => !v)} disabled={busy}>
              📥 تثبيت / تجديد ملف ترخيص</button>
            <button onClick={doActivationRequest} disabled={busy}>
              🖥️ ملف طلب تفعيل (وضع معزول)</button>
            <button onClick={() => setShowRevoke(v => !v)} disabled={busy}>
              🚫 استيراد قائمة إلغاء</button>
            <button onClick={doEvaluate} disabled={busy}>
              🔍 فحص فوري الآن</button>
          </div>
          {showInstall && (
            <div style={{ marginTop: 10 }}>
              <p style={{ fontSize: 12, color: '#666' }}>
                الصق محتوى ملف <code>.license</code> JSON الموقَّع من الشركة.
                أي تعديل ولو بحرف واحد سيُرفض فوراً (التوقيع Ed25519).
              </p>
              <textarea value={licenseText} rows={8}
                onChange={e => setLicenseText(e.target.value)}
                style={{ width: '100%', direction: 'ltr', fontFamily:
                  'monospace', fontSize: 11, borderRadius: 8,
                  border: '1px solid #ccc', padding: 8 }} />
              <button onClick={doInstall} disabled={busy || !licenseText.trim()}
                style={{ marginTop: 6 }}>تثبيت الملف</button>
            </div>
          )}
          {showRevoke && (
            <div style={{ marginTop: 10 }}>
              <p style={{ fontSize: 12, color: '#666' }}>
                قائمة إلغاء موقعة من الشركة (تسلسل متزايد فقط). إدخال
                SUSPEND = إيقاف نهائي بقرار موثّق من الشركة (07 §3).
              </p>
              <textarea value={revokeText} rows={6}
                onChange={e => setRevokeText(e.target.value)}
                style={{ width: '100%', direction: 'ltr', fontFamily:
                  'monospace', fontSize: 11, borderRadius: 8,
                  border: '1px solid #ccc', padding: 8 }} />
              <button onClick={doRevoke} disabled={busy || !revokeText.trim()}
                style={{ marginTop: 6 }}>استيراد القائمة</button>
            </div>
          )}
        </Card>
      )}
      <p style={{ fontSize: 12, color: '#888' }}>
        صارم على الترخيص، رحيم بالتشغيل: لا يُحذف أو يُشفَّر أيُّ بياناتٍ مهما
        كانت حالة الاشتراك، والتصدير والتقارير حقٌّ مطلق للعميل (07 §3).
      </p>
    </main>
  )
}
