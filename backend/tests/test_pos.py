"""اختبارات وحدة POS — معايير القبول الخمسة في ملف 04 §6 + G4:
#1 بيعة نقدية كاملة سريعة + كتالوج ضخم • #2 محاسبة = تقرير = #10..13
#3 خصم مكونات الوصفة بالضبط • #4 لا فقدان فاتورة بعد انقطاع شبكة
#5 كل إلغاء/خصم/مرتجع بمستخدم + سبب + Audit"""
import time
import uuid as _uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import models as m
from app import pos as ps
from app.audit import verify_chain
from app.hotel import folio_balance, walk_in
from app.posting import PostingError
from app.security import hash_password, new_uuid, utcnow

TODAY = date.today()
CU = lambda: f'cu-{_uuid.uuid4().hex[:24]}'


def _outlet(db, tid, code='REST'):
    return db.execute(select(m.PosOutlet).where(
        m.PosOutlet.tenant_id == tid, m.PosOutlet.code == code)).scalar_one()


def _item(db, tid, code):
    return db.execute(select(m.PosItem).where(
        m.PosItem.tenant_id == tid, m.PosItem.code == code)).scalar_one()


def _stock(db, outlet_id, item_id):
    """رصيد صنف في منفذ من دفتر المخزون الموحد (ADR-0017) — المصدر الوحيد
    للحقيقة منذ المرحلة 5؛ نفس الدلالة السابقة تماماً."""
    wh = db.execute(select(m.InvWarehouse).where(
        m.InvWarehouse.pos_outlet_id == outlet_id)).scalar_one_or_none()
    if wh is None:
        return Decimal('0')
    iit = db.execute(select(m.InvItem).where(
        m.InvItem.pos_item_id == item_id)).scalar_one_or_none()
    if iit is None:
        return Decimal('0')
    row = db.execute(select(m.InvStock).where(
        m.InvStock.warehouse_id == wh.id,
        m.InvStock.item_id == iit.id)).scalar_one_or_none()
    return D_(row.qty_on_hand) if row else Decimal('0')


def D_(v):
    return Decimal(str(v)).quantize(Decimal('0.0001'))


def _shift(db, tid, outlet, user='cashier-1', float_=100):
    return ps.open_shift(db, tenant_id=tid, actor_id=user, outlet=outlet,
                         opening_float=float_)


def _order_with(db, tid, outlet, shift, lines, type_='TAKEAWAY',
                user='cashier-1'):
    o = ps.create_order(db, tenant_id=tid, actor_id=user, outlet=outlet,
                        shift=shift, type_=type_)
    for code, qty, kw in lines:
        ps.add_line(db, tenant_id=tid, order=o,
                    item_id=_item(db, tid, code).id, qty=qty,
                    actor_id=user, **kw)
    return o


def _settle(db, tid, order, payments, user='cashier-1', perms={'*'},
            client_uuid=None, **kw):
    return ps.settle_order(db, tenant_id=tid, actor_id=user,
                           actor_perms=perms, order=order, payments=payments,
                           client_uuid=client_uuid or CU(), **kw)


def _mk_supervisor(db, tid, pin='4321'):
    """مستخدم POS_SUPERVISOR برقم PIN للاعتمادات الفورية."""
    role = db.execute(select(m.Role).where(
        m.Role.tenant_id == tid, m.Role.code == 'POS_SUPERVISOR')).scalar_one()
    u = m.User(id=new_uuid(), tenant_id=tid, username='sup1',
               full_name='مشرف البيع',
               password_hash=hash_password('Sup!Pass123'),
               pos_pin_hash=hash_password(pin), created_at=utcnow())
    db.add(u)
    db.flush()
    db.add(m.UserRole(user_id=u.id, role_id=role.id))
    db.flush()
    return u


