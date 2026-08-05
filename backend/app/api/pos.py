"""نقاط وحدة POS — ملف 04 وملف 12:
كتالوج/طلبات/تسديد بكل الوسائل/شحن للغرفة/ورديات/Z-Report/تقارير.
قاعدة مركزية: لا أثراً مالياً إلا عبر app/pos.py → محرك الترحيل (02 §6)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from .. import pos as ps
from ..db import get_db
from ..deps import Principal, get_principal, require_perm
from ..posting import D
from ..schemas_pos import (CategoryIn, ItemIn, ItemPatch, LineIn, LinePatch,
                           ModifierIn, OrderIn, OutletIn, PinSetIn, RecipeSetIn,
                           ReturnIn, ShiftCloseIn, ShiftOpenIn, StockLoadIn,
                           TableIn, VoidIn, SettleIn)
from ..security import new_uuid, utcnow, verify_password

router = APIRouter(prefix='/api/pos', tags=['pos'])


def _it_out(it: m.PosItem) -> dict:
    return {'id': it.id, 'code': it.code, 'name_ar': it.name_ar,
            'name_en': it.name_en, 'barcode': it.barcode,
            'category_id': it.category_id, 'price': D(it.price),
            'tax_included': it.tax_included,
            'revenue_account_code': it.revenue_account_code,
            'item_type': it.item_type, 'cost': D(it.cost),
            'is_active': it.is_active}


def _order_out(db: Session, o: m.PosOrder) -> dict:
    outlet = db.get(m.PosOutlet, o.outlet_id)
    table = db.get(m.PosTable, o.table_id) if o.table_id else None
    lines = db.execute(select(m.PosOrderLine).where(
        m.PosOrderLine.order_id == o.id)).scalars().all()
    normal = [ln for ln in lines if ln.status == 'NORMAL']
    return {'id': o.id, 'outlet_id': o.outlet_id,
            'outlet': outlet.name_ar if outlet else '',
            'shift_id': o.shift_id, 'type': o.type, 'status': o.status,
            'table_id': o.table_id, 'table_name': table.name if table else None,
            'note': o.note, 'cancel_reason': o.cancel_reason,
            'opened_by': o.opened_by,
            'opened_at': o.opened_at.isoformat(),
            'fired_at': o.fired_at.isoformat() if o.fired_at else None,
            'total': sum((D(ln.line_total) - D(ln.discount) for ln in normal),
                         start=D(0)),
            'lines': [{'id': ln.id, 'item_id': ln.item_id,
                       'item_name': ln.item_name, 'station': ln.station,
                       'qty': D(ln.qty), 'unit_price': D(ln.unit_price),
                       'modifiers': ln.modifiers, 'notes': ln.notes,
                       'line_total': D(ln.line_total), 'discount': D(ln.discount),
                       'status': ln.status, 'void_reason': ln.void_reason,
                       'void_by': ln.void_by} for ln in lines]}


def _inv_head(db: Session, iv: m.PosInvoice) -> dict:
    outlet = db.get(m.PosOutlet, iv.outlet_id)
    return {'id': iv.id, 'invoice_no': iv.invoice_no, 'type': iv.type,
            'outlet': outlet.name_ar if outlet else '',
            'business_date': str(iv.business_date),
            'net_total': D(iv.net_total), 'discount_total': D(iv.discount_total),
            'tax_total': D(iv.tax_total),
            'issued_at': iv.issued_at.isoformat(),
            'return_of': iv.return_of_id}


# ── المنافذ والكتالوج ─────────────────────────────────────
@router.get('/outlets')
def get_outlets(db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('pos.view'))):
    rows = db.execute(select(m.PosOutlet).where(
        m.PosOutlet.tenant_id == pr.tenant_id).order_by(m.PosOutlet.code)
    ).scalars().all()
    return [{'id': o.id, 'code': o.code, 'name_ar': o.name_ar,
             'name_en': o.name_en, 'cash_account_code': o.cash_account_code,
             'default_revenue_account_code': o.default_revenue_account_code,
             'allow_negative_stock': o.allow_negative_stock,
             'cash_variance_tolerance': D(o.cash_variance_tolerance),
             'cost_center_code': o.cost_center_code,
             'is_active': o.is_active} for o in rows]


@router.post('/outlets', status_code=201)
def create_outlet(body: OutletIn, db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('pos.catalog.manage'))):
    dup = db.execute(select(m.PosOutlet).where(
        m.PosOutlet.tenant_id == pr.tenant_id,
        m.PosOutlet.code == body.code)).first()
    if dup:
        raise HTTPException(409, {'error': {'code': 'POS.DUP_OUTLET',
                                            'message_ar': 'كود المنفذ مستخدم'}})
    branch = db.execute(select(m.Branch).where(
        m.Branch.tenant_id == pr.tenant_id)).scalar_one()
    o = m.PosOutlet(id=new_uuid(), tenant_id=pr.tenant_id,
                    branch_id=branch.id, code=body.code, name_ar=body.name_ar,
                    name_en=body.name_en,
                    cash_account_code=body.cash_account_code,
                    default_revenue_account_code=body.default_revenue_account_code,
                    house_expense_account_code=body.house_expense_account_code,
                    allow_negative_stock=body.allow_negative_stock,
                    cash_variance_tolerance=body.cash_variance_tolerance,
                    cost_center_code=body.cost_center_code, created_at=utcnow())
    db.add(o)
    db.commit()
    return {'id': o.id, 'code': o.code}


@router.get('/categories')
def get_categories(db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('pos.view'))):
    rows = db.execute(select(m.PosCategory).where(
        m.PosCategory.tenant_id == pr.tenant_id,
        m.PosCategory.is_active.is_(True)).order_by(m.PosCategory.sort_order)
    ).scalars().all()
    return [{'id': c.id, 'code': c.code, 'name_ar': c.name_ar,
             'name_en': c.name_en, 'color': c.color, 'station': c.station,
             'sort_order': c.sort_order} for c in rows]


@router.post('/categories', status_code=201)
def create_category(body: CategoryIn, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('pos.catalog.manage'))):
    dup = db.execute(select(m.PosCategory).where(
        m.PosCategory.tenant_id == pr.tenant_id,
        m.PosCategory.code == body.code)).first()
    if dup:
        raise HTTPException(409, {'error': {'code': 'POS.DUP_CATEGORY',
                                            'message_ar': 'كود التصنيف مستخدم'}})
    c = m.PosCategory(id=new_uuid(), tenant_id=pr.tenant_id, code=body.code,
                      name_ar=body.name_ar, name_en=body.name_en,
                      color=body.color, station=body.station,
                      sort_order=body.sort_order)
    db.add(c)
    db.commit()
    return {'id': c.id}


@router.get('/items')
def get_items(search: str = '', category_id: str = '',
              include_inactive: bool = False, limit: int = 200,
              offset: int = 0, db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('pos.view'))):
    """قائمة الأصناف — مقسطة صفحياً حتى مع 5,000 صنف (قبول #1)."""
    limit = min(limit, 500)
    q = select(m.PosItem).where(m.PosItem.tenant_id == pr.tenant_id)
    if not include_inactive:
        q = q.where(m.PosItem.is_active.is_(True))
    if category_id:
        q = q.where(m.PosItem.category_id == category_id)
    if search:
        like = f'%{search}%'
        q = q.where(m.PosItem.name_ar.like(like)
                    | m.PosItem.name_en.like(like)
                    | m.PosItem.code.like(like)
                    | m.PosItem.barcode.like(like))
    total = db.execute(select(func.count()).select_from(
        q.subquery())).scalar_one()
    rows = db.execute(q.order_by(m.PosItem.code).offset(offset).limit(limit)
                      ).scalars().all()
    return {'total': total, 'items': [_it_out(it) for it in rows]}


@router.post('/items', status_code=201)
def create_item(body: ItemIn, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('pos.catalog.manage'))):
    dup = db.execute(select(m.PosItem).where(
        m.PosItem.tenant_id == pr.tenant_id,
        m.PosItem.code == body.code)).first()
    if dup:
        raise HTTPException(409, {'error': {'code': 'POS.DUP_ITEM',
                                            'message_ar': 'كود الصنف مستخدم'}})
    cat = db.get(m.PosCategory, body.category_id)
    if cat is None or cat.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'POS.UNKNOWN_CATEGORY',
                                            'message_ar': 'تصنيف غير موجود'}})
    it = m.PosItem(id=new_uuid(), tenant_id=pr.tenant_id, code=body.code,
                   name_ar=body.name_ar, name_en=body.name_en,
                   barcode=body.barcode, category_id=body.category_id,
                   price=body.price, tax_included=body.tax_included,
                   revenue_account_code=body.revenue_account_code,
                   item_type=body.item_type, cost=body.cost)
    db.add(it)
    db.commit()
    return {'id': it.id}


