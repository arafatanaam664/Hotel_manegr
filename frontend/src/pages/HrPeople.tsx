// شؤون الموظفين: ملفات/إنهاء/إيقاف + أقسام ووظائف + خطابات التغيير
// بمستند واعتماد غير ذاتي — ملف 06 §1
import { useCallback, useEffect, useState } from 'react'
import { fmt } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote } from '../components/ui'
import type { Department, Employee, EmpChange, Position } from '../hr'
import { CONTRACT_AR, HR_STATUS_AR, hrApi } from '../hr'

const TABS = ['الموظفون', 'الأقسام والوظائف', 'خطابات التغيير'] as const
const inp = 'border border-slate-300 rounded-lg px-2 py-1.5 text-sm'
const th = 'px-3 py-2 text-right text-xs text-slate-500 font-semibold'
const td = 'px-3 py-2 text-sm'

function statusTone(s: string): 'green' | 'red' | 'amber' | 'slate' | 'blue' {
  if (['ACTIVE', 'APPROVED'].includes(s)) return 'green'
  if (['PENDING'].includes(s)) return 'amber'
  if (['TERMINATED', 'REJECTED'].includes(s)) return 'red'
  return 'slate'
}

export default function HrPeople() {
  const { has } = useAuth()
  const canManage = has('hr.employees.manage')
  const canChange = has('hr.changes.manage')
  const canApprove = has('hr.changes.approve')
  const [tab, setTab] = useState<string>(TABS[0])
  const [depts, setDepts] = useState<Department[]>([])
  const [positions, setPositions] = useState<Position[]>([])
  const [emps, setEmps] = useState<Employee[]>([])
  const [changes, setChanges] = useState<EmpChange[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [showForm, setShowForm] = useState(false)

  const [empForm, setEmpForm] = useState({
    emp_no: '', full_name: '', department_id: '', hire_date: '',
    base_salary: '', contract_type: 'PERM', phone: '', national_id: '',
    hou: '', trn: '',
  })
  const [deptForm, setDeptForm] = useState({
    code: '', name_ar: '', cost_center_code: 'CC-ADMIN',
    payroll_account_code: '6310', is_confidential: false })
  const [posForm, setPosForm] = useState({ department_id: '', title: '', grade: 'G1' })
  const [chgForm, setChgForm] = useState({
    employee_id: '', change_type: 'SALARY', base_salary: '',
    department_id: '', doc_ref: '', effective_from: new Date().toISOString().slice(0, 10) })

  const refresh = useCallback(async () => {
    const [ds, ps, es, cs] = await Promise.all([
      hrApi.departments(), hrApi.positions(), hrApi.employees({ q: query }),
      hrApi.changes()])
    setDepts(ds); setPositions(ps); setEmps(es); setChanges(cs)
  }, [query])

  useEffect(() => { refresh().catch((e) => setErr((e as Error).message)) },
             [refresh])

  const run = async (fn: () => Promise<void>, okMsg: string) => {
    setErr(null); setOk(null); setBusy(true)
    try { await fn(); setOk(okMsg); setShowForm(false); await refresh() }
    catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }
  const ask = (t: string) => window.prompt(t)?.trim() ?? ''

  const empName = (id: string) => emps.find((e) => e.id === id)?.full_name ?? '…'
  const deptName = (id: string) => depts.find((d) => d.id === id)?.name_ar ?? '—'

  return (
    <div className='space-y-4'>
      <div className='flex gap-2 flex-wrap'>
        {TABS.map((t) => (
          <Btn key={t} kind={tab === t ? 'primary' : 'ghost'}
            onClick={() => { setTab(t); setShowForm(false); setErr(null); setOk(null) }}>{t}</Btn>))}
      </div>
      <ErrorNote msg={err} />
      <OkNote msg={ok} />

      {/* ═══ الموظفون ═══ */}
      {tab === TABS[0] && (
        <>
          <div className='flex gap-2 flex-wrap items-center'>
            <input className={inp} placeholder='بحث بالاسم…' value={query}
              onChange={(e) => setQuery(e.target.value)} />
            {canManage && <Btn onClick={() => setShowForm(!showForm)}>+ موظف جديد</Btn>}
          </div>
          {showForm && canManage && (
            <Card title='ملف موظف جديد (الراتب مقنّع لغير المخوّل — §6)'>
              <div className='grid md:grid-cols-3 gap-2'>
                <input className={inp} placeholder='الرقم الوظيفي *' value={empForm.emp_no}
                  onChange={(e) => setEmpForm((f) => ({ ...f, emp_no: e.target.value }))} />
                <input className={inp} placeholder='الاسم الكامل *' value={empForm.full_name}
                  onChange={(e) => setEmpForm((f) => ({ ...f, full_name: e.target.value }))} />
                <select className={inp} value={empForm.department_id}
                  onChange={(e) => setEmpForm((f) => ({ ...f, department_id: e.target.value }))}>
                  <option value=''>القسم *</option>
                  {depts.filter((d) => d.is_active).map((d) => (
                    <option key={d.id} value={d.id}>{d.name_ar}</option>))}
                </select>
                <div>
                  <label className='text-xs text-slate-500 block mb-1'>تاريخ التعيين *</label>
                  <input className={inp + ' w-full'} type='date' value={empForm.hire_date}
                    onChange={(e) => setEmpForm((f) => ({ ...f, hire_date: e.target.value }))} />
                </div>
                <input className={inp} placeholder='الأجر الأساسي *' type='number' value={empForm.base_salary}
                  onChange={(e) => setEmpForm((f) => ({ ...f, base_salary: e.target.value }))} />
                <select className={inp} value={empForm.contract_type}
                  onChange={(e) => setEmpForm((f) => ({ ...f, contract_type: e.target.value }))}>
                  {Object.entries(CONTRACT_AR).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
                <input className={inp} placeholder='بدل سكن (مبلغ)' type='number' value={empForm.hou}
                  onChange={(e) => setEmpForm((f) => ({ ...f, hou: e.target.value }))} />
                <input className={inp} placeholder='بدل نقل (مبلغ)' type='number' value={empForm.trn}
                  onChange={(e) => setEmpForm((f) => ({ ...f, trn: e.target.value }))} />
                <input className={inp} placeholder='الهاتف' value={empForm.phone}
                  onChange={(e) => setEmpForm((f) => ({ ...f, phone: e.target.value }))} />
              </div>
              <div className='mt-3'>
                <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                  const allowances: Record<string, string>[] = []
                  if (empForm.hou && parseFloat(empForm.hou) > 0)
                    allowances.push({ code: 'HOU', name: 'بدل سكن', amount: empForm.hou })
                  if (empForm.trn && parseFloat(empForm.trn) > 0)
                    allowances.push({ code: 'TRN', name: 'بدل نقل', amount: empForm.trn })
                  await hrApi.createEmployee({
                    emp_no: empForm.emp_no, full_name: empForm.full_name,
                    department_id: empForm.department_id,
                    hire_date: empForm.hire_date,
                    base_salary: parseFloat(empForm.base_salary || '0'),
                    contract_type: empForm.contract_type,
                    phone: empForm.phone,
                    national_id: empForm.national_id || null, allowances,
                  })
                }, `أُضيف ${empForm.full_name} بنجاح`)}>حفظ الموظف</Btn>
              </div>
            </Card>
          )}
          <Card title={`الموظفون (${emps.length})`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الرقم</th><th className={th}>الاسم</th>
                <th className={th}>القسم</th><th className={th}>التعيين</th>
                <th className={th}>العقد</th><th className={th}>الأساسي+بدلات</th>
                <th className={th}>الحالة</th><th className={th}>إجراءات</th>
              </tr></thead>
              <tbody>
                {emps.map((e) => (
                  <tr key={e.id} className='border-b border-slate-50'>
                    <td className={`${td} font-mono font-bold`}>{e.emp_no}</td>
                    <td className={td}>{e.full_name}</td>
                    <td className={td}>{e.department}
                      {e.department_confidential &&
                        <span className='ms-1' title='قسم سري — رواتب مقنّعة'>🔒</span>}</td>
                    <td className={`${td} font-mono text-xs`}>{e.hire_date}</td>
                    <td className={td}><Badge tone='slate'>{CONTRACT_AR[e.contract_type]}</Badge></td>
                    <td className={`${td} font-mono`}>
                      {e.salary_masked
                        ? <span className='text-slate-400'>••• مقنّع</span>
                        : <>{fmt(e.base_salary ?? '0')}
                            {e.allowances.length > 0 && <span className='text-xs text-emerald-700'>
                              {' '}+{fmt(e.allowances.reduce((s, a) =>
                                s + parseFloat(a.amount ?? '0') +
                                (a.pct_base ? parseFloat(e.base_salary ?? '0') *
                                  parseFloat(a.pct_base) / 100 : 0), 0))} بدلات</span>}</>}
                    </td>
                    <td className={td}>
                      <Badge tone={statusTone(e.status)}>{HR_STATUS_AR[e.status]}</Badge>
                      {e.termination_date &&
                        <div className='text-xs text-red-600'>{e.termination_date}</div>}
                    </td>
                    <td className={td}>
                      {canManage && e.status !== 'TERMINATED' && (
                        <div className='flex gap-1'>
                          <Btn kind='ghost' className='!px-2 !py-1 text-xs'
                            onClick={() => { const r = ask('سبب الإيقاف/الإعادة:');
                              if (r) run(async () => { await hrApi.suspendEmployee(e.id, r) },
                                e.status === 'ACTIVE' ? 'أُوقف (خارج الرواتب)' : 'أُعيد نشاطاً') }}>
                            {e.status === 'ACTIVE' ? 'إيقاف' : 'إعادة'}</Btn>
                          <Btn kind='danger' className='!px-2 !py-1 text-xs'
                            onClick={() => {
                              const dt = ask('تاريخ الإنهاء YYYY-MM-DD:')
                              const r = ask('سبب الإنهاء (مستند):')
                              if (dt && r) run(async () => {
                                await hrApi.terminateEmployee(e.id, {
                                  termination_date: dt, reason: r })
                              }, 'أُنهيت الخدمة — تسويته عبر مسير نهائي من شاشة الرواتب')
                            }}>إنهاء خدمة</Btn>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
                {!emps.length && <tr><td className={td} colSpan={8}>لا موظفون</td></tr>}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ═══ الأقسام والوظائف ═══ */}
      {tab === TABS[1] && (
        <>
          {canManage && (
          <div className='grid md:grid-cols-2 gap-4'>
            <Card title='إضافة قسم'>
              <div className='flex gap-2 flex-wrap'>
                <input className={inp} placeholder='الرمز' value={deptForm.code}
                  onChange={(e) => setDeptForm((f) => ({ ...f, code: e.target.value }))} />
                <input className={inp} placeholder='الاسم *' value={deptForm.name_ar}
                  onChange={(e) => setDeptForm((f) => ({ ...f, name_ar: e.target.value }))} />
                <select className={inp} value={deptForm.payroll_account_code}
                  onChange={(e) => setDeptForm((f) => ({ ...f, payroll_account_code: e.target.value }))}>
                  <option value='6110'>6110 رواتب الاستقبال والطوابق</option>
                  <option value='6210'>6210 رواتب المطبخ والمطعم</option>
                  <option value='6310'>6310 رواتب الإدارة</option>
                </select>
                <select className={inp} value={deptForm.cost_center_code}
                  onChange={(e) => setDeptForm((f) => ({ ...f, cost_center_code: e.target.value }))}>
                  <option value='CC-ROOMS'>مركز تكلفة: الغرف</option>
                  <option value='CC-FB'>الأغذية والمشروبات</option>
                  <option value='CC-ADMIN'>الإدارة والعمومية</option>
                  <option value='CC-MNT'>الصيانة والطاقة</option>
                </select>
                <label className='text-sm flex items-center gap-1'>
                  <input type='checkbox' checked={deptForm.is_confidential}
                    onChange={(e) => setDeptForm((f) => ({ ...f, is_confidential: e.target.checked }))} />
                  قسم سري 🔒 (رواتب مقنّعة)
                </label>
                <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                  await hrApi.createDepartment(deptForm)
                }, `أُضيف القسم ${deptForm.name_ar}`)}>حفظ</Btn>
              </div>
            </Card>
            <Card title='إضافة وظيفة'>
              <div className='flex gap-2 flex-wrap'>
                <select className={inp} value={posForm.department_id}
                  onChange={(e) => setPosForm((f) => ({ ...f, department_id: e.target.value }))}>
                  <option value=''>القسم *</option>
                  {depts.map((d) => <option key={d.id} value={d.id}>{d.name_ar}</option>)}
                </select>
                <input className={inp} placeholder='المسمى *' value={posForm.title}
                  onChange={(e) => setPosForm((f) => ({ ...f, title: e.target.value }))} />
                <select className={inp} value={posForm.grade}
                  onChange={(e) => setPosForm((f) => ({ ...f, grade: e.target.value }))}>
                  {['G1', 'G2', 'G3', 'G4', 'G5', 'G6'].map((g) => <option key={g}>{g}</option>)}
                </select>
                <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                  await hrApi.createPosition(posForm)
                }, `أُضيفت ${posForm.title}`)}>حفظ</Btn>
              </div>
            </Card>
          </div>
          )}
          <Card title={`الأقسام (${depts.length})`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الرمز</th><th className={th}>الاسم</th>
                <th className={th}>حساب الرواتب</th><th className={th}>مركز التكلفة</th>
                <th className={th}>سري؟</th><th className={th}>موظفون</th>
              </tr></thead>
              <tbody>
                {depts.map((d) => (
                  <tr key={d.id} className='border-b border-slate-50'>
                    <td className={`${td} font-mono font-bold`}>{d.code}</td>
                    <td className={td}>{d.name_ar}</td>
                    <td className={`${td} font-mono`}>{d.payroll_account_code}</td>
                    <td className={td}>{d.cost_center_code}</td>
                    <td className={td}>{d.is_confidential ? '🔒' : '—'}</td>
                    <td className={`${td} font-mono`}>
                      {emps.filter((e) => e.department_id === d.id).length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          <Card title={`الوظائف (${positions.length})`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>المسمى</th><th className={th}>القسم</th>
                <th className={th}>الدرجة</th>
              </tr></thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.id} className='border-b border-slate-50'>
                    <td className={td}>{p.title}</td>
                    <td className={td}>{deptName(p.department_id)}</td>
                    <td className={`${td} font-mono`}><Badge tone='blue'>{p.grade}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ═══ خطابات التغيير ═══ */}
      {tab === TABS[2] && (
        <>
          {canChange && (
            <Card title='خطاب تغيير بمستند (نقل/ترقية/أجر) — اعتماده بصلاحية أخرى، لا ذاتياً'>
              {!showForm ? <Btn onClick={() => setShowForm(true)}>+ خطاب جديد</Btn> : (
                <div className='space-y-3'>
                  <div className='flex gap-2 flex-wrap'>
                    <select className={inp} value={chgForm.employee_id}
                      onChange={(e) => setChgForm((f) => ({ ...f, employee_id: e.target.value }))}>
                      <option value=''>الموظف *</option>
                      {emps.filter((e) => e.status !== 'TERMINATED').map((e) => (
                        <option key={e.id} value={e.id}>{e.emp_no} — {e.full_name}</option>))}
                    </select>
                    <select className={inp} value={chgForm.change_type}
                      onChange={(e) => setChgForm((f) => ({ ...f, change_type: e.target.value }))}>
                      <option value='SALARY'>تعديل أجر</option>
                      <option value='TRANSFER'>نقل قسم</option>
                      <option value='PROMOTE'>ترقية وظيفة</option>
                    </select>
                    {chgForm.change_type === 'SALARY' && (
                      <input className={inp} placeholder='الأجر الجديد' type='number'
                        value={chgForm.base_salary}
                        onChange={(e) => setChgForm((f) => ({ ...f, base_salary: e.target.value }))} />)}
                    {chgForm.change_type !== 'SALARY' && (
                      <select className={inp} value={chgForm.department_id}
                        onChange={(e) => setChgForm((f) => ({ ...f, department_id: e.target.value }))}>
                        <option value=''>القسم الجديد</option>
                        {depts.map((d) => <option key={d.id} value={d.id}>{d.name_ar}</option>)}
                      </select>)}
                    <input className={inp} placeholder='مرجع المستند *' value={chgForm.doc_ref}
                      onChange={(e) => setChgForm((f) => ({ ...f, doc_ref: e.target.value }))} />
                    <input className={inp} type='date' value={chgForm.effective_from}
                      onChange={(e) => setChgForm((f) => ({ ...f, effective_from: e.target.value }))} />
                  </div>
                  <div className='flex gap-2'>
                    <Btn kind='gold' disabled={busy} onClick={() => run(async () => {
                      const after = chgForm.change_type === 'SALARY'
                        ? { base_salary: chgForm.base_salary }
                        : chgForm.change_type === 'TRANSFER'
                          ? { department_id: chgForm.department_id }
                          : { position_id: positions[0]?.id, department_id: chgForm.department_id || undefined }
                      await hrApi.createChange({ ...chgForm, after })
                    }, 'أُنشئ الخطاب — بانتظار الاعتماد')}>حفظ الخطاب</Btn>
                    <Btn kind='ghost' onClick={() => setShowForm(false)}>تراجع</Btn>
                  </div>
                </div>
              )}
            </Card>
          )}
          <Card title={`الخطابات (${changes.length})`}>
            <table className='w-full'>
              <thead><tr className='border-b border-slate-100'>
                <th className={th}>الموظف</th><th className={th}>النوع</th>
                <th className={th}>قبل ← بعد</th><th className={th}>المستند</th>
                <th className={th}>الحالة</th><th className={th}>إجراءات</th>
              </tr></thead>
              <tbody>
                {changes.map((c) => (
                  <tr key={c.id} className='border-b border-slate-50'>
                    <td className={td}>{empName(c.employee_id)}</td>
                    <td className={td}><Badge tone='blue'>
                      {c.change_type === 'SALARY' ? 'أجر' : c.change_type === 'TRANSFER' ? 'نقل' : 'ترقية'}</Badge></td>
                    <td className={`${td} text-xs font-mono`}>
                      {JSON.stringify(c.before)} ← {JSON.stringify(c.after)}</td>
                    <td className={`${td} text-xs`}>{c.doc_ref}</td>
                    <td className={td}><Badge tone={statusTone(c.status)}>
                      {HR_STATUS_AR[c.status] ?? c.status}</Badge></td>
                    <td className={td}>
                      {c.status === 'PENDING' && canApprove && (
                        <div className='flex gap-1'>
                          <Btn className='!px-2 !py-1 text-xs' onClick={() => run(async () => {
                            await hrApi.approveChange(c.id)
                          }, 'اعتُمد وطُبق على الملف')}>اعتماد ✅</Btn>
                          <Btn kind='danger' className='!px-2 !py-1 text-xs'
                            onClick={() => { const r = ask('سبب الرفض:');
                              if (r) run(async () => { await hrApi.rejectChange(c.id, r) }, 'رُفض') }}>رفض</Btn>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
                {!changes.length && <tr><td className={td} colSpan={6}>لا خطابات</td></tr>}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  )
}
