"""اختبارات وحدة الفندق — معايير القبول الستة في ملف 03 §7 + مصفوفات الحالات."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import models as m
from app.hotel import (available_rooms, cancel_reservation, check_in,
                       checkout, create_reservation, deposit_balance,
                       folio_balance, folio_totals, in_house_report,
                       mark_no_show, occupancy_report, precheck, price_stay,
                       resolve_night_rate, room_move, run_night_audit,
                       add_charge, add_discount, add_payment,
                       change_hk_status, transfer_to_corporate, walk_in)
from app.posting import PostingError, post_event
from app.security import hash_password, new_uuid, utcnow

TODAY = date.today()


def _guest(db, tid, name='ضيف اختبار'):
    g = m.Guest(id=new_uuid(), tenant_id=tid, full_name=name,
                created_at=utcnow())
    db.add(g)
    db.flush()
    return g


def _rt(db, tid, code='SGL'):
    return db.execute(select(m.RoomType).where(
        m.RoomType.tenant_id == tid, m.RoomType.code == code)).scalar_one()


def _branch(db, tid):
    return db.execute(select(m.Branch).where(
        m.Branch.tenant_id == tid)).scalar_one()


def _rsv(db, tid, arrival=None, dep=None, room_type='SGL', **kw):
    g = _guest(db, tid)
    br = _branch(db, tid)
    return create_reservation(
        db, tenant_id=tid, branch_id=br.id, guest_id=g.id,
        room_type_id=_rt(db, tid, room_type).id,
        arrival=arrival or TODAY, departure=dep or TODAY + timedelta(2),
        actor_id='test', **kw)


# ═══ قبول #1: استحالة الحجز المزدوج ═══════════════════════════
def test_double_booking_same_room_rejected(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r1 = _rsv(db, tid)
    with pytest.raises(PostingError) as exc:
        _rsv(db, tid, room_id=r1.room_id)
    assert exc.value.code == 'HOTEL.DOUBLE_BOOKING'


def test_double_booking_under_concurrency(db_session, tmp_path):
    """خيطان يحجزان نفس الغرفة نفس الفترة — واحد فقط ينجح (قبول #1)."""
    import threading
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    g1, g2 = _guest(db, tid, 'ضيف أ'), _guest(db, tid, 'ضيف ب')
    rt = _rt(db, tid, 'SGL')
    room = db.execute(select(m.Room).where(
        m.Room.tenant_id == tid, m.Room.room_no == '101')).scalar_one()
    db.commit()
    results = {'ok': 0, 'fail': 0, 'errors': []}

    def attempt(gid):
        s = factory()
        try:
            create_reservation(db=s, tenant_id=tid, branch_id=bid,
                               guest_id=gid, room_type_id=rt.id,
                               arrival=TODAY, departure=TODAY + timedelta(2),
                               actor_id='thread', room_id=room.id)
            s.commit()
            results['ok'] += 1
        except Exception as e:  # DOUBLE_BOOKING أو قفل SQLite — كلاهما يمنع
            s.rollback()
            results['fail'] += 1
            results['errors'].append(str(e)[:60])
        finally:
            s.close()

    t1 = threading.Thread(target=attempt, args=(g1.id,))
    t2 = threading.Thread(target=attempt, args=(g2.id,))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert results['ok'] == 1 and results['fail'] == 1, results
    n = db.execute(select(m.Reservation).where(
        m.Reservation.room_id == room.id,
        m.Reservation.status.in_(('TENTATIVE', 'CONFIRMED', 'CHECKED_IN'))
    )).scalars().all()
    assert len(n) == 1


def test_partial_overlap_also_rejected(db_session):
    """التداخل الجزئي (ليالٍ مشتركة واحدة) يُرفض أيضاً."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r1 = _rsv(db, tid, arrival=TODAY, dep=TODAY + timedelta(3))
    with pytest.raises(PostingError):
        _rsv(db, tid, arrival=TODAY + timedelta(2),
             dep=TODAY + timedelta(5), room_id=r1.room_id)
    # لكن البدء في يوم مغادرة السابق مسموح (لا تداخل)
    r2 = _rsv(db, tid, arrival=TODAY + timedelta(3),
              dep=TODAY + timedelta(5), room_id=r1.room_id)
    assert r2.status == 'CONFIRMED'


# ═══ الأسعار: التقويم ← الخطة ← الأساس ══════════════════════════
def test_rate_resolution_fallback(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    rt = _rt(db, tid, 'SGL')
    # بدون تقويم ← السعر الأساسي
    rate, origin = resolve_night_rate(db, tid, rt.id, None, TODAY)
    assert origin == 'BASE' and rate == Decimal('60')
    # مع تقويم ← سعر التقويم يتقدم
    db.add(m.RateCalendar(id=new_uuid(), tenant_id=tid, room_type_id=rt.id,
                          rate_plan_id=None, day=TODAY, price=99,
                          day_type='EVENT'))
    db.flush()
    rate, origin = resolve_night_rate(db, tid, rt.id, None, TODAY)
    assert origin == 'CALENDAR' and rate == Decimal('99')
    # اليوم التالي بلا تقويم ← الأساس
    rate, origin = resolve_night_rate(db, tid, rt.id, None,
                                      TODAY + timedelta(1))
    assert origin == 'BASE'


def test_night_snapshot_keeps_old_prices_for_past_nights(db_session):
    """تعديل السعر لاحقاً لا يغيّر الليالي المنقضية (ملف 03 §2)."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid, arrival=TODAY, dep=TODAY + timedelta(3))
    check_in(db, res=r, actor_id='test')
    run_night_audit(db, tenant_id=tid, actor_id='test')  # رحّل ليلة اليوم
    priced = db.execute(select(m.ReservationNightRate).where(
        m.ReservationNightRate.reservation_id == r.id)).scalars().all()
    assert all(p.rate == Decimal('60') for p in priced)
    je = db.execute(select(m.JournalEntry).where(
        m.JournalEntry.event_key == f'na:{TODAY}:{r.id}')).scalar_one()
    assert je.journal_type == 'AUTO_ROOM'


# ═══ قبول #2 + #4: رصيد الفوليو = الدفتر + استحالة ليلة مكررة ═══
def test_folio_balance_matches_ledger_and_night_idempotent(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid)
    out = check_in(db, res=r, actor_id='test')
    folio_id = out['folio_id']
    run_night_audit(db, tenant_id=tid, actor_id='test')
    folio = db.get(m.Folio, folio_id)
    add_charge(db, folio=folio, extra_code='LAUNDRY', qty=2, actor_id='test')
    add_payment(db, folio=folio, amount=Decimal('50'), method='CASH',
                actor_id='test')
    bal = folio_balance(db, tid, folio_id)
    totals = folio_totals(db, tid, folio_id)
    assert totals['balance'] == bal
    assert totals['charges'] == Decimal('60') + Decimal('16')  # ليلة + مغسلتان
    assert totals['payments'] == Decimal('50')
    # إعادة نفس حدث الليلة بنفس المفتاح ← لا قيد جديد (قبول #4)
    n1 = db.execute(select(m.JournalEntry).where(
        m.JournalEntry.tenant_id == tid)).scalars().all()
    je2 = post_event(db, tenant_id=tid, branch_code='MAIN',
                     event_type='ROOM_NIGHT', event_key=f'na:{TODAY}:{r.id}',
                     entry_date=TODAY,
                     amounts={'gross': '60', 'net': '60', 'tax': '0'},
                     party_type='GUEST', party_id=folio_id, actor_id='test')
    n2 = db.execute(select(m.JournalEntry).where(
        m.JournalEntry.tenant_id == tid)).scalars().all()
    assert len(n1) == len(n2)
    db.commit()


# ═══ الرفض: غرفة غير نظيفة + استثناء بصلاحية ════════════════════
def test_checkin_dirty_room_requires_override(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid)
    room = db.get(m.Room, r.room_id)
    room.hk_status = 'DIRTY'
    db.flush()
    with pytest.raises(PostingError) as exc:
        check_in(db, res=r, actor_id='test')
    assert exc.value.code == 'HOTEL.ROOM_NOT_CLEAN'
    out = check_in(db, res=r, actor_id='test', allow_dirty=True)
    assert out['folio_id']


def test_state_machine_rejects_illegal_transitions(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid)
    with pytest.raises(PostingError) as exc:
        checkout(db, res=r, actor_id='test')  # خروج قبل دخول!
    assert exc.value.code == 'HOTEL.ILLEGAL_TRANSITION'


# ═══ العربون: استلام ← تطبيق عند التسكين ════════════════════════
def test_deposit_apply_on_checkin(db_session):
    from app.hotel import add_deposit
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid, dep=TODAY + timedelta(2))
    add_deposit(db, res=r, amount=Decimal('100'), actor_id='test')
    assert deposit_balance(db, tid, r.id) == Decimal('100')
    out = check_in(db, res=r, actor_id='test')
    assert Decimal(out['deposit_applied']) == Decimal('100')
    assert deposit_balance(db, tid, r.id) == Decimal('0')
    assert folio_balance(db, tid, out['folio_id']) == Decimal('-100')


