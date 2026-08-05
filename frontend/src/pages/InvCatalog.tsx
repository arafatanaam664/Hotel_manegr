// كتالوج المخزون: أصناف/تصنيفات/مستودعات/موردون — ملف 05 §1
import { useCallback, useEffect, useState } from 'react'
import { fmt } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote } from '../components/ui'
import type { InvCategory, InvItem, Supplier, SupplierPrice,
  Warehouse } from '../inv'
import { invApi } from '../inv'

const TABS = ['الأصناف', 'التصنيفات', 'المستودعات', 'الموردون'] as const

export default function InvCatalog() {
  const { has } = useAuth()
  const canCatalog = has('inv.catalog.manage')
  const canSup = has('inv.suppliers.manage')
  const [tab, setTab] = useState<string>(TABS[0])
  const [cats, setCats] = useState<InvCategory[]>([])
  const [items, setItems] = useState<InvItem[]>([])
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [itemForm, setItemForm] = useState({
    code: '', name_ar: '', name_en: '', category_id: '', base_unit: 'حبة',
    barcode: '', reorder_level: '0', safety_level: '0',
    inventory_account_code: '', track_expiry: false,
    alt_unit: '', alt_factor: '',
  })
  const [catForm, setCatForm] = useState({ code: '', name_ar: '', default_account_code: '1210' })
  const [whForm, setWhForm] = useState({
    code: '', name_ar: '', kind: 'SUB', inventory_account_code: '1210',
    allow_negative: false, cost_center_code: '',
  })
  const [supForm, setSupForm] = useState({
    code: '', name: '', contact_person: '', phone: '', terms_days: '0', address: '',
  })
  const [priceFor, setPriceFor] = useState<Supplier | null>(null)
  const [prices, setPrices] = useState<SupplierPrice[]>([])
  const [priceForm, setPriceForm] = useState({ item_id: '', price: '', valid_from: new Date().toISOString().slice(0, 10) })

  const refresh = useCallback(async () => {
    const [cs, ws, ss] = await Promise.all([
      invApi.categories(), invApi.warehouses(), invApi.suppliers()])
    setCats(cs); setWarehouses(ws); setSuppliers(ss)
    setItems(await invApi.items(q))
  }, [q])

  useEffect(() => {
    refresh().catch((e) => setErr((e as Error).message))
  }, [refresh])

  const createItem = async () => {
    setErr(null); setOk(null)
    try {
      const alt_units = itemForm.alt_unit
        ? [{ unit: itemForm.alt_unit, factor: parseFloat(itemForm.alt_factor || '0') }]
        : []
      await invApi.createItem({
        code: itemForm.code, name_ar: itemForm.name_ar,
        name_en: itemForm.name_en, category_id: itemForm.category_id,
        base_unit: itemForm.base_unit, barcode: itemForm.barcode,
        reorder_level: parseFloat(itemForm.reorder_level || '0'),
        safety_level: parseFloat(itemForm.safety_level || '0'),
        inventory_account_code: itemForm.inventory_account_code || null,
        track_expiry: itemForm.track_expiry, alt_units,
      })
      setOk(`أُضيف الصنف ${itemForm.code}`)
      setItemForm((f) => ({ ...f, code: '', name_ar: '', barcode: '' }))
      await refresh()
    } catch (e) { setErr((e as Error).message) }
  }

  const createCategory = async () => {
    setErr(null)
    try {
      await invApi.createCategory(catForm)
      setOk(`أُضيف التصنيف ${catForm.name_ar}`)
      setCatForm({ code: '', name_ar: '', default_account_code: '1210' })
      await refresh()
    } catch (e) { setErr((e as Error).message) }
  }

  const createWarehouse = async () => {
    setErr(null)
    try {
      await invApi.createWarehouse(whForm)
      setOk(`أُضيف المستودع ${whForm.name_ar}`)
      setWhForm({ code: '', name_ar: '', kind: 'SUB', inventory_account_code: '1210', allow_negative: false, cost_center_code: '' })
      await refresh()
    } catch (e) { setErr((e as Error).message) }
  }

  const createSupplier = async () => {
    setErr(null)
    try {
      await invApi.createSupplier({ ...supForm, terms_days: parseInt(supForm.terms_days || '0') })
      setOk(`أُضيف المورد ${supForm.name}`)
      setSupForm({ code: '', name: '', contact_person: '', phone: '', terms_days: '0', address: '' })
      await refresh()
    } catch (e) { setErr((e as Error).message) }
  }

  const openPrices = async (s: Supplier) => {
    setPriceFor(s)
    try { setPrices(await invApi.supplierPrices(s.id)) }
    catch (e) { setErr((e as Error).message) }
  }

  const addPrice = async () => {
    if (!priceFor) return
    setErr(null)
    try {
      await invApi.addSupplierPrice(priceFor.id, {
        item_id: priceForm.item_id, price: parseFloat(priceForm.price || '0'),
        valid_from: priceForm.valid_from,
      })
      setOk('سُجِّل السعر التعاقدي')
      await openPrices(priceFor)
    } catch (e) { setErr((e as Error).message) }
  }

  const inp = 'border border-slate-300 rounded-lg px-2 py-1.5 text-sm'
  const th = 'px-3 py-2 text-right text-xs text-slate-500 font-semibold'
  const td = 'px-3 py-2 text-sm'

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-xl font-black text-atheer-950">كتالوج المخزون</h2>
        <div className="flex gap-1 bg-white rounded-xl border border-slate-200 p-1">
          {TABS.map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-1.5 rounded-lg text-sm transition-colors ${tab === t ? 'bg-atheer-600 text-white font-bold' : 'text-slate-600 hover:bg-slate-100'}`}>
              {t}
            </button>
          ))}
        </div>
      </div>
      <ErrorNote msg={err} /><OkNote msg={ok} />

      {tab === 'الأصناف' && (
        <div className="space-y-4">
          {canCatalog && (
            <Card title="إضافة صنف مخزون">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                <input className={inp} placeholder="الكود *" value={itemForm.code} onChange={(e) => setItemForm({ ...itemForm, code: e.target.value })} />
                <input className={inp} placeholder="الاسم بالعربية *" value={itemForm.name_ar} onChange={(e) => setItemForm({ ...itemForm, name_ar: e.target.value })} />
                <select className={inp} value={itemForm.category_id} onChange={(e) => setItemForm({ ...itemForm, category_id: e.target.value })}>
                  <option value="">التصنيف *</option>
                  {cats.map((c) => <option key={c.id} value={c.id}>{c.name_ar}</option>)}
                </select>
                <input className={inp} placeholder="الوحدة الأساسية" value={itemForm.base_unit} onChange={(e) => setItemForm({ ...itemForm, base_unit: e.target.value })} />
                <input className={inp} placeholder="باركود" value={itemForm.barcode} onChange={(e) => setItemForm({ ...itemForm, barcode: e.target.value })} />
                <input className={inp} placeholder="حد إعادة الطلب" type="number" value={itemForm.reorder_level} onChange={(e) => setItemForm({ ...itemForm, reorder_level: e.target.value })} />
                <input className={inp} placeholder="حد الأمان" type="number" value={itemForm.safety_level} onChange={(e) => setItemForm({ ...itemForm, safety_level: e.target.value })} />
                <input className={inp} placeholder="حساب المخزون (افتراضي التصنيف)" value={itemForm.inventory_account_code} onChange={(e) => setItemForm({ ...itemForm, inventory_account_code: e.target.value })} />
                <input className={inp} placeholder="وحدة بديلة (كرتون)" value={itemForm.alt_unit} onChange={(e) => setItemForm({ ...itemForm, alt_unit: e.target.value })} />
                <input className={inp} placeholder="معاملها (مثل 12)" type="number" value={itemForm.alt_factor} onChange={(e) => setItemForm({ ...itemForm, alt_factor: e.target.value })} />
                <label className="flex items-center gap-2 text-sm text-slate-600">
                  <input type="checkbox" checked={itemForm.track_expiry} onChange={(e) => setItemForm({ ...itemForm, track_expiry: e.target.checked })} />
                  يتتبع دفعات/صلاحية
                </label>
              </div>
              <div className="mt-3">
                <Btn onClick={createItem} disabled={!itemForm.code || !itemForm.name_ar || !itemForm.category_id}>
                  إضافة الصنف
                </Btn>
              </div>
            </Card>
          )}
          <Card title={`الأصناف (${items.length})`} actions={
            <input className={inp} placeholder="بحث بالاسم/الكود/الباركود…" value={q} onChange={(e) => setQ(e.target.value)} />
          }>
            <table className="w-full">
              <thead><tr className="border-b border-slate-100">
                <th className={th}>الكود</th><th className={th}>الاسم</th>
                <th className={th}>التصنيف</th><th className={th}>الوحدة</th>
                <th className={th}>الحدود</th><th className={th}>الرصيد</th>
                <th className={th}>القيمة</th><th className={th}>الحالة</th>
              </tr></thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.id} className="border-b border-slate-50 hover:bg-slate-50/70">
                    <td className={`${td} font-mono font-bold text-atheer-700`}>{it.code}</td>
                    <td className={td}>{it.name_ar}{it.track_expiry && <span title="يتتبع صلاحية"> ⏳</span>}</td>
                    <td className={td}>{it.category}</td>
                    <td className={td}>{it.base_unit}{it.alt_units.length > 0 && <span className="text-xs text-slate-400"> (+{it.alt_units.map((u) => `${u.unit}=${u.factor}`).join('، ')})</span>}</td>
                    <td className={`${td} text-xs`}>{fmt(it.reorder_level, 0)} / {fmt(it.safety_level, 0)}</td>
                    <td className={td}>{fmt(it.on_hand_total)}</td>
                    <td className={td}>{fmt(it.value_total)}</td>
                    <td className={td}>{it.is_active ? <Badge tone="green">فعال</Badge> : <Badge tone="red">موقوف</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      {tab === 'التصنيفات' && (
        <div className="grid md:grid-cols-2 gap-4">
          {canCatalog && (
            <Card title="إضافة تصنيف">
              <div className="space-y-2">
                <input className={inp + ' w-full'} placeholder="الكود (مثل FB)" value={catForm.code} onChange={(e) => setCatForm({ ...catForm, code: e.target.value })} />
                <input className={inp + ' w-full'} placeholder="الاسم بالعربية" value={catForm.name_ar} onChange={(e) => setCatForm({ ...catForm, name_ar: e.target.value })} />
                <input className={inp + ' w-full'} placeholder="حساب المخزون الافتراضي (12xx)" value={catForm.default_account_code} onChange={(e) => setCatForm({ ...catForm, default_account_code: e.target.value })} />
                <p className="text-xs text-slate-400">طريقة التقييم: متوسط مرجح متحرك (FIFO محجوز — ADR-0018)</p>
                <Btn onClick={createCategory} disabled={!catForm.code || !catForm.name_ar}>إضافة</Btn>
              </div>
            </Card>
          )}
          <Card title={`التصنيفات (${cats.length})`}>
            <table className="w-full">
              <thead><tr className="border-b border-slate-100">
                <th className={th}>الكود</th><th className={th}>الاسم</th>
                <th className={th}>الحساب</th><th className={th}>الطريقة</th>
              </tr></thead>
              <tbody>
                {cats.map((c) => (
                  <tr key={c.id} className="border-b border-slate-50">
                    <td className={`${td} font-mono font-bold`}>{c.code}</td>
                    <td className={td}>{c.name_ar}</td>
                    <td className={`${td} font-mono`}>{c.default_account_code}</td>
                    <td className={td}><Badge tone="blue">{c.valuation_method}{c.method_locked ? ' 🔒' : ''}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      {tab === 'المستودعات' && (
        <div className="space-y-4">
          {canCatalog && (
            <Card title="إضافة مستودع">
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                <input className={inp} placeholder="الكود *" value={whForm.code} onChange={(e) => setWhForm({ ...whForm, code: e.target.value })} />
                <input className={inp} placeholder="الاسم *" value={whForm.name_ar} onChange={(e) => setWhForm({ ...whForm, name_ar: e.target.value })} />
                <select className={inp} value={whForm.kind} onChange={(e) => setWhForm({ ...whForm, kind: e.target.value })}>
                  <option value="MAIN">رئيسي</option><option value="SUB">فرعي</option>
                </select>
                <input className={inp} placeholder="حساب المخزون المالي (12xx) *" value={whForm.inventory_account_code} onChange={(e) => setWhForm({ ...whForm, inventory_account_code: e.target.value })} />
                <input className={inp} placeholder="مركز التكلفة" value={whForm.cost_center_code} onChange={(e) => setWhForm({ ...whForm, cost_center_code: e.target.value })} />
                <label className="flex items-center gap-2 text-sm text-slate-600">
                  <input type="checkbox" checked={whForm.allow_negative} onChange={(e) => setWhForm({ ...whForm, allow_negative: e.target.checked })} />
                  سماح بالرصيد السالب (تنبيه فقط)
                </label>
              </div>
              <div className="mt-3"><Btn onClick={createWarehouse} disabled={!whForm.code || !whForm.name_ar}>إضافة المستودع</Btn></div>
            </Card>
          )}
          <Card title={`المستودعات (${warehouses.length})`}>
            <table className="w-full">
              <thead><tr className="border-b border-slate-100">
                <th className={th}>الكود</th><th className={th}>الاسم</th>
                <th className={th}>النوع</th><th className={th}>الحساب المالي</th>
                <th className={th}>الأمين</th><th className={th}>الأصناف</th>
                <th className={th}>قيمة المخزون</th>
              </tr></thead>
              <tbody>
                {warehouses.map((w) => (
                  <tr key={w.id} className="border-b border-slate-50 hover:bg-slate-50/70">
                    <td className={`${td} font-mono font-bold text-atheer-700`}>{w.code}</td>
                    <td className={td}>{w.name_ar}{w.allow_negative && <span title="يسمح بالسالب"> ⚠️</span>}</td>
                    <td className={td}>
                      <Badge tone={w.kind === 'MAIN' ? 'blue' : w.kind === 'OUTLET' ? 'amber' : 'slate'}>
                        {w.kind === 'MAIN' ? 'رئيسي' : w.kind === 'OUTLET' ? 'منفذ بيع' : 'فرعي'}
                      </Badge>
                    </td>
                    <td className={`${td} font-mono`}>{w.inventory_account_code}</td>
                    <td className={td}>{w.keeper_name ?? <span className="text-slate-400">—</span>}</td>
                    <td className={td}>{w.skus}</td>
                    <td className={`${td} font-bold`}>{fmt(w.stock_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      {tab === 'الموردون' && (
        <div className="space-y-4">
          {canSup && (
            <Card title="إضافة مورد">
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                <input className={inp} placeholder="الكود *" value={supForm.code} onChange={(e) => setSupForm({ ...supForm, code: e.target.value })} />
                <input className={inp} placeholder="الاسم *" value={supForm.name} onChange={(e) => setSupForm({ ...supForm, name: e.target.value })} />
                <input className={inp} placeholder="جهة الاتصال" value={supForm.contact_person} onChange={(e) => setSupForm({ ...supForm, contact_person: e.target.value })} />
                <input className={inp} placeholder="الهاتف" value={supForm.phone} onChange={(e) => setSupForm({ ...supForm, phone: e.target.value })} />
                <input className={inp} placeholder="أجل السداد (يوم)" type="number" value={supForm.terms_days} onChange={(e) => setSupForm({ ...supForm, terms_days: e.target.value })} />
                <input className={inp} placeholder="العنوان" value={supForm.address} onChange={(e) => setSupForm({ ...supForm, address: e.target.value })} />
              </div>
              <div className="mt-3"><Btn onClick={createSupplier} disabled={!supForm.code || !supForm.name}>إضافة المورد</Btn></div>
            </Card>
          )}
          <Card title={`الموردون (${suppliers.length})`}>
            <table className="w-full">
              <thead><tr className="border-b border-slate-100">
                <th className={th}>الكود</th><th className={th}>الاسم</th>
                <th className={th}>الاتصال</th><th className={th}>أجل السداد</th>
                <th className={th}>التقييم</th><th className={th}>الذمة المستحقة</th>
                <th className={th}>أسعار تعاقدية</th>
              </tr></thead>
              <tbody>
                {suppliers.map((s) => (
                  <tr key={s.id} className="border-b border-slate-50 hover:bg-slate-50/70">
                    <td className={`${td} font-mono font-bold text-atheer-700`}>{s.code}</td>
                    <td className={td}>{s.name}</td>
                    <td className={`${td} text-xs`}>{s.contact_person}<br />{s.phone}</td>
                    <td className={td}>{s.terms_days} يوم</td>
                    <td className={td} title={`التزام ${s.rating_commitment}/5 — جودة ${s.rating_quality}/5`}>
                      {'★'.repeat(s.rating_quality)}<span className="text-slate-300">{'★'.repeat(5 - s.rating_quality)}</span>
                    </td>
                    <td className={`${td} font-bold ${parseFloat(s.balance) > 0 ? 'text-red-600' : 'text-emerald-700'}`}>{fmt(s.balance)}</td>
                    <td className={td}><Btn kind="ghost" onClick={() => openPrices(s)}>الأسعار 📋</Btn></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          {priceFor && (
            <Card title={`أسعار ${priceFor.name} التعاقدية المؤرخة`}
              actions={<Btn kind="ghost" onClick={() => setPriceFor(null)}>إغلاق ✕</Btn>}>
              {canSup && (
                <div className="flex gap-2 mb-3 flex-wrap">
                  <select className={inp} value={priceForm.item_id} onChange={(e) => setPriceForm({ ...priceForm, item_id: e.target.value })}>
                    <option value="">الصنف *</option>
                    {items.map((it) => <option key={it.id} value={it.id}>{it.code} — {it.name_ar}</option>)}
                  </select>
                  <input className={inp} placeholder="السعر" type="number" value={priceForm.price} onChange={(e) => setPriceForm({ ...priceForm, price: e.target.value })} />
                  <input className={inp} type="date" value={priceForm.valid_from} onChange={(e) => setPriceForm({ ...priceForm, valid_from: e.target.value })} />
                  <Btn onClick={addPrice} disabled={!priceForm.item_id || !priceForm.price}>تسجيل</Btn>
                </div>
              )}
              <table className="w-full">
                <thead><tr className="border-b border-slate-100">
                  <th className={th}>الصنف</th><th className={th}>السعر</th>
                  <th className={th}>من تاريخ</th><th className={th}>إلى</th>
                </tr></thead>
                <tbody>
                  {prices.map((p) => (
                    <tr key={p.id} className="border-b border-slate-50">
                      <td className={`${td} font-mono`}>{p.item_code}</td>
                      <td className={`${td} font-bold`}>{fmt(p.price)}</td>
                      <td className={td}>{p.valid_from}</td>
                      <td className={td}>{p.valid_to ?? 'مفتوح'}</td>
                    </tr>
                  ))}
                  {!prices.length && <tr><td colSpan={4} className={`${td} text-center text-slate-400`}>لا أسعار تعاقدية بعد</td></tr>}
                </tbody>
              </table>
            </Card>
          )}
        </div>
      )}
    </div>
  )
}
