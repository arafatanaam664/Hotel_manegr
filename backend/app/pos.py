"""خدمات وحدة نقاط البيع — ملف 04 (POS_MODULE_SPEC) كقانون ملزم:
- §3 دورة الفاتورة: مسودة بلا أثر → Fire → إقفال وتسديد ذري واحد
- الأحداث #10 نقدي/بنكي، #11 على الغرفة، #12 على شركة، #13 تكلفة تلقائية
- House Use: Dr حساب مصروف المنفذ (6610) باعتماد مدير PIN + سبب
- §4 الشحن على الغرفة: غرفة مشغولة + فوليو مفتوح + ضمن سقف الائتمان،
  والإلغاء فقط من POS بقيد عكسي (مصدر الحقيقة)
- §3.5 Z-Report: عدّ فعلي مقابل نظام، فرق ضمن التسامح ← CASH_OVER/SHORT،
  أرشيف غير قابل للتعديل، ولا وردية جديدة قبل إقفال السابقة
- قبول #4 متانة الشبكة: client_uuid فريد + إعادة الإرسال ترجع الفاتورة نفسها
- قبول #5: كل إلغاء/خصم/مرتجع مرتبط بمستخدم + سبب + Audit"""
import re
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m
from .audit import audit
from .hotel import get_business_date, folio_balance, current_tax_rate
from .posting import (D, PostingError, create_and_post_journal, post_event,
                      reverse_entry)
from .security import new_uuid, utcnow, hash_password, verify_password

CITY_LEDGER = '1120'
GUEST_LEDGER = '1110'
# سقف الخصم الذاتي لمن لا يملك pos.approve (فوقه اعتماد PIN إلزامي — §3)
POS_DISCOUNT_CAP = Decimal('50')
PAYMENT_METHODS = ('CASH', 'CARD', 'EWALLET', 'ROOM', 'CORPORATE', 'HOUSE')
# الوسيلة ← حساب المقبوض الثابت (التفاصيل عبر قراءة نقدية المنفذ للنقد)
CASHLESS_ACCOUNT = {'CARD': '1103', 'EWALLET': '1104'}


def err(code: str, message: str):
    raise PostingError(code, message)


def _q4(v) -> Decimal:
    return D(v)


# ────────────────────────────────────────────────────────────────────
# أدوات تحقق أساسية
# ────────────────────────────────────────────────────────────────────
def outlet_or_err(db: Session, tenant_id: str, outlet_id_or_code: str) -> m.PosOutlet:
    q = select(m.PosOutlet).where(m.PosOutlet.tenant_id == tenant_id)
    row = db.execute(q.where(m.PosOutlet.id == outlet_id_or_code)
                     ).scalar_one_or_none()
    if row is None:
        row = db.execute(select(m.PosOutlet).where(
            m.PosOutlet.tenant_id == tenant_id,
            m.PosOutlet.code == outlet_id_or_code)).scalar_one_or_none()
    if row is None:
        err('POS.UNKNOWN_OUTLET', f'منفذ بيع غير موجود: {outlet_id_or_code}')
    if not row.is_active:
        err('POS.OUTLET_INACTIVE', 'منفذ البيع موقوف')
    return row


def item_or_err(db: Session, tenant_id: str, item_id: str) -> m.PosItem:
    it = db.get(m.PosItem, item_id)
    if it is None or it.tenant_id != tenant_id:
        err('POS.UNKNOWN_ITEM', 'صنف غير موجود')
    if not it.is_active:
        err('POS.ITEM_INACTIVE', f'الصنف «{it.name_ar}» موقوف عن البيع')
    return it


def order_or_err(db: Session, tenant_id: str, order_id: str) -> m.PosOrder:
    o = db.get(m.PosOrder, order_id)
    if o is None or o.tenant_id != tenant_id:
        err('POS.UNKNOWN_ORDER', 'طلب غير موجود')
    return o


def open_shift_or_err(db: Session, tenant_id: str, outlet_id: str,
                      shift_id: str | None = None) -> m.PosShift:
    if shift_id:
        sh = db.get(m.PosShift, shift_id)
        if sh is None or sh.tenant_id != tenant_id or sh.outlet_id != outlet_id:
            err('POS.UNKNOWN_SHIFT', 'وردية غير موجودة لهذا المنفذ')
    else:
        sh = db.execute(select(m.PosShift).where(
            m.PosShift.tenant_id == tenant_id,
            m.PosShift.outlet_id == outlet_id,
            m.PosShift.status == 'OPEN')).scalar_one_or_none()
    if sh is None:
        err('POS.NO_OPEN_SHIFT', 'لا توجد وردية مفتوحة — افتح وردية أولاً')
    if sh.status != 'OPEN':
        err('POS.SHIFT_CLOSED', 'الوردية مقفلة — الترحيل في Z-Report أرشيفي')
    return sh


def _lock_order(db: Session, order_id: str) -> m.PosOrder:
    return db.execute(select(m.PosOrder).where(m.PosOrder.id == order_id)
                      .with_for_update()).scalar_one()


def _branch(db: Session, tenant_id: str) -> m.Branch:
    return db.execute(select(m.Branch).where(m.Branch.tenant_id == tenant_id)
                      .limit(1)).scalar_one()


def next_invoice_no(db: Session, tenant_id: str, outlet: m.PosOutlet,
                    d: date) -> str:
    """تسلسل فواتير مستقل لكل منفذ (§1) — مقفل صفّياً ضد الفجوات (V8)."""
    kind = f'POSI:{outlet.code}'
    row = db.execute(select(m.SequenceCounter).where(
        m.SequenceCounter.tenant_id == tenant_id,
        m.SequenceCounter.kind == kind,
        m.SequenceCounter.year == d.year).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        row = m.SequenceCounter(tenant_id=tenant_id, kind=kind,
                                year=d.year, next_no=1)
        db.add(row)
        db.flush()
    no = row.next_no
    row.next_no = no + 1
    db.flush()
    return f'{outlet.code}-{d.year}-{no:06d}'


# ────────────────────────────────────────────────────────────────────
# اعتماد المدير بـ PIN (§3: خصم فوق حد الدور / مجاني مصرّح House Use)
# ────────────────────────────────────────────────────────────────────
def set_pos_pin(db: Session, *, user: m.User, pin: str, actor_id: str):
    if not re.fullmatch(r'\d{4,8}', pin or ''):
        err('POS.PIN_FORMAT', 'رقم PIN يجب أن يكون من 4 إلى 8 أرقام')
    user.pos_pin_hash = hash_password(pin)
    db.flush()
    audit(db, tenant_id=user.tenant_id, actor_id=actor_id, actor_type='user',
          module='pos', action='pos.pin.set', entity='users',
          entity_id=user.id, after={'pin_set': True})


def verify_approver_pin(db: Session, *, tenant_id: str, pin: str,
                        perm_holders: list[str]) -> m.User:
    """يبحث عن مستخدم نشط حامل للصلاحية والـPIN المطابق (اعتماد فوري §3)."""
    if not pin:
        err('POS.APPROVAL_REQUIRED', 'اعتماد مدير برقم PIN إلزامي هنا')
    users = db.execute(select(m.User).where(
        m.User.tenant_id == tenant_id, m.User.is_active.is_(True),
        m.User.pos_pin_hash.isnot(None), m.User.pos_pin_hash != '')
    ).scalars().all()
    for u in users:
        rids = [ur.role_id for ur in u.roles]
        if not rids:
            continue
        perms: set[str] = set()
        for r in db.execute(select(m.Role).where(m.Role.id.in_(rids))
                            ).scalars().all():
            perms.update(r.permissions or [])
        if '*' not in perms and not any(p in perms for p in perm_holders):
            continue
        if verify_password(pin, u.pos_pin_hash):
            return u
    err('POS.BAD_APPROVER_PIN',
        'رقم PIN غير صحيح أو لا يحمل صلاحية الاعتماد')


# ────────────────────────────────────────────────────────────────────
# دورة الطلب (§3): مسودة → Fire → إغلاق
# ────────────────────────────────────────────────────────────────────
def create_order(db: Session, *, tenant_id: str, actor_id: str,
                 outlet: m.PosOutlet, shift: m.PosShift,
                 type_: str = 'DINE_IN', table_id: str | None = None,
                 reservation_id: str | None = None,
                 note: str = '') -> m.PosOrder:
    if type_ not in ('DINE_IN', 'TAKEAWAY', 'ROOM_SERVICE'):
        err('POS.BAD_ORDER_TYPE', f'نوع طلب غير صالح: {type_}')
    if table_id:
        tb = db.get(m.PosTable, table_id)
        if tb is None or tb.outlet_id != outlet.id or not tb.is_active:
            err('POS.UNKNOWN_TABLE', 'طاولة غير موجودة في هذا المنفذ')
        conflict = db.execute(select(m.PosOrder).where(
            m.PosOrder.table_id == table_id,
            m.PosOrder.status.in_(('DRAFT', 'FIRED')))).first()
        if conflict:
            err('POS.TABLE_BUSY', 'الطاولة مشغولة بطلب مفتوح')
    o = m.PosOrder(id=new_uuid(), tenant_id=tenant_id, outlet_id=outlet.id,
                   shift_id=shift.id, table_id=table_id, type=type_,
                   status='DRAFT', room_reservation_id=reservation_id,
                   note=note, opened_by=actor_id, opened_at=utcnow())
    db.add(o)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='pos', action='order.create', entity='pos_orders',
          entity_id=o.id, after={'outlet': outlet.code, 'type': type_})
    return o


