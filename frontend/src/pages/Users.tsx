// شاشة «المستخدمون والصلاحيات» (ADR-0037): موظفون + أدوار مخصصة +
// استثناءات فردية (حجب/منح) + نوافذ دوام للدخول — تحكم مالك كامل.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { HttpError } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import { OrgRole, OrgUser, orgApi, PermGroup } from '../org'

const input = 'border rounded-lg px-3 py-2 text-sm w-full bg-white'
const label = 'block text-xs text-slate-500 mb-1'
type Run = (fn: () => Promise<unknown>, ok: string) => Promise<boolean>

function Modal({ title, onClose, wide, children }: {
  title: string; onClose: () => void; wide?: boolean; children: React.ReactNode
}) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
         onClick={onClose}>
      <div className={`bg-white rounded-3xl p-6 w-full ${wide ? 'max-w-3xl' : 'max-w-lg'} shadow-2xl max-h-[92vh] overflow-auto`}
           onClick={(e) => e.stopPropagation()}>
        <h3 className="font-black text-lg mb-4">{title}</h3>
        {children}
      </div>
    </div>
  )
}

/* منتقي صلاحيات من الكتالوج العربي المصنّف */
function PermPicker({ catalog, selected, onChange }: {
  catalog: PermGroup[]; selected: string[]
  onChange: (next: string[]) => void
}) {
  const sel = new Set(selected)
  const toggle = (code: string) => {
    const n = new Set(sel)
    if (n.has(code)) n.delete(code); else n.add(code)
    onChange([...n].sort())
  }
  const toggleGroup = (g: PermGroup, on: boolean) => {
    const n = new Set(sel)
    g.perms.forEach((p) => { if (on) n.add(p.code); else n.delete(p.code) })
    onChange([...n].sort())
  }
  return (
    <div className="space-y-2 max-h-72 overflow-auto border rounded-xl p-3 bg-slate-50">
      {catalog.map((g) => {
        const all = g.perms.every((p) => sel.has(p.code))
        return (
          <div key={g.key} className="border-b last:border-0 pb-2">
            <label className="flex items-center gap-2 font-bold text-sm cursor-pointer">
              <input type="checkbox" checked={all}
                     onChange={(e) => toggleGroup(g, e.target.checked)} />
              {g.name}
              <span className="text-[10px] text-slate-400">
                ({g.perms.filter((p) => sel.has(p.code)).length}/{g.perms.length})</span>
            </label>
            <div className="grid grid-cols-2 gap-x-3 mt-1">
              {g.perms.map((p) => (
                <label key={p.code}
                       className="flex items-center gap-1.5 text-[11px] text-slate-600 cursor-pointer py-0.5">
                  <input type="checkbox" checked={sel.has(p.code)}
                         onChange={() => toggle(p.code)} />
                  {p.name}
                </label>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/* محرّر نوافذ الدوام */
function WindowsEditor({ windows, onChange }: {
  windows: { from: string; to: string }[]
  onChange: (w: { from: string; to: string }[]) => void
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className={label.replace(' mb-1', '')}>نوافذ الدوام (فارغ = بلا قيد)</span>
        <Btn kind="ghost" onClick={() => onChange([...windows, { from: '08:00', to: '16:00' }])}>
          + نافذة</Btn>
      </div>
      {windows.map((w, i) => (
        <div key={i} className="flex items-center gap-2 mb-1.5">
          <input type="time" className={input} value={w.from}
                 onChange={(e) => onChange(windows.map((x, j) =>
                   j === i ? { ...x, from: e.target.value } : x))} />
          <span className="text-xs text-slate-400">إلى</span>
          <input type="time" className={input} value={w.to}
                 onChange={(e) => onChange(windows.map((x, j) =>
                   j === i ? { ...x, to: e.target.value } : x))} />
          <Btn kind="danger" onClick={() => onChange(windows.filter((_, j) => j !== i))}>×</Btn>
        </div>
      ))}
      {windows.length > 0 && (
        <p className="text-[10px] text-slate-400">
          الوردية الليلية مدعومة (مثال 22:00–06:00) — الدخول خارجها يُرفض ويُوثَّق.</p>)}
    </div>
  )
}

/* محرّر الاستثناءات الفردية */
function OverridesEditor({ catalog, user, onSave }: {
  catalog: PermGroup[]; user: OrgUser
  onSave: (grants: string[], denies: string[]) => void
}) {
  const [grants, setGrants] = useState(user.grants)
  const [denies, setDenies] = useState(user.denies)
  const [pick, setPick] = useState('')
  const [preview, setPreview] = useState<string[] | null>(null)
  const all = useMemo(() => catalog.flatMap((g) => g.perms), [catalog])
  const nameOf = (c: string) => all.find((p) => p.code === c)?.name ?? c
  useEffect(() => { setGrants(user.grants); setDenies(user.denies); setPreview(null) },
            [user.id, user.grants, user.denies])

  function add(kind: 'grant' | 'deny') {
    if (!pick) return
    if (kind === 'grant') {
      if (!grants.includes(pick)) setGrants([...grants, pick].sort())
      setDenies(denies.filter((d) => d !== pick))
    } else {
      if (!denies.includes(pick)) setDenies([...denies, pick].sort())
      setGrants(grants.filter((g) => g !== pick))
    }
    setPick('')
  }
  const dirty = JSON.stringify(grants) !== JSON.stringify(user.grants)
    || JSON.stringify(denies) !== JSON.stringify(user.denies)

  return (
    <div className="border border-amber-200 bg-amber-50/50 rounded-xl p-3">
      <div className="font-bold text-sm mb-2">استثناءات هذا الموظف
        <span className="text-[10px] font-normal text-slate-500"> (فوق أدواره — الحجب يغلّب؛ «*» المالك لا تُحجب)</span></div>
      <div className="flex gap-1.5 mb-2">
        <select className={input} value={pick} onChange={(e) => setPick(e.target.value)}>
          <option value="">— اختر صلاحية —</option>
          {catalog.map((g) => (
            <optgroup key={g.key} label={g.name}>
              {g.perms.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
            </optgroup>))}
        </select>
        <Btn kind="ghost" onClick={() => add('grant')}>منح ✚</Btn>
        <Btn kind="danger" onClick={() => add('deny')}>حجب ⛔</Btn>
      </div>
      <div className="flex flex-wrap gap-1.5 mb-2">
        {grants.map((c) => (
          <span key={c} className="text-[11px] bg-emerald-100 text-emerald-800 rounded-full
                px-2 py-0.5 border border-emerald-200">
            ✚ {nameOf(c)}
            <button className="mr-1 font-bold" onClick={() =>
              setGrants(grants.filter((g) => g !== c))}>×</button></span>))}
        {denies.map((c) => (
          <span key={c} className="text-[11px] bg-red-100 text-red-800 rounded-full
                px-2 py-0.5 border border-red-200">
            ⛔ {nameOf(c)}
            <button className="mr-1 font-bold" onClick={() =>
              setDenies(denies.filter((d) => d !== c))}>×</button></span>))}
        {grants.length === 0 && denies.length === 0 &&
          <span className="text-[11px] text-slate-400">لا استثناءات — يعمل بصلاحيات أدواره فقط</span>}
      </div>
      <div className="flex items-center gap-2">
        {dirty && <Btn onClick={() => onSave(grants, denies)}>حفظ الاستثناءات</Btn>}
        <Btn kind="ghost" onClick={async () => {
          setPreview((await orgApi.effectivePerms(user.id)).perms)
        }}>معاينة الفعلية</Btn>
      </div>
      {preview && (
        <details className="mt-2 text-[11px] text-slate-600">
          <summary className="cursor-pointer font-bold">
            الصلاحيات الفعلية النهائية ({preview.length})</summary>
          <div className="max-h-32 overflow-auto mt-1 bg-white rounded-lg border p-2 leading-5">
            {preview.join(' · ')}</div>
        </details>)}
    </div>
  )
}

export default function UsersPage() {
  const { has } = useAuth()
  const can = has('users.manage')
  const [tab, setTab] = useState<'users' | 'roles'>('users')
  const [users, setUsers] = useState<OrgUser[]>([])
  const [roles, setRoles] = useState<OrgRole[]>([])
  const [catalog, setCatalog] = useState<PermGroup[]>([])
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  const [busy, setBusy] = useState(false)
  const [editFor, setEditFor] = useState<OrgUser | null>(null)
  const [passFor, setPassFor] = useState<OrgUser | null>(null)
  const [roleEdit, setRoleEdit] = useState<OrgRole | null>(null)
  const [roleNew, setRoleNew] = useState(false)

  const load = useCallback(async () => {
    if (!can) return
    try {
      const [u, r, c] = await Promise.all([orgApi.users(), orgApi.roles(), orgApi.catalog()])
      setUsers(u); setRoles(r); setCatalog(c); setErr('')
    } catch (e) {
      setErr(e instanceof HttpError ? `${e.code}: ${e.message}` : 'تعذر الجلب')
    }
  }, [can])
  useEffect(() => { load() }, [load])

  async function run(fn: () => Promise<unknown>, okMsg: string): Promise<boolean> {
    if (busy) return false
    setBusy(true); setErr(''); setOk('')
    let success = false
    try { await fn(); setOk(okMsg); await load(); success = true }
    catch (e) {
      setErr(e instanceof HttpError ? `${e.code}: ${e.message}` : 'فشل التنفيذ')
    } finally { setBusy(false) }
    return success
  }

  const ROLE_AR = useMemo(() => Object.fromEntries(
    roles.map((r) => [r.code, r.name])), [roles])
  const now = Date.now()

  if (!can) {
    return <ErrorNote msg="هذه الشاشة لمدير المنشأة — صلاحية إدارة المستخدمين غير ممنوحة لك" />
  }

  return (
    <div className="space-y-4" dir="rtl">
      <div className="flex items-center gap-2 flex-wrap">
        <h2 className="text-xl font-black ml-4">👥 المستخدمون والصلاحيات</h2>
        {(['users', 'roles'] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
                  className={`px-3 py-1.5 rounded-full text-sm border transition ${tab === t ? 'bg-sijill-600 text-white border-sijill-600' : 'bg-white hover:bg-slate-50'}`}>
            {t === 'users' ? `👤 الموظفون (${users.length})` : `🛡 الأدوار (${roles.length})`}
          </button>))}
      </div>
      <ErrorNote msg={err} /><OkNote msg={ok} />

      {tab === 'users' && (<>
        <CreateUserCard roles={roles} busy={busy} run={run} />
        <Card title="سجل الموظفين">
          <table className="w-full text-sm">
            <thead><tr className="text-right text-slate-400 text-xs border-b">
              <th className="py-2">المستخدم</th><th>الأدوار والاستثناءات</th>
              <th>نافذة الدوام</th><th>الحالة</th><th>آخر دخول</th><th>إجراءات</th></tr></thead>
            <tbody>
              {users.map((u) => {
                const locked = u.locked_until && new Date(u.locked_until).getTime() > now
                return (
                  <tr key={u.id} className="border-b hover:bg-slate-50 align-top">
                    <td className="py-2">
                      <div className="font-bold">{u.full_name}</div>
                      <div className="text-[11px] text-slate-500 font-mono">@{u.username}
                        {u.must_change_password &&
                          <span title="ينبغي تغيير كلمة المرور المؤقتة"> 🔑</span>}
                      </div></td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {u.roles.map((c) => <Badge key={c} tone="slate">{ROLE_AR[c] ?? c}</Badge>)}
                        {u.grants.length > 0 && <Badge tone="green">✚ {u.grants.length} منح</Badge>}
                        {u.denies.length > 0 && <Badge tone="red">⛔ {u.denies.length} حجب</Badge>}
                        {u.roles.some((c) => c === 'OWNER') && <Badge tone="gold">مالك *</Badge>}
                      </div></td>
                    <td className="text-[11px]">
                      {u.login_windows.length === 0
                        ? <span className="text-slate-400">بلا قيد</span>
                        : u.login_windows.map((w, i) =>
                          <div key={i} className="font-mono">{w.from}–{w.to}</div>)}</td>
                    <td>
                      {locked
                        ? <Badge tone="red">🔒 مقفل مؤقتاً</Badge>
                        : u.is_active
                          ? <Badge tone="green">نشط</Badge>
                          : <Badge tone="red">موقوف</Badge>}</td>
                    <td className="text-[11px] text-slate-500">
                      {u.last_login_at ? String(u.last_login_at).replace('T', ' ').slice(0, 16) : 'لم يدخل بعد'}</td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        <Btn kind="ghost" onClick={() => setEditFor(u)}>تعديل</Btn>
                        <Btn kind="ghost" onClick={() => setPassFor(u)}>كلمة مرور</Btn>
                        {locked &&
                          <Btn kind="gold" onClick={() => run(() => orgApi.unlock(u.id),
                            `فُك قفل ${u.username} ✔`)}>فك قفل</Btn>}
                        <Btn kind="ghost" onClick={() => {
                          if (window.confirm(`سحب كل جلسات ${u.username} فوراً؟ سيُطلب منه الدخول من جديد.`))
                            run(() => orgApi.revokeSessions(u.id), 'سُحبت الجلسات ✔')
                        }}>سحب جلسات</Btn>
                        <Btn kind={u.is_active ? 'danger' : 'primary'} onClick={() => {
                          const msg = u.is_active
                            ? `إيقاف ${u.username}؟ تموت جلساته فوراً ولا يستطيع الدخول (تاريخه محفوظ).`
                            : `إعادة تفعيل ${u.username}؟`
                          if (window.confirm(msg))
                            run(() => orgApi.toggleUser(u.id),
                              u.is_active ? 'أُوقف الحساب ✔' : 'أُعيد التفعيل ✔')
                        }}>{u.is_active ? 'إيقاف' : 'تفعيل'}</Btn>
                        <Link to={`/audit?actor=${u.username}`}
                              className="text-xs text-sijill-700 underline self-center">
                          ماذا فعل؟</Link>
                      </div></td>
                  </tr>)
              })}
            </tbody>
          </table>
        </Card>
        {editFor &&
          <UserEditModal user={editFor} roles={roles} catalog={catalog}
                         busy={busy} run={run} onClose={() => setEditFor(null)} />}
        {passFor &&
          <PasswordModal user={passFor} busy={busy} run={run}
                         onClose={() => setPassFor(null)} />}
      </>)}

      {tab === 'roles' && (<>
        <Card title="الأدوار — الجاهزة نظامية محمية، وأنت تصنع ما شئت بجانبها"
          actions={<Btn onClick={() => setRoleNew(true)}>+ دور مخصص</Btn>}>
          <table className="w-full text-sm">
            <thead><tr className="text-right text-slate-400 text-xs border-b">
              <th className="py-2">الدور</th><th>الوصف</th><th>الصلاحيات</th>
              <th>المستخدمون</th><th></th></tr></thead>
            <tbody>
              {roles.map((r) => (
                <tr key={r.code} className="border-b hover:bg-slate-50">
                  <td className="py-2">
                    <div className="font-bold">{r.name}</div>
                    <div className="text-[10px] font-mono text-slate-400">{r.code}</div></td>
                  <td className="text-[12px] text-slate-500 max-w-[220px]">{r.description}</td>
                  <td><Badge tone="blue">{r.permissions.includes('*') ? 'كل شيء *' : `${r.permissions.length} صلاحية`}</Badge>
                    {r.is_system
                      ? <Badge tone="gold"> نظامي 🔒</Badge>
                      : <Badge tone="green"> مخصص</Badge>}</td>
                  <td className="num">{r.users_count}</td>
                  <td>{!r.is_system &&
                    <div className="flex gap-1">
                      <Btn kind="ghost" onClick={() => setRoleEdit(r)}>تعديل</Btn>
                      <Btn kind="danger" onClick={() => {
                        if (window.confirm(`حذف الدور «${r.name}» نهائياً؟`))
                          run(() => orgApi.deleteRole(r.code), 'حُذف الدور ✔')
                      }}>حذف</Btn></div>}</td>
                </tr>))}
            </tbody>
          </table>
          <p className="text-[11px] text-slate-400 mt-2">
            الأدوار النظامية محمية من التعديل والحذف حفاظاً على ضمانات العمليات
            (فصل المهام ومسارات الاعتماد). الدور المعيَّن لمستخدم لا يُحذف حتى يُنزع عنه.</p>
        </Card>
        {(roleNew || roleEdit) &&
          <RoleEditModal role={roleEdit} catalog={catalog} busy={busy} run={run}
                         onClose={() => { setRoleNew(false); setRoleEdit(null) }} />}
      </>)}
    </div>
  )
}

function CreateUserCard({ roles, busy, run }: {
  roles: OrgRole[]; busy: boolean; run: Run
}) {
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({ username: '', full_name: '', password: '', email: '' })
  const [picked, setPicked] = useState<string[]>(['RECEPTIONIST'])
  const [win, setWin] = useState<{ from: string; to: string }[]>([])
  if (!open) {
    return <Card title="➕ موظف جديد" actions={<Btn onClick={() => setOpen(true)}>إنشاء</Btn>}>
      <p className="text-sm text-slate-500">
        أنشئ لكل موظف حساباً مستقلاً — كل عملية تُسجَّل باسمه، وكلمة المرور المؤقتة
        تُغيَّر إجبارياً عند أول دخوله.</p></Card>
  }
  return (
    <Card title="➕ موظف جديد (كلمة مؤقتة — يغيّرها عند أول دخول)">
      <form onSubmit={(e) => { e.preventDefault(); void run(() => orgApi.createUser({
        username: f.username.trim(), full_name: f.full_name, password: f.password,
        email: f.email || null, role_codes: picked, login_windows: win,
        must_change_password: true,
      }), `أُنشئ حساب ${f.username} ✔`).then((okDone) => {
        if (!okDone) return
        setF({ username: '', full_name: '', password: '', email: '' })
        setPicked(['RECEPTIONIST']); setWin([]); setOpen(false)
      }) }}>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
          <label className={label}>اسم المستخدم
            <input className={input} required pattern="[A-Za-z0-9._-]+"
                   value={f.username} placeholder="recep-am"
                   onChange={(e) => setF({ ...f, username: e.target.value })} /></label>
          <label className={label}>الاسم الكامل
            <input className={input} required value={f.full_name}
                   placeholder="أحمد — استقبال صباحي"
                   onChange={(e) => setF({ ...f, full_name: e.target.value })} /></label>
          <label className={label}>كلمة مرور مؤقتة (≥10)
            <input className={input} required minLength={10} type="password"
                   value={f.password}
                   onChange={(e) => setF({ ...f, password: e.target.value })} /></label>
          <label className={label}>البريد (اختياري)
            <input className={input} type="email" value={f.email}
                   onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
        </div>
        <div className="grid md:grid-cols-2 gap-3 mb-3">
          <div>
            <span className={label}>الأدوار (اختر واحداً أو أكثر)</span>
            <div className="flex flex-wrap gap-1.5 border rounded-xl p-2 max-h-28 overflow-auto">
              {roles.map((r) => (
                <label key={r.code} className="text-[11px] flex items-center gap-1 cursor-pointer">
                  <input type="checkbox" checked={picked.includes(r.code)}
                         onChange={(e) => setPicked(e.target.checked
                           ? [...picked, r.code]
                           : picked.filter((c) => c !== r.code))} />
                  {r.name}</label>))}
            </div>
            {picked.length === 0 &&
              <p className="text-[11px] text-red-600 mt-1">اختر دوراً واحداً على الأقل</p>}
          </div>
          <WindowsEditor windows={win} onChange={setWin} />
        </div>
        <div className="flex gap-2">
          <Btn type="submit" disabled={busy || picked.length === 0}>إنشاء الحساب</Btn>
          <Btn kind="ghost" onClick={() => setOpen(false)}>إلغاء</Btn>
        </div>
      </form>
    </Card>
  )
}

function UserEditModal({ user, roles, catalog, busy, run, onClose }: {
  user: OrgUser; roles: OrgRole[]; catalog: PermGroup[]
  busy: boolean; run: Run; onClose: () => void
}) {
  const [name, setName] = useState(user.full_name)
  const [email, setEmail] = useState(user.email ?? '')
  const [picked, setPicked] = useState(user.roles)
  const [win, setWin] = useState(user.login_windows)
  return (
    <Modal title={`تعديل ${user.full_name} (@${user.username})`} onClose={onClose} wide>
      <div className="grid grid-cols-2 gap-3 mb-3">
        <label className={label}>الاسم الكامل
          <input className={input} value={name}
                 onChange={(e) => setName(e.target.value)} /></label>
        <label className={label}>البريد
          <input className={input} type="email" value={email}
                 onChange={(e) => setEmail(e.target.value)} /></label>
      </div>
      <div className="grid md:grid-cols-2 gap-3 mb-3">
        <div>
          <span className={label}>الأدوار</span>
          <div className="flex flex-wrap gap-1.5 border rounded-xl p-2 max-h-28 overflow-auto">
            {roles.map((r) => (
              <label key={r.code} className="text-[11px] flex items-center gap-1 cursor-pointer">
                <input type="checkbox" checked={picked.includes(r.code)}
                       onChange={(e) => setPicked(e.target.checked
                         ? [...picked, r.code] : picked.filter((c) => c !== r.code))} />
                {r.name} {r.is_system ? '' : '🔧'}</label>))}
          </div>
          {picked.length === 0 &&
            <p className="text-[11px] text-red-600 mt-1">اختر دوراً واحداً على الأقل</p>}
        </div>
        <WindowsEditor windows={win} onChange={setWin} />
      </div>
      <div className="flex gap-2 mb-4">
        <Btn disabled={busy || picked.length === 0} onClick={() =>
          run(() => orgApi.patchUser(user.id, {
            full_name: name, email: email || null,
            role_codes: picked, login_windows: win,
          }), `عُدّل ${user.username} ✔`).then((okDone) => { if (okDone) onClose() })}>حفظ الأساسيات</Btn>
      </div>
      <OverridesEditor catalog={catalog} user={user} onSave={(g, d) =>
        run(() => orgApi.patchUser(user.id, { grants: g, denies: d }),
          'حُفظت الاستثناءات ✔')} />
    </Modal>
  )
}

function PasswordModal({ user, busy, run, onClose }: {
  user: OrgUser; busy: boolean; run: Run; onClose: () => void
}) {
  const [p, setP] = useState('')
  return (
    <Modal title={`كلمة مرور جديدة لـ @${user.username}`} onClose={onClose}>
      <div className="text-[12px] bg-amber-50 border border-amber-200 rounded-lg p-2 mb-3">
        ⚠ التنفيذ يقتل كل جلساته الحالية فوراً، والكلمة مؤقتة —
        سيُطلب منه تعيين كلمته الخاصة عند أول دخول.</div>
      <label className={label}>الكلمة المؤقتة الجديدة (≥10)
        <input className={input} type="text" minLength={10} value={p}
               placeholder="اكتبها وسلّمها للموظف يدوياً"
               onChange={(e) => setP(e.target.value)} /></label>
      <div className="flex gap-2 mt-3">
        <Btn disabled={busy || p.length < 10} onClick={() =>
          run(() => orgApi.resetPassword(user.id, p),
            'أُعيدت الكلمة ✔').then((okDone) => { if (okDone) onClose() })}>تعيين</Btn>
        <Btn kind="ghost" onClick={onClose}>إلغاء</Btn>
      </div>
    </Modal>
  )
}

function RoleEditModal({ role, catalog, busy, run, onClose }: {
  role: OrgRole | null; catalog: PermGroup[]
  busy: boolean; run: Run; onClose: () => void
}) {
  const [f, setF] = useState({
    name: role?.name ?? '', description: role?.description ?? '',
  })
  const [perms, setPerms] = useState<string[]>(role?.permissions ?? [])
  return (
    <Modal title={role ? `تعديل الدور المخصص «${role.name}»` : 'صانع دور مخصص جديد'}
           onClose={onClose} wide>
      <div className="grid grid-cols-2 gap-3 mb-3">
        <label className={label}>اسم الدور
          <input className={input} value={f.name} required
                 placeholder="استقبال بلا خصومات"
                 onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label className={label}>الوصف
          <input className={input} value={f.description}
                 placeholder="ماذا يفعل حامل هذا الدور؟"
                 onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
      </div>
      <span className={label}>الصلاحيات الممنوحة ({perms.length})</span>
      <PermPicker catalog={catalog} selected={perms} onChange={setPerms} />
      <div className="flex gap-2 mt-4">
        <Btn disabled={busy || f.name.trim().length < 2} onClick={() => {
          const body = { name: f.name.trim(), description: f.description, permissions: perms }
          run(() => role ? orgApi.patchRole(role.code, body)
                         : orgApi.createRole(body),
            `حُفظ الدور «${f.name}» ✔`).then((okDone) => { if (okDone) onClose() })
        }}>{role ? 'حفظ' : 'إنشاء الدور'}</Btn>
        <Btn kind="ghost" onClick={onClose}>إلغاء</Btn>
      </div>
    </Modal>
  )
}
