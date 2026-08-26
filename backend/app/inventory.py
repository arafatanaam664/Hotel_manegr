"""خدمات وحدة المخزون والمشتريات — ملف 05 (INVENTORY_SPEC) كقانون ملزم:

§1 الكيانات: أصناف (وحدة أساسية + بدائل بمعامل إلزامي)، مستودعات لكلٌّ
   منها حساب مخزون مالي وأمين، موردون بأسعار تعاقدية مؤرخة.
§2 دورة الشراء: PR ← اعتماد → PO (سلم اعتماد ملف 14: L0/L1/L2) → GRN
   (فروقات كمية بسقف٪ + رفض جودة + دفعة/صلاحية) → مطابقة ثلاثية → سداد
   بخصم مكتسب دائناً 4901 → مرتجع بمستند مستقل. GRN المرحَّل غير قابل
   للتعديل إطلاقاً — التصحيح بعكس + جديد.
§3 الحركة الداخلية: صرف لقسم (#18 بلا أثر دخل)، تحويلات مع «على الطريق»،
   هالك (#19) بمستند+اعتماد+سبب؛ كل حركة تخزن الكمية والتكلفة لحظتها
   والمستند والمستخدم والدفعة/الصلاحية.
§4 التقييم: متوسط مرجح متحرك لكل (صنف/مستودع) بثابتِ القيمة:
   qty × avg = القيمة الدفترية = رصيد الحساب في الأستاذ يومياً (قبول §7.2).
   جرد دوري: تجميد ← عدّ ← فروقات ← اعتماد مزدوج ← تسويات #19/#20 بالهللة.
§7 القبول: لا رصيد سالب في وضع «منع» (خصم ذري محروس)، مطابقة القيمة
   للأستاذ، المطابقة الثلاثية ترفض خارج التسامح تلقائياً، استحالة تعديل
   GRN مرحَّل، وعجز الجرد يولّد #19 بقيمة كشف الفروقات نفسها.

كل قيد يمر عبر نواة المحرك create_and_post_journal حصراً (حساب المستودع
متغير → قوالب الربط الثابتة لا تصلح هنا — نمط ADR-0012، موثق ADR-0020)
وبالنوع AUTO_PURCHASE التزاماً بتعداد journal_type في ملف 02 §DB."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models as m
from .audit import audit
from .posting import D, PostingError, create_and_post_journal, reverse_entry
from .security import new_uuid, utcnow

Q4 = Decimal('0.0001')
AP_ACCOUNT = '2101'
PPV_ACCOUNT = '5120'        # فروقات أسعار الشراء (§2.4 «حساب فرق»)
WASTE_ACCOUNT = '7104'      # خسائر ومسحقات استثنائية (#19)
OVER_ACCOUNT = '4901'       # عمولات وإيرادات متنوعة (#20 + خصم مكتسب)
VAT_INPUT = '1150'
PAY_ACCOUNTS = {'CASH': '1101', 'BANK': '1103', 'EWALLET': '1104'}

# أسباب الحركة الصادرة التي تُحسب «استهلاكاً» في التنبيهات والتقارير
CONSUMPTION_REASONS = ('SALE_POS', 'ISSUE_OUT', 'WASTE', 'COUNT_SHORT',
                       'PURCHASE_RETURN')
FROZEN_STATUSES = ('FREEZE', 'COUNTED', 'PENDING_L1', 'PENDING_L2')


def err(code: str, message: str):
    raise PostingError(code, message)


def _now() -> datetime:
    return utcnow()


# ────────────────────────────────────────────────────────────────────
# أدوات عامة: سياسة، تسلسلات، كيانات، فروع
# ────────────────────────────────────────────────────────────────────
def get_policy(db: Session, tenant_id: str) -> m.InvPolicy:
    p = db.get(m.InvPolicy, tenant_id)
    if p is None:
        p = m.InvPolicy(tenant_id=tenant_id)
        db.add(p)
        db.flush()
    return p


def update_policy(db: Session, *, tenant_id: str, actor_id: str,
                  changes: dict) -> m.InvPolicy:
    p = get_policy(db, tenant_id)
    before = {'po_l0_limit': str(p.po_l0_limit),
              'po_l1_limit': str(p.po_l1_limit),
              'price_tolerance_pct': str(p.price_tolerance_pct),
              'qty_tolerance_pct': str(p.qty_tolerance_pct),
              'expiry_windows': list(p.expiry_windows or []),
              'stagnant_days': p.stagnant_days,
              'consumption_days': p.consumption_days}
    for k in ('po_l0_limit', 'po_l1_limit', 'price_tolerance_pct',
              'qty_tolerance_pct'):
        if k in changes and changes[k] is not None:
            v = D(changes[k])
            if v < 0:
                err('INV.BAD_POLICY', f'قيمة السياسة {k} لا يمكن أن تسالب')
            setattr(p, k, v)
    if changes.get('expiry_windows') is not None:
        p.expiry_windows = sorted((int(w) for w in changes['expiry_windows'][:3]),
                                  reverse=True)
    for k in ('stagnant_days', 'consumption_days'):
        if changes.get(k) is not None:
            v = int(changes[k])
            if v < 1:
                err('INV.BAD_POLICY', f'قيمة السياسة {k} يجب أن تكون موجبة')
            setattr(p, k, v)
    p.updated_by = actor_id
    p.updated_at = _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='policy.update', entity='inv_policy',
          entity_id=tenant_id, before=before,
          after={'po_l0_limit': str(p.po_l0_limit),
                 'po_l1_limit': str(p.po_l1_limit),
                 'price_tolerance_pct': str(p.price_tolerance_pct),
                 'qty_tolerance_pct': str(p.qty_tolerance_pct),
                 'expiry_windows': list(p.expiry_windows or []),
                 'stagnant_days': p.stagnant_days,
                 'consumption_days': p.consumption_days})
    return p


def next_doc_no(db: Session, tenant_id: str, kind: str, prefix: str,
                d: date | None = None) -> str:
    year = (d or date.today()).year
    row = db.execute(
        select(m.SequenceCounter)
        .where(m.SequenceCounter.tenant_id == tenant_id,
               m.SequenceCounter.kind == kind,
               m.SequenceCounter.year == year)
        .with_for_update()).scalar_one_or_none()
    if row is None:
        row = m.SequenceCounter(tenant_id=tenant_id, kind=kind, year=year,
                                next_no=1)
        db.add(row)
        db.flush()
    no = row.next_no
    row.next_no = no + 1
    db.flush()
    return f'{prefix}-{year}-{no:06d}'


def _branch_id(db: Session, tenant_id: str,
               warehouse: m.InvWarehouse | None = None) -> str:
    if warehouse is not None:
        return warehouse.branch_id
    b = db.execute(select(m.Branch).where(
        m.Branch.tenant_id == tenant_id).limit(1)).scalar_one_or_none()
    if b is None:
        err('ORG.UNKNOWN_BRANCH', 'لا يوجد فرع للمستأجر')
    return b.id


def warehouse_or_err(db: Session, tenant_id: str, wh_id: str) -> m.InvWarehouse:
    w = db.get(m.InvWarehouse, wh_id)
    if w is None or w.tenant_id != tenant_id:
        err('INV.UNKNOWN_WAREHOUSE', f'مستودع غير موجود: {wh_id}')
    if not w.is_active:
        err('INV.WAREHOUSE_INACTIVE', f'المستودع «{w.name_ar}» موقوف')
    return w


def item_or_err(db: Session, tenant_id: str, item_id: str) -> m.InvItem:
    it = db.get(m.InvItem, item_id)
    if it is None or it.tenant_id != tenant_id:
        err('INV.UNKNOWN_ITEM', f'صنف غير موجود: {item_id}')
    if not it.is_active:
        err('INV.ITEM_INACTIVE', f'الصنف «{it.name_ar}» موقوف')
    return it


def supplier_or_err(db: Session, tenant_id: str, sup_id: str) -> m.InvSupplier:
    s = db.get(m.InvSupplier, sup_id)
    if s is None or s.tenant_id != tenant_id:
        err('INV.UNKNOWN_SUPPLIER', f'مورد غير موجود: {sup_id}')
    if not s.is_active:
        err('INV.SUPPLIER_INACTIVE', f'المورد «{s.name}» موقوف')
    return s


def _require_reason(reason: str, code: str = 'INV.REASON_REQUIRED'):
    if not reason or len(reason.strip()) < 3:
        err(code, 'المسوّغ إلزامي (3 أحرف على الأقل)')


# ────────────────────────────────────────────────────────────────────
# محرك الحركة — قلب التقييم المتحرك ومنع السالب (قبول §7.1)
# ثابت القيمة: stock.qty × stock.avg = القيمة؛ وكل حركة value_delta
# تطابق أثرها في الأستاذ جنباً إلى جنب (قبول §7.2)
# ────────────────────────────────────────────────────────────────────
def _stock_row(db: Session, tenant_id: str, warehouse_id: str,
               item_id: str) -> m.InvStock:
    row = db.execute(select(m.InvStock).where(
        m.InvStock.warehouse_id == warehouse_id,
        m.InvStock.item_id == item_id).with_for_update()).scalar_one_or_none()
    if row is None:
        row = m.InvStock(id=new_uuid(), tenant_id=tenant_id,
                         warehouse_id=warehouse_id, item_id=item_id,
                         qty_on_hand=Decimal('0'), avg_cost=Decimal('0'))
        db.add(row)
        db.flush()
    return row


def _assert_not_frozen(db: Session, tenant_id: str, warehouse_id: str):
    """تجميد الجرد (§4): أي حركة على مستودع تحت جرد مفتوح ممنوعة."""
    active = db.execute(select(m.InvCount).where(
        m.InvCount.tenant_id == tenant_id,
        m.InvCount.warehouse_id == warehouse_id,
        m.InvCount.status.in_(FROZEN_STATUSES))).first()
    if active:
        err('INV.WAREHOUSE_FROZEN',
            'المستودع مجمّد لجرد مفتوح — يمنع أي حركة حتى اعتماده أو إلغائه')


def _record_move(db: Session, *, tenant_id: str, stock: m.InvStock,
                 qty_delta: Decimal, unit_cost: Decimal, value_delta: Decimal,
                 reason: str, ref_type: str, ref_id: str, actor_id: str,
                 bd: date, batch_no: str = '', expiry_date=None,
                 entry_id: str | None = None) -> m.InvMove:
    mv = m.InvMove(id=new_uuid(), tenant_id=tenant_id,
                   warehouse_id=stock.warehouse_id, item_id=stock.item_id,
                   business_date=bd, qty_delta=qty_delta, unit_cost=unit_cost,
                   value_delta=value_delta, reason=reason, ref_type=ref_type,
                   ref_id=ref_id, batch_no=batch_no or '',
                   expiry_date=expiry_date, actor_id=actor_id,
                   entry_id=entry_id, created_at=_now())
    db.add(mv)
    return mv


def apply_inbound(db: Session, *, tenant_id: str, warehouse: m.InvWarehouse,
                  item_id: str, qty, unit_cost, reason: str, ref_type: str,
                  ref_id: str, actor_id: str, bd: date, batch_no: str = '',
                  expiry_date=None, entry_id: str | None = None,
                  set_avg: bool = True) -> tuple[m.InvMove, Decimal]:
    """إدخال كمية: يعيد المتوسط المرجح المتحرك تلقائياً (§4):
    avg' = (q·avg + x·cost) / (q + x) — ويحفظ ثبات القيمة."""
    qty, unit_cost = D(qty), D(unit_cost)
    if qty <= 0:
        err('INV.BAD_QTY', 'كمية الإدخال يجب أن تكون موجبة')
    if unit_cost < 0:
        err('INV.BAD_COST', 'تكلفة الإدخال سالبة ممنوعة')
    _assert_not_frozen(db, tenant_id, warehouse.id)
    stock = _stock_row(db, tenant_id, warehouse.id, item_id)
    item = db.get(m.InvItem, item_id)
    cat = db.get(m.InvCategory, item.category_id) if item else None
    if cat and cat.valuation_method == 'FIFO':
        # محجوز — ADR-0018: لا يُختار أصلاً عبر API (حارس مزدوج)
        err('INV.FIFO_UNSUPPORTED',
            'طريقة FIFO محجوزة وغير مفعّلة في هذا الإصدار')
    old_q, old_avg = D(stock.qty_on_hand), D(stock.avg_cost)
    new_q = old_q + qty
    if set_avg:
        stock.avg_cost = unit_cost if new_q <= 0 else (
            (old_q * old_avg + qty * unit_cost) / new_q).quantize(Q4)
    stock.qty_on_hand = new_q
    mv = _record_move(db, tenant_id=tenant_id, stock=stock, qty_delta=qty,
                      unit_cost=unit_cost, value_delta=qty * unit_cost,
                      reason=reason, ref_type=ref_type, ref_id=ref_id,
                      actor_id=actor_id, bd=bd, batch_no=batch_no,
                      expiry_date=expiry_date, entry_id=entry_id)
    db.flush()
    return mv, stock.avg_cost


def apply_outbound(db: Session, *, tenant_id: str,
                   warehouse: m.InvWarehouse, item_id: str, qty,
                   reason: str, ref_type: str, ref_id: str, actor_id: str,
                   bd: date, unit_cost=None, allow_negative: bool | None = None,
                   entry_id: str | None = None) -> tuple[m.InvMove, Decimal, bool]:
    """صرف كمية بالمتوسط المتحرك لحظتها (§3 «التكلفة لحظتها»).

    الخصم المحروس (قبول §7.1): في وضع «منع» يُنفَّذ UPDATE شرطي ذرياً
    (qty >= المطلوب) فلا يمكن لتزامنٍ مهما كان أن يولّد رصيداً سالباً.

    يرجع (الحركة، التكلفة المطبقة، تجاوز السالب المسموح).
    unit_cost مخصص يُستخدم في عكس GRN فقط ليغسل القيمة بسعرها الأصلي مع
    إعادة ضبط المتوسط بقاعدة ثبات القيمة (ADRs)."""
    qty = D(qty)
    if qty <= 0:
        err('INV.BAD_QTY', 'كمية الصرف يجب أن تكون موجبة')
    _assert_not_frozen(db, tenant_id, warehouse.id)
    stock = _stock_row(db, tenant_id, warehouse.id, item_id)
    block = not (warehouse.allow_negative if allow_negative is None
                 else allow_negative)
    if block:
        res = db.execute(
            update(m.InvStock)
            .where(m.InvStock.id == stock.id,
                   m.InvStock.qty_on_hand >= qty)
            .values(qty_on_hand=m.InvStock.qty_on_hand - qty))
        if res.rowcount == 0:
            item = db.get(m.InvItem, item_id)
            name = item.name_ar if item else item_id
            err('INV.INSUFFICIENT_STOCK',
                f'رصيد «{name}» لا يكفي في «{warehouse.name_ar}»: '
                f'متاح {stock.qty_on_hand} والمطلوب {qty}')
        db.flush()
        db.refresh(stock)
    else:
        stock.qty_on_hand = D(stock.qty_on_hand) - qty
    went_negative = D(stock.qty_on_hand) < 0
    applied = D(unit_cost) if unit_cost is not None else D(stock.avg_cost)
    if unit_cost is not None and not went_negative:
        # خروج بسعر ≠ المتوسط (عكس استلام بسعره الأصلي): أعد ضبط المتوسط
        # بثبات القيمة — value' = value − applied·qty ⇒ avg' = value'/qty'
        new_q = D(stock.qty_on_hand)
        old_value = (new_q + qty) * D(stock.avg_cost)
        stock.avg_cost = Decimal('0') if new_q <= 0 else (
            (old_value - applied * qty) / new_q).quantize(Q4)
    mv = _record_move(db, tenant_id=tenant_id, stock=stock, qty_delta=-qty,
                      unit_cost=applied, value_delta=-(applied * qty),
                      reason=reason, ref_type=ref_type, ref_id=ref_id,
                      actor_id=actor_id, bd=bd, entry_id=entry_id)
    db.flush()
    return mv, applied, went_negative


