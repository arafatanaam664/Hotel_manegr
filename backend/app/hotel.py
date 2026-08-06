"""خدمات وحدة الفندق — ملف 03 (HOTEL_MODULE_SPEC) كقانون ملزم:
- دورة الحجز State Machine مفروضة هنا وحدها (§2)
- لا حجز مزدوج: قفل صف على الغرفة/النوع + فحص تداخل داخل المعاملة (§2، قبول #1)
- الفوليو بلا رصيد مخزَّن: يُشتق لحظياً من دفتر 1110 بالطرف (§6، قبول #2)
- كل أثر مالي عبر محرك الترحيل فقط — لا قيود يدوية هنا (ملف 02 §6)
- التدقيق الليلي: ذري، idempotent، يتقدم بتاريخ العمل يوماً واحداً فقط (§4)"""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from . import models as m
from .audit import audit
from .posting import D, PostingError, post_event
from .security import new_uuid, utcnow

ACTIVE_RSV = ('TENTATIVE', 'CONFIRMED', 'CHECKED_IN')
BLOCKING_HK = ('OOO', 'OOS')

# مصفوفة انتقالات الحجز (ملف 03 §2) — أي انتقال خارجها مرفوض
RSV_TRANSITIONS = {
    'TENTATIVE': {'CONFIRMED', 'CANCELLED'},
    'CONFIRMED': {'CHECKED_IN', 'CANCELLED', 'NO_SHOW'},
    'CHECKED_IN': {'CHECKED_OUT'},
    'CHECKED_OUT': set(), 'CANCELLED': set(), 'NO_SHOW': set(),
}

# مصفوفة الهوسكيبينج (ملف 03 §5): تنظيف ← hk.cleaning / إدارة ← hk.manage
HK_CLEANING_TRANSITIONS = {('DIRTY', 'CLEANING'), ('CLEANING', 'CLEAN')}
HK_MANAGE_TRANSITIONS = {('CLEAN', 'INSPECTED'), ('INSPECTED', 'DIRTY'),
                         ('CLEAN', 'OOO'), ('DIRTY', 'OOO'),
                         ('CLEAN', 'OOS'), ('DIRTY', 'OOS'),
                         ('OOO', 'DIRTY'), ('OOS', 'DIRTY'),
                         ('INSPECTED', 'CLEAN')}

GUEST_LEDGER = '1110'
DEPOSIT_LEDGER = '2110'
CITY_LEDGER = '1120'
# سقف الخصم الذاتي لمن لا يملك discounts.approve (فوقه اعتماد إلزامي — ملف 03 §3.2)
SELF_DISCOUNT_CAP = Decimal('100')


def err(code: str, message: str):
    raise PostingError(code, message)


# ────────────────────────────────────────────────────────────────────
# أدوات عامة
# ────────────────────────────────────────────────────────────────────
def get_business_date(db: Session, tenant_id: str) -> date:
    st = db.get(m.BusinessDateState, tenant_id)
    if st is None:
        err('HOTEL.NO_BUSINESS_DATE', 'تاريخ العمل غير مهيأ — أعد الزرع')
    return st.current_business_date


def lock_state(db: Session, tenant_id: str) -> m.BusinessDateState:
    """قفل صف تاريخ العمل — يمنع تشغيل تدقيقين متزامنين."""
    return db.execute(
        select(m.BusinessDateState)
        .where(m.BusinessDateState.tenant_id == tenant_id)
        .with_for_update()).scalar_one()


def _next_no(db: Session, tenant_id: str, kind: str, prefix: str,
             year: int | None = None) -> str:
    y = year or date.today().year
    row = db.execute(
        select(m.SequenceCounter)
        .where(m.SequenceCounter.tenant_id == tenant_id,
               m.SequenceCounter.kind == kind,
               m.SequenceCounter.year == y)
        .with_for_update()).scalar_one_or_none()
    if row is None:
        row = m.SequenceCounter(tenant_id=tenant_id, kind=kind, year=y,
                                next_no=1)
        db.add(row)
        db.flush()
    n = row.next_no
    row.next_no = n + 1
    db.flush()
    return f'{prefix}-{y}-{n:06d}'


def current_tax_rate(db: Session, tenant_id: str) -> Decimal:
    row = db.execute(
        select(m.Tax).where(m.Tax.tenant_id == tenant_id,
                            m.Tax.is_active.is_(True)).limit(1)
    ).scalar_one_or_none()
    return D(row.rate) if row else Decimal('0')