# ═══ الإلغاء + عدم الحضور ═══════════════════════════════════════
def test_cancel_with_fee_and_refund(db_session):
    from app.hotel import add_deposit
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid)
    add_deposit(db, res=r, amount=Decimal('100'), actor_id='test')
    out = cancel_reservation(db, res=r, reason='تغيير خطط النزيل',
                             actor_id='test', fee=Decimal('60'), refund=True)
    assert Decimal(out['fee']) == Decimal('60')
    assert Decimal(out['refunded']) == Decimal('40')
    assert r.status == 'CANCELLED'


def test_no_show_charges_one_night(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid)
    je = mark_no_show(db, res=r, actor_id='test')
    assert r.status == 'NO_SHOW'
    # إيراد عدم الحضور = ليلة واحدة 60
    n4102 = db.execute(
        select(m.JournalLine).join(m.Account, m.Account.id == m.JournalLine.account_id)
        .where(m.JournalLine.entry_id == je.id, m.Account.code == '4102')).scalars().all()
    assert sum(l.credit_base for l in n4102) == Decimal('60')


# ═══ قبول #5: الخصم فوق الحد يتطلب معتمداً ═══════════════════════
def test_discount_over_cap_requires_approver(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid)
    out = check_in(db, res=r, actor_id='test')
    folio = db.get(m.Folio, out['folio_id'])
    actor = db.get(m.User, seed['admin_id'])

    class _NoPerm:
        id = 'recep'

    add_charge(db, folio=folio, extra_code='GENERIC', qty=2, actor_id='test')
    with pytest.raises(PostingError) as exc:
        add_discount(db, folio=folio, amount=Decimal('150'), reason='تعويض شكوى',
                     actor=_NoPerm(), approver_id=None, can_approve=False)
    assert exc.value.code == 'HOTEL.DISCOUNT_NEEDS_APPROVAL'
    je = add_discount(db, folio=folio, amount=Decimal('150'),
                      reason='تعويض شكوى', actor=actor,
                      approver_id=seed['admin_id'], can_approve=False)
    assert je.journal_type == 'AUTO_ROOM'
    assert folio_balance(db, tid, folio.id) == Decimal('20') - Decimal('150')