def _post_journal(db: Session, *, tenant_id: str, branch_id: str,
                  entry_date: date, narration: str, raw_lines: list[dict],
                  actor_id: str, source_type: str, source_id: str,
                  event_key: str, reference: str | None = None,
                  journal_type: str = 'AUTO_PURCHASE') -> m.JournalEntry:
    """غلاف إلزامي: كل قيود الوحدة تمر من نواة المحرك فقط."""
    return create_and_post_journal(
        db, tenant_id=tenant_id, branch_id=branch_id,
        journal_type=journal_type, entry_date=entry_date,
        narration=narration, raw_lines=raw_lines, actor_id=actor_id,
        source_type=source_type, source_id=source_id, reference=reference,
        event_key=event_key)


# ────────────────────────────────────────────────────────────────────
# §1 الكتالوج: تصنيفات، أصناف، مستودعات
# ────────────────────────────────────────────────────────────────────
def create_category(db: Session, *, tenant_id: str, actor_id: str, code: str,
                    name_ar: str, default_account_code: str = '1210',
                    valuation_method: str = 'AVG') -> m.InvCategory:
    code = code.strip().upper()
    if db.execute(select(m.InvCategory).where(
            m.InvCategory.tenant_id == tenant_id,
            m.InvCategory.code == code)).first():
        err('INV.DUP_CATEGORY', f'كود التصنيف مستخدم: {code}')
    if valuation_method != 'AVG':
        err('INV.FIFO_UNSUPPORTED',
            'طريقة FIFO محجوزة وغير مفعّلة في هذا الإصدار (ADR-0018)')
    cat = m.InvCategory(id=new_uuid(), tenant_id=tenant_id, code=code,
                        name_ar=name_ar.strip(),
                        default_account_code=default_account_code)
    db.add(cat)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='category.create',
          entity='inv_categories', entity_id=cat.id,
          after={'code': code, 'name': name_ar})
    return cat


def set_category_method(db: Session, *, tenant_id: str, actor_id: str,
                        category_id: str, method: str) -> m.InvCategory:
    """§4: خيار الطريقة «يُفعَّل قبل أول حركة ولا يُغيَّر بعدها»."""
    cat = db.get(m.InvCategory, category_id)
    if cat is None or cat.tenant_id != tenant_id:
        err('INV.UNKNOWN_CATEGORY', 'تصنيف غير موجود')
    if cat.method_locked:
        err('INV.METHOD_LOCKED',
            'طريقة التقييم أُقفلت بعد أول حركة ولا تُغيَّر (ملف 05 §4)')
    if method != 'AVG':
        err('INV.FIFO_UNSUPPORTED',
            'طريقة FIFO محجوزة وغير مفعّلة في هذا الإصدار (ADR-0018)')
    cat.valuation_method = method
    db.flush()
    return cat


def create_item(db: Session, *, tenant_id: str, actor_id: str, code: str,
                name_ar: str, category_id: str, base_unit: str = 'حبة',
                name_en: str = '', alt_units: list | None = None,
                barcode: str = '', reorder_level=0, safety_level=0,
                inventory_account_code: str | None = None,
                track_expiry: bool = False,
                pos_item_id: str | None = None) -> m.InvItem:
    code = code.strip().upper()
    if db.execute(select(m.InvItem).where(
            m.InvItem.tenant_id == tenant_id,
            m.InvItem.code == code)).first():
        err('INV.DUP_ITEM', f'كود الصنف مستخدم: {code}')
    cat = db.get(m.InvCategory, category_id)
    if cat is None or cat.tenant_id != tenant_id or not cat.is_active:
        err('INV.UNKNOWN_CATEGORY', 'تصنيف غير موجود أو موقوف')
    units = []
    seen = {base_unit.strip()}
    for u in (alt_units or []):
        uname = str(u.get('unit', '')).strip()
        factor = D(u.get('factor', 0))
        if not uname or uname in seen:
            continue
        if factor <= 0:  # §1 أدوات: معامل التحويل إلزامي وموجب
            err('INV.BAD_FACTOR', f'معامل التحويل للوحدة «{uname}» إلزامي (> 0)')
        units.append({'unit': uname, 'factor': str(factor)})
        seen.add(uname)
    acct = inventory_account_code or cat.default_account_code
    item = m.InvItem(id=new_uuid(), tenant_id=tenant_id, code=code,
                     name_ar=name_ar.strip(), name_en=name_en.strip(),
                     category_id=category_id, base_unit=base_unit.strip(),
                     alt_units=units, barcode=barcode.strip(),
                     reorder_level=D(reorder_level),
                     safety_level=D(safety_level),
                     inventory_account_code=acct, track_expiry=track_expiry,
                     pos_item_id=pos_item_id, created_at=_now())
    db.add(item)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='item.create', entity='inv_items',
          entity_id=item.id, after={'code': code, 'name': name_ar,
                                    'account': acct})
    return item


def update_item_levels(db: Session, *, tenant_id: str, actor_id: str,
                       item_id: str, changes: dict) -> m.InvItem:
    item = db.get(m.InvItem, item_id)
    if item is None or item.tenant_id != tenant_id:
        err('INV.UNKNOWN_ITEM', 'صنف غير موجود')
    allowed = {'reorder_level', 'safety_level', 'name_ar', 'name_en',
               'barcode', 'track_expiry', 'is_active'}
    for k, v in changes.items():
        if k not in allowed or v is None:
            continue
        if k in ('reorder_level', 'safety_level'):
            v = D(v)
            if v < 0:
                err('INV.BAD_LEVEL', 'الحدود لا تقبل السالب')
        setattr(item, k, v)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='item.update', entity='inv_items',
          entity_id=item.id, after={k: str(v) for k, v in changes.items()
                                    if k in allowed})
    return item


def create_warehouse(db: Session, *, tenant_id: str, branch_id: str,
                     actor_id: str, code: str, name_ar: str, kind: str = 'SUB',
                     inventory_account_code: str = '1210',
                     keeper_user_id: str | None = None,
                     allow_negative: bool = False,
                     pos_outlet_id: str | None = None,
                     cost_center_code: str = '') -> m.InvWarehouse:
    code = code.strip().upper()
    if kind not in ('MAIN', 'SUB', 'OUTLET'):
        err('INV.BAD_WH_KIND', 'نوع المستودع MAIN|SUB|OUTLET فقط')
    if db.execute(select(m.InvWarehouse).where(
            m.InvWarehouse.tenant_id == tenant_id,
            m.InvWarehouse.code == code)).first():
        err('INV.DUP_WAREHOUSE', f'كود المستودع مستخدم: {code}')
    w = m.InvWarehouse(id=new_uuid(), tenant_id=tenant_id,
                       branch_id=branch_id, code=code, name_ar=name_ar.strip(),
                       kind=kind, inventory_account_code=inventory_account_code,
                       keeper_user_id=keeper_user_id,
                       allow_negative=allow_negative,
                       pos_outlet_id=pos_outlet_id,
                       cost_center_code=cost_center_code)
    db.add(w)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='warehouse.create',
          entity='inv_warehouses', entity_id=w.id,
          after={'code': code, 'kind': kind, 'account': inventory_account_code})
    return w


def auto_link_pos_item(db: Session, *, tenant_id: str,
                       pos_item: m.PosItem) -> m.InvItem:
    """جسر ADR-0017: صنف POS مخزوني بلا صنف مخزون ← يُنشأ آلياً موثَّقاً."""
    linked = db.execute(select(m.InvItem).where(
        m.InvItem.tenant_id == tenant_id,
        m.InvItem.pos_item_id == pos_item.id)).scalar_one_or_none()
    if linked:
        return linked
    cat = db.execute(select(m.InvCategory).where(
        m.InvCategory.tenant_id == tenant_id,
        m.InvCategory.code == 'FB')).scalar_one_or_none()
    if cat is None:
        cat = m.InvCategory(id=new_uuid(), tenant_id=tenant_id, code='FB',
                            name_ar='أغذية ومشروبات',
                            default_account_code='1210')
        db.add(cat)
        db.flush()
    code = pos_item.code
    clash = db.execute(select(m.InvItem).where(
        m.InvItem.tenant_id == tenant_id,
        m.InvItem.code == code)).scalar_one_or_none()
    if clash is not None and clash.pos_item_id != pos_item.id:
        code = f'{code}-P'
    item = m.InvItem(id=new_uuid(), tenant_id=tenant_id, code=code,
                     name_ar=pos_item.name_ar, name_en=pos_item.name_en,
                     category_id=cat.id, base_unit='حبة',
                     inventory_account_code='1210',
                     pos_item_id=pos_item.id, created_at=_now())
    db.add(item)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id='system', actor_type='system',
          module='inventory', action='item.autolink', entity='inv_items',
          entity_id=item.id, after={'pos_item': pos_item.code})
    return item


def outlet_warehouse(db: Session, tenant_id: str,
                     outlet: m.PosOutlet) -> m.InvWarehouse:
    """مستودع المنفذ (ملف 04 §1 «مستودع افتراضي») — يُنشأ عند أول استعمال."""
    if outlet.warehouse_id:
        w = db.get(m.InvWarehouse, outlet.warehouse_id)
        if w is not None:
            return w
    w = db.execute(select(m.InvWarehouse).where(
        m.InvWarehouse.tenant_id == tenant_id,
        m.InvWarehouse.pos_outlet_id == outlet.id)).scalar_one_or_none()
    if w is None:
        w = create_warehouse(
            db, tenant_id=tenant_id, branch_id=outlet.branch_id,
            actor_id='system', code=f'POS-{outlet.code}',
            name_ar=f'مستودع {outlet.name_ar}', kind='OUTLET',
            inventory_account_code='1210',
            allow_negative=outlet.allow_negative_stock,
            pos_outlet_id=outlet.id,
            cost_center_code=outlet.cost_center_code)
    outlet.warehouse_id = w.id
    db.flush()
    return w


# ────────────────────────────────────────────────────────────────────
# §1 الموردون وأسعارهم التعاقدية المؤرخة
# ────────────────────────────────────────────────────────────────────
def create_supplier(db: Session, *, tenant_id: str, actor_id: str, code: str,
                    name: str, contact_person: str = '', phone: str = '',
                    address: str = '', terms_days: int = 0,
                    currency: str = 'BASE', notes: str = '') -> m.InvSupplier:
    code = code.strip().upper()
    if db.execute(select(m.InvSupplier).where(
            m.InvSupplier.tenant_id == tenant_id,
            m.InvSupplier.code == code)).first():
        err('INV.DUP_SUPPLIER', f'كود المورد مستخدم: {code}')
    s = m.InvSupplier(id=new_uuid(), tenant_id=tenant_id, code=code,
                      name=name.strip(), contact_person=contact_person,
                      phone=phone, address=address, terms_days=terms_days,
                      currency=currency, notes=notes)
    db.add(s)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='supplier.create',
          entity='inv_suppliers', entity_id=s.id,
          after={'code': code, 'name': name})
    return s


def update_supplier(db: Session, *, tenant_id: str, actor_id: str,
                    supplier_id: str, changes: dict) -> m.InvSupplier:
    s = db.get(m.InvSupplier, supplier_id)
    if s is None or s.tenant_id != tenant_id:
        err('INV.UNKNOWN_SUPPLIER', 'مورد غير موجود')
    allowed = {'name', 'contact_person', 'phone', 'address', 'terms_days',
               'currency', 'notes', 'rating_commitment', 'rating_quality',
               'is_active'}
    for k, v in changes.items():
        if k in allowed and v is not None:
            setattr(s, k, v)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='supplier.update',
          entity='inv_suppliers', entity_id=s.id,
          after={k: str(v) for k, v in changes.items() if k in allowed})
    return s


def set_supplier_price(db: Session, *, tenant_id: str, actor_id: str,
                       supplier_id: str, item_id: str, price,
                       valid_from: date, valid_to=None) -> m.InvSupplierPrice:
    supplier_or_err(db, tenant_id, supplier_id)
    item_or_err(db, tenant_id, item_id)
    price = D(price)
    if price <= 0:
        err('INV.BAD_PRICE', 'السعر التعاقدي يجب أن يكون موجباً')
    if valid_to and valid_to < valid_from:
        err('INV.BAD_PRICE_RANGE', 'نهاية صلاحية السعر قبل بدايتها')
    dup = db.execute(select(m.InvSupplierPrice).where(
        m.InvSupplierPrice.supplier_id == supplier_id,
        m.InvSupplierPrice.item_id == item_id,
        m.InvSupplierPrice.valid_from == valid_from)).scalar_one_or_none()
    if dup:
        dup.price = price
        dup.valid_to = valid_to
        db.flush()
        return dup
    sp = m.InvSupplierPrice(id=new_uuid(), tenant_id=tenant_id,
                            supplier_id=supplier_id, item_id=item_id,
                            price=price, valid_from=valid_from,
                            valid_to=valid_to)
    db.add(sp)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='supplier.price.set',
          entity='inv_supplier_prices', entity_id=sp.id,
          after={'item_id': item_id, 'price': str(price),
                 'from': str(valid_from)})
    return sp


def contract_price(db: Session, tenant_id: str, supplier_id: str,
                   item_id: str, on: date) -> Decimal | None:
    row = db.execute(select(m.InvSupplierPrice).where(
        m.InvSupplierPrice.tenant_id == tenant_id,
        m.InvSupplierPrice.supplier_id == supplier_id,
        m.InvSupplierPrice.item_id == item_id,
        m.InvSupplierPrice.valid_from <= on,
        (m.InvSupplierPrice.valid_to.is_(None)) |
        (m.InvSupplierPrice.valid_to >= on))
        .order_by(m.InvSupplierPrice.valid_from.desc())
        .limit(1)).scalar_one_or_none()
    return D(row.price) if row else None


def supplier_balance(db: Session, tenant_id: str, supplier_id: str) -> Decimal:
    """ذمة المورد من الأستاذ (لا عمود رصيد مخزن — اشتقاق لحظي)."""
    q = (select(func.sum(m.JournalLine.debit_base),
                func.sum(m.JournalLine.credit_base))
         .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
         .join(m.Account, m.Account.id == m.JournalLine.account_id)
         .where(m.JournalLine.tenant_id == tenant_id,
                m.Account.code == AP_ACCOUNT,
                m.JournalLine.party_id == supplier_id,
                m.JournalEntry.status.in_(['POSTED', 'REVERSED'])))
    td, tc = db.execute(q).one()
    return D(tc or 0) - D(td or 0)  # دائن = مستحق للمورد


# ────────────────────────────────────────────────────────────────────
# §2.1 طلبات الشراء الداخلية (PR)
# ────────────────────────────────────────────────────────────────────
def create_pr(db: Session, *, tenant_id: str, actor_id: str, department: str,
              lines: list[dict], notes: str = '') -> m.InvPurchaseRequest:
    if not lines:
        err('INV.PR_EMPTY', 'طلب الشراء بلا بنود')
    seen = set()
    for ln in lines:
        item_or_err(db, tenant_id, ln['item_id'])
        if ln['item_id'] in seen:
            err('INV.DUP_LINE', 'تكرار صنف في الطلب')
        seen.add(ln['item_id'])
        if D(ln['qty']) <= 0:
            err('INV.BAD_QTY', 'كمية البند يجب أن تكون موجبة')
    pr = m.InvPurchaseRequest(
        id=new_uuid(), tenant_id=tenant_id,
        pr_no=next_doc_no(db, tenant_id, 'PR', 'PR'),
        department=department.strip(), notes=notes.strip(),
        created_by=actor_id, created_at=_now())
    db.add(pr)
    db.flush()
    for ln in lines:
        db.add(m.InvPRLine(id=new_uuid(), tenant_id=tenant_id, pr_id=pr.id,
                           item_id=ln['item_id'], qty=D(ln['qty']),
                           note=ln.get('note', '')[:200]))
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='pr.create', entity='inv_prs',
          entity_id=pr.id, after={'pr_no': pr.pr_no, 'lines': len(lines)})
    return pr