def split_gross(amount: Decimal, tax_rate: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """(الإجمالي، الصافي، الضريبة) — الضريبة شاملة السعر عند تفعيلها."""
    if tax_rate and tax_rate > 0:
        net = (amount / (1 + tax_rate)).quantize(Decimal('0.0001'))
        tax = amount - net
        return amount, net, tax
    return amount, amount, Decimal('0')


# ────────────────────────────────────────────────────────────────────
# الأسعار (ملف 03 §1.4: التقويم ← الخطة ← الأساس)
# ────────────────────────────────────────────────────────────────────
def resolve_night_rate(db: Session, tenant_id: str, room_type_id: str,
                       rate_plan_id: str | None, day: date) -> tuple[Decimal, str]:
    q = select(m.RateCalendar).where(m.RateCalendar.tenant_id == tenant_id,
                                     m.RateCalendar.room_type_id == room_type_id,
                                     m.RateCalendar.day == day)
    if rate_plan_id:
        row = db.execute(q.where(m.RateCalendar.rate_plan_id == rate_plan_id)
                         ).scalar_one_or_none()
        if row:
            return D(row.price), 'CALENDAR'
    row = db.execute(q.where(m.RateCalendar.rate_plan_id.is_(None))
                     ).scalar_one_or_none()
    if row:
        return D(row.price), 'CALENDAR'
    if rate_plan_id:
        plan = db.get(m.RatePlan, rate_plan_id)
        if plan and plan.ref_rate is not None:
            rt = db.get(m.RoomType, room_type_id)
            return D(plan.ref_rate) + D(rt.base_rate), 'PLAN'
    rt = db.get(m.RoomType, room_type_id)
    if rt is None:
        err('HOTEL.UNKNOWN_ROOM_TYPE', 'نوع غرفة غير موجود')
    return D(rt.base_rate), 'BASE'


def price_stay(db: Session, tenant_id: str, room_type_id: str,
               rate_plan_id: str | None, arrival: date,
               departure: date) -> list[dict]:
    out = []
    d = arrival
    while d < departure:
        price, origin = resolve_night_rate(db, tenant_id, room_type_id,
                                           rate_plan_id, d)
        out.append({'date': d, 'rate': price, 'origin': origin})
        d += timedelta(days=1)
    return out


# ────────────────────────────────────────────────────────────────────
# التوفر ومنع الحجز المزدوج (قبول #1) + الأجنحة المركبة (ADR-0035)
# ────────────────────────────────────────────────────────────────────
def _overlap(d1a: date, d1b: date, d2a: date, d2b: date) -> bool:
    return d1a < d2b and d2a < d1b


ROOM_KIND_SUITE = 'SUITE_UNIT'   # جناح مركب = غرفة «أب» بيعية
ROOM_KIND_STANDARD = 'STANDARD'


def is_suite(room: m.Room | None) -> bool:
    return room is not None and (getattr(room, 'kind', None)
                                 or ROOM_KIND_STANDARD) == ROOM_KIND_SUITE


def suite_children(db: Session, suite_id: str) -> list[m.Room]:
    return db.execute(select(m.Room).where(
        m.Room.parent_room_id == suite_id,
        m.Room.is_active.is_(True)).order_by(m.Room.room_no)
    ).scalars().all()


def suite_block_reason(db: Session, tenant_id: str, room: m.Room,
                       d_from: date, d_to: date,
                       exclude_id: str | None = None) -> str | None:
    """حجب الأجنحة المركبة — مشتق حسابياً دائماً ولا يُخزَّن أبداً (ADR-0035):
    الابن يُحجب بحجز/تعطيل أبيه الجناح؛ والجناح لا يُباع كاملاً إذا كانت
    أي من غرفه محجوزة أو خارج الخدمة. أمان مضاعف للمسارات غير المغطاة."""
    if room is None:
        return None
    if is_suite(room):
        for c in suite_children(db, room.id):
            if ooo_blocks(db, c, d_from, d_to):
                return (f'لا يُباع الجناح {room.room_no} كاملاً — غرفته '
                        f'{c.room_no} خارج الخدمة')
            hits = overlapping_reservations(db, tenant_id, c.id, d_from,
                                            d_to, exclude_id)
            if hits:
                return (f'لا يُباع الجناح {room.room_no} كاملاً — غرفته '
                        f'{c.room_no} محجوزة ({hits[0].confirmation_no})')
    else:
        parent_id = getattr(room, 'parent_room_id', None)
        if parent_id:
            parent = db.get(m.Room, parent_id)
            if is_suite(parent):
                if ooo_blocks(db, parent, d_from, d_to):
                    return (f'الغرفة {room.room_no} ضمن الجناح {parent.room_no}'
                            ' وهو خارج الخدمة')
                hits = overlapping_reservations(db, tenant_id, parent.id,
                                                d_from, d_to, exclude_id)
                if hits:
                    return (f'الغرفة {room.room_no} محجوبة ضمن حجز الجناح '
                            f'{parent.room_no} ({hits[0].confirmation_no})')
    return None


def assert_linkable(db: Session, tenant_id: str, child: m.Room,
                    parent: m.Room | None) -> None:
    """ربط غرفة بجناح — شروط بنيوية + اتساق الحجوزات النشطة بالاتجاهين
    (لا ربط ينتج تداخلاً فيزيائياً: ADR-0035)."""
    if parent is None or parent.tenant_id != tenant_id:
        err('HOTEL.UNKNOWN_PARENT', 'الجناح الأب غير موجود')
    if parent.id == child.id:
        err('HOTEL.PARENT_SELF', 'لا يمكن ربط الغرفة بنفسها')
    if not is_suite(parent):
        err('HOTEL.PARENT_NOT_SUITE',
            f'الغرفة {parent.room_no} ليست جناحاً مركباً (kind=SUITE_UNIT)')
    if is_suite(child):
        err('HOTEL.NESTED_SUITE', 'لا أجنحة متداخلة — الجناح لا يكون ابناً')
    child_rsv = db.execute(select(m.Reservation).where(
        m.Reservation.tenant_id == tenant_id,
        m.Reservation.room_id == child.id,
        m.Reservation.status.in_(ACTIVE_RSV))).scalars().all()
    parent_rsv = db.execute(select(m.Reservation).where(
        m.Reservation.tenant_id == tenant_id,
        m.Reservation.room_id == parent.id,
        m.Reservation.status.in_(ACTIVE_RSV))).scalars().all()
    for cr in child_rsv:
        for prr in parent_rsv:
            if _overlap(cr.arrival_date, cr.departure_date,
                        prr.arrival_date, prr.departure_date):
                err('HOTEL.SUITE_LINK_CONFLICT',
                    f'تداخل فعلي: حجز الغرفة {cr.confirmation_no} مع حجز '
                    f'الجناح {prr.confirmation_no} — انقل أو ألغِ أولاً')


def assert_unlinkable(db: Session, tenant_id: str, child: m.Room) -> None:
    """فك ربط/تعطيل ابن ممنوع والجناح عليه حجوزات نشطة قادمة (الابن
    مشمول فيزيائياً بها — ADR-0035)."""
    pid = getattr(child, 'parent_room_id', None)
    if not pid:
        return
    bd = get_business_date(db, tenant_id)
    hits = db.execute(select(m.Reservation).where(
        m.Reservation.tenant_id == tenant_id,
        m.Reservation.room_id == pid,
        m.Reservation.status.in_(ACTIVE_RSV),
        m.Reservation.departure_date > bd)).scalars().all()
    if hits:
        err('HOTEL.SUITE_LINKED_BOOKINGS',
            f'لا يمكن فك الربط — الجناح عليه حجز نشط {hits[0].confirmation_no}'
            ' حتى انتهاء الفترة أو إلغاؤها')


def overlapping_reservations(db: Session, tenant_id: str, room_id: str,
                             d_from: date, d_to: date,
                             exclude_id: str | None = None) -> list[m.Reservation]:
    q = select(m.Reservation).where(
        m.Reservation.tenant_id == tenant_id,
        m.Reservation.room_id == room_id,
        m.Reservation.status.in_(ACTIVE_RSV),
        m.Reservation.arrival_date < d_to,
        m.Reservation.departure_date > d_from)
    if exclude_id:
        q = q.where(m.Reservation.id != exclude_id)
    return db.execute(q).scalars().all()


def ooo_blocks(db: Session, room: m.Room, d_from: date, d_to: date) -> bool:
    """هل الغرفة خارج الخدمة متداخلة مع الفترة؟ (ملف 03 §5: تُستثنى آلياً)"""
    if room.hk_status not in BLOCKING_HK:
        return False
    if room.ooo_from is None or room.ooo_to is None:
        return True  # معطلة بلا مدى = محجوبة دائماً
    return _overlap(d_from, d_to, room.ooo_from, room.ooo_to)


def available_rooms(db: Session, tenant_id: str, branch_id: str,
                    room_type_id: str, d_from: date,
                    d_to: date) -> list[m.Room]:
    rooms = db.execute(
        select(m.Room).where(m.Room.tenant_id == tenant_id,
                             m.Room.branch_id == branch_id,
                             m.Room.room_type_id == room_type_id,
                             m.Room.is_active.is_(True))
        .order_by(m.Room.room_no)).scalars().all()
    free = []
    for room in rooms:
        if ooo_blocks(db, room, d_from, d_to):
            continue
        if overlapping_reservations(db, tenant_id, room.id, d_from, d_to):
            continue
        if suite_block_reason(db, tenant_id, room, d_from, d_to):
            continue        # مركّب: ابن محجوب بجناحه أو جناح ناقص (ADR-0035)
        free.append(room)
    return free


def _lock_room(db: Session, room_id: str) -> m.Room:
    """اكتساب قفل كتابة على صف الغرفة = أولوية الحسم التنافسية."""
    room = db.execute(
        select(m.Room).where(m.Room.id == room_id)
        .with_for_update()).scalar_one()
    room.version = (room.version or 0) + 1  # لمسة كتابة حقيقية للقفل
    db.flush()
    return room


def _lock_room_type(db: Session, room_type_id: str) -> None:
    db.execute(select(m.RoomType.id).where(m.RoomType.id == room_type_id)
               .with_for_update()).one()


# ────────────────────────────────────────────────────────────────────
# دورة حياة الحجز (ملف 03 §2)
# ────────────────────────────────────────────────────────────────────
def _require_transition(res: m.Reservation, to: str):
    """تحقق فقط بلا تغيير — الحالة تُثبت في نهاية العملية بعد كل الشروط
    (منع تلوث الحالة عند فشل شرط لاحق داخل نفس الجلسة)."""
    allowed = RSV_TRANSITIONS.get(res.status, set())
    if to not in allowed:
        err('HOTEL.ILLEGAL_TRANSITION',
            f'لا يجوز الانتقال من {res.status} إلى {to}')


def create_reservation(db: Session, *, tenant_id: str, branch_id: str,
                       guest_id: str, room_type_id: str, arrival: date,
                       departure: date, actor_id: str,
                       corporate_id: str | None = None,
                       rate_plan_id: str | None = None,
                       room_id: str | None = None,
                       adults: int = 1, children: int = 0,
                       source: str = 'DIRECT',
                       rate_override: Decimal | None = None,
                       status: str = 'CONFIRMED',
                       trip: dict | None = None) -> m.Reservation:
    if departure <= arrival:
        err('HOTEL.BAD_DATES', 'تاريخ المغادرة يجب أن يكون بعد الوصول')
    guest = db.get(m.Guest, guest_id)
    if guest is None or guest.tenant_id != tenant_id:
        err('HOTEL.UNKNOWN_GUEST', 'نزيل غير موجود')
    if guest.blacklist:
        err('HOTEL.BLACKLISTED', 'نزيل في القائمة السوداء — يمنع الحجز')
    if corporate_id and db.get(m.Corporate, corporate_id) is None:
        err('HOTEL.UNKNOWN_CORPORATE', 'شركة غير موجودة')

    nights = (departure - arrival).days
    priced = price_stay(db, tenant_id, room_type_id, rate_plan_id,
                        arrival, departure)

    # منع مزدوج: قفل + فحص داخل نفس المعاملة (لا تداخل بعدها ممكن)
    chosen_room: m.Room | None = None
    if room_id:
        room = _lock_room(db, room_id)
        if room.room_type_id != room_type_id:
            err('HOTEL.ROOM_TYPE_MISMATCH', 'الغرفة من نوع مختلف عن الطلب')
        if ooo_blocks(db, room, arrival, departure):
            err('HOTEL.ROOM_OOO', f'الغرفة {room.room_no} خارج الخدمة في هذه الفترة')
        if overlapping_reservations(db, tenant_id, room.id, arrival, departure):
            err('HOTEL.DOUBLE_BOOKING', f'الغرفة {room.room_no} محجوزة متداخلة التواريخ')
        sb = suite_block_reason(db, tenant_id, room, arrival, departure)
        if sb:
            err('HOTEL.SUITE_BLOCKED', sb)
        chosen_room = room
    else:
        _lock_room_type(db, room_type_id)
        candidates = available_rooms(db, tenant_id, branch_id, room_type_id,
                                     arrival, departure)
        if not candidates:
            err('HOTEL.NO_AVAILABILITY', 'لا توجد غرفة متاحة لهذا النوع في الفترة')
        chosen_room = candidates[0]

    res = m.Reservation(
        id=new_uuid(), tenant_id=tenant_id, branch_id=branch_id,
        confirmation_no=_next_no(db, tenant_id, 'RESERVATION', 'RSV'),
        guest_id=guest_id, corporate_id=corporate_id,
        room_type_id=room_type_id, room_id=chosen_room.id,
        rate_plan_id=rate_plan_id,
        arrival_date=arrival, departure_date=departure, nights=nights,
        adults=adults, children=children, status=status, source=source,
        agreed_rate=priced[0]['rate'] if priced else Decimal('0'),
        est_total=sum(p['rate'] for p in priced), created_by=actor_id,
        created_at=utcnow(),
        confirmed_at=utcnow() if status == 'CONFIRMED' else None,
        # بيانات الرحلة للمعلومية (0.14.0) — تُملأ من الاستقبال عند الإنشاء:
        purpose=(trip or {}).get('purpose', ''),
        origin_gov=(trip or {}).get('origin_gov', ''),
        origin_district=(trip or {}).get('origin_district', ''),
        vehicle_note=(trip or {}).get('vehicle_note', ''),
        police_notes=(trip or {}).get('police_notes', ''))
    db.add(res)
    db.flush()
    for p in priced:  # Snapshot لكل ليلة — أساس الترحيل الليلي
        db.add(m.ReservationNightRate(
            id=new_uuid(), tenant_id=tenant_id, reservation_id=res.id,
            stay_date=p['date'], room_id=chosen_room.id, rate=p['rate'],
            rate_origin=p['origin']))
    if rate_override is not None:
        for nr in db.execute(
                select(m.ReservationNightRate).where(
                    m.ReservationNightRate.reservation_id == res.id)).scalars().all():
            nr.rate = D(rate_override)
        res.agreed_rate = D(rate_override)
        res.est_total = D(rate_override) * nights
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hotel', action='reservation.create', entity='reservations',
          entity_id=res.id,
          after={'conf': res.confirmation_no, 'room': chosen_room.room_no,
                 'arrival': str(arrival), 'departure': str(departure),
                 'total': str(res.est_total), 'override': str(rate_override)},
          business_date=arrival)
    return res