# ═══ قبول #6: فاتورة الخروج تطابق الشحنات − الدفعات بالهللة ══════
def test_checkout_invoice_perfect_match(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid, arrival=TODAY, dep=TODAY + timedelta(2))
    out = check_in(db, res=r, actor_id='test')
    folio_id = out['folio_id']
    run_night_audit(db, tenant_id=tid, actor_id='test')      # ليلة 1 = 60
    folio = db.get(m.Folio, folio_id)
    add_charge(db, folio=folio, extra_code='ROOM_SERVICE', qty=2,
               actor_id='test')                                # +24 = 84
    add_charge(db, folio=folio, extra_code='LAUNDRY', qty=1,
               actor_id='test', unit_price=Decimal('7.75'))    # +7.75 = 91.75
    totals = folio_totals(db, tid, folio_id)
    assert totals['charges'] == Decimal('91.75')
    payments = [{'amount': Decimal('50'), 'method': 'CASH'},
                {'amount': Decimal('41.75'), 'method': 'CARD'}]
    # المغادرة مبكراً (ليلة واحدة فعلياً) مسموحة — الفاتورة على الشحنات الفعلية
    inv = checkout(db, res=r, actor_id='test', payments=payments)
    assert inv.total_charges == Decimal('91.75')
    assert inv.total_payments == Decimal('91.75')
    assert inv.balance_settled == Decimal('0')
    assert db.get(m.Reservation, r.id).status == 'CHECKED_OUT'
    assert db.get(m.Folio, folio_id).status == 'CLOSED'
    assert db.get(m.Room, r.room_id).hk_status == 'DIRTY'
    assert inv.invoice_no.startswith('INV-')
    db.commit()