@router.patch('/items/{item_id}')
def patch_item(item_id: str, body: ItemPatch, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('pos.catalog.manage'))):
    it = db.get(m.PosItem, item_id)
    if it is None or it.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'POS.UNKNOWN_ITEM',
                                            'message_ar': 'صنف غير موجود'}})
    before = {'price': str(it.price), 'cost': str(it.cost),
              'is_active': it.is_active}
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(it, field, value)
    it.version += 1
    from ..audit import audit
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='pos', action='catalog.item.patch', entity='pos_items',
          entity_id=it.id, before=before,
          after=body.model_dump(exclude_none=True))
    db.commit()
    return _it_out(it)


@router.get('/items/{item_id}/recipe')
def get_recipe(item_id: str, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('pos.view'))):
    rows = db.execute(select(m.PosRecipe).where(
        m.PosRecipe.parent_item_id == item_id)).scalars().all()
    return [{'component_item_id': r.component_item_id,
             'name': (db.get(m.PosItem, r.component_item_id).name_ar
                      if db.get(m.PosItem, r.component_item_id) else ''),
             'qty': D(r.qty)} for r in rows]


@router.put('/items/{item_id}/recipe')
def set_recipe(item_id: str, body: RecipeSetIn, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('pos.catalog.manage'))):
    it = db.get(m.PosItem, item_id)
    if it is None or it.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'POS.UNKNOWN_ITEM',
                                            'message_ar': 'صنف غير موجود'}})
    if it.item_type != 'COMPOSITE':
        raise HTTPException(400, {'error': {'code': 'POS.NOT_COMPOSITE',
                                            'message_ar': 'الوصفات للأصناف المركبة فقط'}})
    for ln in body.lines:
        comp = db.get(m.PosItem, ln.component_item_id)
        if comp is None or comp.tenant_id != pr.tenant_id:
            raise HTTPException(404, {'error': {'code': 'POS.UNKNOWN_COMPONENT',
                                                'message_ar': f'مكوّن غير موجود: {ln.component_item_id}'}})
        if comp.item_type == 'COMPOSITE':
            raise HTTPException(400, {'error': {'code': 'POS.NESTED_RECIPE',
                                                'message_ar': 'مكوّن مركّب ممنوع (لا وصفات متداخلة في v1)'}})
    db.query(m.PosRecipe).filter(m.PosRecipe.parent_item_id == item_id
                                 ).delete(synchronize_session=False)
    for ln in body.lines:
        db.add(m.PosRecipe(id=new_uuid(), tenant_id=pr.tenant_id,
                           parent_item_id=item_id,
                           component_item_id=ln.component_item_id,
                           qty=ln.qty))
    from ..audit import audit
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='pos', action='catalog.recipe.set', entity='pos_items',
          entity_id=item_id,
          after={'components': [ln.model_dump() for ln in body.lines]})
    db.commit()
    return {'set': len(body.lines)}