def modify_reservation(db: Session, *, res: m.Reservation, actor_id: str,
                       new_arrival: date | None = None,
                       new_departure: date | None = None,
                       new_room_id: str | None = None) -> dict:
    """تعديل تواريخ/غرفة — المنقضي يبقى بسعره، القادم يُعاد تسعيره (§2)."""
    if res.status not in ('TENTATIVE', 'CONFIRMED', 'CHECKED_IN'):
        err('HOTEL.NOT_MODIFIABLE', f'لا يمكن تعديل حجز بحالة {res.status}')
    bd = get_business_date(db, res.tenant_id)
    arrival = new_arrival or res.arrival_date
    departure = new_departure or res.departure_date
    if departure <= arrival:
        err('HOTEL.BAD_DATES', 'تاريخ المغادرة يجب أن يكون بعد الوصول')

    target_room = new_room_id or res.room_id
    if target_room != res.room_id or new_arrival or new_departure:
        room = _lock_room(db, target_room)
        if ooo_blocks(db, room, arrival, departure):
            err('HOTEL.ROOM_OOO', f'الغرفة {room.room_no} خارج الخدمة')
        if overlapping_reservations(db, res.tenant_id, room.id, arrival,
                                    departure, exclude_id=res.id):
            err('HOTEL.DOUBLE_BOOKING', f'الغرفة {room.room_no} محجوزة في الفترة الجديدة')
        sb = suite_block_reason(db, res.tenant_id, room, arrival,
                                departure, exclude_id=res.id)
        if sb:
            err('HOTEL.SUITE_BLOCKED', sb)
        res.room_id = room.id

    res.arrival_date, res.departure_date = arrival, departure
    res.nights = (departure - arrival).days
    # الليالي المنقضية تحتفظ بسعرها؛ القادمة تعاد (حذف + إعادة تسعير)
    existing = {nr.stay_date: nr for nr in db.execute(
        select(m.ReservationNightRate).where(
            m.ReservationNightRate.reservation_id == res.id)).scalars().all()}
    priced = price_stay(db, res.tenant_id, res.room_type_id, res.rate_plan_id,
                        arrival, departure)
    total = Decimal('0')
    for p in priced:
        nr = existing.get(p['date'])
        if nr is None:
            nr = m.ReservationNightRate(id=new_uuid(), tenant_id=res.tenant_id,
                                        reservation_id=res.id,
                                        stay_date=p['date'])
            db.add(nr)
        if p['date'] >= bd:  # ليلة قادمة ← إعادة تسعير كاملة
            nr.rate = p['rate']
            nr.rate_origin = p['origin']
        nr.room_id = res.room_id
        total = total + nr.rate
    for sd, nr in existing.items():  # ليالٍ خرجت عن النطاق ← تحذف
        if sd < arrival or sd >= departure:
            db.delete(nr)
    res.est_total = total
    res.version += 1
    db.flush()
    audit(db, tenant_id=res.tenant_id, actor_id=actor_id, actor_type='user',
          module='hotel', action='reservation.modify', entity='reservations',
          entity_id=res.id,
          after={'arrival': str(arrival), 'departure': str(departure),
                 'room_id': res.room_id, 'version': res.version})
    return {'nights': res.nights, 'est_total': str(total)}


def deposit_balance(db: Session, tenant_id: str, reservation_id: str) -> Decimal:
    q = (select(func.sum(m.JournalLine.credit_base),
                func.sum(m.JournalLine.debit_base))
         .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
         .join(m.Account, m.Account.id == m.JournalLine.account_id)
         .where(m.JournalLine.tenant_id == tenant_id,
                m.Account.code == DEPOSIT_LEDGER,
                m.JournalLine.party_id == reservation_id,
                m.JournalEntry.status.in_(['POSTED', 'REVERSED'])))
    tc, td = db.execute(q).one()
    return D(tc or 0) - D(td or 0)


def add_deposit(db: Session, *, res: m.Reservation, amount: Decimal,
                actor_id: str, method: str = 'CASH') -> m.JournalEntry:
    """#01 استلام عربون — Dr النقدية / Cr 2110 (طرف = الحجز)."""
    if res.status not in ('TENTATIVE', 'CONFIRMED'):
        err('HOTEL.BAD_STATE', 'يستلم العربون قبل التسكين فقط')
    if amount <= 0:
        err('HOTEL.BAD_AMOUNT', 'مبلغ العربون يجب أن يكون موجباً')
    je = post_event(
        db, tenant_id=res.tenant_id, branch_code='MAIN',
        event_type='GUEST_DEPOSIT',
        event_key=f'deposit:{res.id}:{new_uuid()}',
        entry_date=get_business_date(db, res.tenant_id),
        amounts={'amount': str(amount)}, party_type='GUEST',
        party_id=res.id, actor_id=actor_id,
        narration=f'عربون حجز {res.confirmation_no} ({method})')
    audit(db, tenant_id=res.tenant_id, actor_id=actor_id, actor_type='user',
          module='hotel', action='reservation.deposit', entity='reservations',
          entity_id=res.id, after={'amount': str(amount), 'method': method})
    return je