# ═══ قبول #3 (04/قبول-3): المركّب يخصم مكونات الوصفة بالضبط ═══
def test_composite_deducts_recipe_components_exactly(db_session):
    """04/قبول-3: بيع 3 برجر كلاسيك = -3 خبز -3 لحم -3 جبن -3 بطاطس بالضبط."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet = _outlet(db, tid)
    before = {c: _stock(db, outlet.id, _item(db, tid, c).id)
              for c in ('BUN', 'BEEF-PAT', 'CHEESE-SL', 'FRIES-PT')}
    shift = _shift(db, tid, outlet)
    o = _order_with(db, tid, outlet, shift, [('BURGER-CL', 3, {})])
    out = _settle(db, tid, o, [{'method': 'CASH', 'amount': '28.5'}])
    inv = out['invoice']
    assert inv.net_total == Decimal('28.5000')
    expected_cost = D_(3) * (D_('0.35') + D_('2.2') + D_('0.3') + D_('0.8'))
    assert inv.cost_total == expected_cost == Decimal('10.9500')
    for c, each in (('BUN', 3), ('BEEF-PAT', 3), ('CHEESE-SL', 3), ('FRIES-PT', 3)):
        after = _stock(db, outlet.id, _item(db, tid, c).id)
        assert before[c] - after == D_(each), f'{c}: {before[c]}→{after}'
    # #13 — قيد التكلفة Dr 5101 / Cr 1210 بالمبلغ الدقيق
    cogs = db.get(m.JournalEntry, inv.cogs_entry_id)
    assert cogs is not None and cogs.journal_type == 'AUTO_POS'
    lines = db.execute(select(m.JournalLine).where(
        m.JournalLine.entry_id == cogs.id)).scalars().all()
    assert sum(D_(ln.debit_base) for ln in lines) == Decimal('10.9500')


def test_composite_without_recipe_cannot_sell(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet, shift = _outlet(db, tid), None
    cat = db.execute(select(m.PosCategory).where(
        m.PosCategory.tenant_id == tid)).scalars().first()
    it = m.PosItem(id=new_uuid(), tenant_id=tid, code='NORECIPE',
                   name_ar='طبق بلا وصفة', category_id=cat.id, price=10,
                   item_type='COMPOSITE')
    db.add(it)
    db.flush()
    shift = _shift(db, tid, outlet)
    o = _order_with(db, tid, outlet, shift, [('NORECIPE', 1, {})])
    with pytest.raises(PostingError) as exc:
        _settle(db, tid, o, [{'method': 'CASH', 'amount': '10'}])
    assert exc.value.code == 'POS.NO_RECIPE'


# ═══ قبول #1 (04/قبول-1): بيعة نقدية سريعة + كتالوج 3,000+ صنف ═══
def test_cash_sale_end_to_end_fast(db_session):
    """04/قبول-1: دورة بيع نقدية كاملة (فتح طلب+بنود+تسديد) أقل بكثير من 15 ث."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet = _outlet(db, tid)
    shift = _shift(db, tid, outlet)
    t0 = time.perf_counter()
    o = _order_with(db, tid, outlet, shift,
                    [('BURGER-CH', 1, {}), ('LATTE', 1, {}), ('WATER', 2, {})])
    db.commit()
    out = _settle(db, tid, o, [{'method': 'CASH', 'amount': '14'}])
    elapsed = time.perf_counter() - t0
    assert out['invoice'].net_total == Decimal('14.0000')
    assert elapsed < 15, f'بيعة بطيئة: {elapsed:.1f} ث'