def _line_total(unit_price: Decimal, qty: Decimal,
                modifiers: list[dict]) -> Decimal:
    mods = sum(D(md.get('price', 0)) for md in modifiers)
    return ((unit_price + mods) * qty).quantize(Decimal('0.0001'))


def add_line(db: Session, *, tenant_id: str, order: m.PosOrder,
             item_id: str, qty, actor_id: str,
             modifiers: list[dict] | None = None, notes: str = '',
             discount=0) -> m.PosOrderLine:
    """إضافة بند لمسودة — السعر Snapshot لحظة الإضافة (ثبات تاريخي)."""
    if order.status != 'DRAFT':
        err('POS.ORDER_NOT_DRAFT',
            'البنود تُضاف في المسودة فقط — بعد الإرسال تُلغى بصلاحية مشرف')
    item = item_or_err(db, tenant_id, item_id)
    qty = D(qty)
    if qty <= 0:
        err('POS.BAD_QTY', 'الكمية يجب أن تكون موجبة')
    mods = modifiers or []
    # المعدلات المسموحة فقط (§2: تتبع الصنف في الفاتورة والتكلفة)
    allowed = db.execute(select(m.PosModifier).join(
        m.PosItemModifier, m.PosItemModifier.modifier_id == m.PosModifier.id
    ).where(m.PosItemModifier.item_id == item.id,
            m.PosModifier.is_active.is_(True))).scalars().all()
    by_id = {md.id: md for md in allowed}
    mods_snap = []
    for md in mods:
        ref = by_id.get(md.get('id'))
        if ref is None:
            err('POS.BAD_MODIFIER', f'معدِّل غير مسموح للصنف: {md.get("id")}')
        mods_snap.append({'id': ref.id, 'name': ref.name_ar,
                          'price': str(D(ref.price))})
    cat = db.get(m.PosCategory, item.category_id)
    ln = m.PosOrderLine(
        id=new_uuid(), tenant_id=tenant_id, order_id=order.id,
        item_id=item.id, item_name=item.name_ar,
        station=cat.station if cat else 'KITCHEN',
        qty=qty, unit_price=D(item.price), modifiers=mods_snap, notes=notes,
        line_total=_line_total(D(item.price), qty, mods_snap),
        discount=D(discount))
    if ln.discount < 0 or ln.discount >= ln.line_total:
        err('POS.BAD_DISCOUNT', 'خصم البند يجب أن يكون أقل من قيمته وغير سالب')
    db.add(ln)
    db.flush()
    return ln


def void_line(db: Session, *, tenant_id: str, order: m.PosOrder,
              line_id: str, reason: str, actor_id: str) -> m.PosOrderLine:
    """إلغاء بند قبل التسديد: بصلاحية مشرف + سبب + Audit — بلا أثر محاسبي
    (المخزون يُخصم عند التسديد وحده، قرار موثق ADR-0013)."""
    if not reason or len(reason.strip()) < 3:
        err('POS.REASON_REQUIRED', 'سبب الإلغاء إلزامي (٣+ أحرف)')
    ln = db.get(m.PosOrderLine, line_id)
    if ln is None or ln.order_id != order.id:
        err('POS.UNKNOWN_LINE', 'بند غير موجود في هذا الطلب')
    if ln.status == 'VOID':
        err('POS.LINE_ALREADY_VOID', 'البند ملغى مسبقاً')
    if order.status in ('CLOSED', 'CANCELLED'):
        err('POS.ORDER_LOCKED', 'الطلب مغلق — التصحيح بفاتورة مرتجع فقط')
    ln.status = 'VOID'
    ln.void_reason = reason.strip()
    ln.void_by = actor_id
    ln.voided_at = utcnow()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='pos', action='order.line.void', entity='pos_order_lines',
          entity_id=ln.id,
          after={'order': order.id, 'item': ln.item_name,
                 'qty': str(ln.qty), 'reason': ln.void_reason})
    return ln


def fire_order(db: Session, *, tenant_id: str, order: m.PosOrder,
               actor_id: str) -> m.PosOrder:
    """إرسال للتحضير (§3.2): يقسم تلقائياً لمطبخ/بار حسب تصنيف البند."""
    if order.status != 'DRAFT':
        err('POS.BAD_STATE', f'لا يمكن الإرسال من حالة {order.status}')
    active = db.execute(select(func.count(m.PosOrderLine.id)).where(
        m.PosOrderLine.order_id == order.id,
        m.PosOrderLine.status == 'NORMAL')).scalar_one()
    if not active:
        err('POS.EMPTY_ORDER', 'لا يمكن إرسال طلب بلا بنود فعالة')
    order = _lock_order(db, order.id)
    order.status = 'FIRED'
    order.fired_at = utcnow()
    order.version += 1
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='pos', action='order.fire', entity='pos_orders',
          entity_id=order.id, after={'lines': active})
    return order


def cancel_order(db: Session, *, tenant_id: str, order: m.PosOrder,
                 reason: str, actor_id: str) -> m.PosOrder:
    """إلغاء طلب كامل قبل التسديد — مشرف + سبب؛ كل بند يسجل إلغاءه."""
    if not reason or len(reason.strip()) < 3:
        err('POS.REASON_REQUIRED', 'سبب الإلغاء إلزامي')
    order = _lock_order(db, order.id)
    if order.status in ('CLOSED', 'CANCELLED'):
        err('POS.ORDER_LOCKED', 'الطلب مغلق مسبقاً')
    for ln in db.execute(select(m.PosOrderLine).where(
            m.PosOrderLine.order_id == order.id,
            m.PosOrderLine.status == 'NORMAL')).scalars().all():
        ln.status, ln.void_reason = 'VOID', f'إلغاء طلب: {reason.strip()}'
        ln.void_by, ln.voided_at = actor_id, utcnow()
    order.status = 'CANCELLED'
    order.cancel_reason = reason.strip()
    order.closed_at = utcnow()
    order.version += 1
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='pos', action='order.cancel', entity='pos_orders',
          entity_id=order.id, after={'reason': reason.strip()})
    return order


