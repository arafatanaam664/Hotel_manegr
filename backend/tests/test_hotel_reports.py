from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app import models as m
from app.reports import hotel_daily_report
from app.security import new_uuid, utcnow


def test_hotel_daily_report_calculates_occupancy_adr_revpar(db_session):
    db, _, seed = db_session
    room = db.execute(select(m.Room).where(m.Room.tenant_id == seed['tenant_id'])
                      ).scalars().first()
    guest = db.execute(select(m.Guest).where(m.Guest.tenant_id == seed['tenant_id'])
                       ).scalars().first()
    if guest is None:
        guest = m.Guest(id=new_uuid(), tenant_id=seed['tenant_id'],
                        full_name='نزيل اختبار التقرير', phone='',
                        id_number_enc='', created_at=utcnow())
        db.add(guest)
        db.flush()
    assert room is not None and guest is not None
    day = date(2026, 2, 10)
    reservation = m.Reservation(
        id=new_uuid(), tenant_id=seed['tenant_id'], branch_id=seed['branch_id'],
        confirmation_no='RPT-001', guest_id=guest.id,
        room_type_id=room.room_type_id, room_id=room.id,
        arrival_date=day, departure_date=date(2026, 2, 12), nights=2,
        status='CHECKED_IN', source='DIRECT', agreed_rate=Decimal('100'),
        est_total=Decimal('200'), created_by=seed['admin_id'], created_at=utcnow())
    db.add(reservation)
    db.add(m.ReservationStay(
        id=new_uuid(), tenant_id=seed['tenant_id'], reservation_id=reservation.id,
        room_id=room.id, from_date=day, to_date=date(2026, 2, 12), seq=1))
    db.add(m.ReservationNightRate(
        id=new_uuid(), tenant_id=seed['tenant_id'], reservation_id=reservation.id,
        stay_date=day, room_id=room.id, rate=Decimal('100')))
    db.commit()

    report = hotel_daily_report(db, seed['tenant_id'], day)
    assert report['rooms_sold'] == 1
    assert report['room_revenue'] == Decimal('100.0000')
    assert report['adr'] == Decimal('100.0000')
    assert report['revpar'] > Decimal('0')
    assert report['arrivals'] == 1
    assert report['departures'] == 0
    assert report['revenue_by_source']['DIRECT'] == Decimal('100.0000')