@router.get('/modifiers')
def get_modifiers(db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('pos.view'))):
    rows = db.execute(select(m.PosModifier).where(
        m.PosModifier.tenant_id == pr.tenant_id,
        m.PosModifier.is_active.is_(True))).scalars().all()
    return [{'id': md.id, 'name_ar': md.name_ar, 'name_en': md.name_en,
             'price': D(md.price)} for md in rows]


@router.post('/modifiers', status_code=201)
def create_modifier(body: ModifierIn, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('pos.catalog.manage'))):
    md = m.PosModifier(id=new_uuid(), tenant_id=pr.tenant_id,
                       name_ar=body.name_ar, name_en=body.name_en,
                       price=body.price)
    db.add(md)
    db.commit()
    return {'id': md.id}


@router.get('/items/{item_id}/modifiers')
def get_item_modifiers(item_id: str, db: Session = Depends(get_db),
                       pr: Principal = Depends(require_perm('pos.view'))):
    rows = db.execute(select(m.PosModifier).join(
        m.PosItemModifier, m.PosItemModifier.modifier_id == m.PosModifier.id
    ).where(m.PosItemModifier.item_id == item_id,
            m.PosModifier.is_active.is_(True))).scalars().all()
    return [{'id': md.id, 'name_ar': md.name_ar, 'price': D(md.price)}
            for md in rows]