# ────────────────────────────────────────────────────────────────────
# المخزون التشغيلي — خصم #13 وقت التسديد بالضبط (§3 قواعد صارمة)
# ADR-0017 (المرحلة 5): دفتر المخزون الموحّد في app/inventory.py هو مصدر
# الحقيقة؛ مستودع المنفذ (OUTLET) يخصم بالمتوسط المرجح المتحرك لحظة البيع
# (ملف 05 §4: قيد التكلفة بتكلفة لحظة البيع المخزنة على سطره).
# ────────────────────────────────────────────────────────────────────
def _inv_for_pos_item(db: Session, tenant_id: str, pos_item_id: str) -> m.InvItem:
    from . import inventory as inv_mod
    pos_item = db.get(m.PosItem, pos_item_id)
    if pos_item is None:
        err('POS.UNKNOWN_ITEM', f'صنف بيع غير موجود: {pos_item_id}')
    return inv_mod.auto_link_pos_item(db, tenant_id=tenant_id,
                                      pos_item=pos_item)


def _deduct_stock(db: Session, *, tenant_id: str, outlet: m.PosOutlet,
                  item_id: str, qty: Decimal, actor_id: str,
                  ref_id: str) -> tuple[Decimal, bool]:
    """يخصم الكمية من مستودع المنفذ بالمتوسط المتحرك لحظتها ويرجع
    (التكلفة الممتدة الفعلية، نُقص بالسالب مسموح) — الخصم ذري محروس."""
    from . import inventory as inv_mod
    wh = inv_mod.outlet_warehouse(db, tenant_id, outlet)
    inv_item = _inv_for_pos_item(db, tenant_id, item_id)
    bd = get_business_date(db, tenant_id)
    try:
        mv, applied, went_negative = inv_mod.apply_outbound(
            db, tenant_id=tenant_id, warehouse=wh, item_id=inv_item.id,
            qty=qty, reason='SALE_POS', ref_type='POS', ref_id=ref_id,
            actor_id=actor_id, bd=bd,
            allow_negative=outlet.allow_negative_stock)
    except Exception as exc:
        if isinstance(exc, PostingError) and \
                exc.code == 'INV.INSUFFICIENT_STOCK':
            item = db.get(m.PosItem, item_id)
            raise PostingError(
                'POS.INSUFFICIENT_STOCK',
                f'رصيد «{item.name_ar if item else item_id}» لا يكفي — {exc.message}')
        raise
    return (applied * qty).quantize(Decimal('0.0001')), went_negative


def load_stock(db: Session, *, tenant_id: str, outlet: m.PosOutlet,
               item_id: str, qty, unit_cost, actor_id: str,
               event_key: str | None = None) -> dict:
    """إدخال رصيد (فتح/توريد مبسّط) — أثر محاسبي STOCK_OPEN_POS عبر المحرك
    وإدخال لدفتر المخزون الموحد بالتكلفة نفسها (ثبات القيمة)."""
    from . import inventory as inv_mod
    item = item_or_err(db, tenant_id, item_id)
    qty, unit_cost = D(qty), D(unit_cost)
    if qty <= 0 or unit_cost < 0:
        err('POS.BAD_STOCK', 'كمية/تكلفة الإدخال غير صالحة')
    wh = inv_mod.outlet_warehouse(db, tenant_id, outlet)
    inv_item = _inv_for_pos_item(db, tenant_id, item_id)
    bd = get_business_date(db, tenant_id)
    if qty * unit_cost > 0:
        post_event(db, tenant_id=tenant_id, branch_code='MAIN',
                   event_type='STOCK_OPEN_POS',
                   event_key=event_key or f'posstock:load:{outlet.code}:{item.code}:{new_uuid()}',
                   entry_date=bd, amounts={'amount': str(qty * unit_cost)},
                   actor_id=actor_id,
                   narration=f'إدخال مخزون {item.name_ar} × {qty} @ {unit_cost}')
    mv, _ = inv_mod.apply_inbound(
        db, tenant_id=tenant_id, warehouse=wh, item_id=inv_item.id,
        qty=qty, unit_cost=unit_cost, reason='OPENING', ref_type='POS_LOAD',
        ref_id=event_key or new_uuid(), actor_id=actor_id, bd=bd)
    db.flush()
    stock = inv_mod._stock_row(db, tenant_id, wh.id, inv_item.id)
    return {'item_id': item_id, 'pos_item_code': item.code,
            'qty_on_hand': D(stock.qty_on_hand)}


def invoice_components(db: Session, tenant_id: str,
                       lines: list[m.PosOrderLine]) -> tuple[list[dict], Decimal]:
    """يفك البنود لمكوناتها (قبول #3): مركّب←وصفة بالحرف، مخزوني←ذاته،
    خدمي←لا شيء. يرجع قائمة مكونات مجمعة والتكلفة الإجمالية."""
    comp: dict[str, Decimal] = {}
    for ln in lines:
        if ln.status != 'NORMAL':
            continue
        item = db.get(m.PosItem, ln.item_id)
        if item is None or item.item_type == 'SERVICE':
            continue
        if item.item_type == 'STOCK':
            comp[str(ln.item_id)] = comp.get(str(ln.item_id), Decimal('0')) + D(ln.qty)
        else:  # COMPOSITE — وصفة إلزامية
            recipe = db.execute(select(m.PosRecipe).where(
                m.PosRecipe.tenant_id == tenant_id,
                m.PosRecipe.parent_item_id == item.id)).scalars().all()
            if not recipe:
                err('POS.NO_RECIPE',
                    f'الصنف المركب «{item.name_ar}» بلا وصفة — يمنع البيع')
            for r in recipe:
                cid = str(r.component_item_id)
                comp[cid] = comp.get(cid, Decimal('0')) + D(r.qty) * D(ln.qty)
    total_cost = Decimal('0')
    resolved = []
    for cid, qty in comp.items():
        item = db.get(m.PosItem, cid)
        c = (D(item.cost) if item else Decimal('0'))
        resolved.append({'item_id': cid, 'qty': qty, 'unit_cost': c,
                         'name': item.name_ar if item else cid})
        total_cost += (c * qty).quantize(Decimal('0.0001'))
    return resolved, total_cost


# ────────────────────────────────────────────────────────────────────
# التحقق من وسائل الدفع (§2/§3/§4)
# ────────────────────────────────────────────────────────────────────
def _corporate_balance(db: Session, tenant_id: str, corporate_id: str) -> Decimal:
    q = (select(func.sum(m.JournalLine.debit_base),
                func.sum(m.JournalLine.credit_base))
         .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
         .join(m.Account, m.Account.id == m.JournalLine.account_id)
         .where(m.JournalLine.tenant_id == tenant_id,
                m.Account.code == CITY_LEDGER,
                m.JournalLine.party_id == corporate_id,
                m.JournalEntry.status.in_(['POSTED', 'REVERSED'])))
    td, tc = db.execute(q).one()
    return D(td or 0) - D(tc or 0)