def cancel_reservation(db: Session, *, res: m.Reservation, reason: str,
                       actor_id: str, fee: Decimal = Decimal('0'),
                       refund: bool = True) -> dict:
    """الإلغاء: سبب إلزامي + غرامة اختيارية من العربون (#02) + رد الباقي."""
    if not reason or len(reason.strip()) < 3:
        err('HOTEL.REASON_REQUIRED', 'سبب الإلغاء إلزامي')
    _require_transition(res, 'CANCELLED')
    bd = get_business_date(db, res.tenant_id)
    dep = deposit_balance(db, res.tenant_id, res.id)
    tax_rate = current_tax_rate(db, res.tenant_id)
    applied_fee = min(D(fee), dep) if fee > 0 else Decimal('0')
    ret = {'cancelled': True, 'fee': str(applied_fee), 'refunded': '0'}
    if applied_fee > 0:
        gross, net, tax = split_gross(applied_fee, tax_rate)
        post_event(db, tenant_id=res.tenant_id, branch_code='MAIN',
                   event_type='CANCEL_FEE',
                   event_key=f'cancelfee:{res.id}:{applied_fee}',
                   entry_date=bd, amounts={'amount': str(gross), 'net': str(net),
                                           'tax': str(tax)},
                   party_type='GUEST', party_id=res.id, actor_id=actor_id,
                   narration=f'غرامة إلغاء {res.confirmation_no}: {reason}')
        dep -= applied_fee
    if refund and dep > 0:
        post_event(db, tenant_id=res.tenant_id, branch_code='MAIN',
                   event_type='DEPOSIT_REFUND',
                   event_key=f'deprefund:{res.id}:{dep}',
                   entry_date=bd, amounts={'amount': str(dep)},
                   party_type='GUEST', party_id=res.id, actor_id=actor_id,
                   narration=f'رد عربون {res.confirmation_no} بعد الإلغاء')
        ret['refunded'] = str(dep)
    res.status = 'CANCELLED'
    res.cancel_reason = reason
    res.cancelled_at = utcnow()
    db.flush()
    audit(db, tenant_id=res.tenant_id, actor_id=actor_id, actor_type='user',
          module='hotel', action='reservation.cancel', entity='reservations',
          entity_id=res.id,
          after={'reason': reason, 'fee': str(applied_fee),
                 'refunded': ret['refunded']})
    return ret


def mark_no_show(db: Session, *, res: m.Reservation, actor_id: str) -> m.JournalEntry:
    """#03 عدم حضور: احتساب ليلة — شركة مؤكدة ← 1120، مباشر ← من عربونه."""
    _require_transition(res, 'NO_SHOW')
    bd = get_business_date(db, res.tenant_id)
    night = db.execute(
        select(m.ReservationNightRate).where(
            m.ReservationNightRate.reservation_id == res.id,
            m.ReservationNightRate.stay_date == res.arrival_date)
        .limit(1)).scalar_one_or_none()
    amount = D(night.rate) if night else D(res.agreed_rate)
    tax_rate = current_tax_rate(db, res.tenant_id)
    gross, net, tax = split_gross(amount, tax_rate)
    ctx = 'CORPORATE' if res.corporate_id else 'GUEST'
    party_id = res.corporate_id if res.corporate_id else res.id
    ptype = 'CORPORATE' if res.corporate_id else 'GUEST'
    je = post_event(db, tenant_id=res.tenant_id, branch_code='MAIN',
                    event_type='NO_SHOW', context_key=ctx,
                    event_key=f'noshow:{res.id}',
                    entry_date=bd,
                    amounts={'amount': str(gross), 'net': str(net),
                             'tax': str(tax)},
                    party_type=ptype, party_id=party_id, actor_id=actor_id,
                    narration=f'عدم حضور {res.confirmation_no} — احتساب ليلة')
    res.status = 'NO_SHOW'
    db.flush()
    audit(db, tenant_id=res.tenant_id, actor_id=actor_id, actor_type='user',
          module='hotel', action='reservation.no_show', entity='reservations',
          entity_id=res.id, after={'charged_night': str(gross)})
    return je


# ────────────────────────────────────────────────────────────────────
# الوصول والإقامة (ملف 03 §3)
# ────────────────────────────────────────────────────────────────────
def _personal_folio(db: Session, res: m.Reservation) -> m.Folio:
    folio = db.execute(
        select(m.Folio).where(m.Folio.reservation_id == res.id,
                              m.Folio.window == 1)).scalar_one_or_none()
    if folio is None:
        corp_limit = None
        if res.corporate_id:
            corp = db.get(m.Corporate, res.corporate_id)
            corp_limit = corp.credit_limit if corp else None
        folio = m.Folio(id=new_uuid(), tenant_id=res.tenant_id,
                        branch_id=res.branch_id, reservation_id=res.id,
                        window=1, type='GUEST', status='OPEN',
                        credit_limit=corp_limit, opened_at=utcnow())
        db.add(folio)
        db.flush()
    return folio


def check_in(db: Session, *, res: m.Reservation, actor_id: str,
             allow_dirty: bool = False) -> dict:
    """Check-in ≤ 60 ثانية: شروط الدخول + فوليو + تطبيق العربون (§3.1).
    كل الشروط أولاً، ثم التثبيت — فشل أي شرط لا يلوث حالة الحجز."""
    _require_transition(res, 'CHECKED_IN')
    bd = get_business_date(db, res.tenant_id)
    if not (res.arrival_date <= bd < res.departure_date):
        err('HOTEL.OUTSIDE_WINDOW',
            f'تاريخ العمل {bd} خارج فترة الإقامة '
            f'({res.arrival_date} ← {res.departure_date})')
    room = _lock_room(db, res.room_id)
    if room.hk_status in BLOCKING_HK:
        err('HOTEL.ROOM_OOO', f'الغرفة {room.room_no} خارج الخدمة')
    if room.hk_status not in ('CLEAN', 'INSPECTED') and not allow_dirty:
        err('HOTEL.ROOM_NOT_CLEAN',
            f'الغرفة {room.room_no} بحالة {room.hk_status} — التسكين يتطلب نظيفة أو استثناء بصلاحية')
    sb = suite_block_reason(db, res.tenant_id, room, bd, res.departure_date,
                            exclude_id=res.id)
    if sb:
        err('HOTEL.SUITE_BLOCKED', sb)   # أمان مضاعف للمسار اليدوي (ADR-0035)

    folio = _personal_folio(db, res)
    # شريحة الإقامة الفعلية
    db.add(m.ReservationStay(id=new_uuid(), tenant_id=res.tenant_id,
                             reservation_id=res.id, room_id=room.id,
                             from_date=bd, to_date=res.departure_date, seq=1))
    # تطبيق العربون كله على الفوليو (ملف 02 §6)
    dep = deposit_balance(db, res.tenant_id, res.id)
    if dep > 0:
        post_event(db, tenant_id=res.tenant_id, branch_code='MAIN',
                   event_type='DEPOSIT_APPLY',
                   event_key=f'depapply:{res.id}:{folio.id}',
                   entry_date=bd, amounts={'amount': str(dep)},
                   parties={'reservation': ('GUEST', res.id),
                            'folio': ('GUEST', folio.id)},
                   actor_id=actor_id,
                   narration=f'تطبيق عربون {res.confirmation_no} على الفوليو')
    res.status = 'CHECKED_IN'
    res.checked_in_at = utcnow()
    db.flush()
    audit(db, tenant_id=res.tenant_id, actor_id=actor_id, actor_type='user',
          module='hotel', action='reservation.check_in',
          entity='reservations', entity_id=res.id,
          after={'room': room.room_no, 'folio': folio.id,
                 'deposit_applied': str(dep), 'dirty_override': allow_dirty},
          business_date=bd)
    return {'folio_id': folio.id, 'room_no': room.room_no,
            'deposit_applied': str(dep)}


def walk_in(db: Session, *, tenant_id: str, branch_id: str, guest_id: str,
            room_type_id: str, departure: date, actor_id: str,
            allow_dirty: bool = False, **kw) -> m.Reservation:
    """حضور مباشر: إنشاء + تسكين بخطوة واحدة (ملف 03 §2 Walk-in)."""
    bd = get_business_date(db, tenant_id)
    res = create_reservation(db, tenant_id=tenant_id, branch_id=branch_id,
                             guest_id=guest_id, room_type_id=room_type_id,
                             arrival=bd, departure=departure,
                             actor_id=actor_id, source='WALKIN', **kw)
    check_in(db, res=res, actor_id=actor_id, allow_dirty=allow_dirty)
    return res