def submit_pr(db: Session, *, tenant_id: str, actor_id: str,
              pr_id: str) -> m.InvPurchaseRequest:
    pr = db.get(m.InvPurchaseRequest, pr_id)
    if pr is None or pr.tenant_id != tenant_id:
        err('INV.UNKNOWN_PR', 'طلب شراء غير موجود')
    if pr.status != 'DRAFT':
        err('INV.PR_STATE', f'لا يمكن رفع طلب بحالة {pr.status}')
    pr.status = 'SUBMITTED'
    pr.submitted_at = _now()
    db.flush()
    return pr


def approve_pr(db: Session, *, tenant_id: str, actor_id: str, pr_id: str,
               approve: bool, reason: str = '') -> m.InvPurchaseRequest:
    pr = db.get(m.InvPurchaseRequest, pr_id)
    if pr is None or pr.tenant_id != tenant_id:
        err('INV.UNKNOWN_PR', 'طلب شراء غير موجود')
    if pr.status != 'SUBMITTED':
        err('INV.PR_STATE', f'لا يمكن اعتماد طلب بحالة {pr.status}')
    if pr.created_by == actor_id:  # ملف 14 §2: لا اعتماد ذاتي
        err('INV.SELF_APPROVAL', 'يمنع اعتماد منشئ الطلب لطلبه')
    if approve:
        pr.status = 'APPROVED'
        pr.approved_by = actor_id
        pr.approved_at = _now()
    else:
        _require_reason(reason, 'INV.REJECT_REASON')
        pr.status = 'REJECTED'
        pr.reject_reason = reason.strip()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='pr.approve' if approve else 'pr.reject',
          entity='inv_prs', entity_id=pr.id,
          after={'approve': approve, 'reason': reason.strip()})
    return pr


# ────────────────────────────────────────────────────────────────────
# §2.2 أوامر الشراء (PO) + سلم الاعتماد (ملف 14 §2)
# ────────────────────────────────────────────────────────────────────
def _po_level(total: Decimal, pol: m.InvPolicy) -> int:
    if total <= D(pol.po_l0_limit):
        return 0
    if total <= D(pol.po_l1_limit):
        return 1
    return 2


def create_po(db: Session, *, tenant_id: str, actor_id: str, supplier_id: str,
              lines: list[dict], expected_date=None, terms: str = '',
              pr_id: str | None = None, tax_amount=0) -> m.InvPurchaseOrder:
    sup = supplier_or_err(db, tenant_id, supplier_id)
    if not lines:
        err('INV.PO_EMPTY', 'أمر الشراء بلا بنود')
    if pr_id:
        pr = db.get(m.InvPurchaseRequest, pr_id)
        if pr is None or pr.tenant_id != tenant_id or pr.status != 'APPROVED':
            err('INV.PR_NOT_APPROVED', 'طلب الشراء المرجعي غير معتمد')
        pr.status = 'CONVERTED'  # §2.1: طلب معتمد تحوّل لأمر — لا إعادة استخدام
    today = date.today()
    pol = get_policy(db, tenant_id)
    built = []
    subtotal = Decimal('0')
    seen = set()
    for ln in lines:
        item = item_or_err(db, tenant_id, ln['item_id'])
        if ln['item_id'] in seen:
            err('INV.DUP_LINE', 'تكرار صنف في أمر الشراء')
        seen.add(ln['item_id'])
        qty = D(ln['qty'])
        if qty <= 0:
            err('INV.BAD_QTY', 'كمية البند يجب أن تكون موجبة')
        uom = (ln.get('uom') or item.base_unit).strip()
        if uom == item.base_unit:
            factor = Decimal('1')
        else:
            factor = D(ln.get('factor', 0))
            if factor <= 0:  # §1 أدوات: المعامل إلزامي عند وحدة ≠ الأساسية
                err('INV.FACTOR_REQUIRED',
                    f'معامل تحويل «{uom}» إلى «{item.base_unit}» إلزامي '
                    f'للصنف {item.code}')
        base_qty = (qty * factor).quantize(Q4)
        price = ln.get('unit_price')
        unit_price = D(price) if price is not None else (
            contract_price(db, tenant_id, supplier_id, item.id, today))
        if unit_price is None:
            err('INV.PRICE_REQUIRED',
                f'لا سعر للصنف {item.code} — أدخل سعراً أو عرّف سعراً تعاقدياً')
        if unit_price <= 0:
            err('INV.BAD_PRICE', 'السعر يجب أن يكون موجباً')
        line_total = (base_qty * unit_price).quantize(Q4)
        built.append({'item_id': item.id, 'uom': uom, 'factor': factor,
                      'qty': qty, 'base_qty': base_qty,
                      'unit_price': unit_price, 'line_total': line_total})
        subtotal += line_total
    tax = D(tax_amount)
    if tax < 0:
        err('INV.BAD_TAX', 'ضريبة الشراء سالبة ممنوعة')
    total = (subtotal + tax).quantize(Q4)
    level = _po_level(total, pol)
    po = m.InvPurchaseOrder(
        id=new_uuid(), tenant_id=tenant_id,
        po_no=next_doc_no(db, tenant_id, 'PO', 'PO'), supplier_id=sup.id,
        pr_id=pr_id, expected_date=expected_date, terms=terms.strip(),
        # قائمة الانتظار تبدأ دوماً من L1 مهما كان السقف النهائي (سلّم
        # تسلسلي: L1 ثم L2 — ملف 14 §2، لا قفز فوق الاعتماد الأول)
        status='APPROVED' if level == 0 else 'PENDING_L1',
        approve_level_required=level, subtotal=subtotal, tax_amount=tax,
        total=total, created_by=actor_id, created_at=_now())
    db.add(po)
    db.flush()
    for b in built:
        db.add(m.InvPOLine(id=new_uuid(), tenant_id=tenant_id, po_id=po.id,
                           **b))
    if level == 0:
        po.approved1_by = 'system'
        po.approved1_at = _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='po.create',
          entity='inv_purchase_orders', entity_id=po.id,
          after={'po_no': po.po_no, 'total': str(total),
                 'level_required': level})
    return po


def approve_po(db: Session, *, tenant_id: str, actor_id: str, po_id: str,
               actor_perms: set[str]) -> m.InvPurchaseOrder:
    """اعتماد على السلم: L1 (مدير القسم) ثم L2 (مالية) — بلا اعتماد ذاتي."""
    po = db.get(m.InvPurchaseOrder, po_id)
    if po is None or po.tenant_id != tenant_id:
        err('INV.UNKNOWN_PO', 'أمر شراء غير موجود')
    if po.created_by == actor_id:
        err('INV.SELF_APPROVAL', 'يمنع اعتماد منشئ الأمر لأمره (ملف 14 §2)')
    if po.status == 'PENDING_L1':
        if 'inv.po.approve.l1' not in actor_perms and '*' not in actor_perms:
            err('RBAC.FORBIDDEN', 'يتطلب اعتماد المستوى الأول للمشتريات')
        po.approved1_by = actor_id
        po.approved1_at = _now()
        if po.approve_level_required >= 2:
            po.status = 'PENDING_L2'
        else:
            po.status = 'APPROVED'
    elif po.status == 'PENDING_L2':
        if 'inv.po.approve.l2' not in actor_perms and '*' not in actor_perms:
            err('RBAC.FORBIDDEN', 'يتطلب اعتماد المستوى الثاني (المالية)')
        po.approved2_by = actor_id
        po.approved2_at = _now()
        po.status = 'APPROVED'
    else:
        err('INV.PO_STATE', f'لا يمكن اعتماد أمر بحالة {po.status}')
    po.version += 1
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='po.approve',
          entity='inv_purchase_orders', entity_id=po.id,
          after={'status': po.status})
    return po


def reject_po(db: Session, *, tenant_id: str, actor_id: str, po_id: str,
              reason: str) -> m.InvPurchaseOrder:
    _require_reason(reason, 'INV.REJECT_REASON')
    po = db.get(m.InvPurchaseOrder, po_id)
    if po is None or po.tenant_id != tenant_id:
        err('INV.UNKNOWN_PO', 'أمر شراء غير موجود')
    if po.status not in ('PENDING_L1', 'PENDING_L2'):
        err('INV.PO_STATE', f'لا يمكن رفض أمر بحالة {po.status}')
    if po.created_by == actor_id:
        err('INV.SELF_APPROVAL', 'يمنع رفض منشئ الأمر لأمره')
    po.status = 'REJECTED'
    po.reject_reason = reason.strip()
    po.version += 1
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='po.reject',
          entity='inv_purchase_orders', entity_id=po.id,
          after={'reason': reason.strip()})
    return po


def cancel_po(db: Session, *, tenant_id: str, actor_id: str, po_id: str,
              reason: str) -> m.InvPurchaseOrder:
    _require_reason(reason)
    po = db.get(m.InvPurchaseOrder, po_id)
    if po is None or po.tenant_id != tenant_id:
        err('INV.UNKNOWN_PO', 'أمر شراء غير موجود')
    if po.status in ('PART_RECEIVED', 'RECEIVED'):
        err('INV.PO_RECEIVED', 'يمنع إلغاء أمر استُلم منه — عالج بالمرتجع')
    if po.status in ('CANCELLED', 'REJECTED'):
        err('INV.PO_STATE', f'الأمر بحالة {po.status} أصلاً')
    po.status = 'CANCELLED'
    po.cancelled_at = _now()
    po.version += 1
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='po.cancel',
          entity='inv_purchase_orders', entity_id=po.id,
          after={'reason': reason.strip()})
    return po


def _refresh_po_receipt_state(db: Session, po_id: str):
    lines = db.execute(select(m.InvPOLine).where(
        m.InvPOLine.po_id == po_id)).scalars().all()
    po = db.get(m.InvPurchaseOrder, po_id)
    if po.status in ('CANCELLED', 'REJECTED'):
        return
    if all(D(l.received_qty) >= D(l.base_qty) for l in lines):
        po.status = 'RECEIVED'
    elif any(D(l.received_qty) > 0 for l in lines):
        po.status = 'PART_RECEIVED'
    else:
        po.status = 'APPROVED'
    po.version += 1
    db.flush()


# ────────────────────────────────────────────────────────────────────
# §2.3 استلام البضاعة (GRN) — الأثر: رصيد + قيد #14/#15
# ────────────────────────────────────────────────────────────────────
def create_grn(db: Session, *, tenant_id: str, actor_id: str, supplier_id: str,
               warehouse_id: str, purchase_type: str, lines: list[dict],
               po_id: str | None = None, supplier_invoice_no: str = '',
               payment_account_code: str = '1101', tax_amount=0,
               note: str = '', bd: date | None = None) -> m.InvGRN:
    sup = supplier_or_err(db, tenant_id, supplier_id)
    wh = warehouse_or_err(db, tenant_id, warehouse_id)
    bd = bd or date.today()
    if purchase_type not in ('CASH', 'CREDIT'):
        err('INV.BAD_PURCHASE_TYPE', 'نوع الشراء CASH|CREDIT فقط')
    if purchase_type == 'CREDIT' and not supplier_invoice_no.strip():
        # §2.3: الفاتورة المرفقة إلزامية للشراء الآجل
        err('INV.INVOICE_REQUIRED',
            'رقم فاتورة المورد إلزامي للشراء الآجل (ملف 05 §2.3)')
    if not lines:
        err('INV.GRN_EMPTY', 'سند الاستلام بلا بنود')
    pol = get_policy(db, tenant_id)
    po = None
    po_lines: dict[str, m.InvPOLine] = {}
    if po_id:
        po = db.get(m.InvPurchaseOrder, po_id)
        if po is None or po.tenant_id != tenant_id:
            err('INV.UNKNOWN_PO', 'أمر شراء غير موجود')
        if po.status not in ('APPROVED', 'PART_RECEIVED'):
            err('INV.PO_NOT_APPROVED',
                f'لا استلام على أمر بحالة {po.status} — اعتماده أولاً')
        if po.supplier_id != sup.id:
            err('INV.PO_SUPPLIER', 'المورد لا يطابق أمر الشراء')
        po_lines = {pl.item_id: pl for pl in db.execute(
            select(m.InvPOLine).where(m.InvPOLine.po_id == po.id))
            .scalars().all()}
    subtotal = Decimal('0')
    built = []
    seen = set()
    for ln in lines:
        item = item_or_err(db, tenant_id, ln['item_id'])
        if item.id in seen:
            err('INV.DUP_LINE', 'تكرار صنف في سند الاستلام')
        seen.add(item.id)
        qty_received = D(ln.get('qty_received', 0))
        qty_rejected = D(ln.get('qty_rejected', 0))
        if qty_received < 0 or qty_rejected < 0:
            err('INV.BAD_QTY', 'كميات الاستلام سالبة ممنوعة')
        if qty_rejected > qty_received:
            err('INV.BAD_REJECT', 'المرفوض يتجاوز المستلم')
        accepted = qty_received - qty_rejected
        if qty_rejected > 0 and not (ln.get('reject_reason') or '').strip():
            err('INV.REJECT_REASON', 'سبب رفض البند الجودة إلزامي (§2.3)')
        if item.track_expiry and accepted > 0 and not ln.get('expiry_date'):
            err('INV.EXPIRY_REQUIRED',
                f'الصنف {item.code} يلزم تاريخ صلاحية عند الاستلام (§1)')
        pl = po_lines.get(item.id)
        unit_price = pl.unit_price if pl else D(ln.get('unit_price', 0))
        if unit_price <= 0:
            err('INV.BAD_PRICE', f'سعر الصنف {item.code} غير صالح')
        if pl is not None:
            # فروقات كمية: نقص حر؛ زيادة ضمن سقف٪ على المتبقي (§2.3)
            remaining = D(pl.base_qty) - D(pl.received_qty)
            cap = (D(pl.base_qty) * D(pol.qty_tolerance_pct) / 100)
            if accepted > remaining + cap.quantize(Q4):
                err('INV.OVER_RECEIPT',
                    f'استلام {item.code} يتجاوز المتبقي {remaining} + '
                    f'تسامح {pol.qty_tolerance_pct}%')
        line_total = (accepted * unit_price).quantize(Q4)
        subtotal += line_total
        built.append({'po_line_id': pl.id if pl else None, 'item_id': item.id,
                      'qty_ordered': D(pl.base_qty) if pl else Decimal('0'),
                      'qty_received': qty_received,
                      'qty_rejected': qty_rejected,
                      'reject_reason': (ln.get('reject_reason') or '').strip()
                                       or None,
                      'unit_price': unit_price, 'line_total': line_total,
                      'batch_no': (ln.get('batch_no') or '').strip(),
                      'expiry_date': ln.get('expiry_date')})
    if not any(b['qty_received'] - b['qty_rejected'] > 0 for b in built):
        err('INV.GRN_ALL_REJECTED', 'كل البنود مرفوضة — لا استلام فعلي')
    tax = D(tax_amount)
    total = (subtotal + tax).quantize(Q4)
    grn = m.InvGRN(id=new_uuid(), tenant_id=tenant_id,
                   grn_no=next_doc_no(db, tenant_id, 'GRN', 'GRN'),
                   po_id=po.id if po else None, supplier_id=sup.id,
                   warehouse_id=wh.id, purchase_type=purchase_type,
                   supplier_invoice_no=supplier_invoice_no.strip(),
                   payment_account_code=payment_account_code,
                   subtotal=subtotal, tax_amount=tax, total=total,
                   note=note.strip(), created_by=actor_id, created_at=_now())
    db.add(grn)
    db.flush()
    for b in built:
        db.add(m.InvGRNLine(id=new_uuid(), tenant_id=tenant_id,
                            grn_id=grn.id, **b))
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='grn.create', entity='inv_grns',
          entity_id=grn.id,
          after={'grn_no': grn.grn_no, 'po': po.po_no if po else None,
                 'total': str(total)})
    return grn


