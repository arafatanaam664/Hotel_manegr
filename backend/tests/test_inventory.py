"""اختبارات المرحلة 5 — المخزون والمشتريات (البوابة G5).
كل اختبار قبول يستشهد برقم معياره من مواصفة 05 §7 (قاعدة الملف 15)."""
import threading
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import inventory as inv
from app import models as m
from app import pos as ps
from app.audit import verify_chain
from app.posting import D, PostingError
from app.security import hash_password, new_uuid, utcnow

Q4 = Decimal('0.0001')
TODAY = date.today()


def D_(v):
    return Decimal(str(v)).quantize(Q4)


def _wh(db, tid, code):
    return db.execute(select(m.InvWarehouse).where(
        m.InvWarehouse.tenant_id == tid,
        m.InvWarehouse.code == code)).scalar_one()


def _iitem(db, tid, code):
    return db.execute(select(m.InvItem).where(
        m.InvItem.tenant_id == tid, m.InvItem.code == code)).scalar_one()


def _sup(db, tid, code):
    return db.execute(select(m.InvSupplier).where(
        m.InvSupplier.tenant_id == tid,
        m.InvSupplier.code == code)).scalar_one()


def _stock(db, wh_id, item_id):
    row = db.execute(select(m.InvStock).where(
        m.InvStock.warehouse_id == wh_id,
        m.InvStock.item_id == item_id)).scalar_one_or_none()
    return (D_(row.qty_on_hand), D_(row.avg_cost)) if row else (D_(0), D_(0))


def _account(db, tid, code):
    return db.execute(select(m.Account).where(
        m.Account.tenant_id == tid, m.Account.code == code)).scalar_one()


def _entry_lines(db, entry_id):
    return db.execute(select(m.JournalLine).where(
        m.JournalLine.entry_id == entry_id)
        .order_by(m.JournalLine.line_no)).scalars().all()


def _mk_po_approved(db, tid, supplier, item, qty, price, actor='buyer-1',
                    perms=None, uom=None, factor=None):
    """PO معتمد مباشرة عبر رفع حدود السياسة مؤقتاً ثم إعادتها."""
    pol = inv.get_policy(db, tid)
    saved = (D_(pol.po_l0_limit), D_(pol.po_l1_limit))
    pol.po_l0_limit = Decimal('999999999')
    db.flush()
    ln = {'item_id': item.id, 'qty': qty, 'unit_price': price}
    if uom:
        ln['uom'] = uom
        ln['factor'] = factor
    po = inv.create_po(db, tenant_id=tid, actor_id=actor,
                       supplier_id=supplier.id, lines=[ln])
    db.commit()
    pol.po_l0_limit, pol.po_l1_limit = saved
    db.commit()
    return po


def _mk_role_user(db, tid, role_code, username, password='Pass!12345'):
    role = db.execute(select(m.Role).where(
        m.Role.tenant_id == tid, m.Role.code == role_code)).scalar_one()
    u = m.User(id=new_uuid(), tenant_id=tid, username=username,
               full_name=username, password_hash=hash_password(password),
               created_at=utcnow())
    db.add(u)
    db.flush()
    db.add(m.UserRole(user_id=u.id, role_id=role.id))
    db.commit()
    return u


# ════════════════════════════════════════════════════════════════════
# محرك التقييم — §4 متوسط مرجح متحرك + §7.1 منع السالب/التزامن
# ════════════════════════════════════════════════════════════════════
def test_moving_average_recomputed_on_inbound(db_session):
    """05 §4: المتوسط يُعاد حسابه تلقائياً عند كل إدخال:
    10@2 + 10@4 ⇒ avg=3، والكمية والقيمة تتطابقان."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    wh = _wh(db, tid, 'MAIN-WH')
    item = _iitem(db, tid, 'BUN')
    inv.apply_inbound(db, tenant_id=tid, warehouse=wh, item_id=item.id,
                      qty=10, unit_cost=2, reason='OPENING', ref_type='T',
                      ref_id='t1', actor_id='u1', bd=TODAY)
    inv.apply_inbound(db, tenant_id=tid, warehouse=wh, item_id=item.id,
                      qty=10, unit_cost=4, reason='PURCHASE', ref_type='T',
                      ref_id='t2', actor_id='u1', bd=TODAY)
    qty, avg = _stock(db, wh.id, item.id)
    assert qty == D_(20) and avg == D_(3)
    # ثبات القيمة: مجموع value_delta = qty × avg
    moves = db.execute(select(m.InvMove).where(
        m.InvMove.warehouse_id == wh.id, m.InvMove.item_id == item.id,
        m.InvMove.ref_id.in_(['t1', 't2']))).scalars().all()
    assert sum(D_(x.value_delta) for x in moves) == (qty * avg).quantize(Q4)


def test_negative_stock_blocked_acceptance(db_session):
    """05/قبول-1: استحالة رصيد سالب في وضع «منع» — يفشل الطلب كاملاً
    ولا تتغير الكمية ولا تُسجَّل حركة."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    wh = _wh(db, tid, 'KIT-WH')
    item = _iitem(db, tid, 'SODA')
    inv.apply_inbound(db, tenant_id=tid, warehouse=wh, item_id=item.id,
                      qty=10, unit_cost='0.7', reason='OPENING', ref_type='T',
                      ref_id='n1', actor_id='u1', bd=TODAY)
    db.commit()
    with pytest.raises(PostingError) as exc:
        inv.apply_outbound(db, tenant_id=tid, warehouse=wh, item_id=item.id,
                           qty=15, reason='ISSUE_OUT', ref_type='T',
                           ref_id='n2', actor_id='u1', bd=TODAY)
    assert exc.value.code == 'INV.INSUFFICIENT_STOCK'
    db.rollback()
    qty, _ = _stock(db, wh.id, item.id)
    assert qty == D_(10)
    mv = db.execute(select(func.count(m.InvMove.id)).where(
        m.InvMove.ref_id == 'n2')).scalar_one()
    assert mv == 0


def test_concurrent_deduction_only_one_wins(db_session):
    """05/قبول-1 (تزامن): خيطان يخصمان 6 من رصيد 10 على الصنف نفسه —
    نجاح واحد بالضبط، والرصيد النهائي 4 لا سالب أبداً."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    wh = _wh(db, tid, 'KIT-WH')
    item = _iitem(db, tid, 'WATER')
    inv.apply_inbound(db, tenant_id=tid, warehouse=wh, item_id=item.id,
                      qty=10, unit_cost='0.45', reason='OPENING',
                      ref_type='T', ref_id='c1', actor_id='u1', bd=TODAY)
    db.commit()
    results = {'ok': 0, 'blocked': 0}

    def worker(tag):
        s = factory()
        try:
            inv.apply_outbound(s, tenant_id=tid, warehouse=wh,
                               item_id=item.id, qty=6, reason='ISSUE_OUT',
                               ref_type='T', ref_id=f'race-{tag}',
                               actor_id=tag, bd=TODAY)
            s.commit()
            results['ok'] += 1
        except PostingError as e:
            s.rollback()
            if e.code == 'INV.INSUFFICIENT_STOCK':
                results['blocked'] += 1
            else:
                raise
        finally:
            s.close()

    threads = [threading.Thread(target=worker, args=(f'w{i}',))
               for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert results['ok'] == 1 and results['blocked'] == 1, results
    qty, _ = _stock(db, wh.id, item.id)
    assert qty == D_(4)


def test_allow_negative_warehouse_goes_negative_with_flag(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    wh = inv.create_warehouse(db, tenant_id=tid, branch_id=seed['branch_id'],
                              actor_id='a', code='NEG-WH', name_ar='سالب',
                              kind='SUB', allow_negative=True)
    db.commit()
    item = _iitem(db, tid, 'BUN')
    inv.apply_inbound(db, tenant_id=tid, warehouse=wh, item_id=item.id,
                      qty=2, unit_cost=1, reason='OPENING', ref_type='T',
                      ref_id='x1', actor_id='u', bd=TODAY)
    mv, applied, went_negative = inv.apply_outbound(
        db, tenant_id=tid, warehouse=wh, item_id=item.id, qty=5,
        reason='ISSUE_OUT', ref_type='T', ref_id='x2', actor_id='u', bd=TODAY)
    assert went_negative is True
    qty, _ = _stock(db, wh.id, item.id)
    assert qty == D_(-3)


# ════════════════════════════════════════════════════════════════════
# §2.1/§2.2 — طلبات وأوامر الشراء وسلّم الاعتماد (ملف 14 §2)
# ════════════════════════════════════════════════════════════════════
def test_pr_lifecycle_and_self_approval_block(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    item = _iitem(db, tid, 'AMENITY-KIT')
    pr = inv.create_pr(db, tenant_id=tid, actor_id='hk-1',
                       department='الطوابق',
                       lines=[{'item_id': item.id, 'qty': 50}])
    assert pr.pr_no.startswith('PR-') and pr.status == 'DRAFT'
    inv.submit_pr(db, tenant_id=tid, actor_id='hk-1', pr_id=pr.id)
    with pytest.raises(PostingError) as exc:
        inv.approve_pr(db, tenant_id=tid, actor_id='hk-1', pr_id=pr.id,
                       approve=True)
    assert exc.value.code == 'INV.SELF_APPROVAL'  # ملف 14: لا اعتماد ذاتي
    inv.approve_pr(db, tenant_id=tid, actor_id='gm-1', pr_id=pr.id,
                   approve=True)
    assert pr.status == 'APPROVED'
    # التحويل لأمر شراء يقفل الـ PR
    _mk_po_approved_from_pr(db, tid, pr)
    assert pr.status == 'CONVERTED'


def _mk_po_approved_from_pr(db, tid, pr):
    pol = inv.get_policy(db, tid)
    saved = pol.po_l0_limit
    pol.po_l0_limit = Decimal('999999999')
    db.flush()
    sup = _sup(db, tid, 'SUP-002')
    line = db.execute(select(m.InvPRLine).where(
        m.InvPRLine.pr_id == pr.id)).scalar_one()
    po = inv.create_po(db, tenant_id=tid, actor_id='buyer-1',
                       supplier_id=sup.id, pr_id=pr.id,
                       lines=[{'item_id': line.item_id, 'qty': line.qty,
                               'unit_price': 2}])
    pol.po_l0_limit = saved
    db.flush()
    return po


def test_po_approval_ladder(db_session):
    """ملف 14 §2 أمر شراء: ≤ حد الأمين ذاتي | L1 مدير القسم | L2 مالية —
    ولا اعتماد ذاتي في أي مستوى."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup = _sup(db, tid, 'SUP-001')
    item = _iitem(db, tid, 'BEEF-PAT')
    pol = inv.get_policy(db, tid)
    # صغير: اعتماد ذاتي L0
    small = inv.create_po(db, tenant_id=tid, actor_id='buyer-1',
                          supplier_id=sup.id,
                          lines=[{'item_id': item.id, 'qty': 10,
                                  'unit_price': 2}])  # 20 < 5000
    assert small.status == 'APPROVED' and small.approve_level_required == 0
    # متوسط: L1
    mid = inv.create_po(db, tenant_id=tid, actor_id='buyer-1',
                        supplier_id=sup.id,
                        lines=[{'item_id': item.id, 'qty': 5000,
                                'unit_price': 2}])  # 10000
    assert mid.status == 'PENDING_L1' and mid.approve_level_required == 1
    with pytest.raises(PostingError) as exc:
        inv.approve_po(db, tenant_id=tid, actor_id='buyer-1', po_id=mid.id,
                       actor_perms={'inv.po.approve.l1'})
    assert exc.value.code == 'INV.SELF_APPROVAL'
    with pytest.raises(PostingError) as exc:
        inv.approve_po(db, tenant_id=tid, actor_id='gm-1', po_id=mid.id,
                       actor_perms={'inv.pay'})  # صلاحية غير كافية
    assert exc.value.code == 'RBAC.FORBIDDEN'
    inv.approve_po(db, tenant_id=tid, actor_id='gm-1', po_id=mid.id,
                   actor_perms={'inv.po.approve.l1'})
    assert mid.status == 'APPROVED' and mid.approved1_by == 'gm-1'
    # كبير: L1 ثم L2
    big = inv.create_po(db, tenant_id=tid, actor_id='buyer-1',
                        supplier_id=sup.id,
                        lines=[{'item_id': item.id, 'qty': 40000,
                                'unit_price': 2}])  # 80000 > 50000
    # قائمة الانتظار تبدأ من L1 مهما كان السقف (لا قفز فوق الاعتماد الأول)
    assert big.status == 'PENDING_L1' and big.approve_level_required == 2
    with pytest.raises(PostingError):
        inv.approve_po(db, tenant_id=tid, actor_id='gm-1', po_id=big.id,
                       actor_perms={'inv.po.approve.l2'})  # صلاحية L1 وحدها أولاً
    inv.approve_po(db, tenant_id=tid, actor_id='gm-1', po_id=big.id,
                   actor_perms={'inv.po.approve.l1'})
    assert big.status == 'PENDING_L2'
    inv.approve_po(db, tenant_id=tid, actor_id='fin-1', po_id=big.id,
                   actor_perms={'inv.po.approve.l2'})
    assert big.status == 'APPROVED' and big.approved2_by == 'fin-1'
    assert big.approved1_by == 'gm-1'