def room_move(db: Session, *, res: m.Reservation, new_room_id: str,
              reason: str, actor_id: str) -> dict:
    """نقل نزيل: إنهاء شريحة وفتح أخرى بنفس الفوليو؛ القديمة ← Dirty (§2)."""
    if res.status != 'CHECKED_IN':
        err('HOTEL.BAD_STATE', 'النقل لنزيل مقيم فقط')
    if not reason or len(reason.strip()) < 3:
        err('HOTEL.REASON_REQUIRED', 'سبب النقل إلزامي')
    bd = get_business_date(db, res.tenant_id)
    old_room = db.get(m.Room, res.room_id)
    new_room = _lock_room(db, new_room_id)
    if new_room.hk_status in BLOCKING_HK:
        err('HOTEL.ROOM_OOO', f'الغرفة {new_room.room_no} خارج الخدمة')
    if overlapping_reservations(db, res.tenant_id, new_room.id, bd,
                                res.departure_date, exclude_id=res.id):
        err('HOTEL.DOUBLE_BOOKING', f'الغرفة {new_room.room_no} محجوزة')
    sb = suite_block_reason(db, res.tenant_id, new_room, bd,
                            res.departure_date, exclude_id=res.id)
    if sb:
        err('HOTEL.SUITE_BLOCKED', sb)
    # إغلاق الشريحة الحالية وفتح الجديدة
    cur = db.execute(
        select(m.ReservationStay).where(
            m.ReservationStay.reservation_id == res.id,
            m.ReservationStay.to_date == res.departure_date)
        .order_by(m.ReservationStay.seq.desc())).scalars().first()
    if cur:
        cur.to_date = bd
    seq = (cur.seq + 1) if cur else 1
    db.add(m.ReservationStay(id=new_uuid(), tenant_id=res.tenant_id,
                             reservation_id=res.id, room_id=new_room.id,
                             from_date=bd, to_date=res.departure_date,
                             seq=seq))
    # ليالي Snapshot القادمة تشير للغرفة الجديدة (المنقضية تبقى تاريخاً)
    for nr in db.execute(
            select(m.ReservationNightRate).where(
                m.ReservationNightRate.reservation_id == res.id,
                m.ReservationNightRate.stay_date >= bd)).scalars().all():
        nr.room_id = new_room.id
    res.room_id = new_room.id
    old_room.hk_status = 'DIRTY'  # تلقائياً (§2)
    db.flush()
    audit(db, tenant_id=res.tenant_id, actor_id=actor_id, actor_type='user',
          module='hotel', action='reservation.room_move',
          entity='reservations', entity_id=res.id,
          after={'from': old_room.room_no, 'to': new_room.room_no,
                 'reason': reason}, business_date=bd)
    return {'old': old_room.room_no, 'new': new_room.room_no}


# ────────────────────────────────────────────────────────────────────
# الفوليو — الرصيد من الدفتر لحظياً (قبول #2)
# ────────────────────────────────────────────────────────────────────
def folio_balance(db: Session, tenant_id: str, folio_id: str) -> Decimal:
    q = (select(func.sum(m.JournalLine.debit_base),
                func.sum(m.JournalLine.credit_base))
         .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
         .join(m.Account, m.Account.id == m.JournalLine.account_id)
         .where(m.JournalLine.tenant_id == tenant_id,
                m.Account.code == GUEST_LEDGER,
                m.JournalLine.party_id == folio_id,
                m.JournalEntry.status.in_(['POSTED', 'REVERSED'])))
    td, tc = db.execute(q).one()
    return D(td or 0) - D(tc or 0)


def folio_lines(db: Session, tenant_id: str, folio_id: str) -> list[dict]:
    q = (select(m.JournalEntry, m.JournalLine)
         .join(m.JournalLine, m.JournalLine.entry_id == m.JournalEntry.id)
         .join(m.Account, m.Account.id == m.JournalLine.account_id)
         .where(m.JournalEntry.tenant_id == tenant_id,
                m.Account.code == GUEST_LEDGER,
                m.JournalLine.party_id == folio_id,
                m.JournalEntry.status.in_(['POSTED', 'REVERSED']))
         .order_by(m.JournalEntry.entry_date, m.JournalEntry.entry_no,
                   m.JournalLine.line_no))
    rows, running = [], Decimal('0')
    for je, ln in db.execute(q).all():
        running += D(ln.debit_base) - D(ln.credit_base)
        rows.append({'entry_id': je.id, 'entry_no': je.entry_no,
                     'date': je.entry_date, 'narration': je.narration,
                     'line_desc': ln.description,
                     'debit': D(ln.debit_base), 'credit': D(ln.credit_base),
                     'running': running})
    return rows


def _sum_account_for_party(db, tenant_id, account_code, party_id):
    q = (select(func.sum(m.JournalLine.debit_base),
                func.sum(m.JournalLine.credit_base))
         .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
         .join(m.Account, m.Account.id == m.JournalLine.account_id)
         .where(m.JournalLine.tenant_id == tenant_id,
                m.Account.code == account_code,
                m.JournalLine.party_id == party_id,
                m.JournalEntry.status.in_(['POSTED', 'REVERSED'])))
    td, tc = db.execute(q).one()
    return D(td or 0), D(tc or 0)


def folio_totals(db: Session, tenant_id: str, folio_id: str) -> dict:
    """الإجماليات الدقيقة من الدفتر: الشحنات (مدين 1110) والمدفوعات (دائن 1110)."""
    td, tc = _sum_account_for_party(db, tenant_id, GUEST_LEDGER, folio_id)
    return {'charges': td, 'payments': tc, 'balance': td - tc}


def open_folio_or_err(db: Session, folio_id: str, tenant_id: str) -> m.Folio:
    folio = db.get(m.Folio, folio_id)
    if folio is None or folio.tenant_id != tenant_id:
        err('HOTEL.UNKNOWN_FOLIO', 'فوليو غير موجود')
    if folio.status != 'OPEN':
        err('HOTEL.FOLIO_CLOSED', 'الفوليو مُقفل — التصحيح بقيد عكسي فقط')
    return folio


def add_charge(db: Session, *, folio: m.Folio, extra_code: str,
               qty: int, actor_id: str, unit_price: Decimal | None = None,
               description: str = '', event_key: str | None = None) -> m.JournalEntry:
    """#05 شحنة خدمة على الفوليو — السعر Snapshot لحظة الإدخال."""
    extra = db.execute(
        select(m.Extra).where(m.Extra.tenant_id == folio.tenant_id,
                              m.Extra.code == extra_code,
                              m.Extra.is_active.is_(True))).scalar_one_or_none()
    if extra is None:
        err('HOTEL.UNKNOWN_EXTRA', f'خدمة غير معروفة: {extra_code}')
    if qty < 1:
        err('HOTEL.BAD_QTY', 'الكمية يجب أن تكون واحداً فأكثر')
    price = D(unit_price) if unit_price is not None else D(extra.price)
    gross = (price * qty).quantize(Decimal('0.0001'))
    tax_rate = current_tax_rate(db, folio.tenant_id)
    g, net, tax = split_gross(gross, tax_rate)
    bd = get_business_date(db, folio.tenant_id)
    je = post_event(
        db, tenant_id=folio.tenant_id, branch_code='MAIN',
        event_type='FOLIO_CHARGE', context_key=extra.code,
        event_key=event_key or f'charge:{folio.id}:{new_uuid()}',
        entry_date=bd,
        amounts={'gross': str(g), 'net': str(net), 'tax': str(tax)},
        party_type='GUEST', party_id=folio.id, actor_id=actor_id,
        narration=description or f'{extra.name_ar} × {qty}')
    return je


def add_payment(db: Session, *, folio: m.Folio, amount: Decimal,
                method: str, actor_id: str,
                event_key: str | None = None) -> m.JournalEntry:
    """#07 دفعة من نزيل — الوسيلة تحدد صندوق التحصيل."""
    if amount <= 0:
        err('HOTEL.BAD_AMOUNT', 'مبلغ الدفعة يجب أن يكون موجباً')
    if method not in ('CASH', 'CARD', 'EWALLET'):
        err('HOTEL.BAD_METHOD', f'وسيلة دفع غير صالحة: {method}')
    bd = get_business_date(db, folio.tenant_id)
    return post_event(
        db, tenant_id=folio.tenant_id, branch_code='MAIN',
        event_type='FOLIO_PAYMENT', context_key=method,
        event_key=event_key or f'pay:{folio.id}:{new_uuid()}',
        entry_date=bd, amounts={'amount': str(D(amount))},
        party_type='GUEST', party_id=folio.id, actor_id=actor_id,
        narration=f'سداد على الفوليو ({method})')