def _validate_payment(db: Session, *, tenant_id: str, pay: dict,
                      actor_perms: set[str]) -> dict:
    """يدقق وسيلة دفع واحدة ويرجع سطر القيد المدين الجاهز + سجل الدفع."""
    method = pay.get('method')
    amount = D(pay.get('amount', 0))
    if method not in PAYMENT_METHODS:
        err('POS.BAD_METHOD', f'وسيلة دفع غير صالحة: {method}')
    if amount <= 0:
        err('POS.BAD_AMOUNT', 'مبلغ الدفعة يجب أن يكون موجباً')
    rec = {'method': method, 'amount': amount}
    line = None
    if method == 'ROOM':
        # §4: غرفة مشغولة فقط + فوليو مفتوح + ضمن سقف الائتمان
        folio_id = pay.get('folio_id')
        folio = db.get(m.Folio, folio_id) if folio_id else None
        if folio is None or folio.tenant_id != tenant_id:
            err('POS.UNKNOWN_FOLIO', 'الفوليو المستهدف غير موجود')
        if folio.status != 'OPEN':
            err('POS.FOLIO_CLOSED', 'الفوليو مقفل')
        res = db.get(m.Reservation, folio.reservation_id)
        if res is None or res.status != 'CHECKED_IN':
            err('POS.ROOM_NOT_OCCUPIED',
                'الغرفة غير مشغولة — التحميل للغرف المشغولة فقط')
        bal = folio_balance(db, tenant_id, folio.id)
        if folio.credit_limit and (bal + amount) > folio.credit_limit:
            err('POS.FOLIO_LIMIT',
                f'يتجاوز سقف الفوليو ({folio.credit_limit}) — الرصيد {bal}')
        room = db.get(m.Room, res.room_id) if res.room_id else None
        line = {'account': GUEST_LEDGER, 'debit': amount, 'credit': Decimal('0'),
                'party_type': 'GUEST', 'party_id': folio.id,
                'description': f'شحنة POS — غرفة {room.room_no if room else "?"}'}
        rec.update({'folio_id': folio.id,
                    'room_no': room.room_no if room else None})
    elif method == 'CORPORATE':
        corp_id = pay.get('corporate_id')
        corp = db.get(m.Corporate, corp_id) if corp_id else None
        if corp is None or corp.tenant_id != tenant_id or not corp.is_active:
            err('POS.UNKNOWN_CORPORATE', 'شركة غير موجودة أو موقوفة')
        cb = _corporate_balance(db, tenant_id, corp.id)
        if corp.credit_limit and (cb + amount) > corp.credit_limit:
            err('POS.CORPORATE_LIMIT',
                f'يتجاوز سقف ائتمان الشركة ({corp.credit_limit}) — الذمة {cb}')
        line = {'account': CITY_LEDGER, 'debit': amount, 'credit': Decimal('0'),
                'party_type': 'CORPORATE', 'party_id': corp.id,
                'description': f'بيع POS آجل — {corp.name}'}
        rec['corporate_id'] = corp.id
    elif method == 'HOUSE':
        # مجاني مصرّح: اعتماد مدير PIN + سبب (§3 — معالجة موثقة Dr 6610)
        reason = (pay.get('reason') or '').strip()
        if len(reason) < 3:
            err('POS.REASON_REQUIRED', 'سبب الضيافة/الاستخدام الداخلي إلزامي')
        approver = verify_approver_pin(db, tenant_id=tenant_id,
                                       pin=pay.get('approver_pin', ''),
                                       perm_holders=['pos.approve'])
        rec.update({'house_approved_by': approver.id, 'house_reason': reason})
        line = {'account': '__HOUSE__', 'debit': amount, 'credit': Decimal('0'),
                'description': f'مجاني مصرّح — {reason} (اعتماد: {approver.full_name})'}
    else:  # CASH / CARD / EWALLET
        acct = '__CASH__' if method == 'CASH' else CASHLESS_ACCOUNT[method]
        line = {'account': acct, 'debit': amount, 'credit': Decimal('0'),
                'description': f'تحصيل {method}'}
    return {'record': rec, 'line': line}


