"""نقاط وحدة الفندق — ملف 12 (API_STRUCTURE) وملف 03:
غرف/حجوزات/تدقيق ليلي/فواتير/هوسكيبينج/تقارير تشغيلية.
قاعدة مركزية: لا أثراً مالياً خارج الخدمات في app/hotel.py (الملف 02 §6)."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import hotel as hs
from .. import models as m
from ..db import get_db
from ..deps import Principal, require_perm
from ..audit import audit
from ..posting import PostingError
from ..schemas_hotel import (CancelIn, ChargeIn, CheckInIn, CheckoutIn,
                             CompanionIn, CompanionPatch, CorporateIn,
                             DepositIn, DiscountIn, ExtraIn,
                             ExtraPatch, GuestIn, GuestPatch, HkChangeIn,
                             ModifyReservationIn, PaymentIn,
                             RateCalendarBulk, RatePlanIn, RatePlanPatch,
                             ReservationIn, RoomIn, RoomMoveIn, RoomPatch,
                             RoomTypeIn, RoomTypePatch, TransferCorpIn,
                             TripPatch, WalkInIn)
from ..security import (decrypt_pii, encrypt_pii, mask_id, new_uuid,
                        utcnow)

router = APIRouter(prefix='/api/hotel', tags=['hotel'])


# ── أدوات ──────────────────────────────────────────────
def _room_type_or_404(db, tid, code) -> m.RoomType:
    rt = db.execute(select(m.RoomType).where(
        m.RoomType.tenant_id == tid, m.RoomType.code == code,
        m.RoomType.is_active.is_(True))).scalar_one_or_none()
    if rt is None:
        raise HTTPException(404, {'error': {'code': 'HOTEL.UNKNOWN_ROOM_TYPE',
                                            'message_ar': f'نوع غرفة غير موجود: {code}'}})
    return rt


def _room_or_404(db, tid, room_no) -> m.Room:
    room = db.execute(select(m.Room).where(
        m.Room.tenant_id == tid, m.Room.room_no == room_no)).scalar_one_or_none()
    if room is None:
        raise HTTPException(404, {'error': {'code': 'HOTEL.UNKNOWN_ROOM',
                                            'message_ar': f'غرفة غير موجودة: {room_no}'}})
    return room


def _rsv_or_404(db, tid, rid) -> m.Reservation:
    r = db.get(m.Reservation, rid)
    if r is None or r.tenant_id != tid:
        raise HTTPException(404, {'error': {'code': 'HOTEL.UNKNOWN_RESERVATION',
                                            'message_ar': 'الحجز غير موجود'}})
    return r


def _rsv_out(db, r: m.Reservation, *, with_companions: bool = False) -> dict:
    room = db.get(m.Room, r.room_id) if r.room_id else None
    rt = db.get(m.RoomType, r.room_type_id)
    guest = db.get(m.Guest, r.guest_id)
    corp = db.get(m.Corporate, r.corporate_id) if r.corporate_id else None
    out = {'id': r.id, 'confirmation_no': r.confirmation_no,
           'status': r.status, 'source': r.source,
           'guest_name': guest.full_name if guest else '—',
           'guest_id_masked': mask_id(guest.id_number_enc) if guest else '',
           'corporate': corp.name if corp else None,
           'room_no': room.room_no if room else None,
           'room_type': rt.name_ar if rt else '—',
           'arrival_date': r.arrival_date, 'departure_date': r.departure_date,
           'nights': r.nights, 'adults': r.adults, 'children': r.children,
           'agreed_rate': str(r.agreed_rate), 'est_total': str(r.est_total),
           'checked_in_at': r.checked_in_at, 'checked_out_at': r.checked_out_at,
           'corporate_id': r.corporate_id,
           # بيانات الرحلة للمعلومية (0.14.0):
           'purpose': r.purpose, 'origin_gov': r.origin_gov,
           'origin_district': r.origin_district,
           'vehicle_note': r.vehicle_note, 'police_notes': r.police_notes,
           'deposit_balance': str(hs.deposit_balance(db, r.tenant_id, r.id))}
    if with_companions:
        comps = db.execute(select(m.ReservationCompanion).where(
            m.ReservationCompanion.reservation_id == r.id).order_by(
            m.ReservationCompanion.sort_order,
            m.ReservationCompanion.created_at)).scalars().all()
        out['companions'] = [_companion_out(c) for c in comps]
    return out


def _companion_out(c: m.ReservationCompanion) -> dict:
    return {'id': c.id, 'full_name': c.full_name, 'id_type': c.id_type,
            'id_masked': mask_id(c.id_number_enc),
            'id_issue_place': c.id_issue_place,
            'id_issue_date': c.id_issue_date, 'phone': c.phone,
            'origin_gov': c.origin_gov, 'origin_district': c.origin_district,
            'has_id': bool(c.id_number_enc), 'sort_order': c.sort_order}


# ── الغرفة الراك (لوحة الطوابق) وأنواع الغرف ─────────────────────────
@router.get('/rooms')
def list_rooms(db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('frontdesk.view'))):
    bd = hs.get_business_date(db, pr.tenant_id)
    rooms = db.execute(
        select(m.Room).where(m.Room.tenant_id == pr.tenant_id)
        .order_by(m.Room.room_no)).scalars().all()
    occupied = {s.room_id: s.reservation_id for s in db.execute(
        select(m.ReservationStay)
        .where(m.ReservationStay.from_date <= bd,
               m.ReservationStay.to_date > bd)).scalars().all()
        if db.get(m.Reservation, s.reservation_id).status == 'CHECKED_IN'}
    rsv_by_room = {r.room_id: r for r in db.execute(
        select(m.Reservation).where(
            m.Reservation.tenant_id == pr.tenant_id,
            m.Reservation.status.in_(hs.ACTIVE_RSV),
            m.Reservation.arrival_date <= bd,
            m.Reservation.departure_date > bd)).scalars().all()}
    # الأجنحة المركبة (ADR-0035): أبناء كل جناح + حالة حجب مشتقة اليوم
    children_map: dict[str, list] = {}
    for room in rooms:
        pid = getattr(room, 'parent_room_id', None)
        if pid:
            children_map.setdefault(pid, []).append(room.room_no)
    room_by_id = {r.id: r for r in rooms}
    horizon = bd + timedelta(days=1)   # حجب الليلة الحالية
    out = []
    for room in rooms:
        rt = db.get(m.RoomType, room.room_type_id)
        rsv = rsv_by_room.get(room.id)
        parent = room_by_id.get(getattr(room, 'parent_room_id', '') or '')
        out.append({'id': room.id, 'room_no': room.room_no, 'floor': room.floor,
                    'type': rt.name_ar if rt else '—', 'type_code': rt.code if rt else '',
                    'base_rate': str(rt.base_rate) if rt else '0',
                    'hk_status': room.hk_status,
                    'occupied': room.id in occupied,
                    'ooo_reason': room.ooo_reason,
                    'ooo_from': room.ooo_from, 'ooo_to': room.ooo_to,
                    'current_rsv': rsv.id if rsv else None,
                    'blocked_for_sale': hs.ooo_blocks(db, room, bd, bd),
                    'kind': getattr(room, 'kind', 'STANDARD') or 'STANDARD',
                    'is_suite': hs.is_suite(room),
                    'parent_room_no': parent.room_no if parent else None,
                    'components': children_map.get(room.id, []),
                    'is_active': room.is_active,
                    'features': room.features or [],
                    'suite_note': hs.suite_block_reason(
                        db, pr.tenant_id, room, bd, horizon)})
    return {'business_date': bd, 'items': out}


@router.post('/rooms', status_code=201)
def create_room(body: RoomIn, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('rooms.manage'))):
    rt = _room_type_or_404(db, pr.tenant_id, body.room_type_code)
    branch = db.execute(select(m.Branch).where(
        m.Branch.tenant_id == pr.tenant_id)).scalar_one()
    dup = db.execute(select(m.Room).where(
        m.Room.tenant_id == pr.tenant_id, m.Room.branch_id == branch.id,
        m.Room.room_no == body.room_no)).scalar_one_or_none()
    if dup:
        raise PostingError('HOTEL.ROOM_EXISTS', f'الغرفة {body.room_no} موجودة')
    parent = None
    if body.parent_room_no:
        parent = _room_or_404(db, pr.tenant_id, body.parent_room_no)
    if body.kind == hs.ROOM_KIND_SUITE and body.parent_room_no:
        raise PostingError('HOTEL.NESTED_SUITE',
                           'الجناح المركب لا يكون ابناً لجناح آخر')
    room = m.Room(id=new_uuid(), tenant_id=pr.tenant_id, branch_id=branch.id,
                  room_no=body.room_no, floor=body.floor,
                  room_type_id=rt.id, features=body.features,
                  kind=body.kind,
                  parent_room_id=parent.id if parent else None)
    if parent is not None:
        hs.assert_linkable(db, pr.tenant_id, room, parent)
    db.add(room)
    db.flush()
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='room.create', entity='rooms',
          entity_id=room.id,
          after={'room_no': room.room_no, 'kind': room.kind,
                 'type': rt.code, 'floor': room.floor,
                 'parent': parent.room_no if parent else None})
    db.commit()
    return {'id': room.id, 'room_no': room.room_no, 'kind': room.kind}


@router.get('/room-types')
def list_room_types(db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('frontdesk.view'))):
    rows = db.execute(select(m.RoomType).where(
        m.RoomType.tenant_id == pr.tenant_id).order_by(
        m.RoomType.display_order)).scalars().all()
    return [{'id': r.id, 'code': r.code, 'name_ar': r.name_ar,
             'name_en': r.name_en,
             'capacity_adults': r.capacity_adults,
             'capacity_children': r.capacity_children, 'beds': r.beds,
             'amenities': r.amenities, 'display_order': r.display_order,
             'base_rate': str(r.base_rate), 'is_active': r.is_active}
            for r in rows]


@router.get('/extras')
def list_extras(all: bool = False, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('frontdesk.view'))):
    q = select(m.Extra).where(m.Extra.tenant_id == pr.tenant_id)
    if not all:
        q = q.where(m.Extra.is_active.is_(True))
    rows = db.execute(q).scalars().all()
    return [{'id': e.id, 'code': e.code, 'name_ar': e.name_ar,
             'price': str(e.price), 'is_active': e.is_active,
             'revenue_account_code': e.revenue_account_code} for e in rows]


# ── إدارة الغرف: تعديل/ربط/فك/تعطيل (rooms.manage) ──────────────────
@router.patch('/rooms/{room_id}')
def update_room(room_id: str, body: RoomPatch,
                db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('rooms.manage'))):
    room = db.get(m.Room, room_id)
    if room is None or room.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'HOTEL.UNKNOWN_ROOM',
                                            'message_ar': 'الغرفة غير موجودة'}})
    before = {'room_no': room.room_no, 'floor': room.floor,
              'room_type_id': room.room_type_id, 'kind': room.kind,
              'parent_room_id': room.parent_room_id,
              'is_active': room.is_active, 'features': room.features}
    if body.room_no and body.room_no != room.room_no:
        dup = db.execute(select(m.Room).where(
            m.Room.tenant_id == pr.tenant_id,
            m.Room.branch_id == room.branch_id,
            m.Room.room_no == body.room_no)).scalar_one_or_none()
        if dup:
            raise PostingError('HOTEL.ROOM_EXISTS',
                               f'الغرفة {body.room_no} موجودة')
        room.room_no = body.room_no
    if body.floor is not None:
        room.floor = body.floor
    if body.room_type_code:
        rt = _room_type_or_404(db, pr.tenant_id, body.room_type_code)
        room.room_type_id = rt.id
    if body.features is not None:
        room.features = body.features
    if body.kind is not None and body.kind != room.kind:
        if body.kind == hs.ROOM_KIND_STANDARD and \
                hs.suite_children(db, room.id):
            raise PostingError('HOTEL.SUITE_HAS_CHILDREN',
                               'فكّ ربط أبناء الجناح قبل تحويله لغرفة عادية')
        if body.kind == hs.ROOM_KIND_SUITE and room.parent_room_id:
            raise PostingError('HOTEL.NESTED_SUITE',
                               'فكّ ربط الغرفة بجناحها قبل جعلها جناحاً')
        room.kind = body.kind
    if body.set_parent:
        new_no = (body.parent_room_no or '').strip()
        old_pid = room.parent_room_id
        if not new_no:
            if old_pid:
                hs.assert_unlinkable(db, pr.tenant_id, room)
                room.parent_room_id = None
        else:
            parent = _room_or_404(db, pr.tenant_id, new_no)
            if old_pid and old_pid != parent.id:
                hs.assert_unlinkable(db, pr.tenant_id, room)  # فك ضمني
            hs.assert_linkable(db, pr.tenant_id, room, parent)
            room.parent_room_id = parent.id
    if body.is_active is not None and body.is_active != room.is_active:
        if not body.is_active:
            hs.assert_unlinkable(db, pr.tenant_id, room)
            bd = hs.get_business_date(db, pr.tenant_id)
            future = hs.overlapping_reservations(
                db, pr.tenant_id, room.id, bd, bd + timedelta(days=3660))
            if future:
                raise PostingError(
                    'HOTEL.ROOM_HAS_BOOKINGS',
                    f'لا يمكن تعطيل الغرفة — عليها حجز نشط '
                    f'{future[0].confirmation_no}')
        room.is_active = body.is_active
    db.flush()
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='room.update', entity='rooms',
          entity_id=room.id,
          before=before,
          after={'room_no': room.room_no, 'floor': room.floor,
                 'room_type_id': room.room_type_id, 'kind': room.kind,
                 'parent_room_id': room.parent_room_id,
                 'is_active': room.is_active, 'features': room.features})
    db.commit()
    parent = db.get(m.Room, room.parent_room_id) if room.parent_room_id else None
    return {'id': room.id, 'room_no': room.room_no, 'kind': room.kind,
            'is_active': room.is_active,
            'parent_room_no': parent.room_no if parent else None}


@router.get('/rooms/{room_id}/components')
def room_components(room_id: str, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('frontdesk.view'))):
    room = db.get(m.Room, room_id)
    if room is None or room.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'HOTEL.UNKNOWN_ROOM',
                                            'message_ar': 'الغرفة غير موجودة'}})
    children = hs.suite_children(db, room.id)
    return {'suite': room.room_no, 'components': [
        {'id': c.id, 'room_no': c.room_no, 'hk_status': c.hk_status,
         'is_active': c.is_active} for c in children]}


# ── أنواع الغرف: إنشاء/تعديل (السعر الأساسي لليلة) ────────────────────
@router.post('/room-types', status_code=201)
def create_room_type(body: RoomTypeIn, db: Session = Depends(get_db),
                     pr: Principal = Depends(require_perm('rooms.manage'))):
    dup = db.execute(select(m.RoomType).where(
        m.RoomType.tenant_id == pr.tenant_id,
        m.RoomType.code == body.code)).scalar_one_or_none()
    if dup:
        raise PostingError('HOTEL.RTYPE_EXISTS', f'النوع {body.code} موجود')
    rt = m.RoomType(id=new_uuid(), tenant_id=pr.tenant_id, code=body.code,
                    name_ar=body.name_ar, name_en=body.name_en,
                    capacity_adults=body.capacity_adults,
                    capacity_children=body.capacity_children,
                    beds=body.beds, amenities=body.amenities,
                    base_rate=body.base_rate,
                    display_order=body.display_order)
    db.add(rt)
    db.flush()
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='roomtype.create', entity='room_types',
          entity_id=rt.id,
          after={'code': body.code, 'name_ar': body.name_ar,
                 'base_rate': str(body.base_rate)})
    db.commit()
    return {'id': rt.id, 'code': rt.code}


@router.patch('/room-types/{rt_id}')
def update_room_type(rt_id: str, body: RoomTypePatch,
                     db: Session = Depends(get_db),
                     pr: Principal = Depends(require_perm('rooms.manage'))):
    rt = db.get(m.RoomType, rt_id)
    if rt is None or rt.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'HOTEL.UNKNOWN_ROOM_TYPE',
                                            'message_ar': 'نوع الغرفة غير موجود'}})
    before = {'name_ar': rt.name_ar, 'name_en': rt.name_en,
              'base_rate': str(rt.base_rate), 'is_active': rt.is_active,
              'capacity_adults': rt.capacity_adults,
              'capacity_children': rt.capacity_children, 'beds': rt.beds,
              'amenities': rt.amenities, 'display_order': rt.display_order}
    for f in ('name_ar', 'name_en', 'capacity_adults', 'capacity_children',
              'beds', 'amenities', 'base_rate', 'display_order', 'is_active'):
        v = getattr(body, f)
        if v is not None:
            setattr(rt, f, v)
    db.flush()
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='roomtype.update', entity='room_types',
          entity_id=rt.id, before=before,
          after={'name_ar': rt.name_ar, 'base_rate': str(rt.base_rate),
                 'is_active': rt.is_active, 'beds': rt.beds,
                 'capacity_adults': rt.capacity_adults,
                 'capacity_children': rt.capacity_children,
                 'amenities': rt.amenities, 'display_order': rt.display_order,
                 'name_en': rt.name_en})
    db.commit()
    return {'id': rt.id, 'code': rt.code, 'base_rate': str(rt.base_rate)}


# ── خطط الأسعار (03 §1.3) ────────────────────────────────────────────
@router.get('/rate-plans')
def list_rate_plans(db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('frontdesk.view'))):
    rows = db.execute(select(m.RatePlan).where(
        m.RatePlan.tenant_id == pr.tenant_id).order_by(
        m.RatePlan.code)).scalars().all()
    return [{'id': p.id, 'code': p.code, 'name_ar': p.name_ar,
             'ref_rate': str(p.ref_rate) if p.ref_rate is not None else None,
             'includes_breakfast': p.includes_breakfast,
             'cancel_policy': p.cancel_policy, 'min_nights': p.min_nights,
             'for_corporate': p.for_corporate,
             'tax_inclusive': p.tax_inclusive,
             'meals_included': p.meals_included,
             'is_active': p.is_active} for p in rows]


@router.post('/rate-plans', status_code=201)
def create_rate_plan(body: RatePlanIn, db: Session = Depends(get_db),
                     pr: Principal = Depends(require_perm('rates.manage'))):
    dup = db.execute(select(m.RatePlan).where(
        m.RatePlan.tenant_id == pr.tenant_id,
        m.RatePlan.code == body.code)).scalar_one_or_none()
    if dup:
        raise PostingError('HOTEL.RPLAN_EXISTS', f'الخطة {body.code} موجودة')
    p = m.RatePlan(id=new_uuid(), tenant_id=pr.tenant_id, code=body.code,
                   name_ar=body.name_ar, ref_rate=body.ref_rate,
                   includes_breakfast=body.includes_breakfast,
                   cancel_policy=body.cancel_policy,
                   min_nights=body.min_nights,
                   for_corporate=body.for_corporate,
                   tax_inclusive=body.tax_inclusive,
                   meals_included=body.meals_included)
    db.add(p)
    db.flush()
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='rateplan.create', entity='rate_plans',
          entity_id=p.id,
          after={'code': body.code, 'name_ar': body.name_ar,
                 'ref_rate': str(body.ref_rate)})
    db.commit()
    return {'id': p.id, 'code': p.code}


@router.patch('/rate-plans/{plan_id}')
def update_rate_plan(plan_id: str, body: RatePlanPatch,
                     db: Session = Depends(get_db),
                     pr: Principal = Depends(require_perm('rates.manage'))):
    p = db.get(m.RatePlan, plan_id)
    if p is None or p.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'HOTEL.UNKNOWN_RATE_PLAN',
                                            'message_ar': 'خطة سعر غير موجودة'}})
    before = {'name_ar': p.name_ar, 'ref_rate': str(p.ref_rate),
              'cancel_policy': p.cancel_policy, 'min_nights': p.min_nights,
              'is_active': p.is_active}
    for f in ('name_ar', 'ref_rate', 'includes_breakfast', 'cancel_policy',
              'min_nights', 'for_corporate', 'tax_inclusive',
              'meals_included', 'is_active'):
        v = getattr(body, f)
        if v is not None:
            setattr(p, f, v)
    db.flush()
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='rateplan.update', entity='rate_plans',
          entity_id=p.id, before=before,
          after={'name_ar': p.name_ar, 'ref_rate': str(p.ref_rate),
                 'cancel_policy': p.cancel_policy, 'min_nights': p.min_nights,
                 'is_active': p.is_active})
    db.commit()
    return {'id': p.id, 'code': p.code}


# ── تقويم الأسعار (03 §1.4): موسم/نهاية أسبوع/مناسبة ──────────────────
@router.get('/rate-calendar')
def list_rate_calendar(room_type: str, date_from: date, date_to: date,
                       rate_plan: str | None = None,
                       db: Session = Depends(get_db),
                       pr: Principal = Depends(require_perm('frontdesk.view'))):
    rt = _room_type_or_404(db, pr.tenant_id, room_type)
    q = select(m.RateCalendar).where(
        m.RateCalendar.tenant_id == pr.tenant_id,
        m.RateCalendar.room_type_id == rt.id,
        m.RateCalendar.day >= date_from,
        m.RateCalendar.day <= date_to).order_by(m.RateCalendar.day)
    if rate_plan:
        plan = db.execute(select(m.RatePlan).where(
            m.RatePlan.tenant_id == pr.tenant_id,
            m.RatePlan.code == rate_plan)).scalar_one_or_none()
        q = q.where(m.RateCalendar.rate_plan_id ==
                    (plan.id if plan else 'none'))
    rows = db.execute(q).scalars().all()
    plans = {p.id: p.code for p in db.execute(
        select(m.RatePlan).where(
            m.RatePlan.tenant_id == pr.tenant_id)).scalars().all()}
    return [{'id': r.id, 'day': str(r.day), 'price': str(r.price),
             'day_type': r.day_type,
             'rate_plan': plans.get(r.rate_plan_id) if r.rate_plan_id
             else None} for r in rows]


@router.post('/rate-calendar/bulk', status_code=201)
def set_rate_calendar(body: RateCalendarBulk,
                      db: Session = Depends(get_db),
                      pr: Principal = Depends(require_perm('rates.manage'))):
    if body.date_to < body.date_from:
        raise PostingError('HOTEL.BAD_DATES', 'النهاية قبل البداية')
    days = (body.date_to - body.date_from).days + 1
    if days > 92:
        raise PostingError('HOTEL.RANGE_TOO_LONG',
                           'المدى الأقصى للتعبئة 92 يوماً')
    rt = _room_type_or_404(db, pr.tenant_id, body.room_type_code)
    plan_id = None
    if (body.rate_plan_code or '').strip():
        plan = db.execute(select(m.RatePlan).where(
            m.RatePlan.tenant_id == pr.tenant_id,
            m.RatePlan.code == body.rate_plan_code)).scalar_one_or_none()
        if plan is None:
            raise PostingError('HOTEL.UNKNOWN_RATE_PLAN',
                               f'خطة سعر غير موجودة: {body.rate_plan_code}')
        plan_id = plan.id
    created = updated = 0
    for i in range(days):
        day = body.date_from + timedelta(days=i)
        q = select(m.RateCalendar).where(
            m.RateCalendar.tenant_id == pr.tenant_id,
            m.RateCalendar.room_type_id == rt.id,
            m.RateCalendar.day == day)
        q = q.where(m.RateCalendar.rate_plan_id.is_(None) if plan_id is None
                    else m.RateCalendar.rate_plan_id == plan_id)
        row = db.execute(q).scalar_one_or_none()
        if row:
            row.price = body.price
            row.day_type = body.day_type
            updated += 1
        else:
            db.add(m.RateCalendar(id=new_uuid(), tenant_id=pr.tenant_id,
                                  room_type_id=rt.id, rate_plan_id=plan_id,
                                  day=day, price=body.price,
                                  day_type=body.day_type))
            created += 1
    db.flush()
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='ratecalendar.set', entity='rate_calendar',
          entity_id=rt.id,
          after={'room_type': rt.code,
                 'rate_plan': body.rate_plan_code or None,
                 'from': str(body.date_from), 'to': str(body.date_to),
                 'price': str(body.price), 'day_type': body.day_type,
                 'created': created, 'updated': updated})
    db.commit()
    return {'days': days, 'created': created, 'updated': updated}


@router.delete('/rate-calendar/{entry_id}')
def delete_rate_calendar(entry_id: str, db: Session = Depends(get_db),
                         pr: Principal = Depends(require_perm('rates.manage'))):
    row = db.get(m.RateCalendar, entry_id)
    if row is None or row.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'HOTEL.UNKNOWN_CAL_ENTRY',
                                            'message_ar': 'قيد تقويم غير موجود'}})
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='ratecalendar.delete',
          entity='rate_calendar', entity_id=row.id,
          before={'day': str(row.day), 'price': str(row.price)})
    db.delete(row)
    db.commit()
    return {'deleted': True}


# ── الخدمات الإضافية: إنشاء/تعديل (rates.manage) ───────────────────────
@router.post('/extras', status_code=201)
def create_extra(body: ExtraIn, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('extras.manage'))):
    dup = db.execute(select(m.Extra).where(
        m.Extra.tenant_id == pr.tenant_id,
        m.Extra.code == body.code)).scalar_one_or_none()
    if dup:
        raise PostingError('HOTEL.EXTRA_EXISTS', f'الخدمة {body.code} موجودة')
    e = m.Extra(id=new_uuid(), tenant_id=pr.tenant_id, code=body.code,
                name_ar=body.name_ar, price=body.price,
                revenue_account_code=body.revenue_account_code)
    db.add(e)
    db.flush()
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='extra.create', entity='extras',
          entity_id=e.id, after={'code': body.code, 'price': str(body.price)})
    db.commit()
    return {'id': e.id, 'code': e.code}


@router.patch('/extras/{extra_id}')
def update_extra(extra_id: str, body: ExtraPatch,
                 db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('extras.manage'))):
    e = db.get(m.Extra, extra_id)
    if e is None or e.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'HOTEL.UNKNOWN_EXTRA',
                                            'message_ar': 'الخدمة غير موجودة'}})
    before = {'name_ar': e.name_ar, 'price': str(e.price),
              'revenue_account_code': e.revenue_account_code,
              'is_active': e.is_active}
    for f in ('name_ar', 'price', 'revenue_account_code', 'is_active'):
        v = getattr(body, f)
        if v is not None:
            setattr(e, f, v)
    db.flush()
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='extra.update', entity='extras',
          entity_id=e.id, before=before,
          after={'name_ar': e.name_ar, 'price': str(e.price),
                 'revenue_account_code': e.revenue_account_code,
                 'is_active': e.is_active})
    db.commit()
    return {'id': e.id, 'code': e.code, 'price': str(e.price)}


# ── الهوسكيبينج ─────────────────────────────────────────
@router.post('/rooms/{room_id}/hk')
def change_hk(room_id: str, body: HkChangeIn,
              db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('hk.cleaning'))):
    room = db.get(m.Room, room_id)
    if room is None or room.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'HOTEL.UNKNOWN_ROOM',
                                            'message_ar': 'الغرفة غير موجودة'}})
    hs.change_hk_status(db, room=room, new_status=body.new_status,
                        can_clean=True, can_manage=pr.has('hk.manage'),
                        actor_id=pr.id, reason=body.reason,
                        ooo_from=body.ooo_from, ooo_to=body.ooo_to)
    db.commit()
    return {'room_no': room.room_no, 'hk_status': room.hk_status}


# ── الضيوف والشركات ────────────────────────────────────
@router.get('/guests')
def list_guests(q: str = '', db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('guests.view'))):
    rows = db.execute(select(m.Guest).where(
        m.Guest.tenant_id == pr.tenant_id).order_by(
        m.Guest.full_name)).scalars().all()
    if q:
        rows = [g for g in rows if q in g.full_name or q in g.phone]
    return [_guest_out(g) for g in rows]


def _guest_out(g: m.Guest) -> dict:
    return {'id': g.id, 'full_name': g.full_name, 'phone': g.phone,
            'id_masked': mask_id(g.id_number_enc), 'id_type': g.id_type,
            'id_issue_place': g.id_issue_place,
            'id_issue_date': g.id_issue_date,
            'nationality': g.nationality, 'vip': g.vip,
            'blacklist': g.blacklist, 'has_id': bool(g.id_number_enc)}


@router.post('/guests', status_code=201)
def create_guest(body: GuestIn, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('guests.manage'))):
    g = m.Guest(id=new_uuid(), tenant_id=pr.tenant_id,
                full_name=body.full_name, phone=body.phone,
                id_number_enc=encrypt_pii(body.id_number),
                id_type=body.id_type, id_issue_place=body.id_issue_place,
                id_issue_date=body.id_issue_date,
                nationality=body.nationality, vip=body.vip,
                notes=body.notes, created_at=utcnow())
    db.add(g)
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='guest.create', entity='guests',
          entity_id=g.id, after={'name': g.full_name})
    db.commit()
    return _guest_out(g)


@router.patch('/guests/{gid}')
def update_guest(gid: str, body: GuestPatch, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('guests.manage'))):
    """تحديث ملف النزيل — منها حقول المعلومية (نوع الهوية وإصدارها)."""
    g = db.get(m.Guest, gid)
    if not g or g.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'GEN.NOT_FOUND',
                                            'message_ar': 'نزيل غير موجود'}})
    before = {'name': g.full_name, 'id_type': g.id_type}
    for f in ('full_name', 'phone', 'nationality', 'vip', 'blacklist',
              'notes', 'id_type', 'id_issue_place', 'id_issue_date'):
        v = getattr(body, f)
        if v is not None:
            setattr(g, f, v)
    if body.id_number is not None:
        g.id_number_enc = encrypt_pii(body.id_number)
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='guest.update', entity='guests',
          entity_id=g.id, before=before,
          after={'name': g.full_name, 'id_type': g.id_type})
    db.commit()
    return _guest_out(g)


@router.get('/corporates')
def list_corporates(db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('corporates.view'))):
    rows = db.execute(select(m.Corporate).where(
        m.Corporate.tenant_id == pr.tenant_id)).scalars().all()
    return [{'id': c.id, 'name': c.name, 'contact_person': c.contact_person,
             'phone': c.phone, 'credit_limit': str(c.credit_limit) if c.credit_limit else None,
             'discount_pct': str(c.discount_pct),
             'settlement_period': c.settlement_period} for c in rows]


@router.post('/corporates', status_code=201)
def create_corporate(body: CorporateIn, db: Session = Depends(get_db),
                     pr: Principal = Depends(require_perm('corporates.manage'))):
    from ..security import new_uuid
    c = m.Corporate(id=new_uuid(), tenant_id=pr.tenant_id, name=body.name,
                    contact_person=body.contact_person, phone=body.phone,
                    credit_limit=body.credit_limit,
                    discount_pct=body.discount_pct)
    db.add(c)
    db.commit()
    return {'id': c.id, 'name': c.name}


# ── الحجوزات ────────────────────────────────────────────
@router.get('/availability')
def availability(room_type: str, date_from: date, date_to: date,
                 db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('frontdesk.view'))):
    rt = _room_type_or_404(db, pr.tenant_id, room_type)
    branch = db.execute(select(m.Branch).where(
        m.Branch.tenant_id == pr.tenant_id)).scalar_one()
    free = hs.available_rooms(db, pr.tenant_id, branch.id, rt.id,
                              date_from, date_to)
    nights = (date_to - date_from).days
    priced = hs.price_stay(db, pr.tenant_id, rt.id, None, date_from, date_to)
    return {'room_type': rt.code, 'available_rooms': [r.room_no for r in free],
            'count': len(free), 'nights': nights,
            'prices': [{'date': str(p['date']), 'rate': str(p['rate']),
                        'origin': p['origin']} for p in priced],
            'total': str(sum(p['rate'] for p in priced))}


@router.get('/reservations')
def list_reservations(status: str | None = None, q: str = '',
                      arrivals_on: date | None = None,
                      departures_on: date | None = None,
                      db: Session = Depends(get_db),
                      pr: Principal = Depends(require_perm('reservations.view'))):
    sq = select(m.Reservation).where(m.Reservation.tenant_id == pr.tenant_id)
    if status:
        sq = sq.where(m.Reservation.status == status)
    if arrivals_on:
        sq = sq.where(m.Reservation.arrival_date == arrivals_on)
    if departures_on:
        sq = sq.where(m.Reservation.departure_date == departures_on)
    rows = db.execute(sq.order_by(m.Reservation.created_at.desc())).scalars().all()
    items = [_rsv_out(db, r) for r in rows]
    if q:
        items = [x for x in items if q in x['guest_name']
                 or q in x['confirmation_no'] or (x['room_no'] or '') == q]
    return {'items': items, 'total': len(items)}


@router.post('/reservations', status_code=201)
def create_reservation(body: ReservationIn, db: Session = Depends(get_db),
                       pr: Principal = Depends(require_perm('reservations.create'))):
    rt = _room_type_or_404(db, pr.tenant_id, body.room_type_code)
    branch = db.execute(select(m.Branch).where(
        m.Branch.tenant_id == pr.tenant_id)).scalar_one()
    plan = None
    if body.rate_plan_code:
        plan = db.execute(select(m.RatePlan).where(
            m.RatePlan.tenant_id == pr.tenant_id,
            m.RatePlan.code == body.rate_plan_code)).scalar_one_or_none()
        if plan is None:
            raise PostingError('HOTEL.UNKNOWN_PLAN', 'خطة سعر غير معروفة')
    room = _room_or_404(db, pr.tenant_id, body.room_no) if body.room_no else None
    res = hs.create_reservation(
        db, tenant_id=pr.tenant_id, branch_id=branch.id,
        guest_id=body.guest_id, room_type_id=rt.id,
        arrival=body.arrival_date, departure=body.departure_date,
        actor_id=pr.id, corporate_id=body.corporate_id,
        rate_plan_id=plan.id if plan else None,
        room_id=room.id if room else None, adults=body.adults,
        children=body.children, source=body.source,
        rate_override=body.rate_override,
        trip={'purpose': body.purpose, 'origin_gov': body.origin_gov,
              'origin_district': body.origin_district,
              'vehicle_note': body.vehicle_note,
              'police_notes': body.police_notes})
    db.commit()
    return _rsv_out(db, res)


@router.get('/reservations/{rid}')
def get_reservation(rid: str, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('reservations.view'))):
    r = _rsv_or_404(db, pr.tenant_id, rid)
    out = _rsv_out(db, r, with_companions=True)
    out['night_rates'] = [
        {'date': str(nr.stay_date), 'rate': str(nr.rate),
         'origin': nr.rate_origin} for nr in db.execute(
            select(m.ReservationNightRate).where(
                m.ReservationNightRate.reservation_id == r.id)
            .order_by(m.ReservationNightRate.stay_date)).scalars().all()]
    folios = db.execute(select(m.Folio).where(
        m.Folio.reservation_id == r.id).order_by(m.Folio.window)).scalars().all()
    out['folios'] = [{'id': f.id, 'window': f.window, 'type': f.type,
                      'status': f.status,
                      'credit_limit': str(f.credit_limit) if f.credit_limit else None,
                      'balance': str(hs.folio_balance(db, r.tenant_id, f.id))}
                     for f in folios]
    return out


@router.post('/reservations/{rid}/modify')
def modify_reservation(rid: str, body: ModifyReservationIn,
                       db: Session = Depends(get_db),
                       pr: Principal = Depends(require_perm('reservations.modify'))):
    r = _rsv_or_404(db, pr.tenant_id, rid)
    room = _room_or_404(db, pr.tenant_id, body.new_room_no) if body.new_room_no else None
    out = hs.modify_reservation(db, res=r, actor_id=pr.id,
                                new_arrival=body.new_arrival,
                                new_departure=body.new_departure,
                                new_room_id=room.id if room else None)
    db.commit()
    return out


# ── بيانات الرحلة والمرافقون (المعلومية — 0.14.0) ─────────────────
@router.patch('/reservations/{rid}/trip')
def update_trip(rid: str, body: TripPatch, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('reservations.modify'))):
    """الغرض من القدوم / الجهة / المركبة / ملاحظات المعلومية — بلا أثر مالي."""
    r = _rsv_or_404(db, pr.tenant_id, rid)
    before = {f: getattr(r, f) for f in
              ('purpose', 'origin_gov', 'origin_district',
               'vehicle_note', 'police_notes')}
    for f in before:
        v = getattr(body, f)
        if v is not None:
            setattr(r, f, v)
    if getattr(r, 'version', None) is not None:
        r.version += 1
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='reservation.trip_update',
          entity='reservations', entity_id=r.id, before=before,
          after={f: getattr(r, f) for f in before})
    db.commit()
    return _rsv_out(db, r)


@router.post('/reservations/{rid}/companions', status_code=201)
def add_companion(rid: str, body: CompanionIn, db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('reservations.modify'))):
    """مرافق جديد على الحجز — صف مستقل في المعلومية ببيانات هويته."""
    r = _rsv_or_404(db, pr.tenant_id, rid)
    if r.status in ('CANCELLED', 'NO_SHOW'):
        raise HTTPException(409, {'error': {
            'code': 'HOTEL.RSV_CLOSED',
            'message_ar': 'لا يضاف مرافق لحجز ملغى أو عدم حضور'}})
    n = db.execute(select(func.count(m.ReservationCompanion.id)).where(
        m.ReservationCompanion.reservation_id == r.id)).scalar_one()
    c = m.ReservationCompanion(
        id=new_uuid(), tenant_id=pr.tenant_id, reservation_id=r.id,
        full_name=body.full_name, id_type=body.id_type,
        id_number_enc=encrypt_pii(body.id_number),
        id_issue_place=body.id_issue_place, id_issue_date=body.id_issue_date,
        phone=body.phone, origin_gov=body.origin_gov,
        origin_district=body.origin_district,
        sort_order=n + 1, created_at=utcnow())
    db.add(c)
    db.flush()
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='companion.create',
          entity='reservation_companions', entity_id=c.id,
          after={'name': c.full_name, 'reservation': r.confirmation_no})
    db.commit()
    return _companion_out(c)


@router.patch('/companions/{cid}')
def update_companion(cid: str, body: CompanionPatch,
                     db: Session = Depends(get_db),
                     pr: Principal = Depends(require_perm('reservations.modify'))):
    c = db.get(m.ReservationCompanion, cid)
    if not c or c.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'GEN.NOT_FOUND',
                                            'message_ar': 'مرافق غير موجود'}})
    for f in ('full_name', 'id_type', 'id_issue_place', 'id_issue_date',
              'phone', 'origin_gov', 'origin_district'):
        v = getattr(body, f)
        if v is not None:
            setattr(c, f, v)
    if body.id_number is not None:
        c.id_number_enc = encrypt_pii(body.id_number)
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='companion.update',
          entity='reservation_companions', entity_id=c.id,
          after={'name': c.full_name})
    db.commit()
    return _companion_out(c)


@router.delete('/companions/{cid}')
def delete_companion(cid: str, db: Session = Depends(get_db),
                     pr: Principal = Depends(require_perm('reservations.modify'))):
    """حذف مرافق (خطأ إدخال) — الأرشيف المعلومة المرسلة سابقاً لا يتأثر أبداً."""
    c = db.get(m.ReservationCompanion, cid)
    if not c or c.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'GEN.NOT_FOUND',
                                            'message_ar': 'مرافق غير موجود'}})
    name = c.full_name
    db.delete(c)
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='companion.delete',
          entity='reservation_companions', entity_id=cid,
          after={'name': name})
    db.commit()
    return {'deleted': True}


@router.post('/reservations/{rid}/deposit', status_code=201)
def add_deposit(rid: str, body: DepositIn, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('folio.pay'))):
    r = _rsv_or_404(db, pr.tenant_id, rid)
    je = hs.add_deposit(db, res=r, amount=body.amount, actor_id=pr.id,
                        method=body.method)
    db.commit()
    return {'entry_no': je.entry_no,
            'deposit_balance': str(hs.deposit_balance(db, pr.tenant_id, r.id))}


@router.post('/reservations/{rid}/cancel')
def cancel_reservation(rid: str, body: CancelIn,
                       db: Session = Depends(get_db),
                       pr: Principal = Depends(require_perm('reservations.cancel'))):
    r = _rsv_or_404(db, pr.tenant_id, rid)
    out = hs.cancel_reservation(db, res=r, reason=body.reason,
                                actor_id=pr.id, fee=body.fee,
                                refund=body.refund)
    db.commit()
    return out


@router.post('/reservations/{rid}/no-show')
def no_show(rid: str, db: Session = Depends(get_db),
            pr: Principal = Depends(require_perm('reservations.cancel'))):
    r = _rsv_or_404(db, pr.tenant_id, rid)
    je = hs.mark_no_show(db, res=r, actor_id=pr.id)
    db.commit()
    return {'entry_no': je.entry_no, 'status': 'NO_SHOW'}


@router.post('/reservations/{rid}/check-in', status_code=201)
def check_in(rid: str, body: CheckInIn, db: Session = Depends(get_db),
             pr: Principal = Depends(require_perm('checkin.do'))):
    if body.allow_dirty and not pr.has('checkin.dirty_override'):
        raise HTTPException(403, {'error': {'code': 'RBAC.FORBIDDEN',
                                            'message_ar': 'تجاوز الغرفة غير النظيفة يتطلب صلاحية checkin.dirty_override'}})
    r = _rsv_or_404(db, pr.tenant_id, rid)
    out = hs.check_in(db, res=r, actor_id=pr.id,
                      allow_dirty=body.allow_dirty)
    db.commit()
    return out


@router.post('/walk-in', status_code=201)
def walk_in(body: WalkInIn, db: Session = Depends(get_db),
            pr: Principal = Depends(require_perm('checkin.do'))):
    if body.allow_dirty and not pr.has('checkin.dirty_override'):
        raise HTTPException(403, {'error': {'code': 'RBAC.FORBIDDEN',
                                            'message_ar': 'تجاوز النظافة يتطلب صلاحية'}})
    rt = _room_type_or_404(db, pr.tenant_id, body.room_type_code)
    branch = db.execute(select(m.Branch).where(
        m.Branch.tenant_id == pr.tenant_id)).scalar_one()
    plan = None
    if body.rate_plan_code:
        plan = db.execute(select(m.RatePlan).where(
            m.RatePlan.tenant_id == pr.tenant_id,
            m.RatePlan.code == body.rate_plan_code)).scalar_one_or_none()
    room = _room_or_404(db, pr.tenant_id, body.room_no) if body.room_no else None
    res = hs.walk_in(db, tenant_id=pr.tenant_id, branch_id=branch.id,
                     guest_id=body.guest_id, room_type_id=rt.id,
                     departure=body.departure_date, actor_id=pr.id,
                     corporate_id=body.corporate_id,
                     rate_plan_id=plan.id if plan else None,
                     room_id=room.id if room else None,
                     adults=body.adults, children=body.children,
                     allow_dirty=body.allow_dirty,
                     trip={'purpose': body.purpose,
                           'origin_gov': body.origin_gov,
                           'origin_district': body.origin_district,
                           'vehicle_note': body.vehicle_note,
                           'police_notes': body.police_notes})
    db.commit()
    return _rsv_out(db, res)


@router.post('/reservations/{rid}/room-move')
def room_move(rid: str, body: RoomMoveIn, db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('checkin.do'))):
    r = _rsv_or_404(db, pr.tenant_id, rid)
    room = _room_or_404(db, pr.tenant_id, body.new_room_no)
    out = hs.room_move(db, res=r, new_room_id=room.id, reason=body.reason,
                       actor_id=pr.id)
    db.commit()
    return out


# ── الفوليو ────────────────────────────────────────────
@router.get('/folios/{folio_id}')
def get_folio(folio_id: str, db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('folio.view'))):
    folio = db.get(m.Folio, folio_id)
    if folio is None or folio.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'HOTEL.UNKNOWN_FOLIO',
                                            'message_ar': 'الفوليو غير موجود'}})
    r = db.get(m.Reservation, folio.reservation_id)
    lines = hs.folio_lines(db, pr.tenant_id, folio.id)
    totals = hs.folio_totals(db, pr.tenant_id, folio.id)
    return {'folio_id': folio.id, 'window': folio.window, 'type': folio.type,
            'status': folio.status, 'reservation_id': r.id,
            'conf': r.confirmation_no,
            'credit_limit': str(folio.credit_limit) if folio.credit_limit else None,
            'lines': [{k: (str(v) if not isinstance(v, str) else v)
                       for k, v in row.items()} for row in lines],
            'charges': str(totals['charges']),
            'payments': str(totals['payments']),
            'balance': str(totals['balance']),
            'high_balance': bool(folio.credit_limit
                                 and totals['balance'] > folio.credit_limit)}


@router.post('/folios/{folio_id}/charges', status_code=201)
def folio_charge(folio_id: str, body: ChargeIn,
                 db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('folio.charge'))):
    folio = hs.open_folio_or_err(db, folio_id, pr.tenant_id)
    je = hs.add_charge(db, folio=folio, extra_code=body.extra_code,
                       qty=body.qty, unit_price=body.unit_price,
                       description=body.description, actor_id=pr.id,
                       event_key=body.event_key)
    db.commit()
    return {'entry_no': je.entry_no,
            'balance': str(hs.folio_balance(db, pr.tenant_id, folio.id))}


@router.post('/folios/{folio_id}/payments', status_code=201)
def folio_payment(folio_id: str, body: PaymentIn,
                  db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('folio.pay'))):
    folio = hs.open_folio_or_err(db, folio_id, pr.tenant_id)
    je = hs.add_payment(db, folio=folio, amount=body.amount,
                        method=body.method, actor_id=pr.id,
                        event_key=body.event_key)
    db.commit()
    return {'entry_no': je.entry_no,
            'balance': str(hs.folio_balance(db, pr.tenant_id, folio.id))}


@router.post('/folios/{folio_id}/discount', status_code=201)
def folio_discount(folio_id: str, body: DiscountIn,
                   db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('folio.discount'))):
    folio = hs.open_folio_or_err(db, folio_id, pr.tenant_id)
    # المسيح: التحقق من المعتمِد يتم هنا على مستوى الصلاحية الفعلية
    if body.approver_id:
        approver = db.get(m.User, body.approver_id)
        if approver is None:
            raise PostingError('HOTEL.BAD_APPROVER', 'المعتمد غير موجود')
        from ..deps import user_perms
        aperms = user_perms(db, approver)
        if not ('*' in aperms or 'discounts.approve' in aperms):
            raise PostingError('HOTEL.BAD_APPROVER',
                               'المعتمد لا يملك صلاحية اعتماد الخصومات')
    je = hs.add_discount(db, folio=folio, amount=body.amount,
                         reason=body.reason, actor=pr.user,
                         approver_id=body.approver_id,
                         can_approve=pr.has('discounts.approve'))
    db.commit()
    return {'entry_no': je.entry_no,
            'balance': str(hs.folio_balance(db, pr.tenant_id, folio.id))}


@router.post('/reservations/{rid}/transfer-to-corporate', status_code=201)
def transfer_corporate(rid: str, body: TransferCorpIn,
                       db: Session = Depends(get_db),
                       pr: Principal = Depends(require_perm('checkout.credit_transfer'))):
    r = _rsv_or_404(db, pr.tenant_id, rid)
    je = hs.transfer_to_corporate(db, res=r, amount=body.amount,
                                  actor_id=pr.id, reason=body.reason)
    db.commit()
    return {'entry_no': je.entry_no}


@router.post('/reservations/{rid}/checkout', status_code=201)
def checkout(rid: str, body: CheckoutIn, db: Session = Depends(get_db),
             pr: Principal = Depends(require_perm('checkout.do'))):
    r = _rsv_or_404(db, pr.tenant_id, rid)
    if body.corporate_transfer and not pr.has('checkout.credit_transfer'):
        raise HTTPException(403, {'error': {'code': 'RBAC.FORBIDDEN',
                                            'message_ar': 'نقل الذمة لشركة يتطلب صلاحية checkout.credit_transfer'}})
    payments = [{'amount': p.amount, 'method': p.method, '_folio': 1}
                for p in body.payments]
    inv = hs.checkout(db, res=r, actor_id=pr.id, late_fee=body.late_fee,
                      payments=payments,
                      corporate_transfer=body.corporate_transfer)
    db.commit()
    return {'invoice_no': inv.invoice_no, 'invoice_id': inv.id,
            'charges': str(inv.total_charges),
            'payments': str(inv.total_payments),
            'balance_settled': str(inv.balance_settled)}


@router.get('/reservations/{rid}/invoice')
def get_invoice(rid: str, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('reservations.view'))):
    r = _rsv_or_404(db, pr.tenant_id, rid)
    inv = db.execute(select(m.GuestInvoice).where(
        m.GuestInvoice.reservation_id == r.id).order_by(
        m.GuestInvoice.issued_at.desc())).scalars().first()
    if inv is None:
        raise HTTPException(404, {'error': {'code': 'HOTEL.NO_INVOICE',
                                            'message_ar': 'لا فاتورة لهذا الحجز'}})
    return {'invoice_no': inv.invoice_no, 'guest_name': inv.guest_name,
            'issued_at': inv.issued_at, 'lines': inv.lines,
            'total_charges': str(inv.total_charges),
            'total_payments': str(inv.total_payments),
            'balance_settled': str(inv.balance_settled)}


# ── التدقيق الليلي ─────────────────────────────────────
@router.get('/night-audit')
def night_audit_home(db: Session = Depends(get_db),
                     pr: Principal = Depends(require_perm('frontdesk.view'))):
    pre = hs.precheck(db, pr.tenant_id)
    runs = db.execute(select(m.NightAuditRun).where(
        m.NightAuditRun.tenant_id == pr.tenant_id).order_by(
        m.NightAuditRun.business_date.desc()).limit(7)).scalars().all()
    return {'precheck': pre,
            'recent_runs': [{'id': r.id, 'business_date': str(r.business_date),
                             'status': r.status, 'totals': r.totals,
                             'completed_at': r.completed_at} for r in runs]}


@router.post('/night-audit/run', status_code=201)
def night_audit_run(db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('nightaudit.run'))):
    run = hs.run_night_audit(db, tenant_id=pr.tenant_id, actor_id=pr.id)
    db.commit()
    return {'id': run.id, 'business_date': str(run.business_date),
            'status': run.status, 'steps': run.steps,
            'snapshot': run.report_snapshot}


def register_into(app):
    """مساعد تسجيل (لاستدعاء من main إن لزم)."""
    app.include_router(router)