@router.post('/items/{item_id}/modifiers/{modifier_id}', status_code=201)
def link_modifier(item_id: str, modifier_id: str,
                  db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('pos.catalog.manage'))):
    if db.get(m.PosItem, item_id) is None or db.get(m.PosModifier, modifier_id) is None:
        raise HTTPException(404, {'error': {'code': 'POS.UNKNOWN_REF',
                                            'message_ar': 'صنف أو معدِّل غير موجود'}})
    if not db.execute(select(m.PosItemModifier).where(
            m.PosItemModifier.item_id == item_id,
            m.PosItemModifier.modifier_id == modifier_id)).first():
        db.add(m.PosItemModifier(id=new_uuid(), tenant_id=pr.tenant_id,
                                 item_id=item_id, modifier_id=modifier_id))
        db.commit()
    return {'linked': True}


# ── الطاولات والمخزون ────────────────────────────────────
@router.get('/tables')
def get_tables(outlet_id: str, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('pos.view'))):
    rows = db.execute(select(m.PosTable).where(
        m.PosTable.outlet_id == outlet_id,
        m.PosTable.is_active.is_(True)).order_by(m.PosTable.name)
    ).scalars().all()
    busy = {r[0] for r in db.execute(
        select(m.PosOrder.table_id).where(
            m.PosOrder.table_id.isnot(None),
            m.PosOrder.status.in_(('DRAFT', 'FIRED')))).all()}
    return [{'id': t.id, 'name': t.name, 'zone': t.zone, 'seats': t.seats,
             'occupied': t.id in busy} for t in rows]


@router.post('/tables', status_code=201)
def create_table(body: TableIn, outlet_id: str,
                 db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('pos.tables.manage'))):
    t = m.PosTable(id=new_uuid(), tenant_id=pr.tenant_id, outlet_id=outlet_id,
                   name=body.name, zone=body.zone, seats=body.seats)
    db.add(t)
    db.commit()
    return {'id': t.id}


@router.get('/stock')
def get_stock(outlet_id: str, db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('pos.view'))):
    rows = db.execute(select(m.PosStock).where(
        m.PosStock.outlet_id == outlet_id)).scalars().all()
    out = []
    for s in rows:
        it = db.get(m.PosItem, s.item_id)
        out.append({'item_id': s.item_id, 'code': it.code if it else '',
                    'name': it.name_ar if it else '',
                    'type': it.item_type if it else '',
                    'qty_on_hand': D(s.qty_on_hand),
                    'unit_cost': D(it.cost) if it else D(0),
                    'negative': D(s.qty_on_hand) < 0})
    return sorted(out, key=lambda r: r['code'])


@router.post('/stock/load', status_code=201)
def stock_load(body: StockLoadIn, outlet_id: str,
               db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('pos.stock.manage'))):
    outlet = ps.outlet_or_err(db, pr.tenant_id, outlet_id)
    key = f'posstock:load:{outlet.code}:{body.item_id}:{new_uuid()}'
    s = ps.load_stock(db, tenant_id=pr.tenant_id, outlet=outlet,
                      item_id=body.item_id, qty=body.qty,
                      unit_cost=body.unit_cost, actor_id=pr.id, event_key=key)
    db.commit()
    return {'item_id': s.item_id, 'qty_on_hand': D(s.qty_on_hand)}