# ────────────────────────────────────────────────────────────────────
# الإقفال والتسديد (§3.2) — ذري واحد: فاتورة + قيد بيع + #13 + مخزون
# ────────────────────────────────────────────────────────────────────
def settle_order(db: Session, *, tenant_id: str, actor_id: str,
                 actor_perms: set[str], order: m.PosOrder,
                 payments: list[dict], client_uuid: str,
                 invoice_discount=0, discount_reason: str = '',
                 approver_pin: str = '') -> dict:
    """ينشئ فاتورة CLOSED غير قابلة للتعديل + أثرها المحاسبي الكامل.
    قبول #4: إعادة الإرسال بنفس client_uuid ترجع الفاتورة نفسها (لا نسخة)."""
    if not client_uuid or len(client_uuid) < 8:
        err('POS.CLIENT_UUID_REQUIRED', 'مفتاح client_uuid إلزامي (شبكة آمنة)')
    previous = db.execute(select(m.PosInvoice).where(
        m.PosInvoice.tenant_id == tenant_id,
        m.PosInvoice.client_uuid == client_uuid)).scalar_one_or_none()
    if previous is not None:
        return {'invoice': previous, 'replayed': True}

    order = _lock_order(db, order.id)
    if order.status not in ('DRAFT', 'FIRED'):
        err('POS.ORDER_LOCKED', f'الطلب بحالة {order.status} — لا تسديد')
    lines = db.execute(select(m.PosOrderLine).where(
        m.PosOrderLine.order_id == order.id,
        m.PosOrderLine.status == 'NORMAL').order_by(m.PosOrderLine.id)
    ).scalars().all()
    if not lines:
        err('POS.EMPTY_ORDER', 'لا بنود فعالة للتسديد')

    outlet = db.get(m.PosOutlet, order.outlet_id)
    bd = get_business_date(db, tenant_id)
    tax_rate = current_tax_rate(db, tenant_id)
    inv_discount = D(invoice_discount)

    # المجاميع + توزيع الإيراد حسب حسابات الأصناف (سلة مختلطة §6)
    gross = sum(D(ln.line_total) for ln in lines)
    line_discounts = sum(D(ln.discount) for ln in lines)
    total_discount = line_discounts + inv_discount
    if inv_discount < 0:
        err('POS.BAD_DISCOUNT', 'خصم الفاتورة سالب ممنوع')
    if total_discount >= gross:
        err('POS.BAD_DISCOUNT', 'الخصم يلتهم الفاتورة كاملة — ممنوع')
    # الخصم فوق حد الدور = اعتماد مدير فوري بـ PIN (§3 «قواعد صارمة»)
    approver = None
    if total_discount > 0:
        if not discount_reason or len(discount_reason.strip()) < 3:
            err('POS.REASON_REQUIRED', 'سبب الخصم إلزامي')
        if total_discount > POS_DISCOUNT_CAP and 'pos.approve' not in actor_perms:
            approver = verify_approver_pin(
                db, tenant_id=tenant_id, pin=approver_pin,
                perm_holders=['pos.approve'])

    net_after = gross - total_discount
    # الإيراد لكل حساب: (بند − حصته من خصم الفاتورة بالتناسب) ثم فصل الضريبة.
    # توزيع بالباقي (remainder) حتى يساوي مجموع الدائن المدين بالحلة (V1).
    revenue_by_acct: dict[str, Decimal] = {}
    tax_total = Decimal('0')
    distributable = gross - line_discounts
    acc_share = Decimal('0')
    bases: list[tuple[str, Decimal]] = []
    for i, ln in enumerate(lines):
        item = db.get(m.PosItem, ln.item_id)
        acct = (item.revenue_account_code if item and item.revenue_account_code
                else outlet.default_revenue_account_code)
        base = D(ln.line_total) - D(ln.discount)
        if inv_discount > 0 and distributable > 0:
            if i == len(lines) - 1:  # البند الأخير يحمل باقي التوزيع
                share = inv_discount - acc_share
            else:
                share = (base * inv_discount / distributable
                         ).quantize(Decimal('0.0001'))
                acc_share += share
            base = base - share
        bases.append((acct, base))
    for acct, base in bases:
        net, tax = base, Decimal('0')
        if tax_rate and tax_rate > 0:
            net = (base / (1 + tax_rate)).quantize(Decimal('0.0001'))
            tax = base - net
        revenue_by_acct[acct] = revenue_by_acct.get(acct, Decimal('0')) + net
        tax_total += tax
    # إن بقي فرق تقريب ضريبة (حلة) يُحمَّل على أكبر حساب إيراد — يمنع V1
    diff = net_after - (sum(revenue_by_acct.values()) + tax_total)
    if diff != 0:
        biggest = max(revenue_by_acct, key=lambda a: revenue_by_acct[a])
        revenue_by_acct[biggest] += diff

    # مدققات الدفع المتفرق (Split §2) — المجموع يطابق الصافي
    if not payments:
        err('POS.NO_PAYMENTS', 'سند دفع واحد على الأقل إلزامي')
    checks = [_validate_payment(db, tenant_id=tenant_id, pay=p,
                                actor_perms=actor_perms) for p in payments]
    pay_sum = sum(c['record']['amount'] for c in checks)
    if pay_sum != net_after:
        err('POS.PAYMENT_MISMATCH',
            f'مجموع السندات {pay_sum} ≠ صافي الفاتورة {net_after}')
    house_expense_acct = outlet.house_expense_account_code
    for c in checks:
        if c['line']['account'] == '__HOUSE__':
            c['line']['account'] = house_expense_acct
        elif c['line']['account'] == '__CASH__':
            c['line']['account'] = outlet.cash_account_code
    # دمج أسطر المدين المتماثلة (حساب + طرف)
    debit_map: dict[tuple, dict] = {}
    for c in checks:
        ln = c['line']
        key = (ln['account'], ln.get('party_id'))
        if key in debit_map:
            debit_map[key]['debit'] += ln['debit']
        else:
            debit_map[key] = dict(ln)

    # قيد البيع المركب (#10/#11/#12) عبر نواة المحرك نفسها (ADR-0012)
    raw_lines = list(debit_map.values())
    for acct, net in sorted(revenue_by_acct.items()):
        if net > 0:
            raw_lines.append({'account': acct, 'debit': Decimal('0'),
                              'credit': net, 'description': 'إيراد مبيعات POS'})
    if tax_total > 0:
        raw_lines.append({'account': '2210', 'debit': Decimal('0'),
                          'credit': tax_total, 'description': 'ضريبة مخرجات'})

    invoice_id = new_uuid()
    inv_no = next_invoice_no(db, tenant_id, outlet, bd)
    branch = _branch(db, tenant_id)
    methods = ','.join(sorted({c['record']['method'] for c in checks}))
    sale_entry = create_and_post_journal(
        db, tenant_id=tenant_id, branch_id=branch.id,
        journal_type='AUTO_POS', entry_date=bd,
        narration=f'فاتورة POS {inv_no} — {outlet.name_ar} ({methods})',
        raw_lines=raw_lines, actor_id=actor_id,
        source_type='POS_INVOICE', source_id=invoice_id,
        reference=inv_no, event_key=f'pos:sale:{client_uuid}')

    # #13: خصم المكونات بالوصفة بالضبط + قيد التكلفة الفعلية بالمتوسط
    # المتحرك لحظة البيع (ملف 05 §4) — مخزوني/مركّب فقط
    comps, _ = invoice_components(db, tenant_id, lines)
    negatives = []
    cost_total = Decimal('0')
    comp_cost: dict[str, Decimal] = {}   # pos_item_id ← متوسط التكلفة المطبق
    for c in comps:
        cost_i, neg = _deduct_stock(db, tenant_id=tenant_id, outlet=outlet,
                                    item_id=c['item_id'], qty=c['qty'],
                                    actor_id=actor_id, ref_id=invoice_id)
        cost_total += cost_i
        if c['qty'] > 0:
            comp_cost[str(c['item_id'])] = (cost_i / c['qty']).quantize(
                Decimal('0.0001'))
        if neg:
            negatives.append(c['name'])
    cogs_entry = None
    if cost_total > 0:
        cogs_entry = post_event(
            db, tenant_id=tenant_id, branch_code='MAIN',
            event_type='POS_COGS', event_key=f'pos:cogs:{client_uuid}',
            entry_date=bd, amounts={'cost': str(cost_total)},
            actor_id=actor_id,
            narration=f'تكلفة فاتورة {inv_no}')

    # الفاتورة + السندات (Snapshot كامل — إيصالات §5 ومرتجعات §3.4)
    # تكلفة الوحدة تُخزَّن على السطر نفسه: قيد التكلفة لا يُعاد حسابه
    # أثراً رجعياً حتى مع تغيّر المتوسط لاحقاً (ملف 05 §4 حرفياً)
    def _line_unit_cost(ln: m.PosOrderLine) -> str | None:
        it = db.get(m.PosItem, ln.item_id)
        if it is None or it.item_type == 'SERVICE':
            return None
        if it.item_type == 'STOCK':
            c = comp_cost.get(str(it.id))
            return str(c) if c is not None else None
        total_c = Decimal('0')
        for r in db.execute(select(m.PosRecipe).where(
                m.PosRecipe.parent_item_id == it.id)).scalars().all():
            total_c += D(r.qty) * comp_cost.get(str(r.component_item_id),
                                                Decimal('0'))
        return str(total_c.quantize(Decimal('0.0001')))
    snap = [{'item_id': ln.item_id, 'item': ln.item_name, 'qty': str(ln.qty),
             'unit_price': str(ln.unit_price), 'modifiers': ln.modifiers,
             'notes': ln.notes, 'total': str(ln.line_total),
             'discount': str(ln.discount),
             'unit_cost': _line_unit_cost(ln)}
            for ln in lines]
    inv = m.PosInvoice(
        id=invoice_id, tenant_id=tenant_id, outlet_id=outlet.id,
        order_id=order.id, shift_id=order.shift_id, invoice_no=inv_no,
        client_uuid=client_uuid, type='SALE', business_date=bd,
        gross_total=gross, discount_total=total_discount, tax_total=tax_total,
        net_total=net_after, cost_total=cost_total,
        sale_entry_id=sale_entry.id,
        cogs_entry_id=cogs_entry.id if cogs_entry else None,
        lines_snapshot=snap, issued_by=actor_id, issued_at=utcnow())
    db.add(inv)
    for c in checks:
        r = c['record']
        db.add(m.PosPayment(
            id=new_uuid(), tenant_id=tenant_id, invoice_id=invoice_id,
            method=r['method'], amount=r['amount'],
            folio_id=r.get('folio_id'), room_no=r.get('room_no'),
            corporate_id=r.get('corporate_id'),
            house_approved_by=r.get('house_approved_by'),
            house_reason=r.get('house_reason')))
    order.status = 'CLOSED'
    order.closed_at = utcnow()
    order.version += 1
    db.flush()

    if total_discount > 0 or negatives:
        audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
              module='pos', action='invoice.settle.flags', entity='pos_invoices',
              entity_id=invoice_id,
              after={'invoice_no': inv_no,
                     'discount': {'amount': str(total_discount),
                                  'reason': discount_reason.strip(),
                                  'approved_by': approver.id if approver else ('self' if 'pos.approve' in actor_perms else 'under-cap')},
                     'negative_stock_alert': negatives},
              business_date=bd)
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='pos', action='invoice.settle', entity='pos_invoices',
          entity_id=invoice_id,
          after={'invoice_no': inv_no, 'net': str(net_after),
                 'entries': [sale_entry.entry_no]+([cogs_entry.entry_no] if cogs_entry else [])},
          business_date=bd)
    return {'invoice': inv, 'replayed': False}