def add_discount(db: Session, *, folio: m.Folio, amount: Decimal,
                 reason: str, actor: 'object', approver_id: str | None,
                 can_approve: bool) -> m.JournalEntry:
    """#06 خصم مسموح — فوق حد الدور يتطلب معتمداً حاملاً discounts.approve."""
    if amount <= 0:
        err('HOTEL.BAD_AMOUNT', 'مبلغ الخصم يجب أن يكون موجباً')
    if not reason or len(reason.strip()) < 3:
        err('HOTEL.REASON_REQUIRED', 'سبب الخصم إلزامي')
    approver = None
    if not can_approve and D(amount) > SELF_DISCOUNT_CAP:
        if not approver_id:
            err('HOTEL.DISCOUNT_NEEDS_APPROVAL',
                f'خصم يتجاوز {SELF_DISCOUNT_CAP} يتطلب اعتماد مدير (discounts.approve)')
        approver = db.get(m.User, approver_id)
        if approver is None or not approver.is_active:
            err('HOTEL.BAD_APPROVER', 'المعتمد غير موجود أو موقوف')
    bd = get_business_date(db, folio.tenant_id)
    je = post_event(
        db, tenant_id=folio.tenant_id, branch_code='MAIN',
        event_type='DISCOUNT',
        event_key=f'disc:{folio.id}:{new_uuid()}',
        entry_date=bd, amounts={'amount': str(D(amount))},
        party_type='GUEST', party_id=folio.id,
        actor_id=getattr(actor, 'id', 'system'),
        narration=f'خصم معتمد — {reason}')
    audit(db, tenant_id=folio.tenant_id, actor_id=getattr(actor, 'id', None),
          actor_type='user', module='hotel', action='folio.discount',
          entity='folios', entity_id=folio.id,
          after={'amount': str(amount), 'reason': reason,
                 'approved_by': approver_id if approver else 'self',
                 'cap': str(SELF_DISCOUNT_CAP)}, business_date=bd)
    return je


def corporate_window(db: Session, res: m.Reservation) -> m.Folio:
    """نافذة الشركة (window=2) — تنشأ عند أول تحويل/نقل."""
    if not res.corporate_id:
        err('HOTEL.NO_CORPORATE', 'لا توجد شركة مرتبطة بهذا الحجز')
    folio = db.execute(
        select(m.Folio).where(m.Folio.reservation_id == res.id,
                              m.Folio.window == 2)).scalar_one_or_none()
    if folio is None:
        folio = m.Folio(id=new_uuid(), tenant_id=res.tenant_id,
                        branch_id=res.branch_id, reservation_id=res.id,
                        window=2, type='CORPORATE',
                        corporate_id=res.corporate_id, status='OPEN',
                        opened_at=utcnow())
        db.add(folio)
        db.flush()
    return folio


def transfer_to_corporate(db: Session, *, res: m.Reservation,
                          amount: Decimal, actor_id: str,
                          reason: str = '') -> m.JournalEntry:
    """تحويل شحنة من النافذة الشخصية لنافذة الشركة (مقيد بصلاحية)."""
    person = _personal_folio(db, res)
    if person.status != 'OPEN':
        err('HOTEL.FOLIO_CLOSED', 'الفوليو الشخصي مُقفل')
    corp_f = corporate_window(db, res)
    bd = get_business_date(db, res.tenant_id)
    return post_event(
        db, tenant_id=res.tenant_id, branch_code='MAIN',
        event_type='FOLIO_TRANSFER',
        event_key=f'xfer:{person.id}:{corp_f.id}:{new_uuid()}',
        entry_date=bd, amounts={'amount': str(D(amount))},
        parties={'to_window': ('CORPORATE', corp_f.id),
                 'from_window': ('GUEST', person.id)},
        actor_id=actor_id,
        narration=f'تحويل {amount} من شخصي إلى نافذة الشركة — {reason}')


# ────────────────────────────────────────────────────────────────────
# المغادرة (ملف 03 §3.3 — فحوص مرتبة + فاتورة ضريبية ختامية)
# ────────────────────────────────────────────────────────────────────
def checkout(db: Session, *, res: m.Reservation, actor_id: str,
             late_fee: Decimal = Decimal('0'),
             payments: list[dict] | None = None,
             corporate_transfer: bool = False) -> m.GuestInvoice:
    _require_transition(res, 'CHECKED_OUT')
    bd = get_business_date(db, res.tenant_id)
    person = _personal_folio(db, res)

    # (ج) رسوم المغادرة المتأخرة أولاً حتى تدخل التسوية
    if late_fee and late_fee > 0:
        tax_rate = current_tax_rate(db, res.tenant_id)
        g, net, tax = split_gross(D(late_fee), tax_rate)
        post_event(db, tenant_id=res.tenant_id, branch_code='MAIN',
                   event_type='LATE_CHECKOUT',
                   event_key=f'lateco:{res.id}:{late_fee}',
                   entry_date=bd,
                   amounts={'gross': str(g), 'net': str(net), 'tax': str(tax)},
                   party_type='GUEST', party_id=person.id, actor_id=actor_id,
                   narration='رسوم مغادرة متأخرة')

    # (ب) تصفير كل نافذة: سداد نقدي/بنكي أو نقل لشركة (#08)
    payments = payments or []
    folios = [f for f in db.execute(
        select(m.Folio).where(m.Folio.reservation_id == res.id,
                              m.Folio.status == 'OPEN')).scalars().all()]
    if person not in folios:
        folios.append(person)

    for folio in folios:
        bal = folio_balance(db, res.tenant_id, folio.id)
        if bal < 0:  # فائض مدفوع ← رد للنزيل نقداً
            post_event(db, tenant_id=res.tenant_id, branch_code='MAIN',
                       event_type='GUEST_REFUND',
                       event_key=f'refund:{folio.id}:{-bal}',
                       entry_date=bd, amounts={'amount': str(-bal)},
                       party_type='GUEST', party_id=folio.id,
                       actor_id=actor_id,
                       narration='رد فائض مدفوعات عند المغادرة')
            bal = Decimal('0')
        if folio.window == 1 and bal > 0:
            for p in [p for p in payments if p.get('_folio', 1) == 1]:
                add_payment(db, folio=folio, amount=D(p['amount']),
                            method=p['method'], actor_id=actor_id)
            bal = folio_balance(db, res.tenant_id, folio.id)
        if bal > 0:
            if not (corporate_transfer and res.corporate_id):
                err('HOTEL.UNSETTLED_BALANCE',
                    f'رصيد مفتوح {bal} على نافذة {folio.window} — '
                    'سدده أو انقله لشركة بصلاحية')
            post_event(db, tenant_id=res.tenant_id, branch_code='MAIN',
                       event_type='CITY_LEDGER_TRANSFER',
                       event_key=f'cityxfer:{folio.id}:{bal}',
                       entry_date=bd, amounts={'amount': str(bal)},
                       parties={'corporate': ('CORPORATE', res.corporate_id),
                                'folio': ('GUEST', folio.id)},
                       actor_id=actor_id,
                       narration=f'نقل ذمة {res.confirmation_no} إلى الشركة')
            bal = folio_balance(db, res.tenant_id, folio.id)
        if bal != 0:
            err('HOTEL.SETTLEMENT_FAILED', f'تعذر تصفير نافذة {folio.window}')
        folio.status = 'CLOSED'
        folio.closed_at = utcnow()
        folio.closed_by = actor_id

    res.status = 'CHECKED_OUT'
    res.checked_out_at = utcnow()
    db.flush()
    room = db.get(m.Room, res.room_id)
    if room and room.hk_status not in BLOCKING_HK:
        room.hk_status = 'DIRTY'  # الغرفة بعد الخروج (§3.3)

    # فاتورة ضريبية نهائية غير قابلة للتعديل — تسلسل رسمي مستقل
    guest = db.get(m.Guest, res.guest_id)
    totals = folio_totals(db, res.tenant_id, person.id)
    lines = folio_lines(db, res.tenant_id, person.id)
    inv = m.GuestInvoice(
        id=new_uuid(), tenant_id=res.tenant_id, branch_id=res.branch_id,
        reservation_id=res.id, folio_id=person.id,
        invoice_no=_next_no(db, res.tenant_id, 'INVOICE', 'INV'),
        guest_name=guest.full_name if guest else '',
        issued_at=utcnow(), issued_by=actor_id,
        lines=[{k: (str(v) if isinstance(v, (Decimal, date)) else v)
                for k, v in row.items()} for row in lines],
        total_charges=totals['charges'], total_payments=totals['payments'],
        balance_settled=totals['balance'])
    db.add(inv)
    db.flush()
    audit(db, tenant_id=res.tenant_id, actor_id=actor_id, actor_type='user',
          module='hotel', action='reservation.check_out',
          entity='reservations', entity_id=res.id,
          after={'invoice': inv.invoice_no, 'charges': str(totals['charges']),
                 'payments': str(totals['payments']),
                 'late_fee': str(late_fee),
                 'corporate_transfer': corporate_transfer},
          business_date=bd)
    return inv


