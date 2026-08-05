"""نقاط وحدة المخزون والمشتريات — ملف 05 وملف 12:
كتالوج/مستودعات/موردون، دورة PR→PO→GRN→مطابقة→سداد→مرتجع، صرف/تحويل/
هالك/جرد، تقارير وتنبيهات. قاعدة مركزية: لا أثراً مالياً ولا مخزونياً
إلا عبر app/inventory.py → محرك الترحيل (02 §6/§11)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import inventory as inv
from .. import models as m
from ..db import get_db
from ..deps import Principal, get_principal, require_perm
from ..posting import D
from ..schemas_inv import (CategoryIn, CountApproveIn, CountEntryIn, CountIn,
                           GRNIn, IssueIn, ItemIn, ItemPatch, PaymentIn,
                           PolicyIn, POIn, PRIn, RejectIn, SupplierIn,
                           SupplierInvoiceIn, SupplierPatch, SupplierPriceIn,
                           SupplierReturnIn, TransferIn, VarianceResolveIn,
                           WarehouseIn, WarehousePatch, WasteIn)

router = APIRouter(prefix='/api/inv', tags=['inventory'])


def _perm403():
    raise HTTPException(403, {'error': {'code': 'RBAC.FORBIDDEN',
                                        'message_ar': 'صلاحية غير كافية'}})


# ═══════════════ الكتالوج: تصنيفات/أصناف/مستودعات ═══════════════
@router.get('/categories')
def get_categories(db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('inv.view'))):
    rows = db.execute(select(m.InvCategory).where(
        m.InvCategory.tenant_id == pr.tenant_id).order_by(m.InvCategory.code)
    ).scalars().all()
    return [{'id': c.id, 'code': c.code, 'name_ar': c.name_ar,
             'default_account_code': c.default_account_code,
             'valuation_method': c.valuation_method,
             'method_locked': c.method_locked, 'is_active': c.is_active}
            for c in rows]


@router.post('/categories', status_code=201)
def create_category(body: CategoryIn, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('inv.catalog.manage'))):
    c = inv.create_category(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                            code=body.code, name_ar=body.name_ar,
                            default_account_code=body.default_account_code,
                            valuation_method='AVG')
    db.commit()
    return {'id': c.id, 'code': c.code}


@router.get('/items')
def get_items(q: str = '', category_id: str = '', active: str = '',
              db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('inv.view'))):
    query = select(m.InvItem).where(m.InvItem.tenant_id == pr.tenant_id)
    if category_id:
        query = query.where(m.InvItem.category_id == category_id)
    if active == '1':
        query = query.where(m.InvItem.is_active.is_(True))
    rows = db.execute(query.order_by(m.InvItem.code)).scalars().all()
    out = []
    for it in rows:
        if q and q not in it.name_ar and q.lower() not in it.code.lower() \
                and q not in (it.barcode or ''):
            continue
        cat = db.get(m.InvCategory, it.category_id)
        # الرصيد الإجمالي عبر المستودعات
        on_hand = db.execute(
            select(m.InvStock).where(m.InvStock.item_id == it.id)
        ).scalars().all()
        qty = sum((D(s.qty_on_hand) for s in on_hand), D(0))
        val = sum((D(s.qty_on_hand) * D(s.avg_cost) for s in on_hand), D(0))
        out.append({'id': it.id, 'code': it.code, 'name_ar': it.name_ar,
                    'name_en': it.name_en, 'category_id': it.category_id,
                    'category': cat.name_ar if cat else '',
                    'base_unit': it.base_unit, 'alt_units': it.alt_units,
                    'barcode': it.barcode,
                    'reorder_level': D(it.reorder_level),
                    'safety_level': D(it.safety_level),
                    'inventory_account_code': it.inventory_account_code,
                    'track_expiry': it.track_expiry,
                    'pos_item_id': it.pos_item_id, 'is_active': it.is_active,
                    'on_hand_total': qty, 'value_total': val.quantize(
                        D('0.0001'))})
    return out


@router.post('/items', status_code=201)
def create_item(body: ItemIn, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('inv.catalog.manage'))):
    it = inv.create_item(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                         code=body.code, name_ar=body.name_ar,
                         name_en=body.name_en, category_id=body.category_id,
                         base_unit=body.base_unit,
                         alt_units=[u.model_dump() for u in body.alt_units],
                         barcode=body.barcode,
                         reorder_level=body.reorder_level,
                         safety_level=body.safety_level,
                         inventory_account_code=body.inventory_account_code,
                         track_expiry=body.track_expiry)
    db.commit()
    return {'id': it.id, 'code': it.code}


@router.patch('/items/{item_id}')
def patch_item(item_id: str, body: ItemPatch, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('inv.catalog.manage'))):
    it = inv.update_item_levels(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                                item_id=item_id,
                                changes=body.model_dump(exclude_unset=True))
    db.commit()
    return {'id': it.id, 'code': it.code}


@router.get('/warehouses')
def get_warehouses(db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('inv.view'))):
    rows = db.execute(select(m.InvWarehouse).where(
        m.InvWarehouse.tenant_id == pr.tenant_id)
        .order_by(m.InvWarehouse.code)).scalars().all()
    out = []
    for w in rows:
        keeper = db.get(m.User, w.keeper_user_id) if w.keeper_user_id else None
        stock_val = db.execute(
            select(m.InvStock).where(m.InvStock.warehouse_id == w.id)
        ).scalars().all()
        out.append({'id': w.id, 'code': w.code, 'name_ar': w.name_ar,
                    'kind': w.kind,
                    'inventory_account_code': w.inventory_account_code,
                    'keeper_user_id': w.keeper_user_id,
                    'keeper_name': keeper.full_name if keeper else None,
                    'allow_negative': w.allow_negative,
                    'pos_outlet_id': w.pos_outlet_id,
                    'cost_center_code': w.cost_center_code,
                    'is_active': w.is_active,
                    'skus': len([s for s in stock_val
                                 if D(s.qty_on_hand) != 0]),
                    'stock_value': sum(
                        (D(s.qty_on_hand) * D(s.avg_cost) for s in stock_val),
                        D(0)).quantize(D('0.0001'))})
    return out


@router.post('/warehouses', status_code=201)
def create_warehouse(body: WarehouseIn, db: Session = Depends(get_db),
                     pr: Principal = Depends(require_perm('inv.catalog.manage'))):
    branch = db.execute(select(m.Branch).where(
        m.Branch.tenant_id == pr.tenant_id).limit(1)).scalar_one()
    w = inv.create_warehouse(
        db, tenant_id=pr.tenant_id, branch_id=branch.id, actor_id=pr.id,
        code=body.code, name_ar=body.name_ar, kind=body.kind,
        inventory_account_code=body.inventory_account_code,
        keeper_user_id=body.keeper_user_id, allow_negative=body.allow_negative,
        cost_center_code=body.cost_center_code)
    db.commit()
    return {'id': w.id, 'code': w.code}


@router.patch('/warehouses/{wh_id}')
def patch_warehouse(wh_id: str, body: WarehousePatch,
                    db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('inv.catalog.manage'))):
    w = inv.warehouse_or_err(db, pr.tenant_id, wh_id)
    data = body.model_dump(exclude_unset=True)
    # حارس أساسي: حساب المستودع لا يُغيَّر بعد أول حركة (اتساق المطابقة)
    data.pop('inventory_account_code', None)
    for k, v in data.items():
        setattr(w, k, v)
    db.commit()
    return {'id': w.id, 'code': w.code}


# ═══════════════ الموردون ═══════════════
def _sup_out(db: Session, s: m.InvSupplier) -> dict:
    return {'id': s.id, 'code': s.code, 'name': s.name,
            'contact_person': s.contact_person, 'phone': s.phone,
            'address': s.address, 'terms_days': s.terms_days,
            'currency': s.currency, 'notes': s.notes,
            'rating_commitment': s.rating_commitment,
            'rating_quality': s.rating_quality, 'is_active': s.is_active,
            'balance': inv.supplier_balance(db, s.tenant_id, s.id)}


@router.get('/suppliers')
def get_suppliers(db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('inv.view'))):
    rows = db.execute(select(m.InvSupplier).where(
        m.InvSupplier.tenant_id == pr.tenant_id).order_by(m.InvSupplier.code)
    ).scalars().all()
    return [_sup_out(db, s) for s in rows]


@router.post('/suppliers', status_code=201)
def create_supplier(body: SupplierIn, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('inv.suppliers.manage'))):
    s = inv.create_supplier(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                            **body.model_dump())
    db.commit()
    return _sup_out(db, s)


@router.patch('/suppliers/{sup_id}')
def patch_supplier(sup_id: str, body: SupplierPatch,
                   db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('inv.suppliers.manage'))):
    s = inv.update_supplier(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                            supplier_id=sup_id,
                            changes=body.model_dump(exclude_unset=True))
    db.commit()
    return _sup_out(db, s)


@router.get('/suppliers/{sup_id}/prices')
def get_supplier_prices(sup_id: str, db: Session = Depends(get_db),
                        pr: Principal = Depends(require_perm('inv.view'))):
    rows = db.execute(select(m.InvSupplierPrice).where(
        m.InvSupplierPrice.tenant_id == pr.tenant_id,
        m.InvSupplierPrice.supplier_id == sup_id)
        .order_by(m.InvSupplierPrice.valid_from.desc())).scalars().all()
    return [{'id': r.id, 'item_id': r.item_id,
             'item_code': (db.get(m.InvItem, r.item_id) or m.InvItem(
                 id='', tenant_id='', code='?', name_ar='?',
                 category_id='')).code,
             'price': D(r.price), 'valid_from': str(r.valid_from),
             'valid_to': str(r.valid_to) if r.valid_to else None}
            for r in rows]


@router.post('/suppliers/{sup_id}/prices', status_code=201)
def set_supplier_price(sup_id: str, body: SupplierPriceIn,
                       db: Session = Depends(get_db),
                       pr: Principal = Depends(require_perm('inv.suppliers.manage'))):
    sp = inv.set_supplier_price(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                                supplier_id=sup_id, item_id=body.item_id,
                                price=body.price, valid_from=body.valid_from,
                                valid_to=body.valid_to)
    db.commit()
    return {'id': sp.id}


@router.get('/suppliers/{sup_id}/statement')
def get_statement(sup_id: str, db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('inv.view'))):
    return inv.supplier_statement(db, pr.tenant_id, sup_id)


# ═══════════════ طلبات الشراء (PR) ═══════════════
def _pr_out(db: Session, pr: m.InvPurchaseRequest) -> dict:
    lines = db.execute(select(m.InvPRLine).where(
        m.InvPRLine.pr_id == pr.id)).scalars().all()
    return {'id': pr.id, 'pr_no': pr.pr_no, 'department': pr.department,
            'status': pr.status, 'notes': pr.notes,
            'created_by': pr.created_by, 'created_at': pr.created_at.isoformat(),
            'approved_by': pr.approved_by, 'reject_reason': pr.reject_reason,
            'lines': [{'item_id': ln.item_id,
                       'item_code': (db.get(m.InvItem, ln.item_id) or
                                     m.InvItem(id='', tenant_id='', code='?',
                                               name_ar='?', category_id='')).code,
                       'qty': D(ln.qty), 'note': ln.note} for ln in lines]}


@router.get('/pr')
def get_prs(status: str = '', db: Session = Depends(get_db),
            pr: Principal = Depends(require_perm('inv.view'))):
    q = select(m.InvPurchaseRequest).where(
        m.InvPurchaseRequest.tenant_id == pr.tenant_id)
    if status:
        q = q.where(m.InvPurchaseRequest.status == status)
    rows = db.execute(q.order_by(m.InvPurchaseRequest.created_at.desc())
                      .limit(300)).scalars().all()
    return [_pr_out(db, r) for r in rows]


@router.post('/pr', status_code=201)
def create_pr(body: PRIn, db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('inv.pr.create'))):
    r = inv.create_pr(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                      department=body.department, notes=body.notes,
                      lines=[ln.model_dump() for ln in body.lines])
    db.commit()
    return _pr_out(db, r)


@router.post('/pr/{pr_id}/submit')
def submit_pr(pr_id: str, db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('inv.pr.create'))):
    r = inv.submit_pr(db, tenant_id=pr.tenant_id, actor_id=pr.id, pr_id=pr_id)
    db.commit()
    return _pr_out(db, r)


@router.post('/pr/{pr_id}/approve')
def approve_pr(pr_id: str, body: RejectIn | None = None,
               approve: bool = True, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('inv.pr.approve'))):
    r = inv.approve_pr(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                       pr_id=pr_id, approve=approve,
                       reason=(body.reason if body else '') or '')
    db.commit()
    return _pr_out(db, r)


# ═══════════════ أوامر الشراء (PO) ═══════════════
def _po_out(db: Session, po: m.InvPurchaseOrder) -> dict:
    sup = db.get(m.InvSupplier, po.supplier_id)
    lines = db.execute(select(m.InvPOLine).where(
        m.InvPOLine.po_id == po.id)).scalars().all()
    return {'id': po.id, 'po_no': po.po_no,
            'supplier_id': po.supplier_id,
            'supplier': sup.name if sup else '', 'status': po.status,
            'pr_id': po.pr_id,
            'expected_date': str(po.expected_date) if po.expected_date else None,
            'terms': po.terms, 'subtotal': D(po.subtotal),
            'tax_amount': D(po.tax_amount), 'total': D(po.total),
            'approve_level_required': po.approve_level_required,
            'created_by': po.created_by, 'created_at': po.created_at.isoformat(),
            'approved1_by': po.approved1_by, 'approved2_by': po.approved2_by,
            'reject_reason': po.reject_reason,
            'lines': [{'id': ln.id, 'item_id': ln.item_id,
                       'item_code': (db.get(m.InvItem, ln.item_id) or
                                     m.InvItem(id='', tenant_id='', code='?',
                                               name_ar='?', category_id='')).code,
                       'item_name': (db.get(m.InvItem, ln.item_id) or
                                     m.InvItem(id='', tenant_id='', code='?',
                                               name_ar='?', category_id='')).name_ar,
                       'uom': ln.uom, 'factor': D(ln.factor), 'qty': D(ln.qty),
                       'base_qty': D(ln.base_qty),
                       'unit_price': D(ln.unit_price),
                       'line_total': D(ln.line_total),
                       'received_qty': D(ln.received_qty)} for ln in lines]}


@router.get('/po')
def get_pos(status: str = '', db: Session = Depends(get_db),
            pr: Principal = Depends(require_perm('inv.view'))):
    q = select(m.InvPurchaseOrder).where(
        m.InvPurchaseOrder.tenant_id == pr.tenant_id)
    if status:
        q = q.where(m.InvPurchaseOrder.status == status)
    rows = db.execute(q.order_by(m.InvPurchaseOrder.created_at.desc())
                      .limit(300)).scalars().all()
    return [_po_out(db, p) for p in rows]


@router.get('/po/{po_id}')
def get_po(po_id: str, db: Session = Depends(get_db),
           pr: Principal = Depends(require_perm('inv.view'))):
    po = db.get(m.InvPurchaseOrder, po_id)
    if po is None or po.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'INV.UNKNOWN_PO',
                                            'message_ar': 'أمر شراء غير موجود'}})
    return _po_out(db, po)


@router.post('/po', status_code=201)
def create_po(body: POIn, db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('inv.po.create'))):
    po = inv.create_po(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                       supplier_id=body.supplier_id,
                       expected_date=body.expected_date, terms=body.terms,
                       pr_id=body.pr_id, tax_amount=body.tax_amount,
                       lines=[ln.model_dump() for ln in body.lines])
    db.commit()
    return _po_out(db, po)


@router.post('/po/{po_id}/approve')
def approve_po(po_id: str, db: Session = Depends(get_db),
               pr: Principal = Depends(get_principal)):
    if not (pr.has('inv.po.approve.l1') or pr.has('inv.po.approve.l2')):
        _perm403()
    po = db.get(m.InvPurchaseOrder, po_id)
    if po is not None and po.status == 'PENDING_L2' \
            and not pr.has('inv.po.approve.l2'):
        _perm403()
    if po is not None and po.status == 'PENDING_L1' \
            and not pr.has('inv.po.approve.l1'):
        _perm403()
    po = inv.approve_po(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                        po_id=po_id, actor_perms=pr.perms)
    db.commit()
    return _po_out(db, po)


@router.post('/po/{po_id}/reject')
def reject_po(po_id: str, body: RejectIn, db: Session = Depends(get_db),
              pr: Principal = Depends(get_principal)):
    if not (pr.has('inv.po.approve.l1') or pr.has('inv.po.approve.l2')):
        _perm403()
    po = inv.reject_po(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                       po_id=po_id, reason=body.reason)
    db.commit()
    return _po_out(db, po)


@router.post('/po/{po_id}/cancel')
def cancel_po(po_id: str, body: RejectIn, db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('inv.po.create'))):
    po = inv.cancel_po(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                       po_id=po_id, reason=body.reason)
    db.commit()
    return _po_out(db, po)


# ═══════════════ استلام البضاعة (GRN) ═══════════════
def _grn_out(db: Session, grn: m.InvGRN) -> dict:
    sup = db.get(m.InvSupplier, grn.supplier_id)
    wh = db.get(m.InvWarehouse, grn.warehouse_id)
    lines = db.execute(select(m.InvGRNLine).where(
        m.InvGRNLine.grn_id == grn.id)).scalars().all()
    return {'id': grn.id, 'grn_no': grn.grn_no, 'status': grn.status,
            'po_id': grn.po_id, 'supplier_id': grn.supplier_id,
            'supplier': sup.name if sup else '',
            'warehouse_id': grn.warehouse_id,
            'warehouse': wh.name_ar if wh else '',
            'purchase_type': grn.purchase_type,
            'supplier_invoice_no': grn.supplier_invoice_no,
            'payment_account_code': grn.payment_account_code,
            'subtotal': D(grn.subtotal), 'tax_amount': D(grn.tax_amount),
            'total': D(grn.total), 'entry_id': grn.entry_id,
            'note': grn.note, 'created_by': grn.created_by,
            'created_at': grn.created_at.isoformat(),
            'posted_by': grn.posted_by,
            'posted_at': grn.posted_at.isoformat() if grn.posted_at else None,
            'lines': [{'item_id': ln.item_id,
                       'item_code': (db.get(m.InvItem, ln.item_id) or
                                     m.InvItem(id='', tenant_id='', code='?',
                                               name_ar='?', category_id='')).code,
                       'qty_ordered': D(ln.qty_ordered),
                       'qty_received': D(ln.qty_received),
                       'qty_rejected': D(ln.qty_rejected),
                       'reject_reason': ln.reject_reason,
                       'unit_price': D(ln.unit_price),
                       'line_total': D(ln.line_total),
                       'batch_no': ln.batch_no,
                       'expiry_date': str(ln.expiry_date)
                       if ln.expiry_date else None} for ln in lines]}


@router.get('/grn')
def get_grns(status: str = '', db: Session = Depends(get_db),
             pr: Principal = Depends(require_perm('inv.view'))):
    q = select(m.InvGRN).where(m.InvGRN.tenant_id == pr.tenant_id)
    if status:
        q = q.where(m.InvGRN.status == status)
    rows = db.execute(q.order_by(m.InvGRN.created_at.desc()).limit(300)
                      ).scalars().all()
    return [_grn_out(db, g) for g in rows]


@router.get('/grn/{grn_id}')
def get_grn(grn_id: str, db: Session = Depends(get_db),
            pr: Principal = Depends(require_perm('inv.view'))):
    grn = db.get(m.InvGRN, grn_id)
    if grn is None or grn.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'INV.UNKNOWN_GRN',
                                            'message_ar': 'سند استلام غير موجود'}})
    return _grn_out(db, grn)


@router.post('/grn', status_code=201)
def create_grn(body: GRNIn, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('inv.grn.manage'))):
    grn = inv.create_grn(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                         supplier_id=body.supplier_id,
                         warehouse_id=body.warehouse_id,
                         purchase_type=body.purchase_type, po_id=body.po_id,
                         supplier_invoice_no=body.supplier_invoice_no,
                         payment_account_code=body.payment_account_code,
                         tax_amount=body.tax_amount, note=body.note,
                         bd=body.business_date,
                         lines=[ln.model_dump() for ln in body.lines])
    db.commit()
    return _grn_out(db, grn)


@router.post('/grn/{grn_id}/post')
def post_grn(grn_id: str, db: Session = Depends(get_db),
             pr: Principal = Depends(require_perm('inv.grn.manage'))):
    grn = inv.post_grn(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                       grn_id=grn_id)
    db.commit()
    return _grn_out(db, grn)


@router.post('/grn/{grn_id}/reverse')
def reverse_grn(grn_id: str, body: RejectIn, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('inv.grn.reverse'))):
    grn = inv.reverse_grn(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                          grn_id=grn_id, reason=body.reason)
    db.commit()
    return _grn_out(db, grn)


# ═══════════════ فواتير الموردين والمطابقة الثلاثية ═══════════════
def _si_out(db: Session, si: m.InvSupplierInvoice) -> dict:
    sup = db.get(m.InvSupplier, si.supplier_id)
    lines = db.execute(select(m.InvSILine).where(
        m.InvSILine.sinv_id == si.id)).scalars().all()
    return {'id': si.id, 'sinv_no': si.sinv_no,
            'supplier_invoice_no': si.supplier_invoice_no,
            'supplier_id': si.supplier_id, 'supplier': sup.name if sup else '',
            'po_id': si.po_id, 'grn_id': si.grn_id,
            'invoice_date': str(si.invoice_date), 'status': si.status,
            'subtotal': D(si.subtotal), 'tax_amount': D(si.tax_amount),
            'total': D(si.total), 'paid_amount': D(si.paid_amount),
            'remaining': D(si.total) - D(si.paid_amount),
            'match_report': si.match_report,
            'variance_approved_by': si.variance_approved_by,
            'created_by': si.created_by,
            'created_at': si.created_at.isoformat(),
            'approved_by': si.approved_by,
            'lines': [{'item_id': ln.item_id,
                       'item_code': (db.get(m.InvItem, ln.item_id) or
                                     m.InvItem(id='', tenant_id='', code='?',
                                               name_ar='?', category_id='')).code,
                       'qty': D(ln.qty), 'unit_price': D(ln.unit_price),
                       'line_total': D(ln.line_total)} for ln in lines]}


@router.get('/invoices')
def get_invoices(status: str = '', db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('inv.view'))):
    q = select(m.InvSupplierInvoice).where(
        m.InvSupplierInvoice.tenant_id == pr.tenant_id)
    if status:
        q = q.where(m.InvSupplierInvoice.status == status)
    rows = db.execute(q.order_by(m.InvSupplierInvoice.created_at.desc())
                      .limit(300)).scalars().all()
    return [_si_out(db, s) for s in rows]


@router.get('/invoices/{sinv_id}')
def get_invoice(sinv_id: str, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('inv.view'))):
    si = db.get(m.InvSupplierInvoice, sinv_id)
    if si is None or si.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'INV.UNKNOWN_SINVOICE',
                                            'message_ar': 'فاتورة غير موجودة'}})
    return _si_out(db, si)


@router.post('/invoices', status_code=201)
def create_invoice(body: SupplierInvoiceIn, db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('inv.invoice.create'))):
    si = inv.create_supplier_invoice(
        db, tenant_id=pr.tenant_id, actor_id=pr.id,
        supplier_id=body.supplier_id,
        supplier_invoice_no=body.supplier_invoice_no,
        invoice_date=body.invoice_date, po_id=body.po_id, grn_id=body.grn_id,
        tax_amount=body.tax_amount,
        lines=[ln.model_dump() for ln in body.lines])
    db.commit()
    return _si_out(db, si)


@router.post('/invoices/{sinv_id}/approve')
def approve_invoice(sinv_id: str, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('inv.invoice.approve'))):
    si = inv.approve_supplier_invoice(db, tenant_id=pr.tenant_id,
                                      actor_id=pr.id, sinv_id=sinv_id)
    db.commit()
    return _si_out(db, si)


@router.post('/invoices/{sinv_id}/rematch')
def rematch_invoice(sinv_id: str, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('inv.invoice.create'))):
    si = db.get(m.InvSupplierInvoice, sinv_id)
    if si is None or si.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'INV.UNKNOWN_SINVOICE',
                                            'message_ar': 'فاتورة غير موجودة'}})
    if si.status not in ('VARIANCE_HOLD', 'MATCHED'):
        raise HTTPException(409, {'error': {'code': 'INV.SI_STATE',
                                            'message_ar': 'حالة الفاتورة لا تسمح بإعادة المطابقة'}})
    inv._run_three_way_match(db, si, pol=inv.get_policy(db, pr.tenant_id))
    db.commit()
    return _si_out(db, si)


@router.post('/invoices/{sinv_id}/resolve-variance')
def resolve_variance(sinv_id: str, body: VarianceResolveIn,
                     db: Session = Depends(get_db),
                     pr: Principal = Depends(get_principal)):
    lines = ([ln.model_dump() for ln in body.corrected_lines]
             if body.corrected_lines else None)
    if body.action == 'EDIT' and not pr.has('inv.invoice.create'):
        _perm403()
    si = inv.resolve_variance(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                              sinv_id=sinv_id, action=body.action,
                              corrected_lines=lines, actor_perms=pr.perms)
    db.commit()
    return _si_out(db, si)


# ═══════════════ السداد والمرتجعات ═══════════════
@router.get('/payments')
def get_payments(supplier_id: str = '', db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('inv.view'))):
    q = select(m.InvSupplierPayment).where(
        m.InvSupplierPayment.tenant_id == pr.tenant_id)
    if supplier_id:
        q = q.where(m.InvSupplierPayment.supplier_id == supplier_id)
    rows = db.execute(q.order_by(m.InvSupplierPayment.created_at.desc())
                      .limit(300)).scalars().all()
    out = []
    for p in rows:
        sup = db.get(m.InvSupplier, p.supplier_id)
        out.append({'id': p.id, 'pay_no': p.pay_no,
                    'supplier': sup.name if sup else '',
                    'payment_date': str(p.payment_date), 'method': p.method,
                    'account_code': p.account_code, 'amount': D(p.amount),
                    'discount': D(p.discount), 'allocations': p.allocations,
                    'created_by': p.created_by})
    return out


@router.post('/payments', status_code=201)
def create_payment(body: PaymentIn, db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('inv.pay'))):
    p = inv.pay_supplier(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                         supplier_id=body.supplier_id, amount=body.amount,
                         method=body.method, discount=body.discount,
                         payment_date=body.payment_date,
                         allocations=[a.model_dump() for a in body.allocations])
    db.commit()
    return {'id': p.id, 'pay_no': p.pay_no}


def _srt_out(db: Session, srt: m.InvSupplierReturn) -> dict:
    sup = db.get(m.InvSupplier, srt.supplier_id)
    wh = db.get(m.InvWarehouse, srt.warehouse_id)
    lines = db.execute(select(m.InvSRTLine).where(
        m.InvSRTLine.srt_id == srt.id)).scalars().all()
    return {'id': srt.id, 'srt_no': srt.srt_no, 'status': srt.status,
            'supplier': sup.name if sup else '',
            'warehouse': wh.name_ar if wh else '',
            'refund_to': srt.refund_to, 'total': D(srt.total),
            'reason': srt.reason, 'created_at': srt.created_at.isoformat(),
            'lines': [{'item_code': (db.get(m.InvItem, ln.item_id) or
                                     m.InvItem(id='', tenant_id='', code='?',
                                               name_ar='?', category_id='')).code,
                       'qty': D(ln.qty), 'unit_cost': D(ln.unit_cost),
                       'line_total': D(ln.line_total)} for ln in lines]}


@router.get('/returns')
def get_returns(db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('inv.view'))):
    rows = db.execute(select(m.InvSupplierReturn).where(
        m.InvSupplierReturn.tenant_id == pr.tenant_id)
        .order_by(m.InvSupplierReturn.created_at.desc()).limit(300)
    ).scalars().all()
    return [_srt_out(db, r) for r in rows]


@router.post('/returns', status_code=201)
def create_return(body: SupplierReturnIn, db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('inv.return.manage'))):
    srt = inv.create_supplier_return(
        db, tenant_id=pr.tenant_id, actor_id=pr.id,
        supplier_id=body.supplier_id, warehouse_id=body.warehouse_id,
        grn_id=body.grn_id, refund_to=body.refund_to, reason=body.reason,
        lines=[ln.model_dump() for ln in body.lines])
    db.commit()
    return _srt_out(db, srt)


@router.post('/returns/{srt_id}/post')
def post_return(srt_id: str, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('inv.return.manage'))):
    srt = inv.post_supplier_return(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                                   srt_id=srt_id)
    db.commit()
    return _srt_out(db, srt)


# ═══════════════ الصرف والتحويلات ═══════════════
def _issue_out(db: Session, iss: m.InvIssue) -> dict:
    src = db.get(m.InvWarehouse, iss.from_warehouse_id)
    dst = db.get(m.InvWarehouse, iss.to_warehouse_id)
    lines = db.execute(select(m.InvIssueLine).where(
        m.InvIssueLine.issue_id == iss.id)).scalars().all()
    return {'id': iss.id, 'iss_no': iss.iss_no, 'status': iss.status,
            'from_warehouse': src.name_ar if src else '',
            'from_warehouse_id': iss.from_warehouse_id,
            'to_warehouse': dst.name_ar if dst else '',
            'to_warehouse_id': iss.to_warehouse_id,
            'department': iss.department, 'reason': iss.reason,
            'entry_id': iss.entry_id, 'created_by': iss.created_by,
            'created_at': iss.created_at.isoformat(),
            'approved_by': iss.approved_by, 'issued_by': iss.issued_by,
            'lines': [{'item_id': ln.item_id,
                       'item_code': (db.get(m.InvItem, ln.item_id) or
                                     m.InvItem(id='', tenant_id='', code='?',
                                               name_ar='?', category_id='')).code,
                       'qty': D(ln.qty),
                       'unit_cost': D(ln.unit_cost) if ln.unit_cost is not None else None,
                       'line_value': D(ln.line_value) if ln.line_value is not None else None}
                      for ln in lines]}


@router.get('/issues')
def get_issues(status: str = '', db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('inv.view'))):
    q = select(m.InvIssue).where(m.InvIssue.tenant_id == pr.tenant_id)
    if status:
        q = q.where(m.InvIssue.status == status)
    rows = db.execute(q.order_by(m.InvIssue.created_at.desc()).limit(300)
                      ).scalars().all()
    return [_issue_out(db, i) for i in rows]


@router.post('/issues', status_code=201)
def create_issue(body: IssueIn, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('inv.issue.create'))):
    iss = inv.create_issue(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                           from_warehouse_id=body.from_warehouse_id,
                           to_warehouse_id=body.to_warehouse_id,
                           department=body.department, reason=body.reason,
                           lines=[ln.model_dump() for ln in body.lines])
    db.commit()
    return _issue_out(db, iss)


@router.post('/issues/{issue_id}/approve')
def approve_issue(issue_id: str, db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('inv.issue.approve'))):
    iss = inv.approve_issue(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                            issue_id=issue_id, approve=True)
    db.commit()
    return _issue_out(db, iss)


@router.post('/issues/{issue_id}/reject')
def reject_issue(issue_id: str, body: RejectIn,
                 db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('inv.issue.approve'))):
    iss = inv.approve_issue(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                            issue_id=issue_id, approve=False,
                            reason=body.reason)
    db.commit()
    return _issue_out(db, iss)


@router.post('/issues/{issue_id}/execute')
def execute_issue(issue_id: str, db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('inv.issue.approve'))):
    iss = inv.execute_issue(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                            issue_id=issue_id)
    db.commit()
    return _issue_out(db, iss)


def _trf_out(db: Session, trf: m.InvTransfer) -> dict:
    src = db.get(m.InvWarehouse, trf.from_warehouse_id)
    dst = db.get(m.InvWarehouse, trf.to_warehouse_id)
    lines = db.execute(select(m.InvTransferLine).where(
        m.InvTransferLine.transfer_id == trf.id)).scalars().all()
    return {'id': trf.id, 'trf_no': trf.trf_no, 'status': trf.status,
            'from_warehouse': src.name_ar if src else '',
            'from_warehouse_id': trf.from_warehouse_id,
            'to_warehouse': dst.name_ar if dst else '',
            'to_warehouse_id': trf.to_warehouse_id,
            'requires_receive': trf.requires_receive, 'reason': trf.reason,
            'entry_id': trf.entry_id, 'created_by': trf.created_by,
            'created_at': trf.created_at.isoformat(),
            'dispatched_by': trf.dispatched_by, 'received_by': trf.received_by,
            'lines': [{'item_id': ln.item_id,
                       'item_code': (db.get(m.InvItem, ln.item_id) or
                                     m.InvItem(id='', tenant_id='', code='?',
                                               name_ar='?', category_id='')).code,
                       'qty': D(ln.qty),
                       'unit_cost': D(ln.unit_cost) if ln.unit_cost is not None else None}
                      for ln in lines]}


@router.get('/transfers')
def get_transfers(status: str = '', db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('inv.view'))):
    q = select(m.InvTransfer).where(m.InvTransfer.tenant_id == pr.tenant_id)
    if status:
        q = q.where(m.InvTransfer.status == status)
    rows = db.execute(q.order_by(m.InvTransfer.created_at.desc()).limit(300)
                      ).scalars().all()
    return [_trf_out(db, t) for t in rows]


@router.post('/transfers', status_code=201)
def create_transfer(body: TransferIn, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('inv.transfer.manage'))):
    trf = inv.create_transfer(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                              from_warehouse_id=body.from_warehouse_id,
                              to_warehouse_id=body.to_warehouse_id,
                              reason=body.reason,
                              requires_receive=body.requires_receive,
                              lines=[ln.model_dump() for ln in body.lines])
    db.commit()
    return _trf_out(db, trf)


@router.post('/transfers/{trf_id}/dispatch')
def dispatch_transfer(trf_id: str, db: Session = Depends(get_db),
                      pr: Principal = Depends(require_perm('inv.transfer.manage'))):
    trf = inv.dispatch_transfer(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                                transfer_id=trf_id)
    db.commit()
    return _trf_out(db, trf)


@router.post('/transfers/{trf_id}/receive')
def receive_transfer(trf_id: str, db: Session = Depends(get_db),
                     pr: Principal = Depends(require_perm('inv.transfer.manage'))):
    trf = inv.receive_transfer(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                               transfer_id=trf_id)
    db.commit()
    return _trf_out(db, trf)


@router.post('/transfers/{trf_id}/cancel')
def cancel_transfer(trf_id: str, body: RejectIn,
                    db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('inv.transfer.manage'))):
    trf = inv.cancel_transfer(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                              transfer_id=trf_id, reason=body.reason)
    db.commit()
    return _trf_out(db, trf)


# ═══════════════ الهالك ═══════════════
def _wst_out(db: Session, wst: m.InvWaste) -> dict:
    wh = db.get(m.InvWarehouse, wst.warehouse_id)
    lines = db.execute(select(m.InvWasteLine).where(
        m.InvWasteLine.waste_id == wst.id)).scalars().all()
    return {'id': wst.id, 'wst_no': wst.wst_no, 'status': wst.status,
            'warehouse': wh.name_ar if wh else '',
            'warehouse_id': wst.warehouse_id, 'reason': wst.reason,
            'photo_ref': wst.photo_ref, 'total_value': D(wst.total_value),
            'entry_id': wst.entry_id, 'created_by': wst.created_by,
            'created_at': wst.created_at.isoformat(),
            'approved_by': wst.approved_by, 'reject_reason': wst.reject_reason,
            'lines': [{'item_id': ln.item_id,
                       'item_code': (db.get(m.InvItem, ln.item_id) or
                                     m.InvItem(id='', tenant_id='', code='?',
                                               name_ar='?', category_id='')).code,
                       'qty': D(ln.qty), 'unit_cost': D(ln.unit_cost),
                       'line_value': D(ln.line_value),
                       'line_reason': ln.line_reason} for ln in lines]}


@router.get('/waste')
def get_waste(status: str = '', db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('inv.view'))):
    q = select(m.InvWaste).where(m.InvWaste.tenant_id == pr.tenant_id)
    if status:
        q = q.where(m.InvWaste.status == status)
    rows = db.execute(q.order_by(m.InvWaste.created_at.desc()).limit(300)
                      ).scalars().all()
    return [_wst_out(db, w) for w in rows]


@router.post('/waste', status_code=201)
def create_waste(body: WasteIn, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('inv.waste.create'))):
    wst = inv.create_waste(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                           warehouse_id=body.warehouse_id, reason=body.reason,
                           photo_ref=body.photo_ref,
                           lines=[ln.model_dump() for ln in body.lines])
    db.commit()
    return _wst_out(db, wst)


@router.post('/waste/{wst_id}/submit')
def submit_waste(wst_id: str, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('inv.waste.create'))):
    wst = inv.submit_waste(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                           waste_id=wst_id)
    db.commit()
    return _wst_out(db, wst)


@router.post('/waste/{wst_id}/approve')
def approve_waste(wst_id: str, db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('inv.waste.approve'))):
    wst = inv.approve_waste(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                            waste_id=wst_id, approve=True)
    db.commit()
    return _wst_out(db, wst)


@router.post('/waste/{wst_id}/reject')
def reject_waste(wst_id: str, body: RejectIn,
                 db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('inv.waste.approve'))):
    wst = inv.approve_waste(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                            waste_id=wst_id, approve=False, reason=body.reason)
    db.commit()
    return _wst_out(db, wst)


# ═══════════════ الجرد ═══════════════
def _cnt_out(db: Session, cnt: m.InvCount, detail: bool = True) -> dict:
    wh = db.get(m.InvWarehouse, cnt.warehouse_id)
    out = {'id': cnt.id, 'cnt_no': cnt.cnt_no, 'status': cnt.status,
           'warehouse': wh.name_ar if wh else '',
           'warehouse_id': cnt.warehouse_id, 'category_id': cnt.category_id,
           'short_value': D(cnt.short_value), 'over_value': D(cnt.over_value),
           'short_entry_id': cnt.short_entry_id,
           'over_entry_id': cnt.over_entry_id,
           'created_by': cnt.created_by,
           'created_at': cnt.created_at.isoformat(),
           'counted_by': cnt.counted_by,
           'approved1_by': cnt.approved1_by,
           'approved2_by': cnt.approved2_by,
           'posted_at': cnt.posted_at.isoformat() if cnt.posted_at else None}
    if detail:
        lines = db.execute(select(m.InvCountLine).where(
            m.InvCountLine.count_id == cnt.id)).scalars().all()
        out['lines'] = [{
            'item_id': ln.item_id,
            'item_code': (db.get(m.InvItem, ln.item_id) or
                          m.InvItem(id='', tenant_id='', code='?',
                                    name_ar='?', category_id='')).code,
            'item_name': (db.get(m.InvItem, ln.item_id) or
                          m.InvItem(id='', tenant_id='', code='?',
                                    name_ar='?', category_id='')).name_ar,
            'system_qty': D(ln.system_qty),
            'counted_qty': D(ln.counted_qty) if ln.counted_qty is not None else None,
            'unit_cost': D(ln.unit_cost),
            'variance_qty': D(ln.variance_qty) if ln.variance_qty is not None else None,
            'variance_value': D(ln.variance_value) if ln.variance_value is not None else None}
            for ln in lines]
    return out


@router.get('/counts')
def get_counts(status: str = '', db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('inv.view'))):
    q = select(m.InvCount).where(m.InvCount.tenant_id == pr.tenant_id)
    if status:
        q = q.where(m.InvCount.status == status)
    rows = db.execute(q.order_by(m.InvCount.created_at.desc()).limit(200)
                      ).scalars().all()
    return [_cnt_out(db, c, detail=False) for c in rows]


@router.get('/counts/{cnt_id}')
def get_count(cnt_id: str, db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('inv.view'))):
    cnt = db.get(m.InvCount, cnt_id)
    if cnt is None or cnt.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'INV.UNKNOWN_COUNT',
                                            'message_ar': 'جرد غير موجود'}})
    return _cnt_out(db, cnt)


@router.post('/counts', status_code=201)
def create_count(body: CountIn, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('inv.count.manage'))):
    cnt = inv.create_count(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                           warehouse_id=body.warehouse_id,
                           category_id=body.category_id)
    db.commit()
    return _cnt_out(db, cnt)


@router.post('/counts/{cnt_id}/enter')
def enter_count(cnt_id: str, body: CountEntryIn,
                db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('inv.count.manage'))):
    cnt = inv.enter_count(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                          count_id=cnt_id,
                          counted=[c.model_dump() for c in body.counted])
    db.commit()
    return _cnt_out(db, cnt)


@router.post('/counts/{cnt_id}/finish')
def finish_count(cnt_id: str, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('inv.count.manage'))):
    cnt = inv.finish_count(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                           count_id=cnt_id)
    db.commit()
    return _cnt_out(db, cnt)


@router.post('/counts/{cnt_id}/approve')
def approve_count(cnt_id: str, body: CountApproveIn,
                  db: Session = Depends(get_db),
                  pr: Principal = Depends(get_principal)):
    cnt = inv.approve_count(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                            count_id=cnt_id, level=body.level,
                            actor_perms=pr.perms)
    db.commit()
    return _cnt_out(db, cnt)


@router.post('/counts/{cnt_id}/cancel')
def cancel_count(cnt_id: str, body: RejectIn,
                 db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('inv.count.manage'))):
    cnt = inv.cancel_count(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                           count_id=cnt_id, reason=body.reason)
    db.commit()
    return _cnt_out(db, cnt)


# ═══════════════ التقارير والتنبيهات والسياسة ═══════════════
@router.get('/reports/stock-value')
def rpt_stock_value(warehouse_id: str = '', as_of: date | None = None,
                    db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('inv.reports'))):
    return inv.valued_stock_report(db, pr.tenant_id,
                                   warehouse_id=warehouse_id or None,
                                   as_of=as_of)


@router.get('/reports/reconciliation')
def rpt_reconciliation(db: Session = Depends(get_db),
                       pr: Principal = Depends(require_perm('inv.reports'))):
    return inv.reconciliation_check(db, pr.tenant_id)


@router.get('/reports/moves')
def rpt_moves(warehouse_id: str = '', item_id: str = '', reason: str = '',
              date_from: date | None = None, date_to: date | None = None,
              db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('inv.reports'))):
    return inv.moves_report(db, pr.tenant_id, warehouse_id=warehouse_id,
                            item_id=item_id, reason=reason,
                            date_from=date_from, date_to=date_to)


@router.get('/reports/purchases')
def rpt_purchases(date_from: date = Query(...), date_to: date = Query(...),
                  db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('inv.reports'))):
    return inv.purchases_report(db, pr.tenant_id, date_from, date_to)


@router.get('/reports/suppliers')
def rpt_suppliers(db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('inv.reports'))):
    return inv.supplier_performance(db, pr.tenant_id)


@router.get('/reports/ppv')
def rpt_ppv(date_from: date = Query(...), date_to: date = Query(...),
            db: Session = Depends(get_db),
            pr: Principal = Depends(require_perm('inv.reports'))):
    return inv.ppv_report(db, pr.tenant_id, date_from, date_to)


@router.get('/reports/waste')
def rpt_waste(months: int = 6, db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('inv.reports'))):
    return {'months': inv.waste_report(db, pr.tenant_id, months=months)}


@router.get('/reports/consumption')
def rpt_consumption(date_from: date = Query(...), date_to: date = Query(...),
                    db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('inv.reports'))):
    return inv.consumption_report(db, pr.tenant_id, date_from, date_to)


@router.get('/alerts')
def get_alerts(db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('inv.alerts'))):
    recon = inv.reconciliation_check(db, pr.tenant_id)
    return {'reorder': inv.reorder_alerts(db, pr.tenant_id),
            'expiry': inv.expiry_alerts(db, pr.tenant_id),
            'stagnant': inv.stagnant_alerts(db, pr.tenant_id),
            'ledger_mismatch': recon['alerts'],
            'ledger_ok': recon['ok']}


@router.get('/settings/policy')
def get_policy_view(db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('inv.view'))):
    p = inv.get_policy(db, pr.tenant_id)
    db.commit()
    return {'po_l0_limit': D(p.po_l0_limit), 'po_l1_limit': D(p.po_l1_limit),
            'price_tolerance_pct': D(p.price_tolerance_pct),
            'qty_tolerance_pct': D(p.qty_tolerance_pct),
            'expiry_windows': p.expiry_windows,
            'stagnant_days': p.stagnant_days,
            'consumption_days': p.consumption_days,
            'updated_by': p.updated_by,
            'updated_at': p.updated_at.isoformat() if p.updated_at else None}


@router.put('/settings/policy')
def put_policy(body: PolicyIn, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('inv.policy.manage'))):
    p = inv.update_policy(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                          changes=body.model_dump(exclude_unset=True))
    db.commit()
    return {'po_l0_limit': D(p.po_l0_limit), 'po_l1_limit': D(p.po_l1_limit),
            'price_tolerance_pct': D(p.price_tolerance_pct),
            'qty_tolerance_pct': D(p.qty_tolerance_pct),
            'expiry_windows': p.expiry_windows,
            'stagnant_days': p.stagnant_days,
            'consumption_days': p.consumption_days}