def post_grn(db: Session, *, tenant_id: str, actor_id: str,
             grn_id: str, bd: date | None = None) -> m.InvGRN:
    """ترحيل GRN: رصيد + متوسط + قيد #14/#15 — ذري واحد (V7)."""
    grn = db.get(m.InvGRN, grn_id)
    if grn is None or grn.tenant_id != tenant_id:
        err('INV.UNKNOWN_GRN', 'سند استلام غير موجود')
    if grn.status != 'DRAFT':
        err('INV.GRN_STATE', f'لا يمكن ترحيل سند بحالة {grn.status}')
    wh = warehouse_or_err(db, tenant_id, grn.warehouse_id)
    bd = bd or date.today()
    lines = db.execute(select(m.InvGRNLine).where(
        m.InvGRNLine.grn_id == grn.id)).scalars().all()
    entry = _post_journal(
        db, tenant_id=tenant_id, branch_id=wh.branch_id, entry_date=bd,
        narration=f'استلام مشتريات {grn.grn_no} — {wh.name_ar}'
                  + (f' (فاتورة {grn.supplier_invoice_no})'
                     if grn.supplier_invoice_no else ''),
        raw_lines=_grn_entry_lines(grn, wh), actor_id=actor_id,
        source_type='GRN', source_id=grn.id, reference=grn.grn_no,
        event_key=f'inv:grn:{grn.id}')
    moves = []
    for ln in lines:
        accepted = D(ln.qty_received) - D(ln.qty_rejected)
        if accepted <= 0:
            continue
        mv, _ = apply_inbound(
            db, tenant_id=tenant_id, warehouse=wh, item_id=ln.item_id,
            qty=accepted, unit_cost=ln.unit_price, reason='PURCHASE',
            ref_type='GRN', ref_id=grn.id, actor_id=actor_id, bd=bd,
            batch_no=ln.batch_no, expiry_date=ln.expiry_date,
            entry_id=entry.id)
        moves.append(mv)
        if ln.po_line_id:
            pl = db.get(m.InvPOLine, ln.po_line_id)
            pl.received_qty = D(pl.received_qty) + accepted
    if grn.po_id:
        _refresh_po_receipt_state(db, grn.po_id)
    grn.status = 'POSTED'
    grn.entry_id = entry.id
    grn.posted_by = actor_id
    grn.posted_at = _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='grn.post', entity='inv_grns',
          entity_id=grn.id,
          after={'grn_no': grn.grn_no, 'entry': entry.entry_no,
                 'total': str(grn.total)}, business_date=bd)
    return grn


def _grn_entry_lines(grn: m.InvGRN, wh: m.InvWarehouse) -> list[dict]:
    """#14 نقدي: Dr حساب المستودع (+1150) | Cr نقد/بنك.
    #15 آجل: Dr حساب المستودع (+1150) | Cr 2101 بطرف المورد."""
    lines = [{'account': wh.inventory_account_code, 'debit': D(grn.subtotal),
              'credit': Decimal('0'), 'description': 'إدخال مخزون بسند استلام'}]
    if D(grn.tax_amount) > 0:
        lines.append({'account': VAT_INPUT, 'debit': D(grn.tax_amount),
                      'credit': Decimal('0'),
                      'description': 'ضريبة مدخلات قابلة للاسترداد'})
    if grn.purchase_type == 'CREDIT':
        lines.append({'account': AP_ACCOUNT, 'debit': Decimal('0'),
                      'credit': D(grn.total), 'party_type': 'SUPPLIER',
                      'party_id': grn.supplier_id, 'description': 'ذمة مورد'})
    else:
        lines.append({'account': grn.payment_account_code,
                      'debit': Decimal('0'), 'credit': D(grn.total),
                      'description': 'سداد شراء نقدي'})
    return lines


def ensure_grn_mutable(grn: m.InvGRN):
    """حارس قبول §7.4 — كل مسار تعديل يمر من هنا (واجهة/خدمة/DB في
    الإنتاج عبر Trigger في sql/postgres_hardening.sql)."""
    if grn.status != 'DRAFT':
        err('INV.GRN_IMMUTABLE',
            'سند استلام مرحَّل لا يُعدَّل إطلاقاً — التصحيح بعكس + سند '
            'جديد (ملف 05 §2 قاعدة)')


def reverse_grn(db: Session, *, tenant_id: str, actor_id: str, grn_id: str,
                reason: str, bd: date | None = None) -> m.InvGRN:
    """عكس GRN مرحَّل: قيد عكسي كامل + سحب الكميات بسعرها الأصلي
    (يغسل القيمة تماماً مع ثبات المتوسط بقاعدة القيمة)."""
    _require_reason(reason)
    grn = db.get(m.InvGRN, grn_id)
    if grn is None or grn.tenant_id != tenant_id:
        err('INV.UNKNOWN_GRN', 'سند استلام غير موجود')
    if grn.status != 'POSTED':
        err('INV.GRN_STATE', f'لا يمكن عكس سند بحالة {grn.status}')
    linked = db.execute(select(m.InvSupplierInvoice).where(
        m.InvSupplierInvoice.grn_id == grn.id,
        m.InvSupplierInvoice.status.in_(['MATCHED', 'VARIANCE_HOLD',
                                         'APPROVED', 'PAID']))).first()
    if linked:
        err('INV.GRN_HAS_INVOICE',
            'السند مرتبط بفاتورة مورد فعالة — ألغِ الفاتورة أولاً')
    wh = warehouse_or_err(db, tenant_id, grn.warehouse_id)
    bd = bd or date.today()
    rev = reverse_entry(db, tenant_id=tenant_id, entry_id=grn.entry_id,
                        reason=f'عكس استلام {grn.grn_no}: {reason.strip()}',
                        actor_id=actor_id, reversal_date=bd)
    for ln in db.execute(select(m.InvGRNLine).where(
            m.InvGRNLine.grn_id == grn.id)).scalars().all():
        accepted = D(ln.qty_received) - D(ln.qty_rejected)
        if accepted <= 0:
            continue
        apply_outbound(db, tenant_id=tenant_id, warehouse=wh,
                       item_id=ln.item_id, qty=accepted,
                       unit_cost=ln.unit_price,  # بسعر الإدخال الأصلي
                       reason='PURCHASE_REV', ref_type='GRN', ref_id=grn.id,
                       actor_id=actor_id, bd=bd, entry_id=rev.id)
        if ln.po_line_id:
            pl = db.get(m.InvPOLine, ln.po_line_id)
            pl.received_qty = D(pl.received_qty) - accepted
    if grn.po_id:
        _refresh_po_receipt_state(db, grn.po_id)
    grn.status = 'REVERSED'
    grn.reversal_entry_id = rev.id
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='grn.reverse', entity='inv_grns',
          entity_id=grn.id,
          after={'grn_no': grn.grn_no, 'reversal': rev.entry_no,
                 'reason': reason.strip()}, business_date=bd)
    return grn


# ────────────────────────────────────────────────────────────────────
# §2.4 فاتورة المورد والمطابقة الثلاثية (PO ↔ GRN ↔ Invoice)
# ────────────────────────────────────────────────────────────────────
def create_supplier_invoice(db: Session, *, tenant_id: str, actor_id: str,
                            supplier_id: str, supplier_invoice_no: str,
                            invoice_date: date, lines: list[dict],
                            po_id: str | None = None, grn_id: str | None = None,
                            tax_amount=0) -> m.InvSupplierInvoice:
    sup = supplier_or_err(db, tenant_id, supplier_id)
    if not supplier_invoice_no.strip():
        err('INV.INVOICE_NO_REQUIRED', 'رقم فاتورة المورد إلزامي')
    if db.execute(select(m.InvSupplierInvoice).where(
            m.InvSupplierInvoice.tenant_id == tenant_id,
            m.InvSupplierInvoice.supplier_id == sup.id,
            m.InvSupplierInvoice.supplier_invoice_no ==
            supplier_invoice_no.strip())).first():
        err('INV.DUP_SUP_INVOICE', 'فاتورة المورد هذه مسجلة مسبقاً (رقم مكرر)')
    if not lines:
        err('INV.SI_EMPTY', 'فاتورة بلا بنود')
    po = None
    if po_id:
        po = db.get(m.InvPurchaseOrder, po_id)
        if po is None or po.tenant_id != tenant_id:
            err('INV.UNKNOWN_PO', 'أمر شراء غير موجود')
        if po.supplier_id != sup.id:
            err('INV.PO_SUPPLIER', 'المورد لا يطابق أمر الشراء')
    grn = None
    if grn_id:
        grn = db.get(m.InvGRN, grn_id)
        if grn is None or grn.tenant_id != tenant_id:
            err('INV.UNKNOWN_GRN', 'سند استلام غير موجود')
        if grn.supplier_id != sup.id:
            err('INV.GRN_SUPPLIER', 'المورد لا يطابق سند الاستلام')
        if grn.status != 'POSTED':
            err('INV.GRN_NOT_POSTED', 'سند الاستلام غير مرحَّل')
    subtotal = Decimal('0')
    inv = m.InvSupplierInvoice(
        id=new_uuid(), tenant_id=tenant_id,
        sinv_no=next_doc_no(db, tenant_id, 'SINV', 'PINV'),
        supplier_invoice_no=supplier_invoice_no.strip(), supplier_id=sup.id,
        po_id=po.id if po else None, grn_id=grn.id if grn else None,
        invoice_date=invoice_date, status='DRAFT', subtotal=Decimal('0'),
        tax_amount=D(tax_amount), total=Decimal('0'), created_by=actor_id,
        created_at=_now())
    db.add(inv)
    db.flush()
    for ln in lines:
        item_or_err(db, tenant_id, ln['item_id'])
        q, p = D(ln['qty']), D(ln['unit_price'])
        if q <= 0 or p <= 0:
            err('INV.BAD_LINE', 'كمية/سعر بند الفاتورة يجب أن يكون موجباً')
        lt = (q * p).quantize(Q4)
        subtotal += lt
        db.add(m.InvSILine(id=new_uuid(), tenant_id=tenant_id,
                           sinv_id=inv.id, item_id=ln['item_id'], qty=q,
                           unit_price=p, line_total=lt))
    inv.subtotal = subtotal
    inv.total = (subtotal + inv.tax_amount).quantize(Q4)
    db.flush()
    _run_three_way_match(db, inv, pol=get_policy(db, tenant_id))
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='sinvoice.create',
          entity='inv_supplier_invoices', entity_id=inv.id,
          after={'sinv_no': inv.sinv_no, 'status': inv.status,
                 'total': str(inv.total)})
    return inv


def _run_three_way_match(db: Session, inv: m.InvSupplierInvoice,
                         pol: m.InvPolicy) -> m.InvSupplierInvoice:
    """المطابقة (قبول §7.3): سعر البند مقابل PO (تسامح٪) والكمية مقابل
    المقبول فعلياً في GRN — أي خرق → VARIANCE_HOLD تلقائياً."""
    issues: list[dict] = []
    po_lines: dict[str, m.InvPOLine] = {}
    if inv.po_id:
        po_lines = {pl.item_id: pl for pl in db.execute(
            select(m.InvPOLine).where(m.InvPOLine.po_id == inv.po_id))
            .scalars().all()}
    grn_accepted: dict[str, Decimal] = {}
    if inv.grn_id:
        for gl in db.execute(select(m.InvGRNLine).where(
                m.InvGRNLine.grn_id == inv.grn_id)).scalars().all():
            acc = D(gl.qty_received) - D(gl.qty_rejected)
            grn_accepted[gl.item_id] = (grn_accepted.get(gl.item_id,
                                                         Decimal('0')) + acc)
    for ln in db.execute(select(m.InvSILine).where(
            m.InvSILine.sinv_id == inv.id)).scalars().all():
        item = db.get(m.InvItem, ln.item_id)
        code = item.code if item else ln.item_id
        pl = po_lines.get(ln.item_id)
        if inv.po_id and pl is None:
            issues.append({'item': code, 'issue': 'NOT_IN_PO',
                           'detail': 'الصنف غير وارد في أمر الشراء'})
            continue
        if pl is not None and D(pl.unit_price) > 0:
            diff = D(ln.unit_price) - D(pl.unit_price)
            limit = (D(pl.unit_price) * D(pol.price_tolerance_pct) / 100)
            if abs(diff) > limit.quantize(Q4):
                issues.append({'item': code, 'issue': 'PRICE_VARIANCE',
                               'detail': f'سعر الفاتورة {ln.unit_price} ≠ '
                                         f'سعر الأمر {pl.unit_price} '
                                         f'(تسامح {pol.price_tolerance_pct}%)',
                               'diff': str(diff)})
        if inv.grn_id:
            accepted = grn_accepted.get(ln.item_id, Decimal('0'))
            if D(ln.qty) > accepted:
                issues.append({'item': code, 'issue': 'QTY_OVER_RECEIVED',
                               'detail': f'مفوتر {ln.qty} > مقبول مستلم '
                                         f'{accepted}'})
    inv.match_report = {'checked_at': _now().isoformat(), 'issues': issues,
                        'result': 'HOLD' if issues else 'MATCH'}
    inv.status = 'VARIANCE_HOLD' if issues else 'MATCHED'
    db.flush()
    return inv


def approve_supplier_invoice(db: Session, *, tenant_id: str, actor_id: str,
                             sinv_id: str) -> m.InvSupplierInvoice:
    inv = db.get(m.InvSupplierInvoice, sinv_id)
    if inv is None or inv.tenant_id != tenant_id:
        err('INV.UNKNOWN_SINVOICE', 'فاتورة مورد غير موجودة')
    if inv.created_by == actor_id:
        err('INV.SELF_APPROVAL', 'يمنع اعتماد منشئ الفاتورة لفاتورته')
    if inv.status != 'MATCHED':
        err('INV.SI_NOT_MATCHED',
            f'لا اعتماد لفاتورة بحالة {inv.status} — عالج الفروقات أولاً')
    inv.status = 'APPROVED'
    inv.approved_by = actor_id
    inv.approved_at = _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='sinvoice.approve',
          entity='inv_supplier_invoices', entity_id=inv.id)
    return inv