def test_catalog_scales_paginated(client, db_session, auth_hdr):
    """04/قبول-1: 3,000 صنف إضافي والقائمة المصفحة مستقرة."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    cat = db.execute(select(m.PosCategory).where(
        m.PosCategory.tenant_id == tid)).scalars().first()
    db.add_all([m.PosItem(id=new_uuid(), tenant_id=tid, code=f'BULK-{i:05d}',
                          name_ar=f'صنف ضخم {i}', category_id=cat.id,
                          price=1, item_type='SERVICE') for i in range(3000)])
    db.commit()
    t0 = time.perf_counter()
    r = client.get('/api/pos/items?limit=500&offset=2500', headers=auth_hdr)
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200
    body = r.json()
    assert body['total'] >= 3023 and len(body['items']) == 500
    assert elapsed < 5, f'قائمة بطيئة: {elapsed:.1f} ث'


# ═══ قبول #2 (04/قبول-2): المحاسبة = التقرير = أحداث #10..13 ═══
def test_accounting_equals_report_equals_journal(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet = _outlet(db, tid)
    shift = _shift(db, tid, outlet)
    o1 = _order_with(db, tid, outlet, shift, [('BURGER-CL', 2, {})])     # 19
    _settle(db, tid, o1, [{'method': 'CASH', 'amount': '19'}])
    o2 = _order_with(db, tid, outlet, shift,
                     [('LATTE', 2, {}), ('TEA-ADANI', 2, {})])            # 10
    _settle(db, tid, o2, [{'method': 'CARD', 'amount': '10'}])
    o3 = _order_with(db, tid, outlet, shift, [('KUNAFA', 2, {})])         # 10
    _settle(db, tid, o3, [{'method': 'EWALLET', 'amount': '10'}])
    db.commit()
    # زاوية القيود: دائن حسابات الإيراد من قيود مصدرها POS_INVOICE
    q = (select(func.sum(m.JournalLine.credit_base))
         .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
         .join(m.Account, m.Account.id == m.JournalLine.account_id)
         .where(m.JournalLine.tenant_id == tid,
                m.Account.code.in_(('4201', '4202', '4203')),
                m.JournalEntry.source_type == 'POS_INVOICE',
                m.JournalEntry.status == 'POSTED'))
    journal_revenue = D_(db.execute(q).scalar() or 0)
    rep = ps.sales_report(db, tid, TODAY, TODAY, 'payment')
    report_total = sum(r['net'] for r in rep)
    pay_q = select(func.sum(m.PosPayment.amount)).where(
        m.PosPayment.tenant_id == tid)
    payments_total = D_(db.execute(pay_q).scalar() or 0)
    assert journal_revenue == report_total == payments_total == Decimal('39.0000')
    # القبض النقدي في 1102 يطابق سندات النقد
    cash_q = (select(func.sum(m.JournalLine.debit_base))
              .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
              .join(m.Account, m.Account.id == m.JournalLine.account_id)
              .where(m.JournalLine.tenant_id == tid, m.Account.code == '1102',
                     m.JournalEntry.source_type == 'POS_INVOICE'))
    assert D_(db.execute(cash_q).scalar() or 0) == Decimal('19.0000')


# ═══ قبول #4 (04/قبول-4): متانة انقطاع الشبكة أثناء البيع ═══
def test_network_reconnect_no_lost_invoice(db_session):
    """04/قبول-4: العميل أرسل ثم «انقطعت الشبكة» قبل وصول الرد؛ إعادة الإرسال
    بـ client_uuid نفسه ترجع الفاتورة ذاتها — بلا نسخة ولا قيد مكرر."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet = _outlet(db, tid)
    shift = _shift(db, tid, outlet)
    o = _order_with(db, tid, outlet, shift, [('BURGER-CL', 1, {}),
                                             ('SODA', 1, {})])
    uuid = CU()
    first = _settle(db, tid, o, [{'method': 'CASH', 'amount': '11'}],
                    client_uuid=uuid)
    entries_before = db.execute(select(func.count(m.JournalEntry.id))
                                ).scalar_one()
    # «الشبكة عادت» — المتصفح أعاد الإرسال من طابوره المحلي
    second = _settle(db, tid, o, [{'method': 'CASH', 'amount': '11'}],
                     client_uuid=uuid)
    entries_after = db.execute(select(func.count(m.JournalEntry.id))
                               ).scalar_one()
    assert second['replayed'] is True
    assert second['invoice'].id == first['invoice'].id
    assert entries_after == entries_before  # لا قيود جديدة إطلاقاً
    n = db.execute(select(func.count(m.PosInvoice.id)).where(
        m.PosInvoice.client_uuid == uuid)).scalar_one()
    assert n == 1