# ────────────────────────────────────────────────────────────────────
# المرتجع بعد التسديد (§3.4): فاتورة منفصلة + قيد عكسي كامل — الأصل لا يُمس
# ────────────────────────────────────────────────────────────────────
def return_invoice(db: Session, *, tenant_id: str, actor_id: str,
                   invoice_id: str, reason: str) -> m.PosInvoice:
    if not reason or len(reason.strip()) < 3:
        err('POS.REASON_REQUIRED', 'سبب المرتجع إلزامي')
    src = db.get(m.PosInvoice, invoice_id)
    if src is None or src.tenant_id != tenant_id:
        err('POS.UNKNOWN_INVOICE', 'فاتورة غير موجودة')
    if src.type == 'RETURN':
        err('POS.ALREADY_RETURN', 'لا مرتجع لفاتورة مرتجع')
    exists = db.execute(select(m.PosInvoice).where(
        m.PosInvoice.return_of_id == src.id)).first()
    if exists:
        err('POS.ALREADY_RETURNED', 'الفاتورة مُرتجعة مسبقاً بقيد عكسي كامل')
    # الشحنة المحملة تُلغى فقط من POS مصدرها (§4) — وهذا هو مكانها الوحيد
    if src.sale_entry_id:
        reverse_entry(db, tenant_id=tenant_id, entry_id=src.sale_entry_id,
                      reason=f'مرتجع فاتورة POS {src.invoice_no}: {reason.strip()}',
                      actor_id=actor_id,
                      reversal_date=get_business_date(db, tenant_id))
    if src.cogs_entry_id:
        reverse_entry(db, tenant_id=tenant_id, entry_id=src.cogs_entry_id,
                      reason=f'مرتجع تكلفة {src.invoice_no}', actor_id=actor_id,
                      reversal_date=get_business_date(db, tenant_id))
    # إعادة المخزون (حركة موجبة بسعر التكلفة الأصلي من دفتر المخزون
    # الموحد؛ مع سقوط توافقي لسجل المرحلة 4 القديم إن وجد)
    from . import inventory as inv_mod
    outlet = db.get(m.PosOutlet, src.outlet_id)
    wh = inv_mod.outlet_warehouse(db, tenant_id, outlet)
    bd_rtn = get_business_date(db, tenant_id)
    restored = 0
    for mv in db.execute(select(m.InvMove).where(
            m.InvMove.ref_id == src.id,
            m.InvMove.reason == 'SALE_POS')).scalars().all():
        inv_mod.apply_inbound(db, tenant_id=tenant_id, warehouse=wh,
                              item_id=mv.item_id, qty=-mv.qty_delta,
                              unit_cost=mv.unit_cost, reason='POS_RETURN',
                              ref_type='POS', ref_id=src.id,
                              actor_id=actor_id, bd=bd_rtn)
        restored += 1
    if restored == 0:  # فاتورة مرحلة 4 قديمة (سجل pos_stock_moves)
        for mv in db.execute(select(m.PosStockMove).where(
                m.PosStockMove.ref_id == src.id,
                m.PosStockMove.reason == 'SALE')).scalars().all():
            inv_item = _inv_for_pos_item(db, tenant_id, mv.item_id)
            inv_mod.apply_inbound(db, tenant_id=tenant_id, warehouse=wh,
                                  item_id=inv_item.id, qty=-mv.qty_delta,
                                  unit_cost=mv.unit_cost, reason='POS_RETURN',
                                  ref_type='POS', ref_id=src.id,
                                  actor_id=actor_id, bd=bd_rtn)
    shift = open_shift_or_err(db, tenant_id, src.outlet_id,
                              shift_id=None)  # المرتجع ضمن وردية مفتوحة
    bd = get_business_date(db, tenant_id)
    rinv = m.PosInvoice(
        id=new_uuid(), tenant_id=tenant_id, outlet_id=src.outlet_id,
        order_id=src.order_id, shift_id=shift.id,
        invoice_no=next_invoice_no(db, tenant_id, outlet, bd),
        client_uuid=f'RTN-{src.client_uuid}', type='RETURN',
        return_of_id=src.id, return_reason=reason.strip(), business_date=bd,
        gross_total=src.gross_total, discount_total=src.discount_total,
        tax_total=src.tax_total, net_total=src.net_total,
        cost_total=src.cost_total, lines_snapshot=src.lines_snapshot,
        issued_by=actor_id, issued_at=utcnow())
    db.add(rinv)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='pos', action='invoice.return', entity='pos_invoices',
          entity_id=src.id,
          after={'return_invoice': rinv.invoice_no, 'reason': reason.strip(),
                 'net': str(src.net_total)}, business_date=bd)
    return rinv


# ────────────────────────────────────────────────────────────────────
# الورديات وZ-Report (§3.5)
# ────────────────────────────────────────────────────────────────────
def open_shift(db: Session, *, tenant_id: str, actor_id: str,
               outlet: m.PosOutlet, opening_float) -> m.PosShift:
    opening_float = D(opening_float)
    if opening_float < 0:
        err('POS.BAD_FLOAT', 'عهدة الافتتاح سالبة ممنوعة')
    existing = db.execute(select(m.PosShift).where(
        m.PosShift.outlet_id == outlet.id,
        m.PosShift.status == 'OPEN')).first()
    if existing:
        err('POS.SHIFT_ALREADY_OPEN',
            'لا تُفتح وردية جديدة قبل إقفال السابقة (§3.5)')
    sh = m.PosShift(id=new_uuid(), tenant_id=tenant_id, outlet_id=outlet.id,
                    opened_by=actor_id, opened_at=utcnow(),
                    opening_float=opening_float)
    db.add(sh)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='pos', action='shift.open', entity='pos_shifts',
          entity_id=sh.id, after={'outlet': outlet.code,
                                  'float': str(opening_float)})
    return sh


def _shift_cash_totals(db: Session, shift_id: str) -> tuple[Decimal, Decimal]:
    """(مبيعات نقدية، مرتجعات نقدية) للوردية من سندات الدفع الفعلية."""
    q = (select(m.PosInvoice.type, func.sum(m.PosPayment.amount))
         .join(m.PosPayment, m.PosPayment.invoice_id == m.PosInvoice.id)
         .where(m.PosInvoice.shift_id == shift_id,
                m.PosPayment.method == 'CASH')
         .group_by(m.PosInvoice.type))
    sales = refunds = Decimal('0')
    for typ, amt in db.execute(q).all():
        if typ == 'SALE':
            sales = D(amt or 0)
        else:
            refunds = D(amt or 0)
    return sales, refunds


def shift_summary(db: Session, tenant_id: str, shift: m.PosShift) -> dict:
    """ملخص الوردية من الفواتير الفعلية — يغذي Z-Report الأرشيفي."""
    invs = db.execute(select(m.PosInvoice).where(
        m.PosInvoice.shift_id == shift.id).order_by(m.PosInvoice.issued_at)
    ).scalars().all()
    by_method: dict[str, Decimal] = {}
    sales_total = Decimal('0')
    returns_total = Decimal('0')
    count_sales = count_returns = 0
    discounts = Decimal('0')
    for iv in invs:
        signs = 1 if iv.type == 'SALE' else -1
        if iv.type == 'SALE':
            sales_total += D(iv.net_total)
            count_sales += 1
            discounts += D(iv.discount_total)
        else:
            returns_total += D(iv.net_total)
            count_returns += 1
        for p in db.execute(select(m.PosPayment).where(
                m.PosPayment.invoice_id == iv.id)).scalars().all():
            by_method[p.method] = by_method.get(p.method, Decimal('0')) + signs * D(p.amount)
    cash_sales, cash_refunds = _shift_cash_totals(db, shift.id)
    expected = D(shift.opening_float) + cash_sales - cash_refunds
    return {'invoices_sales': count_sales, 'invoices_returns': count_returns,
            'sales_total': sales_total, 'returns_total': returns_total,
            'discounts_total': discounts,
            'by_method': {k: str(v) for k, v in by_method.items()},
            'cash_sales': cash_sales, 'cash_refunds': cash_refunds,
            'expected_cash': expected}


