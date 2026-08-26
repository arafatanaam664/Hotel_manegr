import { useEffect, useMemo, useState } from 'react'
import { Badge, Btn, Card, ErrorNote, OkNote, Spinner } from '../components/ui'
import { setupApi, ProductCatalog, ProductConfig } from '../setup'
import { useSearchParams } from 'react-router-dom'

const modeLabels: Record<string, string> = {
  LOCAL: 'محلي داخل الفندق',
  CLOUD: 'سحابي عبر الإنترنت',
  HYBRID: 'محلي وسحابي مع مزامنة',
}

const propertyLabels: Record<string, string> = {
  HOTEL: 'فندق',
  INN: 'نُزل',
  SERVICED_APARTMENTS: 'شقق فندقية',
  RESORT: 'منتجع',
  OTHER: 'منشأة ضيافة أخرى',
}

const featureOrder = [
  'MULTI_BRANCH', 'RESTAURANT', 'POINT_OF_SALE', 'LAUNDRY',
  'HOUSEKEEPING', 'MAINTENANCE', 'MULTI_CURRENCY', 'OFFLINE_POS',
  'POLICE_REPORT',
]

export default function ProductSetup() {
  const [searchParams] = useSearchParams()
  const installerMode = searchParams.get('installer') === '1'
  const [installerToken, setInstallerToken] = useState('')
  const [installerIdentity, setInstallerIdentity] = useState('')
  const [catalog, setCatalog] = useState<ProductCatalog | null>(null)
  const [config, setConfig] = useState<ProductConfig | null>(null)
  const [mode, setMode] = useState('LOCAL')
  const [property, setProperty] = useState('HOTEL')
  const [modules, setModules] = useState<string[]>(['ACCOUNTING'])
  const [features, setFeatures] = useState<Record<string, boolean>>({})
  const [multiBranch, setMultiBranch] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [c, p] = await Promise.all([setupApi.catalog(), setupApi.product()])
      setCatalog(c)
      setConfig(p)
      setMode(p.deployment_mode)
      setProperty(p.property_type)
      setModules(p.modules_enabled)
      setFeatures(p.feature_flags)
      setMultiBranch(Boolean(p.feature_flags.MULTI_BRANCH))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'تعذر تحميل إعداد المنتج')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const moduleList = useMemo(() => Object.entries(catalog?.modules ?? {}), [catalog])
  const featureList = useMemo(
    () => featureOrder.filter(k => catalog?.features[k]).map(k => [k, catalog!.features[k]] as const),
    [catalog],
  )

  if (!installerMode) {
    return <Card title="إعداد خصائص النظام"><p className="text-slate-600">إعداد خصائص المنتج والتثبيت الأول يتم بواسطة موظف شركة الأنظمة فقط. مالك الفندق لا يملك صلاحية تعديل هذه الإعدادات.</p></Card>
  }
  if (loading) return <Spinner />
  if (config?.is_locked) {
    return <Card title="إعداد خصائص النظام مقفل"><p className="text-slate-600">تم إكمال التثبيت وقفل خصائص المنتج. أي تغيير لاحق يحتاج إجراءً مصرحاً من شركة الأنظمة وإصدار ترخيص جديد.</p></Card>
  }

  const toggleModule = (code: string) => {
    if (code === 'ACCOUNTING') return
    setModules(current => current.includes(code)
      ? current.filter(x => x !== code)
      : [...current, code])
  }

  const toggleFeature = (code: string) => {
    if (code === 'MULTI_BRANCH') {
      setMultiBranch(v => !v)
      return
    }
    setFeatures(current => ({ ...current, [code]: !current[code] }))
  }

  const save = async (complete: boolean) => {
    setSaving(true)
    setError(null)
    setOk(null)
    try {
      const next = await setupApi.saveProduct({
        deployment_mode: mode as ProductConfig['deployment_mode'],
        property_type: property,
        modules_enabled: modules,
        feature_flags: { ...features, MULTI_BRANCH: multiBranch },
        multi_branch: multiBranch,
        complete,
        installer_identity: installerIdentity,
      }, installerToken)
      setConfig(next)
      setModules(next.modules_enabled)
      setFeatures(next.feature_flags)
      setOk(complete ? 'اكتمل إعداد المنتج. يمكنك الآن إدخال بيانات الفندق الفعلية.' : 'حُفظت المسودة بنجاح.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'تعذر حفظ إعداد المنتج')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-5 max-w-5xl">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black text-slate-800">إعداد المنتج والتثبيت الأول</h1>
          <p className="text-slate-500 mt-1">اختر طريقة تشغيل الفندق والوحدات التي يحتاجها فقط. المحاسبة تبقى نواة إلزامية.</p>
        </div>
        {config && <Badge tone={config.setup_state === 'COMPLETED' ? 'green' : 'amber'}>
          {config.setup_state === 'COMPLETED' ? 'الإعداد مكتمل' : 'مسودة إعداد'}
        </Badge>}
      </div>

      <ErrorNote msg={error} />
      <OkNote msg={ok} />

      <Card title="صلاحية موظف شركة الأنظمة">
        <p className="text-sm text-slate-600 mb-3">أدخل الرمز الذي سلّمته الشركة لموظف التثبيت. لا تحفظه في جهاز العميل ولا تشاركه مع مالك الفندق.</p>
        <div className="grid md:grid-cols-2 gap-3">
          <label className="text-sm text-slate-600">هوية المثبت<input value={installerIdentity} onChange={e => setInstallerIdentity(e.target.value)} placeholder="اسم الموظف أو رقم أمر التثبيت" className="mt-1 w-full border rounded-xl px-3 py-2" /></label>
          <label className="text-sm text-slate-600">رمز التثبيت<input type="password" value={installerToken} onChange={e => setInstallerToken(e.target.value)} placeholder="INSTALLER TOKEN" className="mt-1 w-full border rounded-xl px-3 py-2" /></label>
        </div>
      </Card>

      <Card title="1. نمط التشغيل ونوع المنشأة">
        <div className="grid md:grid-cols-2 gap-4">
          <label className="block text-sm text-slate-600">طريقة التشغيل
            <select value={mode} onChange={e => setMode(e.target.value)} className="mt-1 w-full border rounded-xl px-3 py-2 bg-white">
              {Object.entries(modeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="block text-sm text-slate-600">نوع المنشأة
            <select value={property} onChange={e => setProperty(e.target.value)} className="mt-1 w-full border rounded-xl px-3 py-2 bg-white">
              {Object.entries(propertyLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
        </div>
        <div className="mt-4 rounded-xl bg-sky-50 border border-sky-100 p-3 text-sm text-sky-900">
          {mode === 'LOCAL' && 'تعمل العمليات الأساسية داخل الفندق دون اشتراط الإنترنت.'}
          {mode === 'CLOUD' && 'تُدار البيانات من السحابة؛ تأكد من اتصال موثوق وسياسة نسخ مناسبة.'}
          {mode === 'HYBRID' && 'يعمل الموقع محلياً وتُرسل الأحداث المسموح بها إلى السحابة عند توفر الاتصال.'}
        </div>
      </Card>

      <Card title="2. الوحدات المفعّلة">
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {moduleList.map(([code, item]) => {
            const checked = modules.includes(code)
            return <button type="button" key={code} onClick={() => toggleModule(code)}
              className={`text-right border rounded-2xl p-4 transition ${checked ? 'border-sijill-500 bg-sijill-50' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-bold text-slate-800">{item.name_ar}</span>
                <span className={`w-5 h-5 rounded-md border flex items-center justify-center ${checked ? 'bg-sijill-600 border-sijill-600 text-white' : 'border-slate-300'}`}>{checked ? '✓' : ''}</span>
              </div>
              <div className="text-xs text-slate-500 mt-2">{item.required ? 'نواة إلزامية' : checked ? 'مفعّلة' : 'معطّلة'}</div>
            </button>
          })}
        </div>
      </Card>

      <Card title="3. خصائص التشغيل">
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {featureList.map(([code, label]) => {
            const checked = code === 'MULTI_BRANCH' ? multiBranch : Boolean(features[code])
            return <button type="button" key={code} onClick={() => toggleFeature(code)}
              className={`text-right border rounded-2xl p-4 transition ${checked ? 'border-gold-400 bg-gold-50' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-bold text-slate-800">{label}</span>
                <span className={`w-5 h-5 rounded-md border flex items-center justify-center ${checked ? 'bg-gold-500 border-gold-500 text-white' : 'border-slate-300'}`}>{checked ? '✓' : ''}</span>
              </div>
              <div className="text-xs text-slate-500 mt-2">{checked ? 'مفعّلة' : 'معطّلة'}</div>
            </button>
          })}
        </div>
      </Card>

      <Card title="4. الحفظ والتفعيل">
        <p className="text-sm text-slate-600 mb-4">حفظ المسودة لا يغلق الإعداد. اختر «إكمال» فقط بعد إدخال الاختيارات التي سيُبنى عليها التثبيت التجاري.</p>
        <div className="flex flex-wrap gap-3">
          <Btn kind="ghost" disabled={saving} onClick={() => void save(false)}>حفظ كمسودة</Btn>
          <Btn disabled={saving} onClick={() => void save(true)}>{saving ? 'جارٍ الحفظ…' : 'إكمال الإعداد'}</Btn>
        </div>
      </Card>
    </div>
  )
}