def resolve_variance(db: Session, *, tenant_id: str, actor_id: str,
                     sinv_id: str, action: str,
                     corrected_lines: list[dict] | None = None,
                     actor_perms: set[str] | None = None,
                     bd: date | None = None) -> m.InvSupplierInvoice:
    """معالجة فرق السعر (§2.4): تفاوض (EDIT وإعادة مطابقة) أو اعتماد
    الفرق لحساب 5120 بقيد تسوية على الذمة."""
    inv = db.get(m.InvSupplierInvoice, sinv_id)
    if inv is None or inv.tenant_id != tenant_id:
        err('INV.UNKNOWN_SINVOICE', 'فاتورة مورد غير موجودة')
    if inv.status != 'VARIANCE_HOLD':
        err('INV.SI_NOT_HELD', f'لا معالجة فروقات لفاتورة بحالة {inv.status}')
    if action == 'EDIT':  # تفاوض: تصحيح بنود الفاتورة ثم إعادة المطابقة
        if not corrected_lines:
            err('INV.EDIT_LINES_REQUIRED', 'بنود مصححة مطلوبة للتفاوض')
        db.query(m.InvSILine).filter(m.InvSILine.sinv_id == inv.id).delete()
        subtotal = Decimal('0')
        for ln in corrected_lines:
            item_or_err(db, tenant_id, ln['item_id'])
            q, p = D(ln['qty']), D(ln['unit_price'])
            if q <= 0 or p <= 0:
                err('INV.BAD_LINE', 'كمية/سعر بند يجب أن يكون موجباً')
            lt = (q * p).quantize(Q4)
            subtotal += lt
            db.add(m.InvSILine(id=new_uuid(), tenant_id=tenant_id,
                               sinv_id=inv.id, item_id=ln['item_id'], qty=q,
                               unit_price=p, line_total=lt))
        inv.subtotal = subtotal
        inv.total = (subtotal + inv.tax_amount).quantize(Q4)
        db.flush()
        _run_three_way_match(db, inv, pol=get_policy(db, tenant_id))
        audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
              module='inventory', action='sinvoice.edit_rematch',
              entity='inv_supplier_invoices', entity_id=inv.id,
              after={'status': inv.status})
        return inv
    if action == 'APPROVE_VARIANCE':
        if actor_perms is None:
            actor_perms = set()
        if 'inv.variance.approve' not in actor_perms and \
                '*' not in actor_perms:
            err('RBAC.FORBIDDEN', 'اعتماد فرق السعر يتطلب صلاحية المالية')
        if inv.created_by == actor_id:
            err('INV.SELF_APPROVAL', 'يمنع اعتماد منشئ الفاتورة لفرقه')
        # فرق السعر الإجمالي مقابل أسعار PO (سالب = لصالحنا)
        diff_total = Decimal('0')
        for iss in (inv.match_report or {}).get('issues', []):
            if iss.get('issue') == 'PRICE_VARIANCE':
                ln = db.execute(select(m.InvSILine).join(
                    m.InvItem, m.InvItem.id == m.InvSILine.item_id).where(
                    m.InvSILine.sinv_id == inv.id,
                    m.InvItem.code == iss['item'])) .scalar_one_or_none()
                if ln is not None:
                    diff_total += D(iss['diff']) * D(ln.qty)
        entry = None
        bd = bd or date.today()
        if diff_total != 0:
            debit = {'account': PPV_ACCOUNT if diff_total > 0 else AP_ACCOUNT,
                     'debit': abs(diff_total), 'credit': Decimal('0'),
                     'description': 'فرق سعر شراء معتمد'}
            credit = {'account': AP_ACCOUNT if diff_total > 0 else PPV_ACCOUNT,
                      'debit': Decimal('0'), 'credit': abs(diff_total),
                      'description': 'تسوية ذمة المورد بفرق السعر'}
            if diff_total > 0:
                credit['party_type'] = 'SUPPLIER'
                credit['party_id'] = inv.supplier_id
            else:
                debit['party_type'] = 'SUPPLIER'
                debit['party_id'] = inv.supplier_id
            entry = _post_journal(
                db, tenant_id=tenant_id,
                branch_id=_branch_id(db, tenant_id), entry_date=bd,
                narration=f'فرق سعر شراء معتمد — فاتورة {inv.sinv_no}',
                raw_lines=[debit, credit], actor_id=actor_id,
                source_type='SUPPLIER_INVOICE', source_id=inv.id,
                reference=inv.sinv_no, event_key=f'inv:ppv:{inv.id}')
        inv.status = 'APPROVED'
        inv.variance_approved_by = actor_id
        inv.variance_entry_id = entry.id if entry else None
        inv.approved_by = actor_id
        inv.approved_at = _now()
        db.flush()
        audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
              module='inventory', action='sinvoice.variance_approve',
              entity='inv_supplier_invoices', entity_id=inv.id,
              after={'diff_total': str(diff_total),
                     'entry': entry.entry_no if entry else None},
              business_date=bd)
        return inv
    err('INV.BAD_RESOLVE', 'إجراء المعالجة EDIT|APPROVE_VARIANCE فقط')


# ────────────────────────────────────────────────────────────────────
# §2.5 سداد المورد (#16) — خصم مكتسب دائناً 4901 دائماً
# ────────────────────────────────────────────────────────────────────
def pay_supplier(db: Session, *, tenant_id: str, actor_id: str,
                 supplier_id: str, amount, method: str = 'CASH',
                 discount=0, allocations: list[dict] | None = None,
                 payment_date: date | None = None) -> m.InvSupplierPayment:
    sup = supplier_or_err(db, tenant_id, supplier_id)
    amount, discount = D(amount), D(discount)
    if amount <= 0:
        err('INV.BAD_AMOUNT', 'مبلغ السداد يجب أن يكون موجباً')
    if discount < 0:
        err('INV.BAD_DISCOUNT', 'الخصم المكتسب سالب ممنوع')
    if method not in PAY_ACCOUNTS:
        err('INV.BAD_METHOD', 'وسيلة سداد CASH|BANK|EWALLET فقط')
    bd = payment_date or date.today()
    allocs = []
    allocated = Decimal('0')
    for a in (allocations or []):
        inv = db.get(m.InvSupplierInvoice, a.get('invoice_id', ''))
        if inv is None or inv.tenant_id != tenant_id or \
                inv.supplier_id != sup.id:
            err('INV.ALLOC_INVOICE', 'فاتورة تخصيص غير صالحة لهذا المورد')
        if inv.status not in ('APPROVED', 'PAID'):
            err('INV.ALLOC_STATE',
                f'لا تخصيص على فاتورة بحالة {inv.status} — اعتمدها أولاً')
        amt = D(a.get('amount', 0))
        if amt <= 0:
            err('INV.ALLOC_AMOUNT', 'مبلغ التخصيص يجب أن يكون موجباً')
        remaining = D(inv.total) - D(inv.paid_amount)
        if amt > remaining:
            err('INV.ALLOC_OVER',
                f'التخصيص {amt} يتجاوز المتبقي للفاتورة {remaining}')
        allocated += amt
        allocs.append({'invoice_id': inv.id, 'sinv_no': inv.sinv_no,
                       'amount': str(amt)})
    if allocated > amount:
        err('INV.ALLOC_OVERPAY', 'مجموع التخصيصات يتجاوز مبلغ السداد')
    pay = m.InvSupplierPayment(
        id=new_uuid(), tenant_id=tenant_id,
        pay_no=next_doc_no(db, tenant_id, 'SPAY', 'SVP'), supplier_id=sup.id,
        payment_date=bd, method=method, account_code=PAY_ACCOUNTS[method],
        amount=amount, discount=discount, allocations=allocs,
        created_by=actor_id, created_at=_now())
    db.add(pay)
    db.flush()
    # #16: Dr 2101 طرف (المبلغ+الخصم) | Cr نقد/بنك (المبلغ) | Cr 4901 (الخصم)
    raw = [{'account': AP_ACCOUNT, 'debit': amount + discount,
            'credit': Decimal('0'), 'party_type': 'SUPPLIER',
            'party_id': sup.id, 'description': 'سداد ذمة مورد'},
           {'account': pay.account_code, 'debit': Decimal('0'),
            'credit': amount, 'description': f'سداد {method}'}]
    if discount > 0:
        raw.append({'account': OVER_ACCOUNT, 'debit': Decimal('0'),
                    'credit': discount, 'description': 'خصم مكتسب'})
    entry = _post_journal(
        db, tenant_id=tenant_id, branch_id=_branch_id(db, tenant_id),
        entry_date=bd,
        narration=f'سداد مورد {sup.name} — سند {pay.pay_no}',
        raw_lines=raw, actor_id=actor_id, source_type='SUPPLIER_PAYMENT',
        source_id=pay.id, reference=pay.pay_no,
        event_key=f'inv:pay:{pay.id}')
    for a in allocs:
        inv = db.get(m.InvSupplierInvoice, a['invoice_id'])
        inv.paid_amount = D(inv.paid_amount) + D(a['amount'])
        if D(inv.paid_amount) >= D(inv.total):
            inv.status = 'PAID'
    pay.entry_id = entry.id
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='supplier.pay',
          entity='inv_supplier_payments', entity_id=pay.id,
          after={'pay_no': pay.pay_no, 'amount': str(amount),
                 'discount': str(discount), 'entry': entry.entry_no},
          business_date=bd)
    return pay


# ────────────────────────────────────────────────────────────────────
# §2.6 مرتجع المشتريات للمورد (#17) — مستند مستقل
# ────────────────────────────────────────────────────────────────────
def create_supplier_return(db: Session, *, tenant_id: str, actor_id: str,
                           supplier_id: str, warehouse_id: str,
                           lines: list[dict], reason: str,
                           grn_id: str | None = None,
                           refund_to: str = 'CREDIT_AP') -> m.InvSupplierReturn:
    sup = supplier_or_err(db, tenant_id, supplier_id)
    wh = warehouse_or_err(db, tenant_id, warehouse_id)
    _require_reason(reason)
    if refund_to not in ('CREDIT_AP', 'CASH'):
        err('INV.BAD_REFUND', 'وجهة الاسترداد CREDIT_AP|CASH فقط')
    if grn_id:
        grn = db.get(m.InvGRN, grn_id)
        if grn is None or grn.tenant_id != tenant_id or \
                grn.supplier_id != sup.id:
            err('INV.GRN_SUPPLIER', 'سند الاستلام المرجعي لا يخص المورد')
    if not lines:
        err('INV.SRT_EMPTY', 'مرتجع بلا بنود')
    srt = m.InvSupplierReturn(
        id=new_uuid(), tenant_id=tenant_id,
        srt_no=next_doc_no(db, tenant_id, 'SRT', 'SRT'), supplier_id=sup.id,
        warehouse_id=wh.id, grn_id=grn_id, refund_to=refund_to,
        reason=reason.strip(), created_by=actor_id, created_at=_now())
    db.add(srt)
    db.flush()
    for ln in lines:
        item_or_err(db, tenant_id, ln['item_id'])
        qty = D(ln['qty'])
        if qty <= 0:
            err('INV.BAD_QTY', 'كمية البند يجب أن تكون موجبة')
        db.add(m.InvSRTLine(id=new_uuid(), tenant_id=tenant_id,
                            srt_id=srt.id, item_id=ln['item_id'], qty=qty))
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='sreturn.create',
          entity='inv_supplier_returns', entity_id=srt.id,
          after={'srt_no': srt.srt_no, 'lines': len(lines)})
    return srt


def post_supplier_return(db: Session, *, tenant_id: str, actor_id: str,
                         srt_id: str, bd: date | None = None) -> m.InvSupplierReturn:
    srt = db.get(m.InvSupplierReturn, srt_id)
    if srt is None or srt.tenant_id != tenant_id:
        err('INV.UNKNOWN_SRT', 'مرتجع غير موجود')
    if srt.status != 'DRAFT':
        err('INV.SRT_STATE', f'لا يمكن ترحيل مرتجع بحالة {srt.status}')
    wh = warehouse_or_err(db, tenant_id, srt.warehouse_id)
    bd = bd or date.today()
    total = Decimal('0')
    for ln in db.execute(select(m.InvSRTLine).where(
            m.InvSRTLine.srt_id == srt.id)).scalars().all():
        mv, applied, _ = apply_outbound(
            db, tenant_id=tenant_id, warehouse=wh, item_id=ln.item_id,
            qty=ln.qty, reason='PURCHASE_RETURN', ref_type='SRT',
            ref_id=srt.id, actor_id=actor_id, bd=bd)
        lt = (applied * D(ln.qty)).quantize(Q4)
        ln.unit_cost, ln.line_total = applied, lt
        total += lt
    srt.total = total
    debit_acct = AP_ACCOUNT if srt.refund_to == 'CREDIT_AP' else '1101'
    debit = {'account': debit_acct, 'debit': total, 'credit': Decimal('0'),
             'description': 'مرتجع مشتريات للمورد'}
    if srt.refund_to == 'CREDIT_AP':
        debit['party_type'] = 'SUPPLIER'
        debit['party_id'] = srt.supplier_id
    entry = _post_journal(
        db, tenant_id=tenant_id, branch_id=wh.branch_id, entry_date=bd,
        narration=f'مرتجع مشتريات {srt.srt_no} — {srt.reason}',
        raw_lines=[debit,
                   {'account': wh.inventory_account_code,
                    'debit': Decimal('0'), 'credit': total,
                    'description': 'خفض مخزون بمرتجع مورد'}],
        actor_id=actor_id, source_type='SUPPLIER_RETURN', source_id=srt.id,
        reference=srt.srt_no, event_key=f'inv:srt:{srt.id}')
    srt.entry_id = entry.id
    srt.status = 'POSTED'
    srt.posted_at = _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='sreturn.post',
          entity='inv_supplier_returns', entity_id=srt.id,
          after={'srt_no': srt.srt_no, 'total': str(total),
                 'entry': entry.entry_no}, business_date=bd)
    return srt


# ────────────────────────────────────────────────────────────────────
# §3 صرف المواد للأقسام (#18) — بلا أثر دخل
# ────────────────────────────────────────────────────────────────────
def create_issue(db: Session, *, tenant_id: str, actor_id: str,
                 from_warehouse_id: str, to_warehouse_id: str,
                 department: str, lines: list[dict],
                 reason: str = '') -> m.InvIssue:
    src = warehouse_or_err(db, tenant_id, from_warehouse_id)
    dst = warehouse_or_err(db, tenant_id, to_warehouse_id)
    if src.id == dst.id:
        err('INV.SAME_WAREHOUSE', 'مصدر الصرف ووجهته مستودع واحد')
    if dst.kind == 'OUTLET':
        err('INV.ISSUE_TO_OUTLET',
            'الصرف للمنافذ يتم عبر تحويل مخزني لا بموجب صرف قسم')
    if not lines:
        err('INV.ISSUE_EMPTY', 'طلب الصرف بلا بنود')
    iss = m.InvIssue(id=new_uuid(), tenant_id=tenant_id,
                     iss_no=next_doc_no(db, tenant_id, 'ISS', 'ISS'),
                     from_warehouse_id=src.id, to_warehouse_id=dst.id,
                     department=department.strip(), reason=reason.strip(),
                     created_by=actor_id, created_at=_now())
    db.add(iss)
    db.flush()
    seen = set()
    for ln in lines:
        item_or_err(db, tenant_id, ln['item_id'])
        if ln['item_id'] in seen:
            err('INV.DUP_LINE', 'تكرار صنف في طلب الصرف')
        seen.add(ln['item_id'])
        if D(ln['qty']) <= 0:
            err('INV.BAD_QTY', 'كمية البند يجب أن تكون موجبة')
        db.add(m.InvIssueLine(id=new_uuid(), tenant_id=tenant_id,
                              issue_id=iss.id, item_id=ln['item_id'],
                              qty=D(ln['qty'])))
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='issue.create', entity='inv_issues',
          entity_id=iss.id, after={'iss_no': iss.iss_no})
    return iss


def approve_issue(db: Session, *, tenant_id: str, actor_id: str,
                  issue_id: str, approve: bool,
                  reason: str = '') -> m.InvIssue:
    iss = db.get(m.InvIssue, issue_id)
    if iss is None or iss.tenant_id != tenant_id:
        err('INV.UNKNOWN_ISSUE', 'طلب صرف غير موجود')
    if iss.status != 'REQUESTED':
        err('INV.ISSUE_STATE', f'لا اعتماد لطلب بحالة {iss.status}')
    if iss.created_by == actor_id:
        err('INV.SELF_APPROVAL', 'يمنع اعتماد منشئ الطلب لطلبه')
    if approve:
        iss.status = 'APPROVED'
        iss.approved_by = actor_id
        iss.approved_at = _now()
    else:
        _require_reason(reason, 'INV.REJECT_REASON')
        iss.status = 'REJECTED'
        iss.reason = f'{iss.reason} — رفض: {reason.strip()}'.strip(' —')
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory',
          action='issue.approve' if approve else 'issue.reject',
          entity='inv_issues', entity_id=iss.id,
          after={'approve': approve})
    return iss