def close_shift(db: Session, *, tenant_id: str, actor_id: str,
                shift: m.PosShift, actual_cash) -> dict:
    """Z-Report (§3.5): عدّ فعلي مقابل نظام → فرق ضمن التسامح يُقيد تلقائياً،
    التقرير يوقّع ويُقفل ويصبح أرشيفاً غير قابل للتعديل إطلاقاً."""
    actual_cash = D(actual_cash)
    if actual_cash < 0:
        err('POS.BAD_COUNT', 'العدّ الفعلي سالب ممنوع')
    open_orders = db.execute(select(func.count(m.PosOrder.id)).where(
        m.PosOrder.shift_id == shift.id,
        m.PosOrder.status.in_(('DRAFT', 'FIRED')))).scalar_one()
    if open_orders:
        err('POS.OPEN_ORDERS',
            f'{open_orders} طلبات مفتوحة على الوردية — أقفلها أو ألغها أولاً')
    outlet = db.get(m.PosOutlet, shift.outlet_id)
    summ = shift_summary(db, tenant_id, shift)
    expected = summ['expected_cash']
    variance = actual_cash - expected
    variance_entry = None
    bd = get_business_date(db, tenant_id)
    if variance != 0:
        if abs(variance) > D(outlet.cash_variance_tolerance):
            err('POS.VARIANCE_OVER_TOLERANCE',
                f'فرق العهدة {variance} يتجاوز التسامح المعتمد '
                f'({outlet.cash_variance_tolerance}) — أعد العدّ وحقّق قبل الإقفال')
        side = 'CASH_OVER' if variance > 0 else 'CASH_SHORT'
        amt = abs(variance)
        raw = ([{'account': outlet.cash_account_code, 'debit': amt,
                 'credit': Decimal('0'), 'description': 'فرق عهدة زيادة'},
                {'account': '4901', 'debit': Decimal('0'), 'credit': amt,
                 'description': 'إيراد فرق صندوق'}]
               if variance > 0 else
               [{'account': '7104', 'debit': amt, 'credit': Decimal('0'),
                 'description': 'خسارة فرق صندوق'},
                {'account': outlet.cash_account_code, 'debit': Decimal('0'),
                 'credit': amt, 'description': 'فرق عهدة نقص'}])
        branch = _branch(db, tenant_id)
        variance_entry = create_and_post_journal(
            db, tenant_id=tenant_id, branch_id=branch.id,
            journal_type='AUTO_POS', entry_date=bd,
            narration=f'فرق عهدة وردية {outlet.code} — {side}',
            raw_lines=raw, actor_id=actor_id, source_type='POS_SHIFT',
            source_id=shift.id, event_key=f'pos:zvar:{shift.id}')
    closer = db.get(m.User, actor_id)
    opener = db.get(m.User, shift.opened_by)
    zrep = {'shift_id': shift.id, 'outlet': outlet.code,
            'outlet_name': outlet.name_ar,
            'opened_by': opener.full_name if opener else shift.opened_by,
            'closed_by': closer.full_name if closer else actor_id,
            'opened_at': shift.opened_at.isoformat(),
            'closed_at': utcnow().isoformat(), 'business_date': str(bd),
            'opening_float': str(shift.opening_float),
            **{k: (str(v) if isinstance(v, Decimal) else v)
               for k, v in summ.items()},
            'actual_cash': str(actual_cash),
            'variance': str(variance),
            'variance_entry': variance_entry.entry_no if variance_entry else None,
            'signature': f'{opener.full_name if opener else ""} / {closer.full_name if closer else ""}'}
    shift.status = 'CLOSED'
    shift.closed_by = actor_id
    shift.closed_at = utcnow()
    shift.actual_cash = actual_cash
    shift.expected_cash = expected
    shift.cash_variance = variance
    shift.variance_entry_id = variance_entry.id if variance_entry else None
    shift.zreport = zrep
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='pos', action='shift.close', entity='pos_shifts',
          entity_id=shift.id,
          after={'actual': str(actual_cash), 'expected': str(expected),
                 'variance': str(variance)}, business_date=bd)
    return zrep


# ────────────────────────────────────────────────────────────────────
# شاشة «تحميل على غرفة» (§4): الغرف المشغولة فقط + اسم النزيل المختصر
# ────────────────────────────────────────────────────────────────────
def occupied_rooms(db: Session, tenant_id: str) -> list[dict]:
    res = db.execute(select(m.Reservation).where(
        m.Reservation.tenant_id == tenant_id,
        m.Reservation.status == 'CHECKED_IN')).scalars().all()
    out = []
    for r in res:
        room = db.get(m.Room, r.room_id) if r.room_id else None
        guest = db.get(m.Guest, r.guest_id)
        folio = db.execute(select(m.Folio).where(
            m.Folio.reservation_id == r.id,
            m.Folio.window == 1)).scalar_one_or_none()
        if folio is None or folio.status != 'OPEN':
            continue
        balance = folio_balance(db, tenant_id, folio.id)
        name = guest.full_name if guest else ''
        parts = name.split()
        short = ' '.join(parts[:2]) + ('…' if len(parts) > 2 else '')
        out.append({'folio_id': folio.id, 'reservation_id': r.id,
                    'room_no': room.room_no if room else '؟',
                    'guest_short': short, 'vip': bool(guest and guest.vip),
                    'balance': balance,
                    'credit_limit': folio.credit_limit})
    return sorted(out, key=lambda x: x['room_no'])


def invoice_view(db: Session, tenant_id: str, invoice_id: str) -> dict:
    iv = db.get(m.PosInvoice, invoice_id)
    if iv is None or iv.tenant_id != tenant_id:
        err('POS.UNKNOWN_INVOICE', 'فاتورة غير موجودة')
    outlet = db.get(m.PosOutlet, iv.outlet_id)
    issuer = db.get(m.User, iv.issued_by)
    pays = db.execute(select(m.PosPayment).where(
        m.PosPayment.invoice_id == iv.id)).scalars().all()
    sold_entry = db.get(m.JournalEntry, iv.sale_entry_id) if iv.sale_entry_id else None
    return {'id': iv.id, 'invoice_no': iv.invoice_no, 'type': iv.type,
            'outlet': outlet.name_ar if outlet else '', 'outlet_code': outlet.code if outlet else '',
            'business_date': str(iv.business_date),
            'issued_by': issuer.full_name if issuer else '',
            'issued_at': iv.issued_at.isoformat(),
            'gross_total': D(iv.gross_total), 'discount_total': D(iv.discount_total),
            'tax_total': D(iv.tax_total), 'net_total': D(iv.net_total),
            'cost_total': D(iv.cost_total), 'lines': iv.lines_snapshot,
            'payments': [{'method': p.method, 'amount': D(p.amount),
                          'room_no': p.room_no,
                          'folio_id': p.folio_id,
                          'corporate_id': p.corporate_id,
                          'house_reason': p.house_reason} for p in pays],
            'entry_no': sold_entry.entry_no if sold_entry else None,
            'return_of': iv.return_of_id, 'return_reason': iv.return_reason}