# ── الطلبات ──────────────────────────────────────────────
@router.post('/orders', status_code=201)
def create_order(body: OrderIn, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('pos.sell'))):
    outlet = ps.outlet_or_err(db, pr.tenant_id, body.outlet_id)
    shift = ps.open_shift_or_err(db, pr.tenant_id, outlet.id)
    o = ps.create_order(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                        outlet=outlet, shift=shift, type_=body.type,
                        table_id=body.table_id, note=body.note)
    db.commit()
    return _order_out(db, o)


@router.get('/orders')
def get_orders(status: str = '', shift_id: str = '',
               db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('pos.view'))):
    q = select(m.PosOrder).where(m.PosOrder.tenant_id == pr.tenant_id)
    if status:
        q = q.where(m.PosOrder.status == status)
    if shift_id:
        q = q.where(m.PosOrder.shift_id == shift_id)
    rows = db.execute(q.order_by(m.PosOrder.opened_at.desc()).limit(100)
                      ).scalars().all()
    return [_order_out(db, o) for o in rows]


@router.get('/orders/{order_id}')
def get_order(order_id: str, db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('pos.view'))):
    return _order_out(db, ps.order_or_err(db, pr.tenant_id, order_id))


@router.post('/orders/{order_id}/lines', status_code=201)
def add_line(order_id: str, body: LineIn, db: Session = Depends(get_db),
             pr: Principal = Depends(require_perm('pos.sell'))):
    o = ps.order_or_err(db, pr.tenant_id, order_id)
    ln = ps.add_line(db, tenant_id=pr.tenant_id, order=o,
                     item_id=body.item_id, qty=body.qty, actor_id=pr.id,
                     modifiers=body.modifiers, notes=body.notes,
                     discount=body.discount)
    db.commit()
    return {'id': ln.id, 'line_total': D(ln.line_total)}


@router.patch('/orders/{order_id}/lines/{line_id}')
def patch_line(order_id: str, line_id: str, body: LinePatch,
               db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('pos.sell'))):
    o = ps.order_or_err(db, pr.tenant_id, order_id)
    if o.status != 'DRAFT':
        raise HTTPException(400, {'error': {'code': 'POS.ORDER_NOT_DRAFT',
                                            'message_ar': 'التعديل على المسودة فقط'}})
    ln = db.get(m.PosOrderLine, line_id)
    if ln is None or ln.order_id != order_id or ln.status != 'NORMAL':
        raise HTTPException(404, {'error': {'code': 'POS.UNKNOWN_LINE',
                                            'message_ar': 'بند غير موجود'}})
    if body.qty is not None:
        ln.qty = body.qty
    if body.discount is not None:
        ln.discount = body.discount
    if body.notes is not None:
        ln.notes = body.notes
    ln.line_total = ps._line_total(D(ln.unit_price), D(ln.qty), ln.modifiers)
    if ln.discount >= ln.line_total:
        raise HTTPException(400, {'error': {'code': 'POS.BAD_DISCOUNT',
                                            'message_ar': 'الخصم يلتهم البند'}})
    db.commit()
    return {'id': ln.id, 'line_total': D(ln.line_total)}


@router.post('/orders/{order_id}/lines/{line_id}/void')
def void_line(order_id: str, line_id: str, body: VoidIn,
              db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('pos.void'))):
    o = ps.order_or_err(db, pr.tenant_id, order_id)
    ps.void_line(db, tenant_id=pr.tenant_id, order=o, line_id=line_id,
                 reason=body.reason, actor_id=pr.id)
    db.commit()
    return {'voided': True}


@router.post('/orders/{order_id}/fire')
def fire_order(order_id: str, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('pos.sell'))):
    o = ps.order_or_err(db, pr.tenant_id, order_id)
    ps.fire_order(db, tenant_id=pr.tenant_id, order=o, actor_id=pr.id)
    db.commit()
    return _order_out(db, o)


@router.post('/orders/{order_id}/cancel')
def cancel_order(order_id: str, body: VoidIn, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('pos.void'))):
    o = ps.order_or_err(db, pr.tenant_id, order_id)
    ps.cancel_order(db, tenant_id=pr.tenant_id, order=o, reason=body.reason,
                    actor_id=pr.id)
    db.commit()
    return {'cancelled': True}