# ────────────────────────────────────────────────────────────────────
# التدقيق الليلي (ملف 03 §4) — معالج خطوات، ذري، idempotent
# ────────────────────────────────────────────────────────────────────
def precheck(db: Session, tenant_id: str) -> dict:
    """فحوص الخطوتين 1 و2 قبل الإقفال: وصولات ومغادرات بلا حسم."""
    bd = get_business_date(db, tenant_id)
    pend_arr = db.execute(
        select(m.Reservation).where(
            m.Reservation.tenant_id == tenant_id,
            m.Reservation.status.in_(('TENTATIVE', 'CONFIRMED')),
            m.Reservation.arrival_date <= bd)).scalars().all()
    pend_dep = db.execute(
        select(m.Reservation).where(
            m.Reservation.tenant_id == tenant_id,
            m.Reservation.status == 'CHECKED_IN',
            m.Reservation.departure_date == bd)).scalars().all()
    in_house = db.execute(
        select(m.Reservation).where(
            m.Reservation.tenant_id == tenant_id,
            m.Reservation.status == 'CHECKED_IN',
            m.Reservation.arrival_date <= bd,
            m.Reservation.departure_date > bd)).scalars().all()
    return {'business_date': bd,
            'pending_arrivals': _rsv_brief(pend_arr),
            'pending_departures': _rsv_brief(pend_dep),
            'in_house_expect_nights': len(in_house),
            'can_run': not pend_arr and not pend_dep}


def _rsv_brief(rows) -> list[dict]:
    return [{'id': r.id, 'conf': r.confirmation_no,
             'arrival': str(r.arrival_date), 'departure': str(r.departure_date),
             'status': r.status} for r in rows]


def _night_rate_for(db: Session, res: m.Reservation, bd: date) -> Decimal:
    nr = db.execute(
        select(m.ReservationNightRate).where(
            m.ReservationNightRate.reservation_id == res.id,
            m.ReservationNightRate.stay_date == bd)).scalar_one_or_none()
    if nr:
        return D(nr.rate)
    price, _ = resolve_night_rate(db, res.tenant_id, res.room_type_id,
                                  res.rate_plan_id, bd)
    return price


def run_night_audit(db: Session, *, tenant_id: str, actor_id: str) -> m.NightAuditRun:
    """الخطوات 1..7 دفعة واحدة ذرية: أي فشل = لا شيء (rollback عند الرفع)."""
    state = lock_state(db, tenant_id)
    bd = state.current_business_date
    pre = precheck(db, tenant_id)
    if not pre['can_run']:
        err('HOTEL.AUDIT_BLOCKED',
            f'لا يمكن الإقفال: {len(pre["pending_arrivals"])} وصول و'
            f'{len(pre["pending_departures"])} مغادرة بلا حسم — '
            'عالجها ثم أعد التدقيق')

    run = m.NightAuditRun(id=new_uuid(), tenant_id=tenant_id,
                          business_date=bd, status='RUNNING',
                          steps=[], started_by=actor_id, started_at=utcnow())
    db.add(run)
    db.flush()
    steps = []

    # الخطوة 3: ترحيل الليالٍ لكل مقيم — ذرياً كلها أو لا شيء
    todays = db.execute(
        select(m.Reservation).where(
            m.Reservation.tenant_id == tenant_id,
            m.Reservation.status == 'CHECKED_IN',
            m.Reservation.arrival_date <= bd,
            m.Reservation.departure_date > bd)).scalars().all()
    posted, revenue = 0, Decimal('0')
    tax_rate = current_tax_rate(db, tenant_id)
    for res in todays:
        folio = _personal_folio(db, res)
        rate = _night_rate_for(db, res, bd)
        gross, net, tax = split_gross(rate, tax_rate)
        room_no = db.get(m.Room, res.room_id).room_no if res.room_id else '—'
        post_event(db, tenant_id=tenant_id, branch_code='MAIN',
                   event_type='ROOM_NIGHT',
                   event_key=f'na:{bd}:{res.id}',  # استحالة التكرار (قبول #4)
                   entry_date=bd,
                   amounts={'gross': str(gross), 'net': str(net),
                            'tax': str(tax)},
                   party_type='GUEST', party_id=folio.id, actor_id=actor_id,
                   narration=f'ليلة {bd} — غرفة {room_no} ({res.confirmation_no})')
        posted += 1
        revenue += gross
    steps.append({'step': 3, 'name': 'ترحيل ليالٍ الإقامة',
                  'nights_posted': posted, 'room_revenue': str(revenue)})

    # الخطوة 4: الشحنات الآلية المجدولة — لا باقات مفعّلة في v1
    steps.append({'step': 4, 'name': 'شحنات آلية مجدولة', 'posted': 0,
                  'note': 'لا باقات يومية مفعّلة'})

    # الخطوة 5: تقارير الجولة
    rooms_active = db.execute(
        select(func.count(m.Room.id)).where(m.Room.tenant_id == tenant_id,
                                            m.Room.is_active.is_(True))).scalar_one()
    arrivals_today = db.execute(
        select(func.count(m.Reservation.id)).where(
            m.Reservation.tenant_id == tenant_id,
            m.Reservation.status == 'CHECKED_IN',
            m.Reservation.arrival_date == bd)).scalar_one()
    open_folios = db.execute(
        select(m.Folio).where(m.Folio.tenant_id == tenant_id,
                              m.Folio.status == 'OPEN')).scalars().all()
    high_balance = []
    for f in open_folios:
        bal = folio_balance(db, tenant_id, f.id)
        if f.credit_limit and bal > f.credit_limit:
            high_balance.append({'folio': f.id, 'balance': str(bal),
                                 'limit': str(f.credit_limit)})
    ooo_alert = _ooo_conflicts(db, tenant_id, bd)
    cash_drawers = {}
    for code in ('1101', '1102', '1103', '1104'):
        q = (select(func.sum(m.JournalLine.debit_base),
                    func.sum(m.JournalLine.credit_base))
             .select_from(m.JournalLine)
             .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
             .join(m.Account, m.Account.id == m.JournalLine.account_id)
             .where(m.JournalLine.tenant_id == tenant_id,
                    m.Account.code == code,
                    m.JournalEntry.status.in_(['POSTED', 'REVERSED'])))
        td, tc = db.execute(q).one()
        cash_drawers[code] = str(D(td or 0) - D(tc or 0))
    steps.append({'step': 5, 'name': 'تقارير الجولة',
                  'checkins_today': arrivals_today,
                  'open_folios': len(open_folios),
                  'high_balance': high_balance, 'ooo_conflicts': ooo_alert,
                  'cash_drawers_system': cash_drawers,
                  'note': 'المطابقة النقدية الفعلية توثّق يدوياً'})

    # الخطوة 6: عدّاد High Balance
    steps.append({'step': 6, 'name': 'عدّاد الأرصدة العالية',
                  'count': len(high_balance)})

    # الخطوة 7: إقفال اليوم + Snapshot غير قابل للتعديل
    occ = posted / rooms_active if rooms_active else 0
    adr = (revenue / posted) if posted else Decimal('0')
    snapshot = {
        'business_date': str(bd), 'rooms_active': rooms_active,
        'nights_posted': posted, 'room_revenue': str(revenue),
        'occupancy_pct': str((D(occ) * 100).quantize(Decimal('0.01'))),
        'adr': str(adr.quantize(Decimal('0.01'))),
        'revpar': str(((revenue / rooms_active) if rooms_active else Decimal('0')).quantize(Decimal('0.01'))),
        'high_balance': high_balance, 'ooo_conflicts': ooo_alert,
        'closed_by': actor_id,
    }
    run.steps = steps
    run.totals = {'nights_posted': posted, 'revenue': str(revenue)}
    run.report_snapshot = snapshot
    run.status = 'COMPLETED'
    run.completed_by = actor_id
    run.completed_at = utcnow()
    state.current_business_date = bd + timedelta(days=1)  # التقدم يوماً واحداً فقط
    state.last_run_id = run.id
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hotel', action='night_audit.run', entity='night_audit_runs',
          entity_id=run.id,
          after={'business_date': str(bd), 'nights': posted,
                 'revenue': str(revenue), 'new_business_date': str(bd + timedelta(days=1))},
          business_date=bd)
    return run