def execute_issue(db: Session, *, tenant_id: str, actor_id: str,
                  issue_id: str, bd: date | None = None) -> m.InvIssue:
    """الصرف الفعلي: خصم المصدر بالمتوسط وإدخال الوجهة بنفس التكلفة،
    وقيد #18 فقط عند اختلاف حسابَي المستودعين (بلا أثر دخل دائماً)."""
    iss = db.get(m.InvIssue, issue_id)
    if iss is None or iss.tenant_id != tenant_id:
        err('INV.UNKNOWN_ISSUE', 'طلب صرف غير موجود')
    if iss.status != 'APPROVED':
        err('INV.ISSUE_STATE', f'لا صرف لطلب بحالة {iss.status}')
    src = warehouse_or_err(db, tenant_id, iss.from_warehouse_id)
    dst = warehouse_or_err(db, tenant_id, iss.to_warehouse_id)
    bd = bd or date.today()
    total = Decimal('0')
    for ln in db.execute(select(m.InvIssueLine).where(
            m.InvIssueLine.issue_id == iss.id)).scalars().all():
        mv, applied, _ = apply_outbound(
            db, tenant_id=tenant_id, warehouse=src, item_id=ln.item_id,
            qty=ln.qty, reason='ISSUE_OUT', ref_type='ISSUE',
            ref_id=iss.id, actor_id=actor_id, bd=bd)
        apply_inbound(db, tenant_id=tenant_id, warehouse=dst,
                      item_id=ln.item_id, qty=ln.qty, unit_cost=applied,
                      reason='ISSUE_IN', ref_type='ISSUE', ref_id=iss.id,
                      actor_id=actor_id, bd=bd)
        ln.unit_cost = applied
        ln.line_value = (applied * D(ln.qty)).quantize(Q4)
        total += ln.line_value
    entry = None
    if src.inventory_account_code != dst.inventory_account_code and total > 0:
        entry = _post_journal(
            db, tenant_id=tenant_id, branch_id=src.branch_id, entry_date=bd,
            narration=f'صرف مواد {iss.iss_no} — {src.name_ar} ← {dst.name_ar}',
            raw_lines=[{'account': dst.inventory_account_code, 'debit': total,
                        'credit': Decimal('0'),
                        'description': 'إدخال لمستودع القسم'},
                       {'account': src.inventory_account_code,
                        'debit': Decimal('0'), 'credit': total,
                        'description': 'خفض مستودع المصدر'}],
            actor_id=actor_id, source_type='STOCK_ISSUE', source_id=iss.id,
            reference=iss.iss_no, event_key=f'inv:issue:{iss.id}')
    iss.entry_id = entry.id if entry else None
    iss.status = 'ISSUED'
    iss.issued_by = actor_id
    iss.issued_at = _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='issue.execute', entity='inv_issues',
          entity_id=iss.id,
          after={'iss_no': iss.iss_no, 'value': str(total),
                 'entry': entry.entry_no if entry else None},
          business_date=bd)
    return iss


# ────────────────────────────────────────────────────────────────────
# §3 التحويلات بين المستودعات + «على الطريق»
# ────────────────────────────────────────────────────────────────────
def create_transfer(db: Session, *, tenant_id: str, actor_id: str,
                    from_warehouse_id: str, to_warehouse_id: str,
                    lines: list[dict], reason: str,
                    requires_receive: bool = True) -> m.InvTransfer:
    _require_reason(reason)  # §3: تحويل بمسوغ
    src = warehouse_or_err(db, tenant_id, from_warehouse_id)
    dst = warehouse_or_err(db, tenant_id, to_warehouse_id)
    if src.id == dst.id:
        err('INV.SAME_WAREHOUSE', 'مصدر التحويل ووجهته مستودع واحد')
    if not lines:
        err('INV.TRF_EMPTY', 'تحويل بلا بنود')
    trf = m.InvTransfer(id=new_uuid(), tenant_id=tenant_id,
                        trf_no=next_doc_no(db, tenant_id, 'TRF', 'TRF'),
                        from_warehouse_id=src.id, to_warehouse_id=dst.id,
                        requires_receive=requires_receive,
                        reason=reason.strip(), created_by=actor_id,
                        created_at=_now())
    db.add(trf)
    db.flush()
    seen = set()
    for ln in lines:
        item_or_err(db, tenant_id, ln['item_id'])
        if ln['item_id'] in seen:
            err('INV.DUP_LINE', 'تكرار صنف في التحويل')
        seen.add(ln['item_id'])
        if D(ln['qty']) <= 0:
            err('INV.BAD_QTY', 'كمية البند يجب أن تكون موجبة')
        db.add(m.InvTransferLine(id=new_uuid(), tenant_id=tenant_id,
                                 transfer_id=trf.id, item_id=ln['item_id'],
                                 qty=D(ln['qty'])))
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='transfer.create',
          entity='inv_transfers', entity_id=trf.id,
          after={'trf_no': trf.trf_no, 'requires_receive': requires_receive})
    return trf


def dispatch_transfer(db: Session, *, tenant_id: str, actor_id: str,
                      transfer_id: str, bd: date | None = None) -> m.InvTransfer:
    trf = db.get(m.InvTransfer, transfer_id)
    if trf is None or trf.tenant_id != tenant_id:
        err('INV.UNKNOWN_TRF', 'تحويل غير موجود')
    if trf.status != 'DRAFT':
        err('INV.TRF_STATE', f'لا شحن لتحويل بحالة {trf.status}')
    src = warehouse_or_err(db, tenant_id, trf.from_warehouse_id)
    bd = bd or date.today()
    for ln in db.execute(select(m.InvTransferLine).where(
            m.InvTransferLine.transfer_id == trf.id)).scalars().all():
        mv, applied, _ = apply_outbound(
            db, tenant_id=tenant_id, warehouse=src, item_id=ln.item_id,
            qty=ln.qty, reason='TRANSFER_OUT', ref_type='TRF',
            ref_id=trf.id, actor_id=actor_id, bd=bd)
        ln.unit_cost = applied
    if trf.requires_receive:
        trf.status = 'IN_TRANSIT'  # «على الطريق» — بانتظار الاستلام (§3)
    trf.dispatched_by = actor_id
    trf.dispatched_at = _now()
    db.flush()
    if not trf.requires_receive:
        _receive_transfer_core(db, tenant_id=tenant_id, trf=trf,
                               actor_id=actor_id, bd=bd)
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='transfer.dispatch',
          entity='inv_transfers', entity_id=trf.id,
          after={'trf_no': trf.trf_no, 'status': trf.status},
          business_date=bd)
    return trf


def _receive_transfer_core(db: Session, *, tenant_id: str,
                           trf: m.InvTransfer, actor_id: str,
                           bd: date) -> m.InvTransfer:
    dst = warehouse_or_err(db, tenant_id, trf.to_warehouse_id)
    src = db.get(m.InvWarehouse, trf.from_warehouse_id)
    total = Decimal('0')
    for ln in db.execute(select(m.InvTransferLine).where(
            m.InvTransferLine.transfer_id == trf.id)).scalars().all():
        cost = D(ln.unit_cost) if ln.unit_cost is not None else Decimal('0')
        apply_inbound(db, tenant_id=tenant_id, warehouse=dst,
                      item_id=ln.item_id, qty=ln.qty, unit_cost=cost,
                      reason='TRANSFER_IN', ref_type='TRF', ref_id=trf.id,
                      actor_id=actor_id, bd=bd)
        total += (cost * D(ln.qty)).quantize(Q4)
    entry = None
    if src.inventory_account_code != dst.inventory_account_code and total > 0:
        entry = _post_journal(
            db, tenant_id=tenant_id, branch_id=src.branch_id, entry_date=bd,
            narration=f'تحويل مخزني {trf.trf_no} — {trf.reason}',
            raw_lines=[{'account': dst.inventory_account_code, 'debit': total,
                        'credit': Decimal('0'),
                        'description': 'إدخال لمستودع الوجهة'},
                       {'account': src.inventory_account_code,
                        'debit': Decimal('0'), 'credit': total,
                        'description': 'خفض مستودع المصدر'}],
            actor_id=actor_id, source_type='STOCK_TRANSFER',
            source_id=trf.id, reference=trf.trf_no,
            event_key=f'inv:trf:{trf.id}')
    trf.entry_id = entry.id if entry else None
    trf.status = 'RECEIVED'
    trf.received_by = actor_id
    trf.received_at = _now()
    db.flush()
    return trf


def receive_transfer(db: Session, *, tenant_id: str, actor_id: str,
                     transfer_id: str, bd: date | None = None) -> m.InvTransfer:
    trf = db.get(m.InvTransfer, transfer_id)
    if trf is None or trf.tenant_id != tenant_id:
        err('INV.UNKNOWN_TRF', 'تحويل غير موجود')
    if trf.status != 'IN_TRANSIT':
        err('INV.TRF_STATE', f'لا استلام لتحويل بحالة {trf.status}')
    if trf.dispatched_by == actor_id:
        err('INV.SELF_RECEIVE', 'يمنع استلام من قام بالشحن (ثنائية التحويل)')
    _receive_transfer_core(db, tenant_id=tenant_id, trf=trf,
                           actor_id=actor_id, bd=bd or date.today())
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='transfer.receive',
          entity='inv_transfers', entity_id=trf.id,
          after={'trf_no': trf.trf_no,
                 'entry': db.get(m.JournalEntry, trf.entry_id).entry_no
                 if trf.entry_id else None})
    return trf


def cancel_transfer(db: Session, *, tenant_id: str, actor_id: str,
                    transfer_id: str, reason: str) -> m.InvTransfer:
    _require_reason(reason)
    trf = db.get(m.InvTransfer, transfer_id)
    if trf is None or trf.tenant_id != tenant_id:
        err('INV.UNKNOWN_TRF', 'تحويل غير موجود')
    if trf.status != 'DRAFT':
        err('INV.TRF_STATE',
            'لا يُلغى إلا تحويل مسودة — الشحن الفعلي يعالج بتحويل عكسي')
    trf.status = 'CANCELLED'
    trf.reason = f'{trf.reason} — إلغاء: {reason.strip()}'
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='transfer.cancel',
          entity='inv_transfers', entity_id=trf.id)
    return trf


# ────────────────────────────────────────────────────────────────────
# §3 الهالك/التالف (#19) — مستند + صورة + اعتماد + سبب
# ────────────────────────────────────────────────────────────────────
def create_waste(db: Session, *, tenant_id: str, actor_id: str,
                 warehouse_id: str, lines: list[dict], reason: str,
                 photo_ref: str = '') -> m.InvWaste:
    wh = warehouse_or_err(db, tenant_id, warehouse_id)
    _require_reason(reason)
    if not lines:
        err('INV.WST_EMPTY', 'مستند الهالك بلا بنود')
    wst = m.InvWaste(id=new_uuid(), tenant_id=tenant_id,
                     wst_no=next_doc_no(db, tenant_id, 'WST', 'WST'),
                     warehouse_id=wh.id, reason=reason.strip(),
                     photo_ref=photo_ref.strip(), created_by=actor_id,
                     created_at=_now())
    db.add(wst)
    db.flush()
    for ln in lines:
        item_or_err(db, tenant_id, ln['item_id'])
        if D(ln['qty']) <= 0:
            err('INV.BAD_QTY', 'كمية البند يجب أن تكون موجبة')
        db.add(m.InvWasteLine(id=new_uuid(), tenant_id=tenant_id,
                              waste_id=wst.id, item_id=ln['item_id'],
                              qty=D(ln['qty']),
                              line_reason=(ln.get('reason') or '').strip()))
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='waste.create', entity='inv_waste',
          entity_id=wst.id, after={'wst_no': wst.wst_no})
    return wst


def submit_waste(db: Session, *, tenant_id: str, actor_id: str,
                 waste_id: str) -> m.InvWaste:
    wst = db.get(m.InvWaste, waste_id)
    if wst is None or wst.tenant_id != tenant_id:
        err('INV.UNKNOWN_WASTE', 'مستند هالك غير موجود')
    if wst.status != 'DRAFT':
        err('INV.WST_STATE', f'لا رفع لمستند بحالة {wst.status}')
    wst.status = 'PENDING'
    db.flush()
    return wst


def approve_waste(db: Session, *, tenant_id: str, actor_id: str,
                  waste_id: str, approve: bool, reason: str = '',
                  bd: date | None = None) -> m.InvWaste:
    """اعتماد الهالك = ترحيل #19: Dr 7104 | Cr حساب المستودع بالمتوسط."""
    wst = db.get(m.InvWaste, waste_id)
    if wst is None or wst.tenant_id != tenant_id:
        err('INV.UNKNOWN_WASTE', 'مستند هالك غير موجود')
    if wst.status != 'PENDING':
        err('INV.WST_STATE', f'لا اعتماد لمستند بحالة {wst.status}')
    if wst.created_by == actor_id:
        err('INV.SELF_APPROVAL', 'يمنع اعتماد منشئ المستند لمستنده')
    wh = warehouse_or_err(db, tenant_id, wst.warehouse_id)
    if not approve:
        _require_reason(reason, 'INV.REJECT_REASON')
        wst.status = 'REJECTED'
        wst.reject_reason = reason.strip()
        db.flush()
        return wst
    bd = bd or date.today()
    total = Decimal('0')
    for ln in db.execute(select(m.InvWasteLine).where(
            m.InvWasteLine.waste_id == wst.id)).scalars().all():
        mv, applied, _ = apply_outbound(
            db, tenant_id=tenant_id, warehouse=wh, item_id=ln.item_id,
            qty=ln.qty, reason='WASTE', ref_type='WASTE', ref_id=wst.id,
            actor_id=actor_id, bd=bd)
        ln.unit_cost = applied
        ln.line_value = (applied * D(ln.qty)).quantize(Q4)
        total += ln.line_value
    entry = None
    if total > 0:
        entry = _post_journal(
            db, tenant_id=tenant_id, branch_id=wh.branch_id, entry_date=bd,
            narration=f'هالك/تالف {wst.wst_no} — {wst.reason}',
            raw_lines=[{'account': WASTE_ACCOUNT, 'debit': total,
                        'credit': Decimal('0'),
                        'description': 'خسارة هالك مخزون معتمد'},
                       {'account': wh.inventory_account_code,
                        'debit': Decimal('0'), 'credit': total,
                        'description': 'خفض المخزون بالهالك'}],
            actor_id=actor_id, source_type='STOCK_WASTE', source_id=wst.id,
            reference=wst.wst_no, event_key=f'inv:waste:{wst.id}')
    wst.total_value = total
    wst.entry_id = entry.id if entry else None
    wst.status = 'POSTED'
    wst.approved_by = actor_id
    wst.approved_at = _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='waste.approve', entity='inv_waste',
          entity_id=wst.id,
          after={'wst_no': wst.wst_no, 'value': str(total),
                 'entry': entry.entry_no if entry else None},
          business_date=bd)
    return wst


# ────────────────────────────────────────────────────────────────────
# §4 الجرد الدوري — تجميد ← عدّ ← فروقات ← اعتماد مزدوج ← #19/#20
# ────────────────────────────────────────────────────────────────────
def create_count(db: Session, *, tenant_id: str, actor_id: str,
                 warehouse_id: str,
                 category_id: str | None = None) -> m.InvCount:
    """إنشاء جرد = تجميد فوري للحركة على النطاق (§4)."""
    wh = warehouse_or_err(db, tenant_id, warehouse_id)
    _assert_not_frozen(db, tenant_id, wh.id)
    cnt = m.InvCount(id=new_uuid(), tenant_id=tenant_id,
                     cnt_no=next_doc_no(db, tenant_id, 'CNT', 'CNT'),
                     warehouse_id=wh.id, category_id=category_id,
                     created_by=actor_id, created_at=_now())
    db.add(cnt)
    db.flush()
    q = select(m.InvStock).where(m.InvStock.tenant_id == tenant_id,
                                 m.InvStock.warehouse_id == wh.id)
    if category_id:
        q = q.join(m.InvItem, m.InvItem.id == m.InvStock.item_id).where(
            m.InvItem.category_id == category_id)
    for s in db.execute(q).scalars().all():
        db.add(m.InvCountLine(id=new_uuid(), tenant_id=tenant_id,
                              count_id=cnt.id, item_id=s.item_id,
                              system_qty=D(s.qty_on_hand),
                              unit_cost=D(s.avg_cost)))
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='count.create', entity='inv_counts',
          entity_id=cnt.id,
          after={'cnt_no': cnt.cnt_no, 'warehouse': wh.code})
    return cnt


def enter_count(db: Session, *, tenant_id: str, actor_id: str, count_id: str,
                counted: list[dict]) -> m.InvCount:
    cnt = db.get(m.InvCount, count_id)
    if cnt is None or cnt.tenant_id != tenant_id:
        err('INV.UNKNOWN_COUNT', 'جرد غير موجود')
    if cnt.status not in ('FREEZE', 'COUNTED'):
        err('INV.CNT_STATE', f'لا إدخال عدّ لجرد بحالة {cnt.status}')
    by_item = {str(c['item_id']): D(c['counted_qty']) for c in counted}
    for iid, q in by_item.items():
        if q < 0:
            err('INV.BAD_QTY', 'كمية العدّ سالبة ممنوعة')
    found = False
    for ln in db.execute(select(m.InvCountLine).where(
            m.InvCountLine.count_id == cnt.id)).scalars().all():
        if ln.item_id in by_item:
            ln.counted_qty = by_item[ln.item_id]
            found = True
    if not found:
        err('INV.COUNT_LINES', 'لم يطابق أي بند من بنود الجرد')
    cnt.status = 'COUNTED'
    cnt.counted_by = actor_id
    cnt.counted_at = _now()
    db.flush()
    return cnt