@router.post('/orders/{order_id}/settle', status_code=201)
def settle_order(order_id: str, body: SettleIn, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('pos.sell'))):
    """الإقفال والتسديد — قبول #4: إعادة إرسال client_uuid نفسه بعد سقوط
    الشبكة ترجع الفاتورة ذاتها (replayed=true) بلا أي تكرار."""
    o = ps.order_or_err(db, pr.tenant_id, order_id)
    out = ps.settle_order(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                          actor_perms=pr.perms, order=o,
                          payments=[p.model_dump() for p in body.payments],
                          client_uuid=body.client_uuid,
                          invoice_discount=body.invoice_discount,
                          discount_reason=body.discount_reason,
                          approver_pin=body.approver_pin)
    db.commit()
    return {'invoice': ps.invoice_view(db, pr.tenant_id, out['invoice'].id),
            'replayed': out['replayed']}


# ── الفواتير والمرتجعات ──────────────────────────────────
@router.get('/invoices')
def get_invoices(outlet_id: str = '', type: str = '',
                 date_from: date | None = None, date_to: date | None = None,
                 limit: int = 100, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('pos.view'))):
    q = select(m.PosInvoice).where(m.PosInvoice.tenant_id == pr.tenant_id)
    if outlet_id:
        q = q.where(m.PosInvoice.outlet_id == outlet_id)
    if type:
        q = q.where(m.PosInvoice.type == type)
    if date_from:
        q = q.where(m.PosInvoice.business_date >= date_from)
    if date_to:
        q = q.where(m.PosInvoice.business_date <= date_to)
    rows = db.execute(q.order_by(m.PosInvoice.issued_at.desc())
                      .limit(min(limit, 500))).scalars().all()
    return [_inv_head(db, iv) for iv in rows]


@router.get('/invoices/{invoice_id}')
def get_invoice(invoice_id: str, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('pos.view'))):
    return ps.invoice_view(db, pr.tenant_id, invoice_id)


@router.post('/invoices/{invoice_id}/return', status_code=201)
def return_invoice(invoice_id: str, body: ReturnIn,
                   db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('pos.return'))):
    rinv = ps.return_invoice(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                             invoice_id=invoice_id, reason=body.reason)
    db.commit()
    return ps.invoice_view(db, pr.tenant_id, rinv.id)


# ── شاشة التحميل على غرفة (§4) ───────────────────────────
@router.get('/room-charge/occupied')
def occupied_rooms(db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('pos.sell',
                                                        'frontdesk.view'))):
    return ps.occupied_rooms(db, pr.tenant_id)


# ── الورديات وZ-Report ───────────────────────────────────
@router.get('/shifts')
def get_shifts(outlet_id: str = '', status: str = '',
               db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('pos.view'))):
    q = select(m.PosShift).where(m.PosShift.tenant_id == pr.tenant_id)
    if outlet_id:
        q = q.where(m.PosShift.outlet_id == outlet_id)
    if status:
        q = q.where(m.PosShift.status == status)
    rows = db.execute(q.order_by(m.PosShift.opened_at.desc()).limit(50)
                      ).scalars().all()
    out = []
    for sh in rows:
        outlet = db.get(m.PosOutlet, sh.outlet_id)
        opener = db.get(m.User, sh.opened_by)
        out.append({'id': sh.id, 'outlet_id': sh.outlet_id,
                    'outlet': outlet.name_ar if outlet else '',
                    'status': sh.status,
                    'opened_by': opener.full_name if opener else '',
                    'opened_at': sh.opened_at.isoformat(),
                    'opening_float': D(sh.opening_float),
                    'closed_at': sh.closed_at.isoformat() if sh.closed_at else None,
                    'actual_cash': D(sh.actual_cash) if sh.actual_cash is not None else None,
                    'expected_cash': D(sh.expected_cash) if sh.expected_cash is not None else None,
                    'cash_variance': D(sh.cash_variance) if sh.cash_variance is not None else None})
    return out


@router.post('/shifts/open', status_code=201)
def open_shift(body: ShiftOpenIn, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('pos.shift.open'))):
    outlet = ps.outlet_or_err(db, pr.tenant_id, body.outlet_id)
    sh = ps.open_shift(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                       outlet=outlet, opening_float=body.opening_float)
    db.commit()
    return {'id': sh.id, 'status': sh.status}


