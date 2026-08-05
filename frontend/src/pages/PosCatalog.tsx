// إدارة كتالوج POS: أصناف/تصنيفات/معدلات/وصفات + رصيد مخزون — ملف 04 §2
import { useCallback, useEffect, useState } from 'react'
import { api, fmt } from '../api'
import { useAuth } from '../auth'
import { Badge, Btn, Card, ErrorNote, OkNote } from '../components/ui'
import type { Category, Item, Outlet, StockRow } from '../pos'
import { posApi } from '../pos'

const TABS = ['الأصناف', 'التصنيفات', 'وصفة صنف', 'المخزون'] as const

export default function PosCatalog() {
  const { has } = useAuth()
  const can = has('pos.catalog.manage')
  const canStock = has('pos.stock.manage')
  const [tab, setTab] = useState<string>(TABS[0])
  const [outlets, setOutlets] = useState<Outlet[]>([])
  const [outletId, setOutletId] = useState('')
  const [cats, setCats] = useState<Category[]>([])
  const [items, setItems] = useState<Item[]>([])
  const [stock, setStock] = useState<StockRow[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [itemForm, setItemForm] = useState({
    code: '', name_ar: '', name_en: '', barcode: '', category_id: '',
    price: '0', item_type: 'SERVICE', cost: '0', revenue_account_code: '4201',
  })
  const [catForm, setCatForm] = useState({ code: '', name_ar: '', color: '#0e7490', station: 'KITCHEN' })
  const [recipeFor, setRecipeFor] = useState<Item | null>(null)
  const [recipe, setRecipe] = useState<{ component_item_id: string; qty: string }[]>([])
  const [stockForm, setStockForm] = useState({ item_id: '', qty: '', unit_cost: '' })

  const refresh = useCallback(async () => {
    const [os, cs] = await Promise.all([posApi.outlets(), posApi.categories()])
    setOutlets(os); setCats(cs)
    if (!outletId && os.length) setOutletId(os[0].id)
    const r = await posApi.items('', '', 500)
    setItems(r.items)
  }, [outletId])

  const refreshStock = useCallback(async () => {
    if (outletId) setStock(await posApi.stock(outletId).catch(() => [] as StockRow[]))
  }, [outletId])

  useEffect(() => { refresh().catch((e) => setErr((e as Error).message)) }, []) // eslint-disable-line
  useEffect(() => { refreshStock().catch(() => undefined) }, [refreshStock])

  const createItem = async () => {
    setErr(null); setOk(null)
    try {
      await api('/api/pos/items', { method: 'POST', body: JSON.stringify({
        ...itemForm, price: parseFloat(itemForm.price || '0'),
        cost: parseFloat(itemForm.cost || '0'),
      }) })
      setOk(`أُضيف الصنف ${itemForm.code}`)
      setItemForm((f) => ({ ...f, code: '', name_ar: '', barcode: '' }))
      await refresh()
    } catch (e) { setErr((e as Error).message) }
  }

  const toggleActive = async (it: Item) => {
    try {
      await api(`/api/pos/items/${it.id}`, { method: 'PATCH',
        body: JSON.stringify({ is_active: !it.is_active }) })
      await refresh()
    } catch (e) { setErr((e as Error).message) }
  }

  const createCategory = async () => {
    setErr(null)
    try {
      await api('/api/pos/categories', { method: 'POST', body: JSON.stringify(catForm) })
      setOk(`أُضيف التصنيف ${catForm.name_ar}`)
      setCatForm({ code: '', name_ar: '', color: '#0e7490', station: 'KITCHEN' })
      await refresh()
    } catch (e) { setErr((e as Error).message) }
  }

  const openRecipe = async (it: Item) => {
    setRecipeFor(it)
    try {
      const r = await api<{ component_item_id: string; qty: string }[]>(
        `/api/pos/items/${it.id}/recipe`)
      setRecipe(r.map((x) => ({ component_item_id: x.component_item_id, qty: x.qty })))
    } catch { setRecipe([]) }
  }

  const saveRecipe = async () => {
    if (!recipeFor) return
    setErr(null)
    try {
      await api(`/api/pos/items/${recipeFor.id}/recipe`, { method: 'PUT',
        body: JSON.stringify({ lines: recipe.map((r) => ({
          component_item_id: r.component_item_id, qty: parseFloat(r.qty || '0'),
        })) }) })
      setOk(`حُفظت وصفة «${recipeFor.name_ar}» — تُخصم كمياتها حرفياً عند البيع`)
      setRecipeFor(null)
    } catch (e) { setErr((e as Error).message) }
  }

  const loadStock = async () => {
    setErr(null)
    try {
      await posApi.stockLoad(outletId, {
        item_id: stockForm.item_id,
        qty: parseFloat(stockForm.qty || '0'),
        unit_cost: parseFloat(stockForm.unit_cost || '0'),
      })
      setOk('أُدخل الرصيد بقيد STOCK_OPEN_POS عبر المحرك')
      setStockForm({ item_id: '', qty: '', unit_cost: '' })
      await refreshStock()
    } catch (e) { setErr((e as Error).message) }
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-xl font-black">كتالوج نقاط البيع</h1>
        <div className="flex gap-1">
          {TABS.map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-3 py-1.5 rounded-lg text-sm border ${tab === t ? 'bg-atheer-700 text-white border-atheer-700' : 'border-slate-300 text-slate-600'}`}>
              {t}
            </button>
          ))}
        </div>
        {!can && <Badge tone="amber">وضع قراءة — الإدارة تتطلب صلاحية كتالوج</Badge>}
      </div>
      <ErrorNote msg={err} />
      <OkNote msg={ok} />

      {tab === 'الأصناف' && (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <Card title="إضافة صنف" actions={null}>
            <div className="space-y-2">
              <input className="border rounded-lg w-full px-3 py-2 text-sm" placeholder="الكود (SKU) *" value={itemForm.code}
                onChange={(e) => setItemForm((f) => ({ ...f, code: e.target.value }))} />
              <input className="border rounded-lg w-full px-3 py-2 text-sm" placeholder="الاسم العربي *" value={itemForm.name_ar}
                onChange={(e) => setItemForm((f) => ({ ...f, name_ar: e.target.value }))} />
              <div className="grid grid-cols-2 gap-2">
                <input className="border rounded-lg px-3 py-2 text-sm" placeholder="باركود" value={itemForm.barcode}
                  onChange={(e) => setItemForm((f) => ({ ...f, barcode: e.target.value }))} />
                <select className="border rounded-lg px-2 py-2 text-sm" value={itemForm.category_id}
                  onChange={(e) => setItemForm((f) => ({ ...f, category_id: e.target.value }))}>
                  <option value="">— التصنيف —</option>
                  {cats.map((c) => <option key={c.id} value={c.id}>{c.name_ar}</option>)}
                </select>
                <input className="border rounded-lg px-3 py-2 text-sm" placeholder="سعر البيع" inputMode="decimal" value={itemForm.price}
                  onChange={(e) => setItemForm((f) => ({ ...f, price: e.target.value }))} />
                <input className="border rounded-lg px-3 py-2 text-sm" placeholder="التكلفة" inputMode="decimal" value={itemForm.cost}
                  onChange={(e) => setItemForm((f) => ({ ...f, cost: e.target.value }))} />
                <select className="border rounded-lg px-2 py-2 text-sm" value={itemForm.item_type}
                  onChange={(e) => setItemForm((f) => ({ ...f, item_type: e.target.value }))}>
                  <option value="SERVICE">خدمي (لا ينقّص)</option>
                  <option value="STOCK">مخزوني (ينقّص #13)</option>
                  <option value="COMPOSITE">مركّب (وصفة)</option>
                </select>
                <input className="border rounded-lg px-3 py-2 text-sm" placeholder="حساب الإيراد (42xx)" value={itemForm.revenue_account_code}
                  onChange={(e) => setItemForm((f) => ({ ...f, revenue_account_code: e.target.value }))} />
              </div>
              <Btn onClick={createItem} disabled={!can || itemForm.code.length < 2 || itemForm.name_ar.length < 2 || !itemForm.category_id}>
                إضافة الصنف
              </Btn>
            </div>
          </Card>
          <div className="xl:col-span-2">
            <Card title={`الأصناف (${items.length})`}>
              <div className="max-h-[520px] overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-white">
                    <tr className="text-slate-500 text-xs border-b">
                      <th className="py-2 text-right">الكود</th><th className="text-right">الاسم</th>
                      <th className="text-right">النوع</th><th className="text-right">السعر</th>
                      <th className="text-right">التكلفة</th><th className="text-right">الحالة</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((it) => (
                      <tr key={it.id} className={`border-b border-slate-100 ${!it.is_active ? 'opacity-40' : ''}`}>
                        <td className="py-1.5 font-bold">{it.code}</td>
                        <td>{it.name_ar}</td>
                        <td className="text-xs">{{ STOCK: 'مخزوني', SERVICE: 'خدمي', COMPOSITE: 'مركّب' }[it.item_type]}</td>
                        <td>{fmt(it.price)}</td>
                        <td>{fmt(it.cost)}</td>
                        <td>{it.is_active ? <Badge tone="green">نشط</Badge> : <Badge tone="red">موقوف</Badge>}</td>
                        <td className="text-left space-x-2">
                          {it.item_type === 'COMPOSITE' && (
                            <button className="text-violet-700 text-xs underline" onClick={() => openRecipe(it)}>الوصفة</button>
                          )}
                          {can && (
                            <button className="text-slate-500 text-xs underline" onClick={() => toggleActive(it)}>
                              {it.is_active ? 'إيقاف' : 'تنشيط'}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        </div>
      )}

      {tab === 'التصنيفات' && (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <Card title="إضافة تصنيف" actions={null}>
            <div className="space-y-2">
              <input className="border rounded-lg w-full px-3 py-2 text-sm" placeholder="الكود *" value={catForm.code}
                onChange={(e) => setCatForm((f) => ({ ...f, code: e.target.value }))} />
              <input className="border rounded-lg w-full px-3 py-2 text-sm" placeholder="الاسم العربي *" value={catForm.name_ar}
                onChange={(e) => setCatForm((f) => ({ ...f, name_ar: e.target.value }))} />
              <div className="grid grid-cols-2 gap-2 items-center">
                <label className="text-xs">اللون
                  <input type="color" className="w-full h-9 border rounded" value={catForm.color}
                    onChange={(e) => setCatForm((f) => ({ ...f, color: e.target.value }))} />
                </label>
                <select className="border rounded-lg px-2 py-2 text-sm" value={catForm.station}
                  onChange={(e) => setCatForm((f) => ({ ...f, station: e.target.value }))}>
                  <option value="KITCHEN">مطبخ</option>
                  <option value="BAR">بار/كوفي</option>
                </select>
              </div>
              <Btn onClick={createCategory} disabled={!can || catForm.code.length < 2 || catForm.name_ar.length < 2}>إضافة</Btn>
            </div>
          </Card>
          <div className="xl:col-span-2">
            <Card title={`التصنيفات (${cats.length})`}>
              <div className="flex flex-wrap gap-2">
                {cats.map((c) => (
                  <span key={c.id} className="px-4 py-2 rounded-xl text-white text-sm font-bold"
                    style={{ background: c.color }}>
                    {c.name_ar} <span className="opacity-70 text-xs">({c.station === 'KITCHEN' ? 'مطبخ' : 'بار'})</span>
                  </span>
                ))}
              </div>
            </Card>
          </div>
        </div>
      )}

      {tab === 'وصفة صنف' && (
        <Card title="وصفات الأصناف المركبة — قبول #3: تُخصم المكونات بكميات الوصفة حرفياً">
          {!recipeFor ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {items.filter((i) => i.item_type === 'COMPOSITE').map((it) => (
                <button key={it.id} onClick={() => openRecipe(it)}
                  className="border border-slate-200 rounded-xl p-3 text-right hover:bg-violet-50 text-sm font-bold">
                  {it.name_ar} <span className="text-xs text-slate-400 font-normal">— تحرير الوصفة ←</span>
                </button>
              ))}
            </div>
          ) : (
            <div className="space-y-3 max-w-xl">
              <div className="font-black">وصفة «{recipeFor.name_ar}» (لكل وحدة مبيع)</div>
              {recipe.map((r, ix) => (
                <div key={ix} className="flex gap-2 items-center">
                  <select className="border rounded-lg px-2 py-1.5 text-sm flex-1" value={r.component_item_id}
                    onChange={(e) => setRecipe((rs) => rs.map((x, i) => i === ix ? { ...x, component_item_id: e.target.value } : x))}>
                    {items.filter((i) => i.item_type === 'STOCK').map((i) => (
                      <option key={i.id} value={i.id}>{i.name_ar} (تكلفة {fmt(i.cost)})</option>
                    ))}
                  </select>
                  <input className="border rounded-lg px-2 py-1.5 w-24 text-sm" value={r.qty} inputMode="decimal"
                    onChange={(e) => setRecipe((rs) => rs.map((x, i) => i === ix ? { ...x, qty: e.target.value } : x))} />
                  <button className="text-red-400" onClick={() => setRecipe((rs) => rs.filter((_, i) => i !== ix))}>×</button>
                </div>
              ))}
              <div className="flex gap-2">
                <Btn kind="ghost" onClick={() => setRecipe((rs) => [...rs, { component_item_id: items.find((i) => i.item_type === 'STOCK')?.id || '', qty: '1' }])}>
                  + مكوّن
                </Btn>
                <Btn onClick={saveRecipe} disabled={!can || !recipe.length}>حفظ الوصفة</Btn>
                <Btn kind="ghost" onClick={() => setRecipeFor(null)}>رجوع</Btn>
              </div>
            </div>
          )}
        </Card>
      )}

      {tab === 'المخزون' && (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <Card title="إدخال رصيد (افتتاحي/توريد مبسط)" actions={null}>
            <select className="border rounded-lg w-full px-3 py-2 text-sm mb-2" value={outletId}
              onChange={(e) => setOutletId(e.target.value)}>
              {outlets.map((o) => <option key={o.id} value={o.id}>{o.name_ar}</option>)}
            </select>
            <select className="border rounded-lg w-full px-3 py-2 text-sm mb-2" value={stockForm.item_id}
              onChange={(e) => setStockForm((f) => ({ ...f, item_id: e.target.value }))}>
              <option value="">— صنف مخزوني —</option>
              {items.filter((i) => i.item_type === 'STOCK').map((i) => (
                <option key={i.id} value={i.id}>{i.name_ar}</option>
              ))}
            </select>
            <div className="grid grid-cols-2 gap-2 mb-2">
              <input className="border rounded-lg px-3 py-2 text-sm" placeholder="الكمية" inputMode="decimal"
                value={stockForm.qty} onChange={(e) => setStockForm((f) => ({ ...f, qty: e.target.value }))} />
              <input className="border rounded-lg px-3 py-2 text-sm" placeholder="تكلفة الوحدة" inputMode="decimal"
                value={stockForm.unit_cost} onChange={(e) => setStockForm((f) => ({ ...f, unit_cost: e.target.value }))} />
            </div>
            <div className="text-[11px] text-slate-400 mb-2">
              الأثر المحاسبي: Dr 1210 / Cr 8002 افتتاحي مرحلي — عبر محرك القيود (ملف 02).
              المشتريات الكاملة والتقييم المتحرك في المرحلة 5.
            </div>
            <Btn onClick={loadStock} disabled={!canStock || !stockForm.item_id || !(parseFloat(stockForm.qty) > 0)}>
              إدخال الرصيد
            </Btn>
          </Card>
          <div className="xl:col-span-2">
            <Card title={`أرصدة المنفذ (${stock.length})`}>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-slate-500 text-xs border-b">
                    <th className="py-2 text-right">الكود</th><th className="text-right">الصنف</th>
                    <th className="text-right">الرصيد</th><th className="text-right">تكلفة الوحدة</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {stock.map((s) => (
                    <tr key={s.item_id} className={`border-b border-slate-100 ${s.negative ? 'bg-red-50' : ''}`}>
                      <td className="py-1.5 font-bold">{s.code}</td>
                      <td>{s.name}</td>
                      <td className={`font-bold ${s.negative ? 'text-red-600' : ''}`}>{fmt(s.qty_on_hand)}</td>
                      <td>{fmt(s.unit_cost)}</td>
                      <td>{s.negative && <Badge tone="red">سالب!</Badge>}</td>
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