# ────────────────────────────────────────────────────────────────────
# التقارير (§5)
# ────────────────────────────────────────────────────────────────────
def sales_report(db: Session, tenant_id: str, date_from: date, date_to: date,
                 group_by: str = 'item') -> list[dict]:
    """مبيعات يومية بالمنفذ/التصنيف/الصنف/الساعة/الدفع/الموظف (§5-1)."""
    invs = db.execute(select(m.PosInvoice).where(
        m.PosInvoice.tenant_id == tenant_id,
        m.PosInvoice.type == 'SALE',
        m.PosInvoice.business_date >= date_from,
        m.PosInvoice.business_date <= date_to)).scalars().all()
    buckets: dict[str, dict] = {}

    def bump(key: str, amount: Decimal, cost: Decimal = Decimal('0')):
        b = buckets.setdefault(key, {'group': key, 'net': Decimal('0'),
                                     'cost': Decimal('0'), 'count': 0})
        b['net'] += amount
        b['cost'] += cost
        b['count'] += 1

    for iv in invs:
        outlet = db.get(m.PosOutlet, iv.outlet_id)
        if group_by == 'outlet':
            bump(outlet.name_ar if outlet else iv.outlet_id, D(iv.net_total),
                 D(iv.cost_total))
        elif group_by == 'hour':
            bump(f'{iv.issued_at.hour:02d}:00', D(iv.net_total), D(iv.cost_total))
        elif group_by == 'user':
            u = db.get(m.User, iv.issued_by)
            bump(u.full_name if u else iv.issued_by, D(iv.net_total),
                 D(iv.cost_total))
        elif group_by == 'payment':
            for p in db.execute(select(m.PosPayment).where(
                    m.PosPayment.invoice_id == iv.id)).scalars().all():
                bump({'CASH': 'نقد', 'CARD': 'بطاقة/بنك', 'EWALLET': 'محفظة',
                      'ROOM': 'على الغرفة', 'CORPORATE': 'على شركة',
                      'HOUSE': 'مجاني مصرّح'}[p.method], D(p.amount))
        elif group_by == 'category':
            for ln in iv.lines_snapshot:
                item = db.get(m.PosItem, ln.get('item_id', ''))
                cat = db.get(m.PosCategory, item.category_id) if item else None
                base = D(ln['total']) - D(ln.get('discount', 0))
                bump(cat.name_ar if cat else 'غير مصنف', base)
        else:  # item — مع الهامش (§5-2 مباشر من #13)
            for ln in iv.lines_snapshot:
                base = D(ln['total']) - D(ln.get('discount', 0))
                item = db.get(m.PosItem, ln.get('item_id', ''))
                uc = Decimal('0')
                if item:
                    if item.item_type == 'STOCK':
                        uc = D(item.cost)
                    elif item.item_type == 'COMPOSITE':
                        uc = sum((D(db.get(m.PosItem, r.component_item_id).cost) * D(r.qty)
                                  for r in db.execute(select(m.PosRecipe).where(
                                      m.PosRecipe.parent_item_id == item.id)).scalars().all()),
                                 Decimal('0'))
                key = ln['item']
                b = buckets.setdefault(key, {'group': key, 'net': Decimal('0'),
                                             'cost': Decimal('0'),
                                             'count': Decimal('0')})
                b['net'] += base
                b['cost'] += (uc * D(ln['qty'])).quantize(Decimal('0.0001'))
                b['count'] += D(ln['qty'])
    out = []
    for b in buckets.values():
        net, cost = b['net'], b['cost']
        row = {'group': b['group'], 'net': net, 'cost': cost,
               'count': str(b['count']),
               'margin': net - cost,
               'margin_pct': (float((net - cost) / net * 100) if net > 0 else 0.0)}
        out.append(row)
    return sorted(out, key=lambda r: str(r['group']))


def control_report(db: Session, tenant_id: str, date_from: date,
                   date_to: date) -> dict:
    """الخصومات والإلغاءات والمرتجعات بالمستخدم (§5-4 — مؤشر رقابي حرج)."""
    voids: dict[str, dict] = {}
    lines = db.execute(
        select(m.PosOrderLine, m.PosOrder)
        .join(m.PosOrder, m.PosOrder.id == m.PosOrderLine.order_id)
        .where(m.PosOrderLine.tenant_id == tenant_id,
               m.PosOrderLine.status == 'VOID',
               m.PosOrderLine.voided_at.isnot(None))).all()
    for ln, o in lines:
        u = db.get(m.User, ln.void_by)
        key = u.full_name if u else (ln.void_by or '؟')
        b = voids.setdefault(key, {'user': key, 'voids': 0,
                                   'void_value': Decimal('0'), 'reasons': []})
        b['voids'] += 1
        b['void_value'] += D(ln.line_total)
        if ln.void_reason:
            b['reasons'].append(ln.void_reason)
    returns: dict[str, dict] = {}
    rts = db.execute(select(m.PosInvoice).where(
        m.PosInvoice.tenant_id == tenant_id, m.PosInvoice.type == 'RETURN',
        m.PosInvoice.business_date >= date_from,
        m.PosInvoice.business_date <= date_to)).scalars().all()
    for iv in rts:
        u = db.get(m.User, iv.issued_by)
        key = u.full_name if u else iv.issued_by
        b = returns.setdefault(key, {'user': key, 'returns': 0,
                                     'value': Decimal('0'), 'reasons': []})
        b['returns'] += 1
        b['value'] += D(iv.net_total)
        if iv.return_reason:
            b['reasons'].append(iv.return_reason)
    discounts: dict[str, dict] = {}
    invs = db.execute(select(m.PosInvoice).where(
        m.PosInvoice.tenant_id == tenant_id, m.PosInvoice.type == 'SALE',
        m.PosInvoice.discount_total > 0,
        m.PosInvoice.business_date >= date_from,
        m.PosInvoice.business_date <= date_to)).scalars().all()
    for iv in invs:
        u = db.get(m.User, iv.issued_by)
        key = u.full_name if u else iv.issued_by
        b = discounts.setdefault(key, {'user': key, 'discounted_invoices': 0,
                                       'discount_value': Decimal('0')})
        b['discounted_invoices'] += 1
        b['discount_value'] += D(iv.discount_total)
    fmt = lambda rows, val_key: [
        {**r, val_key: str(r[val_key])} for r in rows]
    return {'voids': fmt([{**r, 'void_value': r['void_value']} for r in voids.values()], 'void_value'),
            'returns': fmt([{**r, 'value': r['value']} for r in returns.values()], 'value'),
            'discounts': fmt([{**r, 'discount_value': r['discount_value']} for r in discounts.values()], 'discount_value')}


def consumption_report(db: Session, tenant_id: str, outlet_id: str,
                       date_from: date, date_to: date) -> list[dict]:
    """الاستهلاك النظري (من الوصفات/المبيعات) مقابل الفعلي (الحركات) — فروقات
    الهدر (§5-3). الفعلي v1 = حركات البيع+المرتجع؛ الجرد الفعلي في مرحلة 05."""
    moves = db.execute(select(m.PosStockMove).where(
        m.PosStockMove.tenant_id == tenant_id,
        m.PosStockMove.outlet_id == outlet_id,
        func.date(m.PosStockMove.created_at) >= date_from,
        func.date(m.PosStockMove.created_at) <= date_to)).scalars().all()
    actual: dict[str, Decimal] = {}
    for mv in moves:
        if mv.reason in ('SALE', 'RETURN'):
            actual[mv.item_id] = actual.get(mv.item_id, Decimal('0')) - D(mv.qty_delta)
    rows = []
    for item_id, qty in sorted(actual.items()):
        item = db.get(m.PosItem, item_id)
        stock = db.execute(select(m.PosStock).where(
            m.PosStock.outlet_id == outlet_id,
            m.PosStock.item_id == item_id)).scalar_one_or_none()
        rows.append({'item': item.name_ar if item else item_id,
                     'theoretical_out': qty,  # = الفعلي هنا ما لم يوجد جرد
                     'actual_out': qty, 'variance': Decimal('0'),
                     'qty_on_hand': D(stock.qty_on_hand) if stock else Decimal('0'),
                     'note': 'الجرد الفعلي وفروقات الهدر في مرحلة المخزون (05)'})
    return rows