@router.post('/shifts/{shift_id}/close')
def close_shift(shift_id: str, body: ShiftCloseIn,
                db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('pos.shift.close'))):
    sh = db.get(m.PosShift, shift_id)
    if sh is None or sh.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'POS.UNKNOWN_SHIFT',
                                            'message_ar': 'وردية غير موجودة'}})
    if sh.status != 'OPEN':
        raise HTTPException(400, {'error': {'code': 'POS.SHIFT_CLOSED',
                                            'message_ar': 'الوردية مقفلة — Z-Report أرشيفي لا يُعدَّل'}})
    z = ps.close_shift(db, tenant_id=pr.tenant_id, actor_id=pr.id, shift=sh,
                       actual_cash=body.actual_cash)
    db.commit()
    return z


@router.get('/shifts/{shift_id}/zreport')
def get_zreport(shift_id: str, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('pos.zreport.view'))):
    sh = db.get(m.PosShift, shift_id)
    if sh is None or sh.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'POS.UNKNOWN_SHIFT',
                                            'message_ar': 'وردية غير موجودة'}})
    if sh.status == 'OPEN':
        summ = ps.shift_summary(db, pr.tenant_id, sh)
        return {'status': 'OPEN', 'live_summary': {
            k: str(v) if not isinstance(v, (int, dict, list)) else v
            for k, v in summ.items()}}
    return {'status': 'CLOSED', 'zreport': sh.zreport}


@router.get('/z-reports')
def z_reports(outlet_id: str = '', db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('pos.zreport.view'))):
    """أرشيف تقارير Z المقفلة — قراءة فقط ولا يوجد أي مسار تعديل (§5)."""
    q = select(m.PosShift).where(m.PosShift.tenant_id == pr.tenant_id,
                                 m.PosShift.status == 'CLOSED')
    if outlet_id:
        q = q.where(m.PosShift.outlet_id == outlet_id)
    rows = db.execute(q.order_by(m.PosShift.closed_at.desc()).limit(100)
                      ).scalars().all()
    return [{'shift_id': sh.id, 'zreport': sh.zreport} for sh in rows]


# ── PIN الاعتماد الفوري ──────────────────────────────────
@router.post('/users/me/pin', status_code=201)
def set_my_pin(body: PinSetIn, db: Session = Depends(get_db),
               pr: Principal = Depends(get_principal)):
    if not verify_password(body.current_password, pr.user.password_hash):
        raise HTTPException(403, {'error': {'code': 'AUTH.BAD_PASSWORD',
                                            'message_ar': 'كلمة المرور الحالية غير صحيحة'}})
    ps.set_pos_pin(db, user=pr.user, pin=body.pin, actor_id=pr.id)
    db.commit()
    return {'pin_set': True}


# ── التقارير (§5) ────────────────────────────────────────
@router.get('/reports/sales')
def report_sales(date_from: date, date_to: date, group_by: str = 'item',
                 db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('pos.reports'))):
    if group_by not in ('outlet', 'category', 'item', 'hour', 'payment', 'user'):
        raise HTTPException(400, {'error': {'code': 'POS.BAD_GROUP',
                                            'message_ar': 'group_by غير صالح'}})
    rows = ps.sales_report(db, pr.tenant_id, date_from, date_to, group_by)
    return [{**r, 'net': str(r['net']), 'cost': str(r['cost']),
             'margin': str(r['margin']), 'margin_pct': round(r['margin_pct'], 2)}
            for r in rows]


@router.get('/reports/control')
def report_control(date_from: date, date_to: date,
                   db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('pos.reports'))):
    return ps.control_report(db, pr.tenant_id, date_from, date_to)


@router.get('/reports/consumption')
def report_consumption(outlet_id: str, date_from: date, date_to: date,
                       db: Session = Depends(get_db),
                       pr: Principal = Depends(require_perm('pos.reports'))):
    rows = ps.consumption_report(db, pr.tenant_id, outlet_id,
                                 date_from, date_to)
    return [{**r, 'theoretical_out': str(r['theoretical_out']),
             'actual_out': str(r['actual_out']), 'variance': str(r['variance']),
             'qty_on_hand': str(r['qty_on_hand'])} for r in rows]