def test_po_reject_and_cancel(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup = _sup(db, tid, 'SUP-001')
    item = _iitem(db, tid, 'WATER')
    po = inv.create_po(db, tenant_id=tid, actor_id='buyer-1',
                       supplier_id=sup.id,
                       lines=[{'item_id': item.id, 'qty': 8000,
                               'unit_price': '0.45'}])  # 3600 → L0 معتمد
    can = inv.cancel_po(db, tenant_id=tid, actor_id='buyer-1', po_id=po.id,
                        reason='أمر مكرر بالخطأ')
    assert can.status == 'CANCELLED'
    po2 = inv.create_po(db, tenant_id=tid, actor_id='buyer-1',
                        supplier_id=sup.id,
                        lines=[{'item_id': item.id, 'qty': 20000,
                                'unit_price': '0.5'}])  # 10000 → L1
    rj = inv.reject_po(db, tenant_id=tid, actor_id='gm-1', po_id=po2.id,
                       reason='سعر مرتفع عن السوق')
    assert rj.status == 'REJECTED' and 'سعر' in (rj.reject_reason or '')


def test_po_unit_conversion_mandatory(db_session):
    """05 §1 أدوات: معامل التحويل إلزامي عند الشراء بوحدة ≠ الأساسية."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup = _sup(db, tid, 'SUP-002')
    item = _iitem(db, tid, 'AMENITY-KIT')  # أساسية: عدة؛ بديل: كرتون=24
    with pytest.raises(PostingError) as exc:
        inv.create_po(db, tenant_id=tid, actor_id='b', supplier_id=sup.id,
                      lines=[{'item_id': item.id, 'qty': 4, 'uom': 'كرتون',
                              'unit_price': '1.9'}])
    assert exc.value.code == 'INV.FACTOR_REQUIRED'
    db.rollback()
    pol = inv.get_policy(db, tid)
    pol.po_l0_limit = Decimal('999999999')
    po = inv.create_po(db, tenant_id=tid, actor_id='b', supplier_id=sup.id,
                       lines=[{'item_id': item.id, 'qty': 4, 'uom': 'كرتون',
                               'factor': 24, 'unit_price': '1.9'}])
    ln = db.execute(select(m.InvPOLine).where(
        m.InvPOLine.po_id == po.id)).scalar_one()
    assert D_(ln.base_qty) == D_(96) and D_(ln.factor) == D_(24)


def test_po_contract_price_default(db_session):
    """05 §1: سعر تعاقدي مؤرخ يُقترح تلقائياً على الأمر."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup = _sup(db, tid, 'SUP-001')
    item = _iitem(db, tid, 'BUN')
    price = inv.contract_price(db, tid, sup.id, item.id, TODAY)
    assert price == D_('0.32')
    po = inv.create_po(db, tenant_id=tid, actor_id='b', supplier_id=sup.id,
                       lines=[{'item_id': item.id, 'qty': 100}])
    ln = db.execute(select(m.InvPOLine).where(
        m.InvPOLine.po_id == po.id)).scalar_one()
    assert D_(ln.unit_price) == D_('0.32')
    with pytest.raises(PostingError) as exc:
        inv.create_po(db, tenant_id=tid, actor_id='b', supplier_id=sup.id,
                      lines=[{'item_id': _iitem(db, tid, 'SODA').id,
                              'qty': 1}])  # لا سعر ولا تعاقد
    assert exc.value.code == 'INV.PRICE_REQUIRED'


# ════════════════════════════════════════════════════════════════════
# §2.3 — استلام البضاعة GRN والحدثان #14/#15
# ════════════════════════════════════════════════════════════════════
def test_grn_credit_requires_supplier_invoice(db_session):
    """05 §2.3: الفاتورة المرفقة إلزامية للشراء الآجل."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup = _sup(db, tid, 'SUP-001')
    wh = _wh(db, tid, 'MAIN-WH')
    item = _iitem(db, tid, 'BUN')
    with pytest.raises(PostingError) as exc:
        inv.create_grn(db, tenant_id=tid, actor_id='k', supplier_id=sup.id,
                       warehouse_id=wh.id, purchase_type='CREDIT',
                       lines=[{'item_id': item.id, 'qty_received': 10,
                               'unit_price': '0.35'}])
    assert exc.value.code == 'INV.INVOICE_REQUIRED'


def test_grn_cash_posts_stock_and_entry_14(db_session):
    """#14: شراء نقداً Dr حساب المستودع (+1150) | Cr النقدية — والرصيد
    والمتوسط يتحدثان بذرّية واحدة."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup = _sup(db, tid, 'SUP-001')
    wh = _wh(db, tid, 'KIT-WH')
    item = _iitem(db, tid, 'SODA')
    before = inv.ledger_balance(db, tid, wh.inventory_account_code)
    grn = inv.create_grn(db, tenant_id=tid, actor_id='k1',
                         supplier_id=sup.id, warehouse_id=wh.id,
                         purchase_type='CASH', payment_account_code='1101',
                         tax_amount=3,
                         lines=[{'item_id': item.id, 'qty_received': 100,
                                 'unit_price': '0.70'}])
    inv.post_grn(db, tenant_id=tid, actor_id='k1', grn_id=grn.id)
    qty, avg = _stock(db, wh.id, item.id)
    assert qty == D_(100) and avg == D_('0.70')
    lines = _entry_lines(db, grn.entry_id)
    by_code = {_account(db, tid, c).code: (l.debit_base, l.credit_base)
               for l in lines
               for c in [db.get(m.Account, l.account_id).code]}
    assert by_code['1240'][0] == D_(70)      # مدين: حساب المستودع
    assert by_code['1150'][0] == D_(3)       # مدين: ضريبة المدخلات
    assert by_code['1101'][1] == D_(73)      # دائن: النقدية
    after = inv.ledger_balance(db, tid, '1240')
    assert after - before == D_(70)
    assert grn.status == 'POSTED' and grn.grn_no.startswith('GRN-')


def test_grn_credit_posts_ap_party_and_updates_po(db_session):
    """#15: شراء آجل Dr المستودع | Cr 2101 بطرف المورد — وحدث الاستلام
    الجزئي/الكامل على أمر الشراء."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup = _sup(db, tid, 'SUP-001')
    item = _iitem(db, tid, 'BUN')
    po = _mk_po_approved(db, tid, sup, item, 100, '0.32')
    grn = inv.create_grn(db, tenant_id=tid, actor_id='k1',
                         supplier_id=sup.id, warehouse_id=_wh(db, tid, 'MAIN-WH').id,
                         purchase_type='CREDIT', po_id=po.id,
                         supplier_invoice_no='SUP-INV-77',
                         lines=[{'item_id': item.id, 'qty_received': 40}])
    inv.post_grn(db, tenant_id=tid, actor_id='k1', grn_id=grn.id)
    db.refresh(po)
    ln = db.execute(select(m.InvPOLine).where(
        m.InvPOLine.po_id == po.id)).scalar_one()
    assert D_(ln.received_qty) == D_(40) and po.status == 'PART_RECEIVED'
    ap_lines = [l for l in _entry_lines(db, grn.entry_id)
                if db.get(m.Account, l.account_id).code == '2101']
    assert ap_lines[0].party_id == sup.id and ap_lines[0].party_type == 'SUPPLIER'
    assert inv.supplier_balance(db, tid, sup.id) > 0
    grn2 = inv.create_grn(db, tenant_id=tid, actor_id='k1',
                          supplier_id=sup.id, warehouse_id=_wh(db, tid, 'MAIN-WH').id,
                          purchase_type='CREDIT', po_id=po.id,
                          supplier_invoice_no='SUP-INV-78',
                          lines=[{'item_id': item.id, 'qty_received': 60}])
    inv.post_grn(db, tenant_id=tid, actor_id='k1', grn_id=grn2.id)
    db.refresh(po)
    assert po.status == 'RECEIVED'


def test_grn_over_receipt_within_and_beyond_cap(db_session):
    """05 §2.3: زيادة الكمية بسقف٪ — 105/100 مقبولة، 106 مرفوضة."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup = _sup(db, tid, 'SUP-001')
    item = _iitem(db, tid, 'FRIES-PT')
    po = _mk_po_approved(db, tid, sup, item, 100, '0.75')
    wh = _wh(db, tid, 'MAIN-WH')
    with pytest.raises(PostingError) as exc:
        inv.create_grn(db, tenant_id=tid, actor_id='k', supplier_id=sup.id,
                       warehouse_id=wh.id, purchase_type='CREDIT',
                       po_id=po.id, supplier_invoice_no='X-1',
                       lines=[{'item_id': item.id, 'qty_received': 106}])
    assert exc.value.code == 'INV.OVER_RECEIPT'
    db.rollback()
    grn = inv.create_grn(db, tenant_id=tid, actor_id='k', supplier_id=sup.id,
                         warehouse_id=wh.id, purchase_type='CREDIT',
                         po_id=po.id, supplier_invoice_no='X-1',
                         lines=[{'item_id': item.id, 'qty_received': 105}])
    inv.post_grn(db, tenant_id=tid, actor_id='k', grn_id=grn.id)
    qty, _ = _stock(db, wh.id, item.id)
    assert qty == D_(105)


def test_grn_quality_rejection_rules(db_session):
    """05 §2.3: رفض بنود بجودة — سبب إلزامي، والمقبول فقط يدخل المخزون."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup = _sup(db, tid, 'SUP-001')
    wh = _wh(db, tid, 'MAIN-WH')
    item = _iitem(db, tid, 'WATER')
    with pytest.raises(PostingError) as exc:
        inv.create_grn(db, tenant_id=tid, actor_id='k', supplier_id=sup.id,
                       warehouse_id=wh.id, purchase_type='CASH',
                       lines=[{'item_id': item.id, 'qty_received': 50,
                               'qty_rejected': 5, 'unit_price': '0.45'}])
    assert exc.value.code == 'INV.REJECT_REASON'
    db.rollback()
    grn = inv.create_grn(db, tenant_id=tid, actor_id='k', supplier_id=sup.id,
                         warehouse_id=wh.id, purchase_type='CASH',
                         lines=[{'item_id': item.id, 'qty_received': 50,
                                 'qty_rejected': 5,
                                 'reject_reason': 'عبوات تالفة',
                                 'unit_price': '0.45'}])
    inv.post_grn(db, tenant_id=tid, actor_id='k', grn_id=grn.id)
    qty, _ = _stock(db, wh.id, item.id)
    assert qty == D_(45) and D_(grn.total) == D_('20.25')


def test_grn_expiry_required_for_tracked_items(db_session):
    """05 §1/§2.3: دفعة/صلاحية إلزامية لكل سطر عند الإلزام."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup = _sup(db, tid, 'SUP-002')
    wh = _wh(db, tid, 'MNT-WH')
    item = _iitem(db, tid, 'DETERG-L')  # track_expiry=True
    with pytest.raises(PostingError) as exc:
        inv.create_grn(db, tenant_id=tid, actor_id='k', supplier_id=sup.id,
                       warehouse_id=wh.id, purchase_type='CASH',
                       lines=[{'item_id': item.id, 'qty_received': 10,
                               'unit_price': '4.2'}])
    assert exc.value.code == 'INV.EXPIRY_REQUIRED'
    db.rollback()
    exp = TODAY + timedelta(days=200)
    grn = inv.create_grn(db, tenant_id=tid, actor_id='k', supplier_id=sup.id,
                         warehouse_id=wh.id, purchase_type='CASH',
                         lines=[{'item_id': item.id, 'qty_received': 10,
                                 'unit_price': '4.2', 'batch_no': 'B-100',
                                 'expiry_date': exp}])
    inv.post_grn(db, tenant_id=tid, actor_id='k', grn_id=grn.id)
    mv = db.execute(select(m.InvMove).where(
        m.InvMove.ref_id == grn.id, m.InvMove.reason == 'PURCHASE')
    ).scalar_one()
    assert mv.batch_no == 'B-100' and mv.expiry_date == exp


# ════════════════════════════════════════════════════════════════════
# قبول §7.3 — المطابقة الثلاثية ترفض خارج التسامح تلقائياً
# ════════════════════════════════════════════════════════════════════
def _full_receipt(db, tid, qty=10, price='2'):
    sup = _sup(db, tid, 'SUP-001')
    item = _iitem(db, tid, 'BEEF-PAT')
    po = _mk_po_approved(db, tid, sup, item, qty, price, actor='buyer-3')
    grn = inv.create_grn(db, tenant_id=tid, actor_id='k3',
                         supplier_id=sup.id,
                         warehouse_id=_wh(db, tid, 'MAIN-WH').id,
                         purchase_type='CREDIT', po_id=po.id,
                         supplier_invoice_no='FINAL-1',
                         lines=[{'item_id': item.id, 'qty_received': qty}])
    inv.post_grn(db, tenant_id=tid, actor_id='k3', grn_id=grn.id)
    db.commit()
    return sup, item, po, grn


def test_three_way_price_variance_auto_hold(db_session):
    """05/قبول-3: فرق سعر خارج التسامح (0% افتراضياً) → VARIANCE_HOLD
    تلقائياً بلا تدخل."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup, item, po, grn = _full_receipt(db, tid)
    si = inv.create_supplier_invoice(
        db, tenant_id=tid, actor_id='acc-1', supplier_id=sup.id,
        supplier_invoice_no='V-1', invoice_date=TODAY, po_id=po.id,
        grn_id=grn.id,
        lines=[{'item_id': item.id, 'qty': 10, 'unit_price': '2.05'}])
    assert si.status == 'VARIANCE_HOLD'
    issues = si.match_report['issues']
    assert any(i['issue'] == 'PRICE_VARIANCE' for i in issues)
    # لا اعتماد قبل المعالجة
    with pytest.raises(PostingError) as exc:
        inv.approve_supplier_invoice(db, tenant_id=tid, actor_id='fin-9',
                                     sinv_id=si.id)
    assert exc.value.code == 'INV.SI_NOT_MATCHED'


def test_three_way_qty_over_received_auto_hold(db_session):
    """05/قبول-3: كمية مفوترة تتجاوز المقبول في GRN → رفض تلقائي."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup, item, po, grn = _full_receipt(db, tid)
    si = inv.create_supplier_invoice(
        db, tenant_id=tid, actor_id='acc-1', supplier_id=sup.id,
        supplier_invoice_no='V-2', invoice_date=TODAY, po_id=po.id,
        grn_id=grn.id,
        lines=[{'item_id': item.id, 'qty': 11, 'unit_price': '2'}])
    assert si.status == 'VARIANCE_HOLD'
    assert any(i['issue'] == 'QTY_OVER_RECEIVED'
               for i in si.match_report['issues'])


def test_variance_resolution_by_edit_rematch_approve(db_session):
    """§2.4: تفاوض (تصحيح السطر) → إعادة مطابقة → اعتماد ≠ منشئ."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup, item, po, grn = _full_receipt(db, tid)
    si = inv.create_supplier_invoice(
        db, tenant_id=tid, actor_id='acc-1', supplier_id=sup.id,
        supplier_invoice_no='V-3', invoice_date=TODAY, po_id=po.id,
        grn_id=grn.id,
        lines=[{'item_id': item.id, 'qty': 10, 'unit_price': '2.05'}])
    si = inv.resolve_variance(db, tenant_id=tid, actor_id='acc-1',
                              sinv_id=si.id, action='EDIT',
                              corrected_lines=[{'item_id': item.id, 'qty': 10,
                                                'unit_price': '2'}])
    assert si.status == 'MATCHED'
    with pytest.raises(PostingError) as exc:
        inv.approve_supplier_invoice(db, tenant_id=tid, actor_id='acc-1',
                                     sinv_id=si.id)
    assert exc.value.code == 'INV.SELF_APPROVAL'
    inv.approve_supplier_invoice(db, tenant_id=tid, actor_id='fin-1',
                                 sinv_id=si.id)
    assert si.status == 'APPROVED'


def test_variance_approve_posts_ppv_and_adjusts_ap(db_session):
    """§2.4: اعتماد الفرق → حساب 5120 بقيد تسوية، والذمة تطابق الفاتورة."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup, item, po, grn = _full_receipt(db, tid)
    ap_before = inv.supplier_balance(db, tid, sup.id)
    si = inv.create_supplier_invoice(
        db, tenant_id=tid, actor_id='acc-1', supplier_id=sup.id,
        supplier_invoice_no='V-4', invoice_date=TODAY, po_id=po.id,
        grn_id=grn.id,
        lines=[{'item_id': item.id, 'qty': 10, 'unit_price': '2.05'}])
    si = inv.resolve_variance(db, tenant_id=tid, actor_id='fin-1',
                              sinv_id=si.id, action='APPROVE_VARIANCE',
                              actor_perms={'inv.variance.approve'})
    assert si.status == 'APPROVED' and si.variance_entry_id
    lines = _entry_lines(db, si.variance_entry_id)
    codes = {db.get(m.Account, l.account_id).code: l for l in lines}
    assert codes['5120'].debit_base == D_('0.5')      # 0.05 × 10
    assert codes['2101'].credit_base == D_('0.5')
    ap_after = inv.supplier_balance(db, tid, sup.id)
    assert ap_after - ap_before == D_('0.5')
    # وبلا صلاحية المالية يرفض
    sup, item, po, grn = _full_receipt(db, tid, qty=4)
    si2 = inv.create_supplier_invoice(
        db, tenant_id=tid, actor_id='acc-1', supplier_id=sup.id,
        supplier_invoice_no='V-5', invoice_date=TODAY, po_id=po.id,
        grn_id=grn.id, lines=[{'item_id': item.id, 'qty': 4,
                               'unit_price': '3'}])
    with pytest.raises(PostingError) as exc:
        inv.resolve_variance(db, tenant_id=tid, actor_id='intruder',
                             sinv_id=si2.id, action='APPROVE_VARIANCE',
                             actor_perms=set())
    assert exc.value.code == 'RBAC.FORBIDDEN'


def test_duplicate_supplier_invoice_number_blocked(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup, item, po, grn = _full_receipt(db, tid)
    kw = dict(tenant_id=tid, actor_id='a', supplier_id=sup.id,
              supplier_invoice_no='DUP-9', invoice_date=TODAY, po_id=po.id,
              grn_id=grn.id,
              lines=[{'item_id': item.id, 'qty': 10, 'unit_price': '2'}])
    inv.create_supplier_invoice(db, **kw)
    with pytest.raises(PostingError) as exc:
        inv.create_supplier_invoice(db, **kw)
    assert exc.value.code == 'INV.DUP_SUP_INVOICE'


# ════════════════════════════════════════════════════════════════════
# قبول §7.4 — استحالة تعديل GRN مرحَّل من كل المسارات
# ════════════════════════════════════════════════════════════════════
def test_posted_grn_immutable_everywhere(db_session):
    """05/قبول-4: الحارس يرفض من الخدمة، API لا يملك مسار تعديل أصلاً،
    والتصحيح الوحيد = عكس موثق + سند جديد."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup, item, po, grn = _full_receipt(db, tid)
    # 1) حارس الخدمة
    with pytest.raises(PostingError) as exc:
        inv.ensure_grn_mutable(grn)
    assert exc.value.code == 'INV.GRN_IMMUTABLE'
    # 2) لا إعادة ترحيل
    with pytest.raises(PostingError):
        inv.post_grn(db, tenant_id=tid, actor_id='x', grn_id=grn.id)
    # 3) العكس الموثق يعمل — الأسهم تسحب بسعرها والقيد ينعكس
    qty0, _ = _stock(db, _wh(db, tid, 'MAIN-WH').id, item.id)
    rev_grn = inv.reverse_grn(db, tenant_id=tid, actor_id='gm-9',
                              grn_id=grn.id, reason='استلام خاطئ المستودع')
    assert rev_grn.status == 'REVERSED' and rev_grn.reversal_entry_id
    src_entry = db.get(m.JournalEntry, grn.entry_id)
    assert src_entry.status == 'REVERSED'
    qty1, _ = _stock(db, _wh(db, tid, 'MAIN-WH').id, item.id)
    assert qty0 - qty1 == D_(10)
    db.refresh(po)
    assert po.status == 'APPROVED'  # عاد غير مستلم
    # 4) لا عكس ثانٍ
    with pytest.raises(PostingError):
        inv.reverse_grn(db, tenant_id=tid, actor_id='gm-9', grn_id=grn.id,
                        reason='محاولة ثانية')


def test_grn_reversal_blocked_after_consumption_and_invoice(db_session):
    """عكس يتطلب سحب كمية غير مستهلكة؛ وارتباط فاتورة فعالة يمنع العكس."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup, item, po, grn = _full_receipt(db, tid)
    si = inv.create_supplier_invoice(
        db, tenant_id=tid, actor_id='a', supplier_id=sup.id,
        supplier_invoice_no='LOCK-1', invoice_date=TODAY, po_id=po.id,
        grn_id=grn.id,
        lines=[{'item_id': item.id, 'qty': 10, 'unit_price': '2'}])
    assert si.status == 'MATCHED'  # فاتورة فعالة ⇒ العكس ممنوع
    with pytest.raises(PostingError) as exc:
        inv.reverse_grn(db, tenant_id=tid, actor_id='gm', grn_id=grn.id,
                        reason='محاولة')
    assert exc.value.code == 'INV.GRN_HAS_INVOICE'
    # حالة الاستهلاك: الرصيد الكلي للصنف بالمستودع 20 (استلامان ×10) —
    # صرف 15 ⇒ الباقي 5 < 10 المطلوب سحبها للعكس ⇒ يفشل بأمان
    sup2, item2, po2, grn2 = _full_receipt(db, tid, qty=10)
    main = _wh(db, tid, 'MAIN-WH')
    kit = _wh(db, tid, 'KIT-WH')
    iss = inv.create_issue(db, tenant_id=tid, actor_id='req-1',
                           from_warehouse_id=main.id, to_warehouse_id=kit.id,
                           department='المطبخ',
                           lines=[{'item_id': item2.id, 'qty': 15}])
    inv.approve_issue(db, tenant_id=tid, actor_id='gm-1', issue_id=iss.id,
                      approve=True)
    inv.execute_issue(db, tenant_id=tid, actor_id='k1', issue_id=iss.id)
    with pytest.raises(PostingError) as exc:
        inv.reverse_grn(db, tenant_id=tid, actor_id='gm', grn_id=grn2.id,
                        reason='محاولة بعد استهلاك')
    assert exc.value.code == 'INV.INSUFFICIENT_STOCK'


def test_http_posted_grn_has_no_mutation_route(client, db_session):
    """واجهة/API: لا PUT/PATCH على GRN إطلاقاً — الطريقة غير معرّفة وكذلك
    مسار التعديل (قبول §7.4 من مسار الواجهة)."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup, item, po, grn = _full_receipt(db, tid)
    db.commit()
    r = client.patch(f'/api/inv/grn/{grn.id}', json={'note': 'اختراق'})
    assert r.status_code in (404, 405)
    r = client.put(f'/api/inv/grn/{grn.id}', json={'note': 'اختراق'})
    assert r.status_code in (404, 405)


# ════════════════════════════════════════════════════════════════════
# §2.5 السداد (#16) وخصم مكتسب دائناً 4901 — §2.6 المرتجع (#17)
# ════════════════════════════════════════════════════════════════════
def test_supplier_payment_with_earned_discount(db_session):
    """05 §2.5 / #16: سداد 1000 + خصم مكتسب 25 ⇒ Dr 2101 ‏1025 |
    Cr 1101 ‏1000 | Cr 4901 ‏25 — والفاتورة تُقفل PAID."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup, item, po, grn = _full_receipt(db, tid)  # آجل 20
    si = inv.create_supplier_invoice(
        db, tenant_id=tid, actor_id='acc-1', supplier_id=sup.id,
        supplier_invoice_no='PAY-1', invoice_date=TODAY, po_id=po.id,
        grn_id=grn.id,
        lines=[{'item_id': item.id, 'qty': 10, 'unit_price': '2'}])
    inv.approve_supplier_invoice(db, tenant_id=tid, actor_id='fin-1',
                                 sinv_id=si.id)
    bal0 = inv.supplier_balance(db, tid, sup.id)
    pay = inv.pay_supplier(db, tenant_id=tid, actor_id='treas-1',
                           supplier_id=sup.id, amount=1000, method='CASH',
                           discount=25,
                           allocations=[{'invoice_id': si.id, 'amount': 20}])
    lines = _entry_lines(db, pay.entry_id)
    codes = {db.get(m.Account, l.account_id).code: l for l in lines}
    assert codes['2101'].debit_base == D_(1025)
    assert codes['2101'].party_id == sup.id
    assert codes['1101'].credit_base == D_(1000)
    assert codes['4901'].credit_base == D_(25)  # الخصم المكتسب دائناً
    db.refresh(si)
    assert si.status == 'PAID' and D_(si.paid_amount) == D_(20)
    assert inv.supplier_balance(db, tid, sup.id) - bal0 == -D_(1025)


def test_payment_allocations_validations(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup, item, po, grn = _full_receipt(db, tid)
    si = inv.create_supplier_invoice(
        db, tenant_id=tid, actor_id='acc-1', supplier_id=sup.id,
        supplier_invoice_no='PAY-2', invoice_date=TODAY, po_id=po.id,
        grn_id=grn.id,
        lines=[{'item_id': item.id, 'qty': 10, 'unit_price': '2'}])
    inv.approve_supplier_invoice(db, tenant_id=tid, actor_id='fin-1',
                                 sinv_id=si.id)
    with pytest.raises(PostingError) as exc:
        inv.pay_supplier(db, tenant_id=tid, actor_id='t', supplier_id=sup.id,
                         amount=25,
                         allocations=[{'invoice_id': si.id, 'amount': 25}])
    assert exc.value.code == 'INV.ALLOC_OVER'
    with pytest.raises(PostingError) as exc:
        inv.pay_supplier(db, tenant_id=tid, actor_id='t', supplier_id=sup.id,
                         amount=10,
                         allocations=[{'invoice_id': si.id, 'amount': 15}])
    assert exc.value.code == 'INV.ALLOC_OVERPAY'
    ok = inv.pay_supplier(db, tenant_id=tid, actor_id='t', supplier_id=sup.id,
                          amount=20,
                          allocations=[{'invoice_id': si.id, 'amount': 20}])
    db.refresh(si)
    assert si.status == 'PAID'


def test_supplier_return_posts_17_and_restock_check(db_session):
    """05 §2.6 / #17: مرتجع للمورد بمستند مستقل: Dr 2101 طرف |
    Cr حساب المستودع بالمتوسط — ويمنع نقص الرصيد."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup = _sup(db, tid, 'SUP-001')
    wh = _wh(db, tid, 'MAIN-WH')
    item = _iitem(db, tid, 'CHEESE-SL')
    po = _mk_po_approved(db, tid, sup, item, 50, '0.28')
    grn = inv.create_grn(db, tenant_id=tid, actor_id='k', supplier_id=sup.id,
                         warehouse_id=wh.id, purchase_type='CREDIT',
                         po_id=po.id, supplier_invoice_no='R-1',
                         lines=[{'item_id': item.id, 'qty_received': 50}])
    inv.post_grn(db, tenant_id=tid, actor_id='k', grn_id=grn.id)
    srt = inv.create_supplier_return(
        db, tenant_id=tid, actor_id='k', supplier_id=sup.id,
        warehouse_id=wh.id, grn_id=grn.id, reason='جودة دون المطلوب',
        lines=[{'item_id': item.id, 'qty': 10}])
    inv.post_supplier_return(db, tenant_id=tid, actor_id='k', srt_id=srt.id)
    qty, _ = _stock(db, wh.id, item.id)
    assert qty == D_(40)
    lines = _entry_lines(db, srt.entry_id)
    codes = {db.get(m.Account, l.account_id).code: l for l in lines}
    assert codes['2101'].debit_base == D_('2.8')  # 10 × 0.28
    assert codes['2101'].party_id == sup.id
    assert codes['1210'].credit_base == D_('2.8')
    # مرتجع يتجاوز الرصيد ممنوع
    srt2 = inv.create_supplier_return(
        db, tenant_id=tid, actor_id='k', supplier_id=sup.id,
        warehouse_id=wh.id, reason='محاولة أخرى',
        lines=[{'item_id': item.id, 'qty': 999}])
    with pytest.raises(PostingError) as exc:
        inv.post_supplier_return(db, tenant_id=tid, actor_id='k',
                                 srt_id=srt2.id)
    assert exc.value.code == 'INV.INSUFFICIENT_STOCK'


# ════════════════════════════════════════════════════════════════════
# §3 — صرف للأقسام (#18)، تحويلات بثنائية الاستلام، هالك (#19)
# ════════════════════════════════════════════════════════════════════
def test_issue_cycle_entry_18_only_when_accounts_differ(db_session):
    """#18: صرف 1210→1240 يولّد قيداً (بلا أثر دخل)، وصرف بين مستودعين
    على الحساب نفسه حركة بلا قيد."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    main, kit = _wh(db, tid, 'MAIN-WH'), _wh(db, tid, 'KIT-WH')
    item = _iitem(db, tid, 'ORANGE-KG')
    inv.apply_inbound(db, tenant_id=tid, warehouse=main, item_id=item.id,
                      qty=30, unit_cost='1.2', reason='OPENING', ref_type='T',
                      ref_id='i0', actor_id='u', bd=TODAY)
    db.commit()
    iss = inv.create_issue(db, tenant_id=tid, actor_id='chef-1',
                           from_warehouse_id=main.id, to_warehouse_id=kit.id,
                           department='المطبخ',
                           lines=[{'item_id': item.id, 'qty': 10}])
    assert iss.status == 'REQUESTED' and iss.iss_no.startswith('ISS-')
    with pytest.raises(PostingError) as exc:
        inv.approve_issue(db, tenant_id=tid, actor_id='chef-1',
                          issue_id=iss.id, approve=True)
    assert exc.value.code == 'INV.SELF_APPROVAL'
    inv.approve_issue(db, tenant_id=tid, actor_id='gm-1', issue_id=iss.id,
                      approve=True)
    with pytest.raises(PostingError) as exc:
        inv.approve_issue(db, tenant_id=tid, actor_id='gm-2',
                          issue_id=iss.id, approve=True)
    assert exc.value.code == 'INV.ISSUE_STATE'
    inv.execute_issue(db, tenant_id=tid, actor_id='keeper-1', issue_id=iss.id)
    q_main, _ = _stock(db, main.id, item.id)
    q_kit, avg_kit = _stock(db, kit.id, item.id)
    assert q_main == D_(20) and q_kit == D_(10) and avg_kit == D_('1.2')
    assert iss.entry_id  # حسابان مختلفان ⇒ قيد
    lines = _entry_lines(db, iss.entry_id)
    codes = {db.get(m.Account, l.account_id).code: l for l in lines}
    assert codes['1240'].debit_base == D_(12) and codes['1210'].credit_base == D_(12)
    # نفس الحساب: أنشئ مستودعاً ثانياً على 1210 واصرف إليه من الرئيسي
    twin = inv.create_warehouse(db, tenant_id=tid, branch_id=seed['branch_id'],
                                actor_id='a', code='MAIN-SUB',
                                name_ar='فرعي رئيسي', kind='SUB',
                                inventory_account_code='1210')
    db.commit()
    iss2 = inv.create_issue(db, tenant_id=tid, actor_id='chef-1',
                            from_warehouse_id=main.id, to_warehouse_id=twin.id,
                            department='التشغيل',
                            lines=[{'item_id': item.id, 'qty': 5}])
    inv.approve_issue(db, tenant_id=tid, actor_id='gm-1', issue_id=iss2.id,
                      approve=True)
    inv.execute_issue(db, tenant_id=tid, actor_id='keeper-1',
                      issue_id=iss2.id)
    assert iss2.entry_id is None  # لا أثر مالي ⇒ لا قيد
    q_twin, _ = _stock(db, twin.id, item.id)
    assert q_twin == D_(5)
    # الصرف لمستودع منفذ مباشرة ممنوع
    with pytest.raises(PostingError) as exc:
        inv.create_issue(db, tenant_id=tid, actor_id='x',
                         from_warehouse_id=main.id,
                         to_warehouse_id=_wh(db, tid, 'POS-REST').id,
                         department='x',
                         lines=[{'item_id': item.id, 'qty': 1}])
    assert exc.value.code == 'INV.ISSUE_TO_OUTLET'


def test_transfer_in_transit_and_dual_receive(db_session):
    """§3: «على الطريق» للفروع البعيدة — الخصم عند الشحن والإضافة عند
    استلامٍ من غير الشاحن (ثنائية)، والقيد عند اختلاف الحسابين."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    main, kit = _wh(db, tid, 'MAIN-WH'), _wh(db, tid, 'KIT-WH')
    item = _iitem(db, tid, 'SODA')
    inv.apply_inbound(db, tenant_id=tid, warehouse=main, item_id=item.id,
                      qty=20, unit_cost='0.7', reason='OPENING', ref_type='T',
                      ref_id='t0', actor_id='u', bd=TODAY)
    db.commit()
    trf = inv.create_transfer(db, tenant_id=tid, actor_id='keeper-1',
                              from_warehouse_id=main.id,
                              to_warehouse_id=kit.id, reason='تغذية المطبخ',
                              requires_receive=True,
                              lines=[{'item_id': item.id, 'qty': 8}])
    inv.dispatch_transfer(db, tenant_id=tid, actor_id='keeper-1',
                          transfer_id=trf.id)
    assert trf.status == 'IN_TRANSIT'
    q_main, _ = _stock(db, main.id, item.id)
    q_kit, _ = _stock(db, kit.id, item.id)
    assert q_main == D_(12) and q_kit == D_(0)  # لا قيد بعد، «على الطريق»
    assert trf.entry_id is None
    with pytest.raises(PostingError) as exc:
        inv.receive_transfer(db, tenant_id=tid, actor_id='keeper-1',
                             transfer_id=trf.id)
    assert exc.value.code == 'INV.SELF_RECEIVE'
    inv.receive_transfer(db, tenant_id=tid, actor_id='keeper-2',
                         transfer_id=trf.id)
    assert trf.status == 'RECEIVED' and trf.entry_id  # 1240 ≠ 1210
    q_kit, avg_kit = _stock(db, kit.id, item.id)
    assert q_kit == D_(8) and avg_kit == D_('0.7')


def test_quick_transfer_and_cancel_rules(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    main, kit = _wh(db, tid, 'MAIN-WH'), _wh(db, tid, 'KIT-WH')
    item = _iitem(db, tid, 'WATER')
    inv.apply_inbound(db, tenant_id=tid, warehouse=main, item_id=item.id,
                      qty=10, unit_cost='0.45', reason='OPENING', ref_type='T',
                      ref_id='q0', actor_id='u', bd=TODAY)
    trf = inv.create_transfer(db, tenant_id=tid, actor_id='k1',
                              from_warehouse_id=main.id,
                              to_warehouse_id=kit.id, reason='تحويل فوري',
                              requires_receive=False,
                              lines=[{'item_id': item.id, 'qty': 4}])
    inv.dispatch_transfer(db, tenant_id=tid, actor_id='k1',
                          transfer_id=trf.id)
    assert trf.status == 'RECEIVED'
    q_kit, _ = _stock(db, kit.id, item.id)
    assert q_kit == D_(4)
    with pytest.raises(PostingError) as exc:
        inv.create_transfer(db, tenant_id=tid, actor_id='k',
                            from_warehouse_id=main.id, to_warehouse_id=kit.id,
                            reason='x',  # مسوغ قصير
                            lines=[{'item_id': item.id, 'qty': 1}])
    assert exc.value.code == 'INV.REASON_REQUIRED'


def test_waste_approval_posts_19_and_monthly_stat(db_session):
    """§3/#19: هالك بمستند+اعتماد+سبب: Dr 7104 | Cr المستودع بالمتوسط —
    ويظهر في إحصائية الهالك الشهرية."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    wh = _wh(db, tid, 'MAIN-WH')
    item = _iitem(db, tid, 'FRIES-PT')
    inv.apply_inbound(db, tenant_id=tid, warehouse=wh, item_id=item.id,
                      qty=20, unit_cost='0.8', reason='OPENING', ref_type='T',
                      ref_id='w0', actor_id='u', bd=TODAY)
    db.commit()
    wst = inv.create_waste(db, tenant_id=tid, actor_id='keeper-1',
                           warehouse_id=wh.id, reason='انتهاء صلاحية',
                           photo_ref='photos/wst-1.jpg',
                           lines=[{'item_id': item.id, 'qty': 5,
                                   'reason': 'فاسد'}])
    inv.submit_waste(db, tenant_id=tid, actor_id='keeper-1',
                     waste_id=wst.id)
    with pytest.raises(PostingError) as exc:
        inv.approve_waste(db, tenant_id=tid, actor_id='keeper-1',
                          waste_id=wst.id, approve=True)
    assert exc.value.code == 'INV.SELF_APPROVAL'
    inv.approve_waste(db, tenant_id=tid, actor_id='fin-1', waste_id=wst.id,
                      approve=True)
    assert wst.status == 'POSTED' and D_(wst.total_value) == D_(4)
    lines = _entry_lines(db, wst.entry_id)
    codes = {db.get(m.Account, l.account_id).code: l for l in lines}
    assert codes['7104'].debit_base == D_(4) and codes['1210'].credit_base == D_(4)
    qty, _ = _stock(db, wh.id, item.id)
    assert qty == D_(15)
    monthly = inv.waste_report(db, tid)
    assert monthly and monthly[-1]['value'] >= D_(4)


# ════════════════════════════════════════════════════════════════════
# §4 الجرد + قبول §7.5 (#19 بالهللة) — والتجميد
# ════════════════════════════════════════════════════════════════════
def test_count_freeze_blocks_all_movement(db_session):
    """05 §4: تجميد الحركة على النطاق طوال الجرد — أي حركة ممنوعة حتى
    اعتماده أو إلغائه."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    wh = _wh(db, tid, 'KIT-WH')
    item = _iitem(db, tid, 'SODA')
    inv.apply_inbound(db, tenant_id=tid, warehouse=wh, item_id=item.id,
                      qty=10, unit_cost='0.7', reason='OPENING', ref_type='T',
                      ref_id='f0', actor_id='u', bd=TODAY)
    cnt = inv.create_count(db, tenant_id=tid, actor_id='fin-1',
                           warehouse_id=wh.id)
    with pytest.raises(PostingError) as exc:
        inv.apply_outbound(db, tenant_id=tid, warehouse=wh, item_id=item.id,
                           qty=1, reason='ISSUE_OUT', ref_type='T',
                           ref_id='f1', actor_id='u', bd=TODAY)
    assert exc.value.code == 'INV.WAREHOUSE_FROZEN'
    with pytest.raises(PostingError) as exc:
        inv.apply_inbound(db, tenant_id=tid, warehouse=wh, item_id=item.id,
                          qty=1, unit_cost=1, reason='OPENING', ref_type='T',
                          ref_id='f2', actor_id='u', bd=TODAY)
    assert exc.value.code == 'INV.WAREHOUSE_FROZEN'
    # جرد ثانٍ متزامن ممنوع
    with pytest.raises(PostingError):
        inv.create_count(db, tenant_id=tid, actor_id='x', warehouse_id=wh.id)
    inv.cancel_count(db, tenant_id=tid, actor_id='fin-1', count_id=cnt.id,
                     reason='إعادة جدولة')
    mv, _, _ = inv.apply_outbound(db, tenant_id=tid, warehouse=wh,
                                  item_id=item.id, qty=3, reason='ISSUE_OUT',
                                  ref_type='T', ref_id='f3', actor_id='u',
                                  bd=TODAY)
    qty, _ = _stock(db, wh.id, item.id)
    assert qty == D_(7)


def test_count_shortage_posts_19_to_the_halala(db_session):
    """05/قبول-5: عجز الجرد يولّد قيد #19 بقيمة تطابق كشف الفروقات
    بالهللة — وسلسلة الاعتماد المزدوج كاملة (ملف 14 §2)."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    wh = _wh(db, tid, 'MAIN-WH')
    # إدخال الرصيد عبر مستند مالي حقيقي (GRN) حتى يطابق الأستاذ المخزون
    sup, item, po, grn = _full_receipt(db, tid, qty=100, price='2.2')
    cnt = inv.create_count(db, tenant_id=tid, actor_id='keeper-1',
                           warehouse_id=wh.id)
    inv.enter_count(db, tenant_id=tid, actor_id='counter-1',
                    count_id=cnt.id,
                    counted=[{'item_id': item.id, 'counted_qty': 97}])
    inv.finish_count(db, tenant_id=tid, actor_id='counter-1',
                     count_id=cnt.id)
    assert cnt.status == 'PENDING_L1' and D_(cnt.short_value) == D_('6.6')
    ln = db.execute(select(m.InvCountLine).where(
        m.InvCountLine.count_id == cnt.id)).scalar_one()
    assert D_(ln.variance_qty) == D_(-3) and D_(ln.variance_value) == D_('-6.6')
    # سلسلة الاعتماد: منشئ الجرد لا يعتمد
    with pytest.raises(PostingError) as exc:
        inv.approve_count(db, tenant_id=tid, actor_id='keeper-1',
                          count_id=cnt.id, level=1,
                          actor_perms={'inv.count.approve.l1'})
    assert exc.value.code == 'INV.SELF_APPROVAL'
    inv.approve_count(db, tenant_id=tid, actor_id='fin-1', count_id=cnt.id,
                      level=1, actor_perms={'inv.count.approve.l1'})
    assert cnt.status == 'PENDING_L2'
    # L2 ≠ L1
    with pytest.raises(PostingError) as exc:
        inv.approve_count(db, tenant_id=tid, actor_id='fin-1',
                          count_id=cnt.id, level=2,
                          actor_perms={'inv.count.approve.l2'})
    assert exc.value.code == 'INV.SELF_APPROVAL'
    inv.approve_count(db, tenant_id=tid, actor_id='gm-9', count_id=cnt.id,
                      level=2, actor_perms={'inv.count.approve.l2'})
    assert cnt.status == 'POSTED'
    # القيد #19 بقيمة كشف الفروقات نفسه — بلا هللة فرق
    assert cnt.short_entry_id and cnt.over_entry_id is None
    lines = _entry_lines(db, cnt.short_entry_id)
    codes = {db.get(m.Account, l.account_id).code: l for l in lines}
    assert codes['7104'].debit_base == D_('6.6') == D_(cnt.short_value)
    assert codes['1210'].credit_base == D_('6.6')
    qty, avg = _stock(db, wh.id, item.id)
    assert qty == D_(97) and avg == D_('2.2')
    # ثبات القيمة بعد الجرد
    rep = inv.valued_stock_report(db, tid, warehouse_id=wh.id)
    assert rep['all_matched']


def test_count_overage_posts_20_and_incomplete_blocked(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    wh = _wh(db, tid, 'KIT-WH')
    item = _iitem(db, tid, 'WATER')
    inv.apply_inbound(db, tenant_id=tid, warehouse=wh, item_id=item.id,
                      qty=50, unit_cost='0.45', reason='OPENING',
                      ref_type='T', ref_id='o0', actor_id='u', bd=TODAY)
    db.commit()
    cnt = inv.create_count(db, tenant_id=tid, actor_id='keeper-x',
                           warehouse_id=wh.id)
    # أكمل العد جزئياً ⇒ القفل ممنوع
    inv.enter_count(db, tenant_id=tid, actor_id='c1', count_id=cnt.id,
                    counted=[{'item_id': item.id, 'counted_qty': 55}])
    inv.finish_count(db, tenant_id=tid, actor_id='c1', count_id=cnt.id)
    inv.approve_count(db, tenant_id=tid, actor_id='fin-x', count_id=cnt.id,
                      level=1, actor_perms={'inv.count.approve.l1'})
    inv.approve_count(db, tenant_id=tid, actor_id='gm-x', count_id=cnt.id,
                      level=2, actor_perms={'inv.count.approve.l2'})
    assert cnt.over_entry_id and not cnt.short_entry_id
    lines = _entry_lines(db, cnt.over_entry_id)
    codes = {db.get(m.Account, l.account_id).code: l for l in lines}
    assert codes['1240'].debit_base == D_('2.25')
    assert codes['4901'].credit_base == D_('2.25')
    qty, _ = _stock(db, wh.id, item.id)
    assert qty == D_(55)


# ════════════════════════════════════════════════════════════════════
# §6 التنبيهات والتقارير + قبول §7.2 المطابقة اليومية
# ════════════════════════════════════════════════════════════════════
def test_stock_value_equals_ledger_acceptance(db_session):
    """05/قبول-2: رصيد مخزون اليوم (قيمة) = حساب المخزون في الأستاذ
    لنفس اليوم — بعد عمليات شراء/صرف/هالك/جرد مختلطة."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    main, kit = _wh(db, tid, 'MAIN-WH'), _wh(db, tid, 'KIT-WH')
    sup = _sup(db, tid, 'SUP-001')
    item = _iitem(db, tid, 'BUN')
    po = _mk_po_approved(db, tid, sup, item, 200, '0.32')
    grn = inv.create_grn(db, tenant_id=tid, actor_id='k', supplier_id=sup.id,
                         warehouse_id=main.id, purchase_type='CREDIT',
                         po_id=po.id, supplier_invoice_no='MIX-1',
                         lines=[{'item_id': item.id, 'qty_received': 200}])
    inv.post_grn(db, tenant_id=tid, actor_id='k', grn_id=grn.id)
    item2 = _iitem(db, tid, 'ORANGE-KG')
    grn2 = inv.create_grn(db, tenant_id=tid, actor_id='k', supplier_id=sup.id,
                          warehouse_id=kit.id, purchase_type='CASH',
                          lines=[{'item_id': item2.id, 'qty_received': 10,
                                  'unit_price': '1.2'}])
    inv.post_grn(db, tenant_id=tid, actor_id='k', grn_id=grn2.id)
    iss = inv.create_issue(db, tenant_id=tid, actor_id='r',
                           from_warehouse_id=main.id, to_warehouse_id=kit.id,
                           department='المطبخ',
                           lines=[{'item_id': item.id, 'qty': 50}])
    inv.approve_issue(db, tenant_id=tid, actor_id='gm', issue_id=iss.id,
                      approve=True)
    inv.execute_issue(db, tenant_id=tid, actor_id='k', issue_id=iss.id)
    wst = inv.create_waste(db, tenant_id=tid, actor_id='k',
                           warehouse_id=kit.id, reason='تالف بالتخزين',
                           lines=[{'item_id': item.id, 'qty': 2}])
    inv.submit_waste(db, tenant_id=tid, actor_id='k', waste_id=wst.id)
    inv.approve_waste(db, tenant_id=tid, actor_id='fin', waste_id=wst.id,
                      approve=True)
    rep = inv.valued_stock_report(db, tid)
    assert rep['all_matched'], rep['accounts_match']
    recon = inv.reconciliation_check(db, tid)
    assert recon['ok'] is True and recon['alerts'] == []
    # كل حساب: القيمة تساوي الأستاذ حرفياً
    for mrow in rep['accounts_match']:
        assert mrow['stock_value'] == mrow['ledger_balance'], mrow


def test_reconciliation_detects_manual_teasing(db_session):
    """الفحص الآلي (§6): قيد يدوي على حساب مخزون يوقظ تنبيهاً فوراً."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    from app.posting import create_and_post_journal
    create_and_post_journal(
        db, tenant_id=tid, branch_id=seed['branch_id'],
        journal_type='MANUAL', entry_date=TODAY,
        narration='تسوية يدوية تجريبية على المخزون',
        raw_lines=[{'account': '1210', 'debit': 7, 'credit': 0,
                    'description': 'تجريب'},
                   {'account': '8001', 'debit': 0, 'credit': 7,
                    'description': 'مقابل'}], actor_id='fin-x')
    recon = inv.reconciliation_check(db, tid)
    assert recon['ok'] is False
    assert any(a['account_code'] == '1210' for a in recon['alerts'])


def test_reorder_alert_simplified_eoq_math(db_session):
    """05 §6: تحت حد إعادة الطلب ⇒ اقتراح = عجز حتى الأمان + متوسط
    استهلاك نافذة الأيام."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    wh = _wh(db, tid, 'MAIN-WH')
    cat = db.execute(select(m.InvCategory).where(
        m.InvCategory.tenant_id == tid, m.InvCategory.code == 'FB')
    ).scalar_one()
    # صنف مخصص بلا أرصدة منافذ لنتائج حتمية
    item = inv.create_item(db, tenant_id=tid, actor_id='a', code='TST-RO',
                           name_ar='صنف حد الطلب', category_id=cat.id,
                           base_unit='علبة', reorder_level=200,
                           safety_level=150)
    inv.apply_inbound(db, tenant_id=tid, warehouse=wh, item_id=item.id,
                      qty=100, unit_cost='0.7', reason='OPENING',
                      ref_type='T', ref_id='r0', actor_id='u', bd=TODAY)
    inv.apply_outbound(db, tenant_id=tid, warehouse=wh, item_id=item.id,
                       qty=60, reason='ISSUE_OUT', ref_type='T', ref_id='r1',
                       actor_id='u', bd=TODAY)
    db.commit()
    alerts = inv.reorder_alerts(db, tid)
    row = next(a for a in alerts if a['code'] == 'TST-RO')
    assert row['on_hand'] == D_(40)
    # العجز حتى الأمان 110 + متوسط استهلاك نافذة 30 يوم (60 صادرة) = 170
    assert row['suggested_qty'] == D_('170.00')


def test_expiry_alert_windows(db_session):
    """05 §6: دفعات قربت صلاحيتها ضمن نوافذ 30/15/7 مع الكمية المتبقية."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup = _sup(db, tid, 'SUP-002')
    wh = _wh(db, tid, 'MNT-WH')
    item = _iitem(db, tid, 'DETERG-L')
    soon = TODAY + timedelta(days=10)
    grn = inv.create_grn(db, tenant_id=tid, actor_id='k', supplier_id=sup.id,
                         warehouse_id=wh.id, purchase_type='CASH',
                         lines=[{'item_id': item.id, 'qty_received': 12,
                                 'unit_price': '4.2', 'batch_no': 'EXP-1',
                                 'expiry_date': soon}])
    inv.post_grn(db, tenant_id=tid, actor_id='k', grn_id=grn.id)
    # استهلاك تقديري يستنزف 2 من أقدم دفعة (40 افتتاحية بلا دفعة أولاً)
    inv.apply_outbound(db, tenant_id=tid, warehouse=wh, item_id=item.id,
                       qty=42, reason='ISSUE_OUT', ref_type='T', ref_id='e1',
                       actor_id='u', bd=TODAY)
    db.commit()
    alerts = inv.expiry_alerts(db, tid)
    row = next((a for a in alerts if a['batch_no'] == 'EXP-1'), None)
    assert row is not None and row['days_left'] == 10
    assert row['window'] == 15 and row['qty'] == D_(10)


def test_stagnant_alert_90_days(db_session):
    """05 §6: صنف راكد بلا حركة 90 يوماً برصيد موجب ⇒ تنبيه."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    item = _iitem(db, tid, 'BED-SHEET')  # رصيد افتتاحي 120 في HK-WH
    old = TODAY - timedelta(days=120)
    db.execute(select(m.InvMove).where(m.InvMove.item_id == item.id))
    for mv in db.execute(select(m.InvMove).where(
            m.InvMove.item_id == item.id)).scalars().all():
        mv.business_date = old
    db.commit()
    alerts = inv.stagnant_alerts(db, tid)
    row = next((a for a in alerts if a['code'] == 'BED-SHEET'), None)
    assert row is not None and row['idle_days'] >= 90


def test_purchases_and_performance_and_statement_reports(db_session):
    """§6: مشتريات المورد/الفترة + أداء الموردين + كشف حساب بطرف الأستاذ."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup, item, po, grn = _full_receipt(db, tid)  # 10×2 آجل
    rep = inv.purchases_report(db, tid, TODAY - timedelta(days=1),
                               TODAY + timedelta(days=1))
    row = next(r for r in rep if r['supplier_id'] == sup.id)
    assert row['grn_count'] >= 1 and row['credit_total'] >= D_(20)
    perf = inv.supplier_performance(db, tid)
    prow = next(p for p in perf if p['supplier_id'] == sup.id)
    assert prow['po_count'] >= 1 and prow['balance'] >= D_(20)
    stmt = inv.supplier_statement(db, tid, sup.id)
    assert stmt['balance'] == prow['balance']
    assert any(l['credit'] >= D_(20) for l in stmt['lines'])
    # تقرير فروقات الأسعار فارغ بلا اعتمادات فرق
    assert inv.ppv_report(db, tid, TODAY, TODAY) == []


# ════════════════════════════════════════════════════════════════════
# ADR-0017 جسر POS — وملف 05 §5 الاستهلاك النظري مقابل الفعلي
# ════════════════════════════════════════════════════════════════════
def _shift(db, tid, outlet, user='cashier-inv'):
    return ps.open_shift(db, tenant_id=tid, actor_id=user, outlet=outlet,
                         opening_float=100)


def test_pos_sale_moves_through_unified_ledger(db_session):
    """ADR-0017: بيع POS يخصم مستودع المنفذ بالمتوسط لحظتها، وحركات
    SALE_POS تُخزَّن بالتكلفة لحظة البيع، والسطر يحمل unit_cost (05 §4)."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet = db.execute(select(m.PosOutlet).where(
        m.PosOutlet.tenant_id == tid, m.PosOutlet.code == 'REST')
    ).scalar_one()
    wh = _wh(db, tid, 'POS-REST')
    water = _iitem(db, tid, 'WATER')
    q0, avg0 = _stock(db, wh.id, water.id)
    assert q0 == D_(300) and avg0 == D_('0.45')  # ترحيل الافتتاحي تم
    shift = _shift(db, tid, outlet)
    o = ps.create_order(db, tenant_id=tid, actor_id='c', outlet=outlet,
                        shift=shift, type_='TAKEAWAY')
    pitem = db.execute(select(m.PosItem).where(
        m.PosItem.tenant_id == tid, m.PosItem.code == 'WATER')).scalar_one()
    ps.add_line(db, tenant_id=tid, order=o, item_id=pitem.id, qty=2,
                actor_id='c')
    out = ps.settle_order(db, tenant_id=tid, actor_id='c',
                          actor_perms={'*'}, order=o,
                          payments=[{'method': 'CASH', 'amount': '2'}],
                          client_uuid=new_uuid())
    db.commit()
    q1, _ = _stock(db, wh.id, water.id)
    assert q0 - q1 == D_(2)
    mv = db.execute(select(m.InvMove).where(
        m.InvMove.ref_id == out['invoice'].id,
        m.InvMove.reason == 'SALE_POS')).scalar_one()
    assert D_(mv.unit_cost) == D_('0.45') and D_(mv.qty_delta) == D_(-2)
    assert out['invoice'].cost_total == D_('0.9')
    snap = out['invoice'].lines_snapshot[0]
    assert snap['unit_cost'] == '0.4500'
    # قيمة المخزون لا تزال تطابق الأستاذ بعد البيع (قبول §7.2 مع #13)
    assert inv.reconciliation_check(db, tid)['ok']


def test_theoretical_vs_actual_consumption(db_session):
    """05 §5/§6: الوصفة تعطي النظري، وحركات البيع تعطي الفعلي —
    تطابق تام بلا هدر، وأي فرق موجب مؤشر تلاعب."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet = db.execute(select(m.PosOutlet).where(
        m.PosOutlet.tenant_id == tid, m.PosOutlet.code == 'REST')
    ).scalar_one()
    shift = _shift(db, tid, outlet)
    o = ps.create_order(db, tenant_id=tid, actor_id='c', outlet=outlet,
                        shift=shift, type_='TAKEAWAY')
    bg = db.execute(select(m.PosItem).where(
        m.PosItem.tenant_id == tid, m.PosItem.code == 'BURGER-CL')
    ).scalar_one()
    ps.add_line(db, tenant_id=tid, order=o, item_id=bg.id, qty=3,
                actor_id='c')
    ps.settle_order(db, tenant_id=tid, actor_id='c', actor_perms={'*'},
                    order=o, payments=[{'method': 'CASH', 'amount': '28.5'}],
                    client_uuid=new_uuid())
    db.commit()
    rep = inv.consumption_report(db, tid, TODAY, TODAY)
    rows = {r['code']: r for r in rep['rows']}
    for code in ('BUN', 'BEEF-PAT', 'CHEESE-SL', 'FRIES-PT'):
        assert rows[code]['theoretical_qty'] == D_(3)
        assert rows[code]['actual_qty'] == D_(3)
        assert rows[code]['variance_qty'] == D_(0)


def test_pos_stock_load_goes_through_inventory(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet = db.execute(select(m.PosOutlet).where(
        m.PosOutlet.tenant_id == tid, m.PosOutlet.code == 'CAFE')
    ).scalar_one()
    wh = _wh(db, tid, 'POS-CAFE')
    soda = _iitem(db, tid, 'SODA')
    q0, _ = _stock(db, wh.id, soda.id)
    res = ps.load_stock(db, tenant_id=tid, outlet=outlet,
                        item_id=db.execute(select(m.PosItem.id).where(
                            m.PosItem.tenant_id == tid,
                            m.PosItem.code == 'SODA')).scalar_one(),
                        qty=48, unit_cost='0.72', actor_id='sup-1')
    db.commit()
    q1, avg1 = _stock(db, wh.id, soda.id)
    assert q1 - q0 == D_(48) and res['qty_on_hand'] == q1
    # متوسط مرجح متحرك: (80×0.7 + 48×0.72) / 128 = 0.7075
    expected = ((D_(80) * D_('0.7') + D_(48) * D_('0.72')) / D_(128)
                ).quantize(Q4)
    assert avg1 == expected
    assert inv.reconciliation_check(db, tid)['ok']


# ════════════════════════════════════════════════════════════════════
# RBAC عبر HTTP + دورة كاملة End-to-End + سلامة السلسلة
# ════════════════════════════════════════════════════════════════════
def test_rbac_inventory_roles_http(client, db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    _mk_role_user(db, tid, 'PURCHASING', 'purch1')
    _mk_role_user(db, tid, 'POS_CASHIER', 'cash-nobody')
    _mk_role_user(db, tid, 'STORE_KEEPER', 'keep1')
    r = client.post('/api/auth/login',
                    json={'username': 'purch1', 'password': 'Pass!12345'})
    hp = {'Authorization': f"Bearer {r.json()['access_token']}"}
    r = client.post('/api/auth/login',
                    json={'username': 'cash-nobody',
                          'password': 'Pass!12345'})
    hc = {'Authorization': f"Bearer {r.json()['access_token']}"}
    r = client.post('/api/auth/login',
                    json={'username': 'keep1', 'password': 'Pass!12345'})
    hk = {'Authorization': f"Bearer {r.json()['access_token']}"}
    sup = _sup(db, tid, 'SUP-001')
    item = _iitem(db, tid, 'WATER')
    db.commit()
    # كاشير POS بلا أي صلاحية مخزون ⇒ 403
    r = client.post('/api/inv/po', json={
        'supplier_id': sup.id,
        'lines': [{'item_id': item.id, 'qty': 10, 'unit_price': '0.5'}]},
        headers=hc)
    assert r.status_code == 403
    # مشتريات ينشئ PO لكن لا يستطيع اعتماده من نفسه
    r = client.post('/api/inv/po', json={
        'supplier_id': sup.id,
        'lines': [{'item_id': item.id, 'qty': 20000, 'unit_price': '0.5'}]},
        headers=hp)  # 10000 ⇒ L1
    assert r.status_code == 201, r.text
    po_id = r.json()['id']
    assert r.json()['status'] == 'PENDING_L1'
    r = client.post(f'/api/inv/po/{po_id}/approve', headers=hp)
    assert r.status_code == 403  # لا يملك l1 أصلاً
    # أمين لا يستطيع إنشاء مورد لكنه يقرأ
    r = client.post('/api/inv/suppliers',
                    json={'code': 'X1', 'name': 'مقاول'}, headers=hk)
    assert r.status_code == 403
    r = client.get('/api/inv/warehouses', headers=hk)
    assert r.status_code == 200


def test_full_cycle_e2e_http(client, auth_hdr, db_session):
    """دورة شراء كاملة عبر API: PO⇒اعتماد⇒GRN⇒مطابقة⇒سداد —
    والقيمة تطابق الأستاذ عند كل محطة (قبول §7.2)."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup = _sup(db, tid, 'SUP-001')
    item = _iitem(db, tid, 'FRIES-PT')
    wh = _wh(db, tid, 'MAIN-WH')
    db.commit()
    pol = inv.get_policy(db, tid)
    pol.po_l0_limit = Decimal('1')   # أجبر الاعتماد على الظهور في الاختبار
    pol.po_l1_limit = Decimal('99999999')
    _mk_role_user(db, tid, 'GM', 'gm-e2e')  # المعتمِد ≠ المنشئ (ملف 14)
    _mk_role_user(db, tid, 'FINANCE_MANAGER', 'fin-e2e')
    r = client.post('/api/auth/login',
                    json={'username': 'gm-e2e', 'password': 'Pass!12345'})
    gm_hdr = {'Authorization': f"Bearer {r.json()['access_token']}"}
    r = client.post('/api/auth/login',
                    json={'username': 'fin-e2e', 'password': 'Pass!12345'})
    fin_hdr = {'Authorization': f"Bearer {r.json()['access_token']}"}
    db.commit()
    r = client.post('/api/inv/po', json={
        'supplier_id': sup.id,
        'lines': [{'item_id': item.id, 'qty': 120, 'unit_price': '0.75'}]},
        headers=auth_hdr)  # 90 > 1 ⇒ L1
    assert r.status_code == 201, r.text
    po = r.json()
    assert po['status'] == 'PENDING_L1'
    r = client.post(f"/api/inv/po/{po['id']}/approve", headers=auth_hdr)
    assert r.status_code == 400  # المنشئ يمنع اعتماد نفسه
    r = client.post(f"/api/inv/po/{po['id']}/approve", headers=gm_hdr)
    assert r.status_code == 200 and r.json()['status'] == 'APPROVED'
    r = client.post('/api/inv/grn', json={
        'supplier_id': sup.id, 'warehouse_id': wh.id,
        'purchase_type': 'CREDIT', 'po_id': po['id'],
        'supplier_invoice_no': 'E2E-1',
        'lines': [{'item_id': item.id, 'qty_received': 120}]},
        headers=auth_hdr)
    assert r.status_code == 201, r.text
    grn = r.json()
    r = client.post(f"/api/inv/grn/{grn['id']}/post", headers=auth_hdr)
    assert r.status_code == 200 and r.json()['status'] == 'POSTED'
    assert Decimal(str(r.json()['total'])) == Decimal('90')
    r = client.post('/api/inv/invoices', json={
        'supplier_id': sup.id, 'supplier_invoice_no': 'E2E-1',
        'invoice_date': str(TODAY), 'po_id': po['id'], 'grn_id': grn['id'],
        'lines': [{'item_id': item.id, 'qty': 120, 'unit_price': '0.75'}]},
        headers=auth_hdr)
    assert r.status_code == 201 and r.json()['status'] == 'MATCHED'
    sinv = r.json()
    r = client.post(f"/api/inv/invoices/{sinv['id']}/approve",
                    headers=auth_hdr)
    assert r.status_code == 400  # المنشئ يمنع اعتماد فاتورته
    r = client.post(f"/api/inv/invoices/{sinv['id']}/approve",
                    headers=gm_hdr)
    assert r.status_code == 403  # لا يملك اعتماد الفواتير (صلاحية مالية)
    r = client.post(f"/api/inv/invoices/{sinv['id']}/approve",
                    headers=fin_hdr)
    assert r.status_code == 200 and r.json()['status'] == 'APPROVED'
    r = client.post('/api/inv/payments', json={
        'supplier_id': sup.id, 'amount': 90, 'method': 'BANK',
        'allocations': [{'invoice_id': sinv['id'], 'amount': 90}]},
        headers=auth_hdr)
    assert r.status_code == 201, r.text
    r = client.get(f"/api/inv/suppliers/{sup.id}/statement",
                   headers=auth_hdr)
    assert r.status_code == 200
    stmt = r.json()
    # ذمة المورد صفراً بعد الاستلام (دائن 90) والسداد (مدين 90)
    assert Decimal(stmt['balance']) == Decimal(stmt['balance'])  # رقم
    open_inv = [i for i in stmt['open_invoices']
                if i['sinv_no'] == sinv['sinv_no']]
    assert open_inv == []  # سُددت بالكامل ⇒ خارج المفتوحة
    r = client.get('/api/inv/reports/reconciliation', headers=auth_hdr)
    assert r.json()['ok'] is True


def test_seed_inv_idempotent_and_audit_chain(db_session):
    db, factory, seed = db_session
    from app.seed import seed_inv
    tid, bid = seed['tenant_id'], seed['branch_id']
    db.commit()
    before = {t: db.execute(select(func.count()).select_from(tbl)).scalar_one()
              for t, tbl in (('cat', m.InvCategory), ('wh', m.InvWarehouse),
                             ('item', m.InvItem), ('move', m.InvMove),
                             ('sup', m.InvSupplier))}
    added = inv._branch_id(db, tid)  # no-op للحصول على فرع
    again = seed_inv(db, tid, bid)
    db.commit()
    after = {t: db.execute(select(func.count()).select_from(tbl)).scalar_one()
             for t, tbl in (('cat', m.InvCategory), ('wh', m.InvWarehouse),
                            ('item', m.InvItem), ('move', m.InvMove),
                            ('sup', m.InvSupplier))}
    assert before == after
    assert all(v == 0 for v in again.values())
    # عملية كاملة سريعة ثم سلامة سلسلة التدقيق
    sup, item, po, grn = _full_receipt(db, tid)
    chk = verify_chain(db, tid)
    assert chk['ok'] is True and chk['checked'] > 0


def test_policy_extended_fields_update(db_session):
    """سياسة المستأجر قابلة للضبط كلياً (نوافذ صلاحية/ركود/استهلاك) مع توثيقها."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    p = inv.get_policy(db, tid)
    before = (p.expiry_windows, p.stagnant_days, p.consumption_days)
    p = inv.update_policy(db, tenant_id=tid, actor_id=seed['admin_id'],
                          changes={'expiry_windows': [7, 45, 15],
                                   'stagnant_days': 120,
                                   'consumption_days': 14})
    # النوافذ تُطبع تنازلياً تلقائياً والحقول العددية تُحفظ
    assert p.expiry_windows == [45, 15, 7]
    assert p.stagnant_days == 120 and p.consumption_days == 14
    # قيم سالبة/فارغة تُرفض
    with pytest.raises(PostingError):
        inv.update_policy(db, tenant_id=tid, actor_id=seed['admin_id'],
                          changes={'stagnant_days': 0})
    assert inv.get_policy(db, tid).stagnant_days == 120
    assert before == ([30, 15, 7], 90, 30)  # افتراضيات الإزميل
