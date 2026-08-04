"""نقاط وحدة الفندق — ملف 12 (API_STRUCTURE) وملف 03:
غرف/حجوزات/تدقيق ليلي/فواتير/هوسكيبينج/تقارير تشغيلية.
قاعدة مركزية: لا أثراً مالياً خارج الخدمات في app/hotel.py (الملف 02 §6)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import hotel as hs
from .. import models as m
from ..db import get_db
from ..deps import Principal, require_perm
from ..posting import PostingError
from ..schemas_hotel import (CancelIn, ChargeIn, CheckInIn, CheckoutIn,
                             CorporateIn, DepositIn, DiscountIn, GuestIn,
                             HkChangeIn, ModifyReservationIn, PaymentIn,
                             ReservationIn, RoomIn, RoomMoveIn, TransferCorpIn,
                             WalkInIn)
from ..security import decrypt_pii, encrypt_pii, mask_id, utcnow

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


def _rsv_out(db, r: m.Reservation) -> dict:
    room = db.get(m.Room, r.room_id) if r.room_id else None
    rt = db.get(m.RoomType, r.room_type_id)
    guest = db.get(m.Guest, r.guest_id)
    corp = db.get(m.Corporate, r.corporate_id) if r.corporate_id else None
    return {'id': r.id, 'confirmation_no': r.confirmation_no,
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
            'deposit_balance': str(hs.deposit_balance(db, r.tenant_id, r.id))}


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
    out = []
    for room in rooms:
        rt = db.get(m.RoomType, room.room_type_id)
        rsv = rsv_by_room.get(room.id)
        out.append({'id': room.id, 'room_no': room.room_no, 'floor': room.floor,
                    'type': rt.name_ar if rt else '—', 'type_code': rt.code if rt else '',
                    'hk_status': room.hk_status,
                    'occupied': room.id in occupied,
                    'ooo_reason': room.ooo_reason,
                    'ooo_from': room.ooo_from, 'ooo_to': room.ooo_to,
                    'current_rsv': rsv.id if rsv else None,
                    'blocked_for_sale': hs.ooo_blocks(db, room, bd, bd)})
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
    from ..security import new_uuid
    room = m.Room(id=new_uuid(), tenant_id=pr.tenant_id, branch_id=branch.id,
                  room_no=body.room_no, floor=body.floor,
                  room_type_id=rt.id, features=body.features)
    db.add(room)
    db.commit()
    return {'id': room.id, 'room_no': room.room_no}


@router.get('/room-types')
def list_room_types(db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('frontdesk.view'))):
    rows = db.execute(select(m.RoomType).where(
        m.RoomType.tenant_id == pr.tenant_id).order_by(
        m.RoomType.display_order)).scalars().all()
    return [{'id': r.id, 'code': r.code, 'name_ar': r.name_ar,
             'capacity_adults': r.capacity_adults,
             'capacity_children': r.capacity_children, 'beds': r.beds,
             'base_rate': str(r.base_rate), 'is_active': r.is_active}
            for r in rows]


@router.get('/extras')
def list_extras(db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('frontdesk.view'))):
    rows = db.execute(select(m.Extra).where(
        m.Extra.tenant_id == pr.tenant_id,
        m.Extra.is_active.is_(True))).scalars().all()
    return [{'code': e.code, 'name_ar': e.name_ar, 'price': str(e.price),
             'revenue_account_code': e.revenue_account_code} for e in rows]


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
    return [{'id': g.id, 'full_name': g.full_name, 'phone': g.phone,
             'id_masked': mask_id(g.id_number_enc),
             'nationality': g.nationality, 'vip': g.vip,
             'blacklist': g.blacklist} for g in rows]


@router.post('/guests', status_code=201)
def create_guest(body: GuestIn, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('guests.manage'))):
    from ..security import new_uuid
    g = m.Guest(id=new_uuid(), tenant_id=pr.tenant_id,
                full_name=body.full_name, phone=body.phone,
                id_number_enc=encrypt_pii(body.id_number),
                nationality=body.nationality, vip=body.vip,
                notes=body.notes, created_at=utcnow())
    db.add(g)
    from ..audit import audit
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='guest.create', entity='guests',
          entity_id=g.id, after={'name': g.full_name})
    db.commit()
    return {'id': g.id, 'full_name': g.full_name,
            'id_masked': mask_id(g.id_number_enc)}


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
        rate_override=body.rate_override)
    db.commit()
    return _rsv_out(db, res)


@router.get('/reservations/{rid}')
def get_reservation(rid: str, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('reservations.view'))):
    r = _rsv_or_404(db, pr.tenant_id, rid)
    out = _rsv_out(db, r)
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
                     allow_dirty=body.allow_dirty)
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