# ═══ قبول #5 (04/قبول-5): إلغاء/خصم/مرتجع = مستخدم + سبب + تدقيق ═══
def test_void_line_supervisor_reason_audit(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet = _outlet(db, tid)
    shift = _shift(db, tid, outlet)
    sup = _mk_supervisor(db, tid)
    o = _order_with(db, tid, outlet, shift,
                    [('BURGER-CL', 1, {}), ('TEA-ADANI', 1, {})])
    ps.fire_order(db, tenant_id=tid, order=o, actor_id='cashier-1')
    tea_line = db.execute(select(m.PosOrderLine).where(
        m.PosOrderLine.order_id == o.id,
        m.PosOrderLine.item_id == _item(db, tid, 'TEA-ADANI').id)
    ).scalar_one()
    with pytest.raises(PostingError) as exc:  # بلا سبب ممنوع
        ps.void_line(db, tenant_id=tid, order=o, line_id=tea_line.id,
                     reason='', actor_id=sup.id)
    assert exc.value.code == 'POS.REASON_REQUIRED'
    ps.void_line(db, tenant_id=tid, order=o, line_id=tea_line.id,
                 reason='العميل غيّر رأيه', actor_id=sup.id)
    db.flush()  # autoflush معطّل: أظهر الصف المعلق قبل الاستعلام
    rec = db.execute(select(m.AuditLog).where(
        m.AuditLog.action == 'order.line.void',
        m.AuditLog.entity_id == tea_line.id)).scalar_one()
    assert rec.actor_user_id == sup.id and 'غيّر' in str(rec.after)


def test_discount_over_cap_requires_manager_pin(db_session):
    """04/§3: خصم فوق حد الدور (50) = اعتماد مدير فوري بـ PIN + سبب."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet = _outlet(db, tid)
    shift = _shift(db, tid, outlet)
    sup = _mk_supervisor(db, tid, pin='9876')
    o = _order_with(db, tid, outlet, shift, [('KEBAB', 1, {})])  # 14
    # بلا سبب — مرفوض
    with pytest.raises(PostingError) as exc:
        _settle(db, tid, o, [{'method': 'CASH', 'amount': '12'}],
                invoice_discount=2, discount_reason='', perms={'pos.sell'})
    assert exc.value.code == 'POS.REASON_REQUIRED'
    # خصم 60 فوق حد الكاشير (50) بلا PIN — مرفوض
    o2 = _order_with(db, tid, outlet, shift, [('KEBAB', 5, {})])  # 70
    with pytest.raises(PostingError) as exc:
        _settle(db, tid, o2, [{'method': 'CASH', 'amount': '10'}],
                invoice_discount=60, discount_reason='زبون دائم',
                perms={'pos.sell'}, approver_pin='')
    assert exc.value.code == 'POS.APPROVAL_REQUIRED'
    # PIN خاطئ — مرفوض
    with pytest.raises(PostingError) as exc:
        _settle(db, tid, o2, [{'method': 'CASH', 'amount': '10'}],
                invoice_discount=60, discount_reason='زبون دائم',
                perms={'pos.sell'}, approver_pin='0000')
    assert exc.value.code == 'POS.BAD_APPROVER_PIN'
    # PIN المشرف الصحيح — يمر ومُسجَّل بالتدقيق
    out = _settle(db, tid, o2, [{'method': 'CASH', 'amount': '10'}],
                  invoice_discount=60, discount_reason='زبون دائم',
                  perms={'pos.sell'}, approver_pin='9876')
    inv = out['invoice']
    assert inv.net_total == Decimal('10.0000')
    db.flush()  # autoflush معطّل: أظهر الصف المعلق قبل الاستعلام
    rec = db.execute(select(m.AuditLog).where(
        m.AuditLog.action == 'invoice.settle.flags',
        m.AuditLog.entity_id == inv.id)).scalar_one()
    assert sup.id in str(rec.after)


def test_return_full_reversal_original_untouched(db_session):
    """04/§3.4: مرتجع بعد التسديد = فاتورة منفصلة + قيد عكسي كامل،
    الفاتورة الأصلية لا تُعدَّل بتاتاً."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet = _outlet(db, tid)
    water = _item(db, tid, 'WATER')
    s0 = _stock(db, outlet.id, water.id)
    shift = _shift(db, tid, outlet)
    o = _order_with(db, tid, outlet, shift, [('WATER', 4, {})])
    inv = _settle(db, tid, o, [{'method': 'CASH', 'amount': '4'}])['invoice']
    sale_entry_id = inv.sale_entry_id
    assert _stock(db, outlet.id, water.id) == s0 - 4
    with pytest.raises(PostingError) as exc:  # بلا سبب
        ps.return_invoice(db, tenant_id=tid, actor_id='sup-1',
                          invoice_id=inv.id, reason='x')
    assert exc.value.code == 'POS.REASON_REQUIRED'
    rinv = ps.return_invoice(db, tenant_id=tid, actor_id='sup-1',
                             invoice_id=inv.id, reason='منتج تالف')
    assert rinv.type == 'RETURN' and rinv.return_of_id == inv.id
    assert rinv.return_reason == 'منتج تالف'
    src = db.get(m.JournalEntry, sale_entry_id)   # الأصل: موسوم REVERSED فقط
    assert src.status == 'REVERSED'
    rev = db.get(m.JournalEntry, src.reversed_entry_id)
    assert rev is not None and rev.journal_type == 'REVERSAL'
    assert _stock(db, outlet.id, water.id) == s0  # المخزون عاد
    with pytest.raises(PostingError) as exc:  # مرتجع على مرتجع ممنوع
        ps.return_invoice(db, tenant_id=tid, actor_id='sup-1',
                          invoice_id=inv.id, reason='محاولة ثانية')
    assert exc.value.code == 'POS.ALREADY_RETURNED'


# ═══ المخزون: منع السالب افتراضياً / سماح بتنبيه (§3 قواعد صارمة) ═══
def test_negative_stock_blocked_by_default(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet = _outlet(db, tid)
    cat = db.execute(select(m.PosCategory).where(
        m.PosCategory.tenant_id == tid)).scalars().first()
    it = m.PosItem(id=new_uuid(), tenant_id=tid, code='NOSTOCK',
                   name_ar='صنف بلا رصيد', category_id=cat.id, price=5,
                   item_type='STOCK', cost=2)
    db.add(it)
    db.flush()
    shift = _shift(db, tid, outlet)
    o = ps.create_order(db, tenant_id=tid, actor_id='c1', outlet=outlet,
                        shift=shift, type_='TAKEAWAY')
    ps.add_line(db, tenant_id=tid, order=o, item_id=it.id, qty=1, actor_id='c1')
    with pytest.raises(PostingError) as exc:
        _settle(db, tid, o, [{'method': 'CASH', 'amount': '5'}])
    assert exc.value.code == 'POS.INSUFFICIENT_STOCK'
    # الطلب سليم بعد الرفض — لا قيود نصفية بعد التراجع (ذرية المعاملة V7)
    db.rollback()
    n_entries = db.execute(select(func.count(m.JournalEntry.id)).where(
        m.JournalEntry.source_type == 'POS_INVOICE')).scalar_one()
    assert n_entries == 0


def test_negative_stock_allowed_outlet_flags_alert(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    bid = seed['branch_id']
    outlet = m.PosOutlet(id=new_uuid(), tenant_id=tid, branch_id=bid,
                         code='NEG1', name_ar='منفذ تجريبي سالب',
                         allow_negative_stock=True, created_at=utcnow())
    db.add(outlet)
    db.flush()
    item = _item(db, tid, 'WATER')
    shift = _shift(db, tid, outlet)
    o = ps.create_order(db, tenant_id=tid, actor_id='c1', outlet=outlet,
                        shift=shift, type_='TAKEAWAY')
    ps.add_line(db, tenant_id=tid, order=o, item_id=item.id, qty=3,
                actor_id='c1')
    out = _settle(db, tid, o, [{'method': 'CASH', 'amount': '3'}],
                  client_uuid=CU())
    db.flush()
    rec = db.execute(select(m.AuditLog).where(
        m.AuditLog.action == 'invoice.settle.flags',
        m.AuditLog.entity_id == out['invoice'].id)).scalar_one()
    assert 'مياه معدنية' in str(rec.after)  # تنبيه السالب موثق
    assert _stock(db, outlet.id, item.id) == Decimal('-3.0000')


# ═══ التحميل على الغرفة (§4) — تكامل فندقي ثنائي الاتجاه ═══
def _checked_in_res(db, tid, room_no='101'):
    g = m.Guest(id=new_uuid(), tenant_id=tid, full_name='محمد أحمد سالم',
                created_at=utcnow())
    db.add(g)
    db.flush()
    rt = db.execute(select(m.RoomType).where(
        m.RoomType.tenant_id == tid, m.RoomType.code == 'SGL')).scalar_one()
    room = db.execute(select(m.Room).where(
        m.Room.tenant_id == tid, m.Room.room_no == room_no)).scalar_one()
    return walk_in(db, tenant_id=tid, branch_id=db.execute(
        select(m.Branch).where(m.Branch.tenant_id == tid)).scalar_one().id,
        guest_id=g.id, room_type_id=rt.id,
        departure=TODAY + timedelta(2), actor_id='recep', room_id=room.id)


def test_room_charge_full_flow_and_pos_only_void(db_session):
    """04/§4: غرفة مشغولة فقط، يظهر فوراً بالفوليو بتفاصيل المنفذ والفاتورة،
    والإلغاء فقط من POS بقيد عكسي."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    res = _checked_in_res(db, tid)
    rooms = ps.occupied_rooms(db, tid)
    assert len(rooms) == 1 and rooms[0]['room_no'] == '101'
    assert rooms[0]['guest_short'].startswith('محمد أحمد')
    folio_id = rooms[0]['folio_id']
    outlet = _outlet(db, tid)
    shift = _shift(db, tid, outlet)
    o = _order_with(db, tid, outlet, shift, [('BURGER-CL', 1, {}),
                                             ('ESPRESSO', 1, {})])
    out = _settle(db, tid, o, [{'method': 'ROOM', 'amount': '12',
                                'folio_id': folio_id}], client_uuid=CU())
    inv = out['invoice']
    assert folio_balance(db, tid, folio_id) == Decimal('12.0000')
    pay = db.execute(select(m.PosPayment).where(
        m.PosPayment.invoice_id == inv.id)).scalar_one()
    assert pay.room_no == '101' and pay.folio_id == folio_id
    entry = db.get(m.JournalEntry, inv.sale_entry_id)
    assert 'المطعم الرئيسي' in entry.narration and inv.invoice_no in (entry.reference or '')
    # الإلغاء من مصدر الحقيقة (POS) — قيد عكسي يصفّر أثر الشحنة
    ps.return_invoice(db, tenant_id=tid, actor_id='sup-1', invoice_id=inv.id,
                      reason='شحنة خطأ بالغرفة')
    assert folio_balance(db, tid, folio_id) == Decimal('0.0000')


def test_room_charge_rejects_unoccupied_room(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet, shift = _outlet(db, tid), None
    shift = _shift(db, tid, outlet)
    o = _order_with(db, tid, outlet, shift, [('TEA-ADANI', 1, {})])
    with pytest.raises(PostingError) as exc:
        _settle(db, tid, o, [{'method': 'ROOM', 'amount': '1.5',
                              'folio_id': 'ghost-folio'}])
    assert exc.value.code == 'POS.UNKNOWN_FOLIO'


# ═══ بيع آجل لشركة (§3) — سقف الائتمان ═══
def test_corporate_charge_credit_limit(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    corp = m.Corporate(id=new_uuid(), tenant_id=tid, name='شركة الاختبار',
                       credit_limit=Decimal('50'))
    db.add(corp)
    db.flush()
    outlet = _outlet(db, tid)
    shift = _shift(db, tid, outlet)
    o1 = _order_with(db, tid, outlet, shift, [('KEBAB', 2, {})])  # 28
    _settle(db, tid, o1, [{'method': 'CORPORATE', 'amount': '28',
                           'corporate_id': corp.id}])
    o2 = _order_with(db, tid, outlet, shift, [('TIKA', 2, {})])   # 24 > باقي 22
    with pytest.raises(PostingError) as exc:
        _settle(db, tid, o2, [{'method': 'CORPORATE', 'amount': '24',
                               'corporate_id': corp.id}])
    assert exc.value.code == 'POS.CORPORATE_LIMIT'


# ═══ مجاني مصرّح House Use (§3) — اعتماد + حساب مصروف ═══
def test_house_use_requires_pin_and_posts_6610(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    sup = _mk_supervisor(db, tid, pin='5555')
    outlet = _outlet(db, tid)
    shift = _shift(db, tid, outlet)
    o = _order_with(db, tid, outlet, shift, [('HUMMUS', 1, {})])  # 4
    with pytest.raises(PostingError) as exc:  # بلا سبب
        _settle(db, tid, o, [{'method': 'HOUSE', 'amount': '4',
                              'approver_pin': '5555', 'reason': ''}])
    assert exc.value.code == 'POS.REASON_REQUIRED'
    with pytest.raises(PostingError) as exc:  # بلا PIN
        _settle(db, tid, o, [{'method': 'HOUSE', 'amount': '4',
                              'reason': 'ضيافة إدارة'}])
    assert exc.value.code == 'POS.APPROVAL_REQUIRED'
    out = _settle(db, tid, o, [{'method': 'HOUSE', 'amount': '4',
                                'reason': 'ضيافة إدارة',
                                'approver_pin': '5555'}])
    inv = out['invoice']
    q = (select(m.JournalLine)
         .join(m.Account, m.Account.id == m.JournalLine.account_id)
         .where(m.JournalLine.entry_id == inv.sale_entry_id,
                m.Account.code == '6610'))
    ln = db.execute(q).scalar_one()
    assert D_(ln.debit_base) == Decimal('4.0000')
    pay = db.execute(select(m.PosPayment).where(
        m.PosPayment.invoice_id == inv.id)).scalar_one()
    assert pay.house_approved_by == sup.id and 'ضيافة' in pay.house_reason


# ═══ الدفع المتفرق Split (§2) ═══
def test_split_payment_must_match_total(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet, shift = _outlet(db, tid), None
    shift = _shift(db, tid, outlet)
    o = _order_with(db, tid, outlet, shift, [('BURGER-CL', 1, {}),
                                             ('SODA', 1, {})])     # 11
    with pytest.raises(PostingError) as exc:
        _settle(db, tid, o, [{'method': 'CASH', 'amount': '5'},
                             {'method': 'CARD', 'amount': '5'}])
    assert exc.value.code == 'POS.PAYMENT_MISMATCH'
    out = _settle(db, tid, o, [{'method': 'CASH', 'amount': '5'},
                               {'method': 'CARD', 'amount': '6'}],
                  client_uuid=CU())
    n = db.execute(select(func.count(m.PosPayment.id)).where(
        m.PosPayment.invoice_id == out['invoice'].id)).scalar_one()
    assert n == 2


# ═══ الورديات وZ-Report (§3.5) ═══
def test_shift_lifecycle_and_zreport_archive(db_session):
    """04/§5: Z-Report أرشيف غير قابل للتعديل + لا وردية قبل إقفال السابقة."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet = _outlet(db, tid)
    shift = _shift(db, tid, outlet, float_=50)
    with pytest.raises(PostingError) as exc:
        _shift(db, tid, outlet)
    assert exc.value.code == 'POS.SHIFT_ALREADY_OPEN'
    o = _order_with(db, tid, outlet, shift, [('BURGER-CL', 2, {})])  # 19
    _settle(db, tid, o, [{'method': 'CASH', 'amount': '11'},
                         {'method': 'CARD', 'amount': '8'}])
    # فرق ضمن التسامح: الفعلي 61.5 والمتوقع 50+11=61 → +0.5 زيادة عهدة
    z = ps.close_shift(db, tenant_id=tid, actor_id='cashier-1', shift=shift,
                       actual_cash=Decimal('61.5'))
    assert z['variance'] == '0.5000'
    ventry = db.execute(select(m.JournalEntry).where(
        m.JournalEntry.entry_no == z['variance_entry'])).scalar_one()
    lines = db.execute(select(m.JournalLine)
                       .join(m.Account, m.Account.id == m.JournalLine.account_id)
                       .where(m.JournalLine.entry_id == ventry.id,
                              m.Account.code == '4901')).scalar_one()
    assert D_(lines.credit_base) == Decimal('0.5000')
    shift2 = db.get(m.PosShift, shift.id)
    assert shift2.status == 'CLOSED' and shift2.zreport is not None
    _shift(db, tid, outlet)  # وردية جديدة بعد الإقفال — مسموح


def test_shift_close_over_tolerance_rejected(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet = _outlet(db, tid)
    shift = _shift(db, tid, outlet, float_=50)
    with pytest.raises(PostingError) as exc:
        ps.close_shift(db, tenant_id=tid, actor_id='c1', shift=shift,
                       actual_cash=Decimal('20'))  # -30 > تسامح 10
    assert exc.value.code == 'POS.VARIANCE_OVER_TOLERANCE'
    assert db.get(m.PosShift, shift.id).status == 'OPEN'


def test_shift_close_with_open_orders_rejected(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet, = [_outlet(db, tid)]
    shift = _shift(db, tid, outlet, float_=0)
    _order_with(db, tid, outlet, shift, [('TEA-ADANI', 1, {})])  # DRAFT مفتوح
    with pytest.raises(PostingError) as exc:
        ps.close_shift(db, tenant_id=tid, actor_id='c1', shift=shift,
                       actual_cash=Decimal('0'))
    assert exc.value.code == 'POS.OPEN_ORDERS'


def test_no_open_shift_blocks_orders(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet = _outlet(db, tid)
    with pytest.raises(PostingError) as exc:
        ps.open_shift_or_err(db, tid, outlet.id)
    assert exc.value.code == 'POS.NO_OPEN_SHIFT'


# ═══ دورة الطلب ═══
def test_order_state_machine(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet, shift = _outlet(db, tid), None
    shift = _shift(db, tid, outlet)
    o = ps.create_order(db, tenant_id=tid, actor_id='c1', outlet=outlet,
                        shift=shift, type_='TAKEAWAY')
    with pytest.raises(PostingError) as exc:  # إرسال فارغ ممنوع
        ps.fire_order(db, tenant_id=tid, order=o, actor_id='c1')
    assert exc.value.code == 'POS.EMPTY_ORDER'
    line = ps.add_line(db, tenant_id=tid, order=o,
                       item_id=_item(db, tid, 'LATTE').id, qty=1,
                       actor_id='c1')
    ps.fire_order(db, tenant_id=tid, order=o, actor_id='c1')
    with pytest.raises(PostingError) as exc:  # إضافة بعد الإرسال ممنوعة
        ps.add_line(db, tenant_id=tid, order=o,
                    item_id=_item(db, tid, 'WATER').id, qty=1, actor_id='c1')
    assert exc.value.code == 'POS.ORDER_NOT_DRAFT'
    with pytest.raises(PostingError) as exc:  # إعادة إرسال ممنوعة
        ps.fire_order(db, tenant_id=tid, order=o, actor_id='c1')
    assert exc.value.code == 'POS.BAD_STATE'


def test_modifiers_snapshotted_and_restricted(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet, shift = _outlet(db, tid), None
    shift = _shift(db, tid, outlet)
    burger = _item(db, tid, 'BURGER-CL')
    extra_cheese = db.execute(select(m.PosModifier).where(
        m.PosModifier.tenant_id == tid,
        m.PosModifier.name_ar == 'إكسترا جبن')).scalar_one()
    oat = db.execute(select(m.PosModifier).where(
        m.PosModifier.tenant_id == tid,
        m.PosModifier.name_ar == 'حليب شوفان')).scalar_one()
    o = ps.create_order(db, tenant_id=tid, actor_id='c1', outlet=outlet,
                        shift=shift, type_='TAKEAWAY')
    ln = ps.add_line(db, tenant_id=tid, order=o, item_id=burger.id, qty=1,
                     actor_id='c1', modifiers=[{'id': extra_cheese.id}])
    assert ln.line_total == Decimal('10.5000')  # 9.5 + 1
    with pytest.raises(PostingError) as exc:  # حليب شوفان غير مسموح للبرجر
        ps.add_line(db, tenant_id=tid, order=o, item_id=burger.id, qty=1,
                    actor_id='c1', modifiers=[{'id': oat.id}])
    assert exc.value.code == 'POS.BAD_MODIFIER'


def test_table_busy_conflict(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet, shift = _outlet(db, tid), None
    shift = _shift(db, tid, outlet)
    table = db.execute(select(m.PosTable).where(
        m.PosTable.outlet_id == outlet.id, m.PosTable.name == 'طاولة 1')
    ).scalar_one()
    ps.create_order(db, tenant_id=tid, actor_id='c1', outlet=outlet,
                    shift=shift, type_='DINE_IN', table_id=table.id)
    with pytest.raises(PostingError) as exc:
        ps.create_order(db, tenant_id=tid, actor_id='c2', outlet=outlet,
                        shift=shift, type_='DINE_IN', table_id=table.id)
    assert exc.value.code == 'POS.TABLE_BUSY'


# ═══ RBAC عبر HTTP ═══
def _mk_cashier(db, tid):
    role = db.execute(select(m.Role).where(
        m.Role.tenant_id == tid, m.Role.code == 'POS_CASHIER')).scalar_one()
    u = m.User(id=new_uuid(), tenant_id=tid, username='cashier9',
               full_name='كاشير تسعة',
               password_hash=hash_password('Cash!Pass123'), created_at=utcnow())
    db.add(u)
    db.flush()
    db.add(m.UserRole(user_id=u.id, role_id=role.id))
    db.commit()
    return u


def test_rbac_cashier_cannot_void_or_close_catalog(client, db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    _mk_cashier(db, tid)
    r = client.post('/api/auth/login',
                    json={'username': 'cashier9', 'password': 'Cash!Pass123'})
    hdr = {'Authorization': f"Bearer {r.json()['access_token']}"}
    outlet = _outlet(db, tid)
    shift = _shift(db, tid, outlet)
    db.commit()
    o = _order_with(db, tid, outlet, shift, [('TEA-ADANI', 1, {})])
    db.commit()
    ln = db.execute(select(m.PosOrderLine).where(
        m.PosOrderLine.order_id == o.id)).scalar_one()
    r = client.post(f'/api/pos/orders/{o.id}/lines/{ln.id}/void',
                    json={'reason': 'خطأ إدخال'}, headers=hdr)
    assert r.status_code == 403
    r = client.post('/api/pos/items', json={
        'code': 'HACK-1', 'name_ar': 'محاولة', 'category_id': 'x',
        'price': 1, 'item_type': 'SERVICE'}, headers=hdr)
    assert r.status_code == 403
    r = client.post('/api/pos/shifts/open',
                    json={'outlet_id': outlet.id, 'opening_float': 10},
                    headers=hdr)
    assert r.status_code == 400  # توجد وردية مفتوحة (الكاشير يملك فتح وردية)


def test_settle_via_http_full(client, db_session, auth_hdr):
    """مسار HTTP كامل: فتح وردية → طلب → بند → تسديد نقدي → إعادة إرسال."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet = _outlet(db, tid)
    r = client.post('/api/pos/shifts/open',
                    json={'outlet_id': outlet.id, 'opening_float': 20},
                    headers=auth_hdr)
    assert r.status_code == 201
    db.expire_all()
    r = client.post('/api/pos/orders',
                    json={'outlet_id': outlet.id, 'type': 'TAKEAWAY'},
                    headers=auth_hdr)
    assert r.status_code == 201, r.text
    oid = r.json()['id']
    burger = _item(db, tid, 'BURGER-CL')
    r = client.post(f'/api/pos/orders/{oid}/lines',
                    json={'item_id': burger.id, 'qty': 1, 'modifiers': []},
                    headers=auth_hdr)
    assert r.status_code == 201, r.text
    uuid = CU()
    r = client.post(f'/api/pos/orders/{oid}/settle',
                    json={'client_uuid': uuid,
                          'payments': [{'method': 'CASH', 'amount': 9.5}]},
                    headers=auth_hdr)
    assert r.status_code == 201, r.text
    assert r.json()['invoice']['invoice_no'].startswith('REST-')
    assert float(r.json()['invoice']['net_total']) == 9.5
    r2 = client.post(f'/api/pos/orders/{oid}/settle',
                     json={'client_uuid': uuid,
                           'payments': [{'method': 'CASH', 'amount': 9.5}]},
                     headers=auth_hdr)
    assert r2.json()['replayed'] is True
    assert r2.json()['invoice']['id'] == r.json()['invoice']['id']
    # Z عبر HTTP
    sh = db.execute(select(m.PosShift).where(
        m.PosShift.outlet_id == outlet.id,
        m.PosShift.status == 'OPEN')).scalar_one()
    r = client.post(f'/api/pos/shifts/{sh.id}/close',
                    json={'actual_cash': 29.5}, headers=auth_hdr)
    assert r.status_code == 200, r.text
    assert r.json()['variance'] == '0.0000'
    r = client.get(f'/api/pos/shifts/{sh.id}/zreport', headers=auth_hdr)
    assert r.json()['status'] == 'CLOSED'


def test_audit_chain_intact_after_pos_activity(db_session):
    """سلسلة التدقيق تظل سليمة بعد كل عمليات POS (حماية العبث)."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    outlet, shift = _outlet(db, tid), None
    shift = _shift(db, tid, outlet)
    o = _order_with(db, tid, outlet, shift, [('BURGER-CL', 1, {})])
    _settle(db, tid, o, [{'method': 'CASH', 'amount': '9.5'}])
    ps.close_shift(db, tenant_id=tid, actor_id='c1', shift=shift,
                   actual_cash=Decimal('109.5'))
    assert verify_chain(db, tid)['ok'] is True