def finish_count(db: Session, *, tenant_id: str, actor_id: str,
                 count_id: str) -> m.InvCount:
    """قفل العدّ واحتساب الفروقات بالقيمة — أساس قبول §7.5."""
    cnt = db.get(m.InvCount, count_id)
    if cnt is None or cnt.tenant_id != tenant_id:
        err('INV.UNKNOWN_COUNT', 'جرد غير موجود')
    if cnt.status != 'COUNTED':
        err('INV.CNT_STATE', 'أدخل العدّ الفعلي أولاً (الحالة COUNTED)')
    missing = [ln for ln in db.execute(select(m.InvCountLine).where(
        m.InvCountLine.count_id == cnt.id)).scalars().all()
        if ln.counted_qty is None]
    if missing:
        err('INV.COUNT_INCOMPLETE',
            f'بنود بلا عدّ فعلي: {len(missing)} — أكمل العدّ قبل القفل')
    short_v, over_v = Decimal('0'), Decimal('0')
    for ln in db.execute(select(m.InvCountLine).where(
            m.InvCountLine.count_id == cnt.id)).scalars().all():
        var = D(ln.counted_qty) - D(ln.system_qty)
        val = (var * D(ln.unit_cost)).quantize(Q4)
        ln.variance_qty, ln.variance_value = var, val
        if var < 0:
            short_v += -val
        elif var > 0:
            over_v += val
    cnt.short_value, cnt.over_value = short_v, over_v
    cnt.status = 'PENDING_L1'
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='count.finish', entity='inv_counts',
          entity_id=cnt.id,
          after={'short': str(short_v), 'over': str(over_v)})
    return cnt


def approve_count(db: Session, *, tenant_id: str, actor_id: str,
                  count_id: str, level: int, bd: date | None = None,
                  actor_perms: set[str] | None = None) -> m.InvCount:
    """اعتماد مزدوج (ملف 14 §2): L1 أمين+مالية ثم L2 مدير عام — والترحيل
    يلغي التجميد ويولّد #19 للعجز و#20 للزيادة بقيمة كشف الفروقات."""
    cnt = db.get(m.InvCount, count_id)
    if cnt is None or cnt.tenant_id != tenant_id:
        err('INV.UNKNOWN_COUNT', 'جرد غير موجود')
    perms = actor_perms or set()
    if cnt.created_by == actor_id:
        err('INV.SELF_APPROVAL', 'يمنع اعتماد منشئ الجرد لجرده')
    if level == 1:
        if cnt.status != 'PENDING_L1':
            err('INV.CNT_STATE', f'لا اعتماد أول لجرد بحالة {cnt.status}')
        if 'inv.count.approve.l1' not in perms and '*' not in perms:
            err('RBAC.FORBIDDEN', 'يتطلب اعتماد الجرد الأول (أمين+مالية)')
        cnt.approved1_by = actor_id
        cnt.approved1_at = _now()
        cnt.status = 'PENDING_L2'
        db.flush()
        audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
              module='inventory', action='count.approve1',
              entity='inv_counts', entity_id=cnt.id)
        return cnt
    if level == 2:
        if cnt.status != 'PENDING_L2':
            err('INV.CNT_STATE', f'لا اعتماد ثانٍ لجرد بحالة {cnt.status}')
        if 'inv.count.approve.l2' not in perms and '*' not in perms:
            err('RBAC.FORBIDDEN', 'يتطلب اعتماد الجرد الثاني (مدير عام)')
        if cnt.approved1_by == actor_id:
            err('INV.SELF_APPROVAL', 'الاعتماد الثاني يجب أن يكون بغير المعتمِد الأول')
        return _post_count(db, tenant_id=tenant_id, cnt=cnt,
                           actor_id=actor_id, bd=bd or date.today())
    err('INV.BAD_LEVEL', 'مستوى الاعتماد 1|2 فقط')


def _post_count(db: Session, *, tenant_id: str, cnt: m.InvCount,
                actor_id: str, bd: date) -> m.InvCount:
    cnt.approved2_by = actor_id
    cnt.approved2_at = _now()
    cnt.status = 'POSTED'  # رفع التجميد أولاً حتى تمر تسويات الجرد نفسها
    cnt.posted_at = _now()
    db.flush()
    wh = warehouse_or_err(db, tenant_id, cnt.warehouse_id)
    short_entry = over_entry = None
    for ln in db.execute(select(m.InvCountLine).where(
            m.InvCountLine.count_id == cnt.id)).scalars().all():
        var = D(ln.variance_qty or 0)
        if var < 0:
            mv, applied, _ = apply_outbound(
                db, tenant_id=tenant_id, warehouse=wh, item_id=ln.item_id,
                qty=-var, reason='COUNT_SHORT', ref_type='COUNT',
                ref_id=cnt.id, actor_id=actor_id, bd=bd)
            ln.variance_value = (applied * var).quantize(Q4)
        elif var > 0:
            mv, _ = apply_inbound(
                db, tenant_id=tenant_id, warehouse=wh, item_id=ln.item_id,
                qty=var, unit_cost=ln.unit_cost, reason='COUNT_OVER',
                ref_type='COUNT', ref_id=cnt.id, actor_id=actor_id, bd=bd,
                set_avg=False)  # زيادة جرد بالمتوسط نفسه — المتوسط لا يتغير
            ln.variance_value = (D(ln.unit_cost) * var).quantize(Q4)
    # إعادة احتساب المجاميع بالتكلفة المطبقة فعلياً (دقة الهللة — قبول §7.5)
    short_v = over_v = Decimal('0')
    for ln in db.execute(select(m.InvCountLine).where(
            m.InvCountLine.count_id == cnt.id)).scalars().all():
        v = D(ln.variance_value or 0)
        if v < 0:
            short_v += -v
        elif v > 0:
            over_v += v
    cnt.short_value, cnt.over_value = short_v, over_v
    if short_v > 0:
        short_entry = _post_journal(
            db, tenant_id=tenant_id, branch_id=wh.branch_id, entry_date=bd,
            narration=f'تسوية عجز جرد {cnt.cnt_no} — {wh.name_ar}',
            raw_lines=[{'account': WASTE_ACCOUNT, 'debit': short_v,
                        'credit': Decimal('0'),
                        'description': 'عجز جرد معتمد (#19)'},
                       {'account': wh.inventory_account_code,
                        'debit': Decimal('0'), 'credit': short_v,
                        'description': 'خفض المخزون بعجز الجرد'}],
            actor_id=actor_id, source_type='STOCK_COUNT', source_id=cnt.id,
            reference=cnt.cnt_no, event_key=f'inv:count:short:{cnt.id}')
    if over_v > 0:
        over_entry = _post_journal(
            db, tenant_id=tenant_id, branch_id=wh.branch_id, entry_date=bd,
            narration=f'تسوية زيادة جرد {cnt.cnt_no} — {wh.name_ar}',
            raw_lines=[{'account': wh.inventory_account_code, 'debit': over_v,
                        'credit': Decimal('0'),
                        'description': 'زيادة جرد (#20)'},
                       {'account': OVER_ACCOUNT, 'debit': Decimal('0'),
                        'credit': over_v,
                        'description': 'إيراد زيادة جرد معتمدة'}],
            actor_id=actor_id, source_type='STOCK_COUNT', source_id=cnt.id,
            reference=cnt.cnt_no, event_key=f'inv:count:over:{cnt.id}')
    cnt.short_entry_id = short_entry.id if short_entry else None
    cnt.over_entry_id = over_entry.id if over_entry else None
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='count.post', entity='inv_counts',
          entity_id=cnt.id,
          after={'cnt_no': cnt.cnt_no, 'short': str(short_v),
                 'over': str(over_v),
                 'entries': [e.entry_no for e in (short_entry, over_entry)
                             if e]}, business_date=bd)
    return cnt


def cancel_count(db: Session, *, tenant_id: str, actor_id: str,
                 count_id: str, reason: str) -> m.InvCount:
    _require_reason(reason)
    cnt = db.get(m.InvCount, count_id)
    if cnt is None or cnt.tenant_id != tenant_id:
        err('INV.UNKNOWN_COUNT', 'جرد غير موجود')
    if cnt.status == 'POSTED':
        err('INV.CNT_POSTED', 'الجرد المرحَّل لا يُلغى — عالج بجردٍ عكسي')
    cnt.status = 'CANCELLED'  # رفع التجميد
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='inventory', action='count.cancel', entity='inv_counts',
          entity_id=cnt.id, after={'reason': reason.strip()})
    return cnt


# ────────────────────────────────────────────────────────────────────
# §6 التقارير والتنبيهات
# ────────────────────────────────────────────────────────────────────
def ledger_balance(db: Session, tenant_id: str, account_code: str,
                   as_of: date | None = None) -> Decimal:
    q = (select(func.sum(m.JournalLine.debit_base),
                func.sum(m.JournalLine.credit_base))
         .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
         .join(m.Account, m.Account.id == m.JournalLine.account_id)
         .where(m.JournalLine.tenant_id == tenant_id,
                m.Account.code == account_code,
                m.JournalEntry.status.in_(['POSTED', 'REVERSED'])))
    if as_of:
        q = q.where(m.JournalEntry.entry_date <= as_of)
    td, tc = db.execute(q).one()
    return D(td or 0) - D(tc or 0)


def stock_by_account(db: Session, tenant_id: str) -> dict[str, dict]:
    """قيمة المخزون مجمعة بحساب المستودع المالي — للمطابقة اليومية (§6)."""
    out: dict[str, dict] = {}
    q = (select(m.InvWarehouse.inventory_account_code,
                func.sum(m.InvStock.qty_on_hand * m.InvStock.avg_cost))
         .join(m.InvStock,
               m.InvStock.warehouse_id == m.InvWarehouse.id)
         .where(m.InvWarehouse.tenant_id == tenant_id,
                m.InvWarehouse.is_active.is_(True))
         .group_by(m.InvWarehouse.inventory_account_code))
    for acct, val in db.execute(q).all():
        out[acct] = {'value': D(val or 0)}
    return out


def valued_stock_report(db: Session, tenant_id: str,
                        warehouse_id: str | None = None,
                        as_of: date | None = None) -> dict:
    """كشف أرصدة المستودعات بالقيمة + مطابقة الأستاذ (قبول §7.2 + §6)."""
    wq = select(m.InvWarehouse).where(m.InvWarehouse.tenant_id == tenant_id,
                                      m.InvWarehouse.is_active.is_(True))
    if warehouse_id:
        wq = wq.where(m.InvWarehouse.id == warehouse_id)
    warehouses = db.execute(wq.order_by(m.InvWarehouse.code)).scalars().all()
    rows = []
    for w in warehouses:
        for s in db.execute(select(m.InvStock).where(
                m.InvStock.warehouse_id == w.id,
                m.InvStock.qty_on_hand != 0)).scalars().all():
            item = db.get(m.InvItem, s.item_id)
            val = (D(s.qty_on_hand) * D(s.avg_cost)).quantize(Q4)
            rows.append({'warehouse_id': w.id, 'warehouse': w.name_ar,
                         'warehouse_code': w.code,
                         'account_code': w.inventory_account_code,
                         'item_id': s.item_id,
                         'item_code': item.code if item else '',
                         'item_name': item.name_ar if item else '',
                         'unit': item.base_unit if item else '',
                         'qty': D(s.qty_on_hand), 'avg_cost': D(s.avg_cost),
                         'value': val})
    # المطابقة معيار شامل للمستأجر (الأستاذ لا يعرف المستودعات) — تُحسب
    # دائماً على كامل المخزون حتى مع ترشيح صفوف العرض بمستودع واحد
    global_totals = {a: x['value'] for a, x in
                     stock_by_account(db, tenant_id).items()}
    matches = []
    for acct in sorted(global_totals):
        stock_val = global_totals[acct].quantize(Q4)
        ledger_val = ledger_balance(db, tenant_id, acct, as_of=as_of)
        matches.append({'account_code': acct, 'stock_value': stock_val,
                        'ledger_balance': ledger_val,
                        'diff': (stock_val - ledger_val).quantize(Q4),
                        'matched': abs(stock_val - ledger_val) < Q4})
    return {'rows': sorted(rows, key=lambda r: (r['warehouse_code'],
                                                r['item_code'])),
            'accounts_match': matches,
            'all_matched': all(x['matched'] for x in matches)}


def reconciliation_check(db: Session, tenant_id: str) -> dict:
    """الفحص الليلي (§6): أي فرق بين قيمة المخزون وحساباته → تنبيه."""
    match = valued_stock_report(db, tenant_id)['accounts_match']
    alerts = [{'account_code': x['account_code'], 'diff': str(x['diff'])}
              for x in match if not x['matched']]
    return {'ok': not alerts, 'alerts': alerts, 'checked': len(match)}


def reorder_alerts(db: Session, tenant_id: str) -> list[dict]:
    """§6: تحت حد إعادة الطلب → اقتراح PO بكمية اقتصادية مبسطة:
    عجز حتى حد الأمان + متوسط استهلاك نافذة الأيام."""
    pol = get_policy(db, tenant_id)
    days = pol.consumption_days
    since = date.today() - timedelta(days=days)
    on_hand: dict[str, Decimal] = {}
    for iid, q in db.execute(
            select(m.InvStock.item_id, func.sum(m.InvStock.qty_on_hand))
            .where(m.InvStock.tenant_id == tenant_id)
            .group_by(m.InvStock.item_id)).all():
        on_hand[iid] = D(q or 0)
    consumed: dict[str, Decimal] = {}
    for iid, q in db.execute(
            select(m.InvMove.item_id, func.sum(-m.InvMove.qty_delta))
            .where(m.InvMove.tenant_id == tenant_id,
                   m.InvMove.reason.in_(CONSUMPTION_REASONS),
                   m.InvMove.qty_delta < 0,
                   m.InvMove.business_date >= since)
            .group_by(m.InvMove.item_id)).all():
        consumed[iid] = D(q or 0)
    out = []
    items = db.execute(select(m.InvItem).where(
        m.InvItem.tenant_id == tenant_id,
        m.InvItem.is_active.is_(True),
        m.InvItem.reorder_level > 0)).scalars().all()
    for it in items:
        total = on_hand.get(it.id, Decimal('0'))
        if total >= D(it.reorder_level):
            continue
        avg_daily = consumed.get(it.id, Decimal('0')) / days
        deficit = max(Decimal('0'), D(it.safety_level) - total)
        suggested = (deficit + avg_daily * days).quantize(
            Decimal('0.01'))
        out.append({'item_id': it.id, 'code': it.code, 'name': it.name_ar,
                    'unit': it.base_unit, 'on_hand': total,
                    'reorder_level': D(it.reorder_level),
                    'safety_level': D(it.safety_level),
                    'avg_daily_consumption': avg_daily.quantize(Q4),
                    'suggested_qty': suggested})
    return sorted(out, key=lambda r: r['code'])