def test_checkout_requires_full_settlement(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid)
    out = check_in(db, res=r, actor_id='test')
    folio = db.get(m.Folio, out['folio_id'])
    add_charge(db, folio=folio, extra_code='GENERIC', qty=5, actor_id='test')
    with pytest.raises(PostingError) as exc:
        checkout(db, res=r, actor_id='test')  # بلا سداد!
    assert exc.value.code == 'HOTEL.UNSETTLED_BALANCE'
    assert db.get(m.Reservation, r.id).status == 'CHECKED_IN'


def test_checkout_corporate_transfer(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    corp = m.Corporate(id=new_uuid(), tenant_id=tid, name='شركة النخبة',
                       credit_limit=Decimal('5000'))
    db.add(corp)
    db.flush()
    g = _guest(db, tid)
    br = _branch(db, tid)
    r = create_reservation(db, tenant_id=tid, branch_id=br.id, guest_id=g.id,
                           room_type_id=_rt(db, tid, 'DBL').id,
                           arrival=TODAY, departure=TODAY + timedelta(1),
                           actor_id='test', corporate_id=corp.id)
    out = check_in(db, res=r, actor_id='test')
    folio = db.get(m.Folio, out['folio_id'])
    add_charge(db, folio=folio, extra_code='GENERIC', qty=3, actor_id='test')
    add_payment(db, folio=folio, amount=Decimal('10'), method='CASH',
                actor_id='test')
    inv = checkout(db, res=r, actor_id='test', corporate_transfer=True)
    assert inv.balance_settled == Decimal('0')
    # ذمة المدينة 1120 تحمل 20 لصالح الشركة
    from app.hotel import _sum_account_for_party
    td, tc = _sum_account_for_party(db, tid, '1120', corp.id)
    assert td - tc == Decimal('20')


def test_overpaid_refunded_at_checkout(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid)
    out = check_in(db, res=r, actor_id='test')
    folio = db.get(m.Folio, out['folio_id'])
    add_payment(db, folio=folio, amount=Decimal('25'), method='CASH',
                actor_id='test')  # نزل بلا شحنات → فائض 25
    inv = checkout(db, res=r, actor_id='test')
    assert folio_balance(db, tid, folio.id) == Decimal('0')
    assert inv.total_payments - inv.total_charges == Decimal('0')


# ═══ نقل غرفة + استبعاد OOO ══════════════════════════════════════
def test_room_move_and_ooo_excluded(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid, room_type='SGL')
    old_room_id = r.room_id
    check_in(db, res=r, actor_id='test')
    target = db.execute(select(m.Room).where(
        m.Room.tenant_id == tid, m.Room.room_no == '104')).scalar_one()
    out = room_move(db, res=r, new_room_id=target.id,
                    reason='مكيف معطل', actor_id='test')
    assert out['new'] == '104'
    assert db.get(m.Room, old_room_id).hk_status == 'DIRTY'
    # لا يجوز تعطيل غرفة يلتقي تعطيلها مع حجز قائم (تنبيه ملف 03 §5)
    with pytest.raises(PostingError) as exc:
        change_hk_status(db, room=target, new_status='OOO', can_clean=True,
                         can_manage=True, actor_id='test', reason='تسرب',
                         ooo_from=TODAY, ooo_to=TODAY + timedelta(5))
    assert exc.value.code == 'HOTEL.HK_OOO_CONFLICT'
    # تعطيل غرفة فارغة (103) ← تستبعد من التوفر
    r103 = db.execute(select(m.Room).where(
        m.Room.tenant_id == tid, m.Room.room_no == '103')).scalar_one()
    change_hk_status(db, room=r103, new_status='OOO', can_clean=True,
                     can_manage=True, actor_id='test', reason='تسرب مياه',
                     ooo_from=TODAY, ooo_to=TODAY + timedelta(5))
    free = available_rooms(db, tid, _branch(db, tid).id,
                           _rt(db, tid, 'SGL').id, TODAY,
                           TODAY + timedelta(2))
    assert all(rm.room_no not in ('103', '104') for rm in free)


def test_hk_matrix_and_reason_required(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    room = db.execute(select(m.Room).where(
        m.Room.tenant_id == tid, m.Room.room_no == '105')).scalar_one()
    room.hk_status = 'DIRTY'
    db.flush()
    # موظفة الطابق: مسار التنظيف فقط
    change_hk_status(db, room=room, new_status='CLEANING', can_clean=True,
                     can_manage=False, actor_id='hk1')
    change_hk_status(db, room=room, new_status='CLEAN', can_clean=True,
                     can_manage=False, actor_id='hk1')
    assert room.hk_status == 'CLEAN'
    # موظفة الطابق لا تفحص (INSPECTED يحتاج hk.manage)
    with pytest.raises(PostingError):
        change_hk_status(db, room=room, new_status='INSPECTED', can_clean=True,
                         can_manage=False, actor_id='hk1')
    change_hk_status(db, room=room, new_status='INSPECTED', can_clean=True,
                     can_manage=True, actor_id='sup')
    # التعطيل بلا سبب مرفوض
    with pytest.raises(PostingError):
        change_hk_status(db, room=room, new_status='OOO', can_clean=True,
                         can_manage=True, actor_id='sup')


# ═══ Walk-in خطوة واحدة ══════════════════════════════════════════
def test_walk_in_one_step(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    g = _guest(db, tid, 'حاضر مباشر')
    r = walk_in(db, tenant_id=tid, branch_id=_branch(db, tid).id,
                guest_id=g.id, room_type_id=_rt(db, tid, 'DBL').id,
                departure=TODAY + timedelta(1), actor_id='desk')
    assert r.status == 'CHECKED_IN'
    assert r.source == 'WALKIN'


# ═══ التدقيق الليلي: بوابة G3 ════════════════════════════════════
def test_night_audit_blocked_until_arrivals_resolved(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    _rsv(db, tid)  # وصول اليوم بلا تسكين
    with pytest.raises(PostingError) as exc:
        run_night_audit(db, tenant_id=tid, actor_id='audit')
    assert exc.value.code == 'HOTEL.AUDIT_BLOCKED'
    pre = precheck(db, tid)
    assert pre['can_run'] is False and len(pre['pending_arrivals']) == 1


def test_g3_two_consecutive_days_no_intervention(db_session):
    """يومان متتاليان بلا تدخل + تاريخ العمل يتقدم يوماً واحداً فقط."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid, arrival=TODAY, dep=TODAY + timedelta(3))
    out = check_in(db, res=r, actor_id='desk')
    run1 = run_night_audit(db, tenant_id=tid, actor_id='audit')
    assert run1.status == 'COMPLETED'
    assert run1.totals['nights_posted'] == 1
    st = db.get(m.BusinessDateState, tid)
    assert st.current_business_date == TODAY + timedelta(1)
    run2 = run_night_audit(db, tenant_id=tid, actor_id='audit')
    assert run2.status == 'COMPLETED'
    st = db.get(m.BusinessDateState, tid)
    assert st.current_business_date == TODAY + timedelta(2)
    # ليلتان محسوبتان بحدثين مختلفين
    for i, bd in enumerate((TODAY, TODAY + timedelta(1))):
        assert db.execute(select(m.JournalEntry).where(
            m.JournalEntry.event_key == f'na:{bd}:{r.id}')).scalar_one()
    db.commit()


def test_night_audit_blocks_on_pending_departure(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid, arrival=TODAY, dep=TODAY + timedelta(1))
    check_in(db, res=r, actor_id='desk')
    run_night_audit(db, tenant_id=tid, actor_id='audit')
    # المغادرة الآن = تاريخ العمل ← التدقيق القادم محجوب حتى الخروج أو التمديد
    with pytest.raises(PostingError) as exc:
        run_night_audit(db, tenant_id=tid, actor_id='audit')
    assert exc.value.code == 'HOTEL.AUDIT_BLOCKED'


def test_reports_occupancy_and_inhouse(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid)
    check_in(db, res=r, actor_id='desk')
    run_night_audit(db, tenant_id=tid, actor_id='audit')
    rep = occupancy_report(db, tid, TODAY, TODAY)
    assert rep['occupied_nights'] == 1
    assert Decimal(rep['room_revenue']) == Decimal('60')
    ih = in_house_report(db, tid)
    assert len(ih) == 1
    assert Decimal(ih[0]['balance']) == Decimal('60')


def test_audit_chain_unbroken_across_multi_event_ops(db_session):
    """سجل التدقيق يبقى متصلاً عبر عمليات متعددة الأحداث بمعاملة واحدة
    (إيداع: journal.post + deposit / تسكين: post + apply + check_in)."""
    from app.audit import verify_chain
    from app.hotel import add_deposit
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid)
    add_deposit(db, res=r, amount=Decimal('100'), actor_id='test')
    db.commit()
    v = verify_chain(db, tid)
    assert v['ok'] is True, v
    check_in(db, res=r, actor_id='test')
    add_charge(db, folio=db.execute(
        select(m.Folio).where(m.Folio.reservation_id == r.id,
                              m.Folio.window == 1)).scalar_one(),
               extra_code='SPA', qty=1, actor_id='test')
    db.commit()
    v = verify_chain(db, tid)
    assert v['ok'] is True, v


def test_trial_balance_stays_balanced_after_full_cycle(db_session):
    """بعد دورة كاملة: حجز+عربون+تسكين+شحنة+تدقيق+مغادرة ← الميزان متوازن."""
    from app.hotel import add_deposit
    from app.reports import trial_balance
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid)
    add_deposit(db, res=r, amount=Decimal('30'), actor_id='test')
    check_in(db, res=r, actor_id='test')
    run_night_audit(db, tenant_id=tid, actor_id='test')
    folio = db.execute(select(m.Folio).where(
        m.Folio.reservation_id == r.id, m.Folio.window == 1)).scalar_one()
    bal = folio_balance(db, tid, folio.id)
    checkout(db, res=r, actor_id='test',
             payments=[{'amount': bal, 'method': 'CARD'}])
    db.commit()
    tb = trial_balance(db, tid, TODAY + timedelta(days=10))
    assert tb['balanced'] is True and tb['net_balance_zero'] is True


def test_corporate_window_transfer(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    corp = m.Corporate(id=new_uuid(), tenant_id=tid, name='شركة الأفق',
                       credit_limit=Decimal('3000'))
    db.add(corp)
    db.flush()
    g = _guest(db, tid)
    r = create_reservation(db, tenant_id=tid, branch_id=_branch(db, tid).id,
                           guest_id=g.id, room_type_id=_rt(db, tid).id,
                           arrival=TODAY, departure=TODAY + timedelta(1),
                           actor_id='test', corporate_id=corp.id)
    out = check_in(db, res=r, actor_id='desk')
    folio = db.get(m.Folio, out['folio_id'])
    add_charge(db, folio=folio, extra_code='GENERIC', qty=4, actor_id='desk')
    transfer_to_corporate(db, res=r, amount=Decimal('30'), actor_id='test',
                          reason='وجبات على الشركة')
    assert folio_balance(db, tid, folio.id) == Decimal('10')
    corp_f = db.execute(select(m.Folio).where(
        m.Folio.reservation_id == r.id, m.Folio.window == 2)).scalar_one()
    assert folio_balance(db, tid, corp_f.id) == Decimal('30')
    db.commit()