def _ooo_conflicts(db: Session, tenant_id: str, bd: date) -> list[dict]:
    """غرف معطلة متداخلة مع حجوزات قائمة = تنبيه أحمر (§5)."""
    out = []
    rooms = db.execute(
        select(m.Room).where(m.Room.tenant_id == tenant_id,
                             m.Room.hk_status.in_(BLOCKING_HK))).scalars().all()
    horizon = bd + timedelta(days=90)
    for room in rooms:
        hits = overlapping_reservations(db, tenant_id, room.id, bd, horizon)
        if hits:
            out.append({'room': room.room_no,
                        'reservations': _rsv_brief(hits)})
    return out


# ────────────────────────────────────────────────────────────────────
# الهوسكيبينج (ملف 03 §5)
# ────────────────────────────────────────────────────────────────────
def change_hk_status(db: Session, *, room: m.Room, new_status: str,
                     can_clean: bool, can_manage: bool, actor_id: str,
                     reason: str | None = None, ooo_from: date | None = None,
                     ooo_to: date | None = None) -> m.Room:
    pair = (room.hk_status, new_status)
    if pair in HK_CLEANING_TRANSITIONS and can_clean:
        pass
    elif pair in HK_MANAGE_TRANSITIONS and can_manage:
        pass
    else:
        err('HOTEL.HK_FORBIDDEN',
            f'الانتقال {room.hk_status} ← {new_status} غير مسموح لدورك')
    if new_status in BLOCKING_HK:
        if not reason:
            err('HOTEL.HK_REASON_REQUIRED', 'سبب التعطيل إلزامي')
        room.ooo_reason = reason
        room.ooo_from, room.ooo_to = ooo_from, ooo_to
        # تنبيه: حجوزات متعارضة مع مدى التعطيل
        if ooo_from and ooo_to:
            hits = overlapping_reservations(db, room.tenant_id, room.id,
                                            ooo_from, ooo_to)
            if hits:
                err('HOTEL.HK_OOO_CONFLICT',
                    f'يوجد {len(hits)} حجزاً متداخلاً مع مدى التعطيل — '
                    'انقلها أولاً أو عدّل المدى')
    else:
        if room.hk_status in BLOCKING_HK:
            pass  # خروج من التعطيل — السبب يبقى في السجل
        room.ooo_reason = None
        room.ooo_from = room.ooo_to = None
    old = room.hk_status
    room.hk_status = new_status
    db.flush()
    audit(db, tenant_id=room.tenant_id, actor_id=actor_id, actor_type='user',
          module='hotel', action='room.hk_change', entity='rooms',
          entity_id=room.id,
          after={'room': room.room_no, 'from': old, 'to': new_status,
                 'reason': reason})
    return room


# ────────────────────────────────────────────────────────────────────
# التقارير التشغيلية (ملف 03 §6) — من المحاسبة أولاً للاتساق
# ────────────────────────────────────────────────────────────────────
def occupancy_report(db: Session, tenant_id: str, d_from: date,
                     d_to: date) -> dict:
    """الإشغال وADR وRevPAR — الإيراد من قيود 4101 المرحلة فعلياً."""
    q_rev = (select(func.sum(m.JournalLine.credit_base),
                    func.count(m.JournalEntry.id.distinct()))
             .select_from(m.JournalLine)
             .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
             .join(m.Account, m.Account.id == m.JournalLine.account_id)
             .where(m.JournalLine.tenant_id == tenant_id,
                    m.Account.code == '4101',
                    m.JournalEntry.status.in_(['POSTED', 'REVERSED']),
                    m.JournalEntry.entry_date >= d_from,
                    m.JournalEntry.entry_date <= d_to))
    rev_rows = db.execute(q_rev)
    total_rev = Decimal('0')
    for s, _ in rev_rows:
        total_rev += D(s or 0)
    # ليالٍ مشغولة = أحداث ترحيل ليلة فعلية في الفترة
    nights = db.execute(
        select(func.count(m.JournalEntry.id)).where(
            m.JournalEntry.tenant_id == tenant_id,
            m.JournalEntry.source_type == 'ROOM_NIGHT',
            m.JournalEntry.status.in_(['POSTED', 'REVERSED']),
            m.JournalEntry.entry_date >= d_from,
            m.JournalEntry.entry_date <= d_to)).scalar_one()
    rooms_active = db.execute(
        select(func.count(m.Room.id)).where(m.Room.tenant_id == tenant_id,
                                            m.Room.is_active.is_(True))).scalar_one()
    days = (d_to - d_from).days + 1
    capacity_nights = rooms_active * days
    occ = D(nights) / capacity_nights if capacity_nights else Decimal('0')
    adr = total_rev / nights if nights else Decimal('0')
    revpar = total_rev / capacity_nights if capacity_nights else Decimal('0')
    return {'from': str(d_from), 'to': str(d_to), 'days': days,
            'rooms_active': rooms_active, 'capacity_nights': capacity_nights,
            'occupied_nights': nights, 'room_revenue': str(total_rev),
            'occupancy_pct': str((occ * 100).quantize(Decimal('0.01'))),
            'adr': str(adr.quantize(Decimal('0.01'))),
            'revpar': str(revpar.quantize(Decimal('0.01')))}


def pickup_report(db: Session, tenant_id: str) -> dict:
    """توقعات الإشغال 30/60/90 يوماً من الحجوزات القائمة (§6)."""
    bd = get_business_date(db, tenant_id)
    out = {}
    for horizon in (30, 60, 90):
        end = bd + timedelta(days=horizon)
        rows = db.execute(
            select(m.Reservation).where(
                m.Reservation.tenant_id == tenant_id,
                m.Reservation.status.in_(ACTIVE_RSV),
                m.Reservation.arrival_date < end,
                m.Reservation.departure_date > bd)).scalars().all()
        room_nights = Decimal('0')
        for r in rows:
            overlap_nights = (min(r.departure_date, end)
                              - max(r.arrival_date, bd)).days
            room_nights += max(0, overlap_nights)
        out[str(horizon)] = {'window_days': horizon,
                             'booked_room_nights': int(room_nights),
                             'reservations': len(rows)}
    return {'as_of': str(bd), 'horizons': out}


def deposits_aging(db: Session, tenant_id: str) -> list[dict]:
    """عربون معلق في 2110 بأعماره (§6) — طرف = حجز."""
    q = (select(m.JournalLine.party_id,
                func.min(m.JournalEntry.entry_date),
                func.sum(m.JournalLine.credit_base),
                func.sum(m.JournalLine.debit_base))
         .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
         .join(m.Account, m.Account.id == m.JournalLine.account_id)
         .where(m.JournalLine.tenant_id == tenant_id,
                m.Account.code == DEPOSIT_LEDGER,
                m.JournalEntry.status.in_(['POSTED', 'REVERSED']))
         .group_by(m.JournalLine.party_id))
    bd = get_business_date(db, tenant_id)
    out = []
    for party_id, first_d, tc, td in db.execute(q).all():
        bal = D(tc or 0) - D(td or 0)
        if bal == 0:
            continue
        age = (bd - first_d).days if first_d else 0
        res = db.get(m.Reservation, party_id)
        out.append({'reservation_id': party_id,
                    'conf': res.confirmation_no if res else '—',
                    'status': res.status if res else '—',
                    'since': str(first_d), 'age_days': age,
                    'balance': str(bal)})
    return sorted(out, key=lambda r: -r['age_days'])


def in_house_report(db: Session, tenant_id: str) -> list[dict]:
    """المقيمون الآن مع أرصدة الفواتير من الدفتر + علم High Balance."""
    bd = get_business_date(db, tenant_id)
    rows = db.execute(
        select(m.Reservation).where(
            m.Reservation.tenant_id == tenant_id,
            m.Reservation.status == 'CHECKED_IN',
            m.Reservation.arrival_date <= bd,
        )).scalars().all()
    out = []
    for r in rows:
        folio = db.execute(
            select(m.Folio).where(m.Folio.reservation_id == r.id,
                                  m.Folio.window == 1)).scalar_one_or_none()
        room = db.get(m.Room, r.room_id)
        guest = db.get(m.Guest, r.guest_id)
        bal = folio_balance(db, tenant_id, folio.id) if folio else Decimal('0')
        out.append({'reservation_id': r.id, 'conf': r.confirmation_no,
                    'room': room.room_no if room else '—',
                    'guest': guest.full_name if guest else '—',
                    'departure': str(r.departure_date),
                    'folio_id': folio.id if folio else None,
                    'balance': str(bal),
                    'high_balance': bool(folio and folio.credit_limit
                                         and bal > folio.credit_limit)})
    return out