def expiry_alerts(db: Session, tenant_id: str) -> list[dict]:
    """§6: دفعات قربت صلاحيتها (نوافذ السياسة 30/15/7) — استهلاك تقديري
    بترتيب الصلاحية (FIFO طبيعي على الدفعات الواردة)."""
    pol = get_policy(db, tenant_id)
    windows = sorted((pol.expiry_windows or [30, 15, 7]), reverse=True)
    today = date.today()
    # الوارد بدفعات مؤرخة مقابل الوارد غير المدفَّع والصادر الكلي:
    # الصادر يستنزف أولاً المخزون غير المدفَّع (تاريخه مجهول)، ثم أقدم
    # الدفعات صلاحية — تقدير فيزيائي منطقي موثق لأعمار الدفعات المتبقية
    inbound: dict[tuple, dict] = {}
    batchless_in: dict[str, Decimal] = {}
    out_by_item: dict[str, Decimal] = {}
    for mv in db.execute(select(m.InvMove).where(
            m.InvMove.tenant_id == tenant_id)).scalars().all():
        if mv.qty_delta > 0:
            if mv.batch_no:
                key = (mv.warehouse_id, mv.item_id, mv.batch_no,
                       mv.expiry_date)
                rec = inbound.setdefault(key, {'qty': Decimal('0'),
                                               'expiry': mv.expiry_date})
                rec['qty'] += D(mv.qty_delta)
            else:
                batchless_in[mv.item_id] = (batchless_in.get(mv.item_id,
                                                             Decimal('0'))
                                            + D(mv.qty_delta))
        else:
            out_by_item[mv.item_id] = (out_by_item.get(mv.item_id,
                                                       Decimal('0'))
                                       + -D(mv.qty_delta))
    by_item: dict[str, list] = {}
    for (wh, iid, batch, exp), rec in inbound.items():
        by_item.setdefault(iid, []).append((exp or date.max, wh, batch, rec))
    out = []
    for iid, batches in by_item.items():
        remaining_out = max(Decimal('0'),
                            out_by_item.get(iid, Decimal('0'))
                            - batchless_in.get(iid, Decimal('0')))
        for exp, wh, batch, rec in sorted(batches, key=lambda b: b[0]):
            take = min(rec['qty'], remaining_out)
            rec['qty'] -= take
            remaining_out -= take
        for exp, wh, batch, rec in batches:
            if rec['qty'] <= 0 or exp == date.max or exp is None:
                continue
            days_left = (exp - today).days
            if days_left > windows[0]:
                continue
            bucket = next((w for w in sorted(windows) if days_left <= w),
                          windows[0])
            item = db.get(m.InvItem, iid)
            whr = db.get(m.InvWarehouse, wh)
            out.append({'item_id': iid,
                        'code': item.code if item else '',
                        'name': item.name_ar if item else '',
                        'warehouse': whr.name_ar if whr else '',
                        'batch_no': batch, 'expiry_date': str(exp),
                        'days_left': days_left, 'window': bucket,
                        'qty': rec['qty'].quantize(Q4)})
    return sorted(out, key=lambda r: (r['days_left'], r['code']))


def stagnant_alerts(db: Session, tenant_id: str) -> list[dict]:
    """§6: أصناف راكدة — رصيد موجب بلا أي حركة منذ نافذة السياسة."""
    pol = get_policy(db, tenant_id)
    cutoff = date.today() - timedelta(days=pol.stagnant_days)
    last_move: dict[str, date] = {}
    for iid, dmax in db.execute(
            select(m.InvMove.item_id, func.max(m.InvMove.business_date))
            .where(m.InvMove.tenant_id == tenant_id)
            .group_by(m.InvMove.item_id)).all():
        last_move[iid] = dmax
    on_hand: dict[str, Decimal] = {}
    for iid, q in db.execute(
            select(m.InvStock.item_id, func.sum(m.InvStock.qty_on_hand))
            .where(m.InvStock.tenant_id == tenant_id)
            .group_by(m.InvStock.item_id)).all():
        if D(q or 0) > 0:
            on_hand[iid] = D(q)
    out = []
    for iid, qty in on_hand.items():
        lm = last_move.get(iid)
        if lm is not None and lm >= cutoff:
            continue
        item = db.get(m.InvItem, iid)
        out.append({'item_id': iid, 'code': item.code if item else '',
                    'name': item.name_ar if item else '', 'qty': qty,
                    'last_move_date': str(lm) if lm else None,
                    'idle_days': (date.today() - lm).days if lm else None})
    return sorted(out, key=lambda r: r['code'])


def moves_report(db: Session, tenant_id: str, warehouse_id: str = '',
                 item_id: str = '', reason: str = '', date_from=None,
                 date_to=None, limit: int = 500) -> list[dict]:
    q = select(m.InvMove).where(m.InvMove.tenant_id == tenant_id)
    if warehouse_id:
        q = q.where(m.InvMove.warehouse_id == warehouse_id)
    if item_id:
        q = q.where(m.InvMove.item_id == item_id)
    if reason:
        q = q.where(m.InvMove.reason == reason)
    if date_from:
        q = q.where(m.InvMove.business_date >= date_from)
    if date_to:
        q = q.where(m.InvMove.business_date <= date_to)
    out = []
    for mv in db.execute(q.order_by(m.InvMove.created_at.desc())
                         .limit(min(limit, 2000))).scalars().all():
        item = db.get(m.InvItem, mv.item_id)
        wh = db.get(m.InvWarehouse, mv.warehouse_id)
        out.append({'id': mv.id, 'business_date': str(mv.business_date),
                    'warehouse': wh.name_ar if wh else '',
                    'item_code': item.code if item else '',
                    'item_name': item.name_ar if item else '',
                    'qty_delta': D(mv.qty_delta), 'unit_cost': D(mv.unit_cost),
                    'value_delta': D(mv.value_delta), 'reason': mv.reason,
                    'ref_type': mv.ref_type, 'ref_id': mv.ref_id,
                    'batch_no': mv.batch_no,
                    'expiry_date': str(mv.expiry_date)
                    if mv.expiry_date else None})
    return out


def purchases_report(db: Session, tenant_id: str, date_from: date,
                     date_to: date) -> list[dict]:
    """§6: مشتريات المورد/الفترة (GRN مرحَّل فقط)."""
    rows: dict[str, dict] = {}
    for grn in db.execute(select(m.InvGRN).where(
            m.InvGRN.tenant_id == tenant_id, m.InvGRN.status == 'POSTED',
            m.InvGRN.posted_at >= datetime.combine(date_from, datetime.min.time(),
                                                   tzinfo=timezone.utc),
            m.InvGRN.posted_at <= datetime.combine(date_to, datetime.max.time(),
                                                   tzinfo=timezone.utc))
    ).scalars().all():
        sup = db.get(m.InvSupplier, grn.supplier_id)
        rec = rows.setdefault(grn.supplier_id, {
            'supplier_id': grn.supplier_id,
            'supplier': sup.name if sup else '', 'grn_count': 0,
            'cash_total': Decimal('0'), 'credit_total': Decimal('0'),
            'total': Decimal('0')})
        rec['grn_count'] += 1
        if grn.purchase_type == 'CASH':
            rec['cash_total'] += D(grn.total)
        else:
            rec['credit_total'] += D(grn.total)
        rec['total'] += D(grn.total)
    return sorted(rows.values(), key=lambda r: -r['total'])


def supplier_performance(db: Session, tenant_id: str) -> list[dict]:
    """§6: أداء الموردين — أحجام، مرتجعات، مرفوضات جودة، وتقييم مُدخل."""
    out = []
    for sup in db.execute(select(m.InvSupplier).where(
            m.InvSupplier.tenant_id == tenant_id)).scalars().all():
        po_count = db.execute(select(func.count(m.InvPurchaseOrder.id))
                              .where(m.InvPurchaseOrder.supplier_id == sup.id,
                                     m.InvPurchaseOrder.status.notin_(
                                         ['CANCELLED', 'REJECTED']))
                              ).scalar_one()
        received = rejected = Decimal('0')
        for gl in db.execute(select(m.InvGRNLine).join(
                m.InvGRN, m.InvGRN.id == m.InvGRNLine.grn_id).where(
                m.InvGRN.tenant_id == tenant_id,
                m.InvGRN.supplier_id == sup.id,
                m.InvGRN.status == 'POSTED')).scalars().all():
            received += D(gl.qty_received)
            rejected += D(gl.qty_rejected)
        returns_count = db.execute(
            select(func.count(m.InvSupplierReturn.id)).where(
                m.InvSupplierReturn.supplier_id == sup.id,
                m.InvSupplierReturn.status == 'POSTED')).scalar_one()
        reject_rate = (rejected / received * 100).quantize(Decimal('0.01')) \
            if received > 0 else Decimal('0')
        out.append({'supplier_id': sup.id, 'code': sup.code,
                    'name': sup.name, 'po_count': po_count,
                    'received_qty': received, 'rejected_qty': rejected,
                    'quality_reject_rate_pct': reject_rate,
                    'returns_count': returns_count,
                    'balance': supplier_balance(db, tenant_id, sup.id),
                    'rating_commitment': sup.rating_commitment,
                    'rating_quality': sup.rating_quality})
    return out


def ppv_report(db: Session, tenant_id: str, date_from: date,
               date_to: date) -> list[dict]:
    """§6: فروقات أسعار الشراء من قيود 5120 المعتمدة."""
    out = []
    q = (select(m.JournalLine, m.JournalEntry)
         .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
         .join(m.Account, m.Account.id == m.JournalLine.account_id)
         .where(m.JournalLine.tenant_id == tenant_id,
                m.Account.code == PPV_ACCOUNT,
                m.JournalEntry.status.in_(['POSTED', 'REVERSED']),
                m.JournalEntry.entry_date >= date_from,
                m.JournalEntry.entry_date <= date_to))
    for ln, je in db.execute(q).all():
        out.append({'entry_no': je.entry_no, 'entry_date': str(je.entry_date),
                    'narration': je.narration,
                    'debit': D(ln.debit_base), 'credit': D(ln.credit_base)})
    return out


def waste_report(db: Session, tenant_id: str, months: int = 6) -> list[dict]:
    """§3: إحصائية هالك شهرية."""
    since = date.today().replace(day=1) - timedelta(days=31 * (months - 1))
    rows: dict[str, dict] = {}
    for mv in db.execute(select(m.InvMove).where(
            m.InvMove.tenant_id == tenant_id, m.InvMove.reason == 'WASTE',
            m.InvMove.business_date >= since)).scalars().all():
        key = mv.business_date.strftime('%Y-%m')
        rec = rows.setdefault(key, {'month': key, 'moves': 0,
                                    'qty': Decimal('0'),
                                    'value': Decimal('0')})
        rec['moves'] += 1
        rec['qty'] += -D(mv.qty_delta)
        rec['value'] += -D(mv.value_delta)
    return [rows[k] for k in sorted(rows)]


def consumption_report(db: Session, tenant_id: str, date_from: date,
                       date_to: date) -> dict:
    """§5/§6: استهلاك نظري (وصفات مبيعات POS) مقابل فعلي (حركات الصرف)
    — مؤشر هدر/تلاعب رئيسي. البيع ينقّص مستودع المنفذ (ADR-0017)؛
    الفعلي هنا = SALE_POS + WASTE + COUNT_SHORT لكل صنف."""
    # النظري من الفواتير
    theoretical: dict[str, Decimal] = {}
    for inv in db.execute(select(m.PosInvoice).where(
            m.PosInvoice.tenant_id == tenant_id,
            m.PosInvoice.type == 'SALE',
            m.PosInvoice.business_date >= date_from,
            m.PosInvoice.business_date <= date_to)).scalars().all():
        lines = db.execute(select(m.PosOrderLine).where(
            m.PosOrderLine.order_id == inv.order_id,
            m.PosOrderLine.status == 'NORMAL')).scalars().all()
        for ln in lines:
            item = db.get(m.PosItem, ln.item_id)
            if item is None:
                continue
            if item.item_type == 'STOCK':
                inv_item = auto_link_pos_item(db, tenant_id=tenant_id,
                                              pos_item=item)
                theoretical[inv_item.id] = (theoretical.get(inv_item.id,
                                                            Decimal('0'))
                                            + D(ln.qty))
            elif item.item_type == 'COMPOSITE':
                for r in db.execute(select(m.PosRecipe).where(
                        m.PosRecipe.parent_item_id == item.id)).scalars().all():
                    comp = db.get(m.PosItem, r.component_item_id)
                    inv_item = auto_link_pos_item(db, tenant_id=tenant_id,
                                                  pos_item=comp)
                    theoretical[inv_item.id] = (
                        theoretical.get(inv_item.id, Decimal('0'))
                        + D(r.qty) * D(ln.qty))
    # المرتجعات تظهر تلقائياً في «الفعلي» كحركات POS_RETURN موجبة تخفض
    # صافي الصادر — لا حاجة لتعديل النظري (فواتير البيع كما وقعت)
    # الفعلي من حركات المخزون
    actual: dict[str, Decimal] = {}
    waste: dict[str, Decimal] = {}
    for mv in db.execute(select(m.InvMove).where(
            m.InvMove.tenant_id == tenant_id,
            m.InvMove.reason.in_(('SALE_POS', 'POS_RETURN', 'WASTE',
                                  'COUNT_SHORT')),
            m.InvMove.business_date >= date_from,
            m.InvMove.business_date <= date_to)).scalars().all():
        if mv.reason in ('SALE_POS', 'POS_RETURN'):
            actual[mv.item_id] = (actual.get(mv.item_id, Decimal('0'))
                                  + -D(mv.qty_delta))
        else:
            waste[mv.item_id] = (waste.get(mv.item_id, Decimal('0'))
                                 + -D(mv.qty_delta))
    rows = []
    for iid in sorted(set(theoretical) | set(actual), key=str):
        item = db.get(m.InvItem, iid)
        theo = theoretical.get(iid, Decimal('0'))
        act = actual.get(iid, Decimal('0'))
        wst = waste.get(iid, Decimal('0'))
        var = (act - theo).quantize(Q4)
        rows.append({'item_id': iid, 'code': item.code if item else '',
                     'name': item.name_ar if item else '',
                     'unit': item.base_unit if item else '',
                     'theoretical_qty': theo, 'actual_qty': act,
                     'variance_qty': var, 'waste_count_qty': wst,
                     'variance_pct': ((var / theo * 100).quantize(
                         Decimal('0.01')) if theo > 0 else None)})
    return {'date_from': str(date_from), 'date_to': str(date_to),
            'rows': sorted(rows, key=lambda r: r['code']),
            'note': 'الفعلي = صافي البيع الفعلي من مستودعات المنافذ + '
                    'الهالك/الجرد؛ الفرق الموجب مؤشر هدر/تلاعب (ملف 05 §5)'}


def supplier_statement(db: Session, tenant_id: str,
                       supplier_id: str) -> dict:
    """كشف حساب مورد: أستاذ 2101 بمطابقته + الفواتير المفتوحة."""
    sup = supplier_or_err(db, tenant_id, supplier_id)
    q = (select(m.JournalLine, m.JournalEntry)
         .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
         .join(m.Account, m.Account.id == m.JournalLine.account_id)
         .where(m.JournalLine.tenant_id == tenant_id,
                m.Account.code == AP_ACCOUNT,
                m.JournalLine.party_id == supplier_id,
                m.JournalEntry.status.in_(['POSTED', 'REVERSED']))
         .order_by(m.JournalEntry.entry_date, m.JournalEntry.entry_no))
    lines, running = [], Decimal('0')
    for ln, je in db.execute(q).all():
        running += D(ln.credit_base) - D(ln.debit_base)
        lines.append({'entry_no': je.entry_no,
                      'entry_date': str(je.entry_date),
                      'narration': je.narration, 'debit': D(ln.debit_base),
                      'credit': D(ln.credit_base), 'balance': running})
    open_invoices = [{'sinv_no': i.sinv_no,
                      'supplier_invoice_no': i.supplier_invoice_no,
                      'total': D(i.total), 'paid': D(i.paid_amount),
                      'remaining': D(i.total) - D(i.paid_amount),
                      'status': i.status}
                     for i in db.execute(select(m.InvSupplierInvoice).where(
                         m.InvSupplierInvoice.supplier_id == supplier_id,
                         m.InvSupplierInvoice.status.in_(
                             ['APPROVED', 'MATCHED', 'VARIANCE_HOLD']))
                     ).scalars().all()]
    return {'supplier': {'id': sup.id, 'code': sup.code, 'name': sup.name,
                         'terms_days': sup.terms_days},
            'balance': supplier_balance(db, tenant_id, supplier_id),
            'lines': lines, 'open_invoices': open_invoices}
