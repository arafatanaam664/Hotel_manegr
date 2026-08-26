"""اختبارات وحدة «الغرف والأسعار» + الأجنحة المركبة (ADR-0035):
الحجب المشتق بالاتجاهين (لا بيع مزدوج جناح/غرفه)، الإتاحة الاتجاهية،
حراس الربط/الفك، CRUD الأنواع/الخطط/التقويم/الخدمات، RBAC، ولقط المزامنة."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import models as m
from app import synck as SK
from app.hotel import (available_rooms, cancel_reservation, check_in,
                       folio_totals, price_stay, resolve_night_rate,
                       room_move, run_night_audit, suite_block_reason,
                       create_reservation, suite_children)
from app.posting import PostingError
from app.security import hash_password, new_uuid, utcnow

TODAY = date.today()
D = TODAY
P2, P3, P5, P7 = (timedelta(2), timedelta(3), timedelta(5), timedelta(7))


def _guest(db, tid, name='ضيف جناح'):
    g = m.Guest(id=new_uuid(), tenant_id=tid, full_name=name,
                created_at=utcnow())
    db.add(g)
    db.flush()
    return g


def _rt(db, tid, code):
    return db.execute(select(m.RoomType).where(
        m.RoomType.tenant_id == tid, m.RoomType.code == code)).scalar_one()


def _branch(db, tid):
    return db.execute(select(m.Branch).where(
        m.Branch.tenant_id == tid)).scalar_one()


def _room(db, no):
    return db.execute(select(m.Room).where(m.Room.room_no == no)).scalar_one()


def _rsv(db, tid, room_type, arrival=D, dep=D + P2, room_no=None, **kw):
    g = _guest(db, tid)
    br = _branch(db, tid)
    room_id = _room(db, room_no).id if room_no else None
    return create_reservation(
        db, tenant_id=tid, branch_id=br.id, guest_id=g.id,
        room_type_id=_rt(db, tid, room_type).id, arrival=arrival,
        departure=dep, actor_id='suite-test', room_id=room_id, **kw)


def _expect(db, code, fn, *args, **kw):
    with pytest.raises(PostingError) as exc:
        fn(*args, **kw)
    assert exc.value.code == code


# ═══ البذرة: الجناح المركب التجريبي ═══
def test_seed_composite_suite_exists(db_session):
    db, factory, seed = db_session
    suite = _room(db, 'J-401')
    assert suite.kind == 'SUITE_UNIT'
    assert _rt(db, seed['tenant_id'], 'RSUITE').base_rate == Decimal('300')
    children = suite_children(db, suite.id)
    assert [c.room_no for c in children] == ['401', '402']
    for c in children:
        assert c.parent_room_id == suite.id and c.kind == 'STANDARD'


# ═══ إنشاء/ربط عبر API + الرفض البنيوي ═══
def test_create_suite_and_link_via_api(client, db_session, auth_hdr):
    db, factory, seed = db_session
    r = client.post('/api/hotel/rooms', headers=auth_hdr, json={
        'room_no': 'J-402', 'floor': 4, 'room_type_code': 'RSUITE',
        'kind': 'SUITE_UNIT'})
    assert r.status_code == 201 and r.json()['kind'] == 'SUITE_UNIT'
    r = client.post('/api/hotel/rooms', headers=auth_hdr, json={
        'room_no': '403', 'floor': 4, 'room_type_code': 'DBL',
        'parent_room_no': 'J-402'})
    assert r.status_code == 201
    assert _room(db, '403').parent_room_id == _room(db, 'J-402').id
    # جناح داخل جناح ممنوع
    r = client.post('/api/hotel/rooms', headers=auth_hdr, json={
        'room_no': 'J-403', 'floor': 4, 'room_type_code': 'RSUITE',
        'kind': 'SUITE_UNIT', 'parent_room_no': 'J-402'})
    assert r.status_code == 400
    assert r.json()['error']['code'] == 'HOTEL.NESTED_SUITE'
    # الأب غرفة عادية مرفوض
    r = client.post('/api/hotel/rooms', headers=auth_hdr, json={
        'room_no': '404', 'floor': 4, 'room_type_code': 'DBL',
        'parent_room_no': '101'})
    assert r.status_code == 400
    assert r.json()['error']['code'] == 'HOTEL.PARENT_NOT_SUITE'
    # فك ربط بلا حجوزات: مسموح وموثق
    rid = _room(db, '403').id
    r = client.patch(f'/api/hotel/rooms/{rid}', headers=auth_hdr, json={
        'set_parent': True, 'parent_room_no': ''})
    assert r.status_code == 200 and r.json()['parent_room_no'] is None
    assert db.execute(select(m.AuditLog).where(
        m.AuditLog.action == 'room.create')).first() is not None


# ═══ قبول رئيسي: حجز الجناح يقفل أبناءه ═══
def test_suite_booking_blocks_children(db_session):
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    r_suite = _rsv(db, tid, 'RSUITE', arrival=D, dep=D + P3, room_no='J-401')
    assert r_suite.room_id == _room(db, 'J-401').id
    for cn in ('401', '402'):
        _expect(db, 'HOTEL.SUITE_BLOCKED', _rsv, db, tid, 'DBL',
                arrival=D, dep=D + P2, room_no=cn)
    # والإتاحة النوعية تُخفيهما أيضاً
    free = available_rooms(db, tid, bid, _rt(db, tid, 'DBL').id, D, D + P2)
    assert '401' not in [f.room_no for f in free]
    assert '402' not in [f.room_no for f in free]
    # بعد انتهاء حجز الجناح: الأبناء متاحون
    free2 = available_rooms(db, tid, bid, _rt(db, tid, 'DBL').id,
                            D + P3, D + P5)
    assert '401' in [f.room_no for f in free2]


# ═══ عكسها: حجز ابن يقتل بيع الجناح فقط (الأشقاء يُباعون) ═══
def test_child_booking_blocks_suite_only(db_session):
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    _rsv(db, tid, 'DBL', arrival=D, dep=D + P2, room_no='401')
    _expect(db, 'HOTEL.SUITE_BLOCKED', _rsv, db, tid, 'RSUITE',
            arrival=D, dep=D + P2, room_no='J-401')
    # الشقيق 402 ما زال يُباع مفرداً
    r402 = _rsv(db, tid, 'DBL', arrival=D, dep=D + P2, room_no='402')
    assert r402.room_id == _room(db, '402').id
    # وبعد فترة الابن: الجناح يُباع كاملاً
    r_suite = _rsv(db, tid, 'RSUITE', arrival=D + P2, dep=D + P3,
                   room_no='J-401')
    assert r_suite.status == 'CONFIRMED'
    # توافر النوع: الجناح غير متاح خلال تداخل الابن
    free = available_rooms(db, tid, bid, _rt(db, tid, 'RSUITE').id,
                           D, D + P2)
    assert free == []


# ═══ التعطيل OOO بالاتجاهين ═══
def test_ooo_blocks_both_directions(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    suite = _room(db, 'J-401')
    # جناح خارج الخدمة ⟵ أبناؤه محجوبون
    suite.hk_status = 'OOO'
    suite.ooo_from, suite.ooo_to = D, D + P2
    db.flush()
    _expect(db, 'HOTEL.SUITE_BLOCKED', _rsv, db, tid, 'DBL',
            arrival=D, dep=D + P2, room_no='401')
    suite.hk_status, suite.ooo_from, suite.ooo_to = 'CLEAN', None, None
    # ابن خارج الخدمة ⟵ الجناح لا يُباع كاملاً (وأشقاؤه لا يتأثرون)
    c402 = _room(db, '402')
    c402.hk_status = 'OOO'
    c402.ooo_from, c402.ooo_to = D, D + P2
    db.flush()
    _expect(db, 'HOTEL.SUITE_BLOCKED', _rsv, db, tid, 'RSUITE',
            arrival=D, dep=D + P2, room_no='J-401')
    r401 = _rsv(db, tid, 'DBL', arrival=D, dep=D + P2, room_no='401')
    assert r401.status == 'CONFIRMED'


# ═══ التعديل والنقل يمرّان بنفس الفرض ═══
def test_modify_respects_suite_block(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    _rsv(db, tid, 'DBL', arrival=D, dep=D + P2, room_no='401')
    r_suite = _rsv(db, tid, 'RSUITE', arrival=D + P5, dep=D + P7,
                   room_no='J-401')
    from app.hotel import modify_reservation
    _expect(db, 'HOTEL.SUITE_BLOCKED', modify_reservation, db,
            res=r_suite, actor_id='t', new_arrival=D)


def test_room_move_respects_suite_block(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r102 = _rsv(db, tid, 'DBL', arrival=D, dep=D + P2, room_no='102')
    out = check_in(db, res=r102, actor_id='t')
    assert out['folio_id']
    _rsv(db, tid, 'RSUITE', arrival=D, dep=D + P3, room_no='J-401')  # يقفل أبناءه
    _expect(db, 'HOTEL.SUITE_BLOCKED', room_move, db, res=r102,
            new_room_id=_room(db, '402').id, reason='طلب النزيل',
            actor_id='t')


# ═══ حارس الفك: جناح عليه حجز نشط ⟵ ممنوع فك أبنائه ═══
def test_unlink_guard_with_active_suite_booking(client, db_session,
                                                auth_hdr):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r_suite = _rsv(db, tid, 'RSUITE', arrival=D + P5, dep=D + P7,
                   room_no='J-401')
    db.commit()
    rid = _room(db, '401').id
    r = client.patch(f'/api/hotel/rooms/{rid}', headers=auth_hdr, json={
        'set_parent': True, 'parent_room_no': ''})
    assert r.status_code == 400
    assert r.json()['error']['code'] == 'HOTEL.SUITE_LINKED_BOOKINGS'
    # بعد الإلغاء: الفك مسموح
    cancel_reservation(db, res=r_suite, actor_id='t', reason='إلغاء اختبار')
    db.commit()
    r = client.patch(f'/api/hotel/rooms/{rid}', headers=auth_hdr, json={
        'set_parent': True, 'parent_room_no': ''})
    assert r.status_code == 200
    assert _room(db, '401').parent_room_id is None


# ═══ التدقيق الليلي على الجناح: سعر النوع RSUITE (الصورة الليلية) ═══
def test_night_audit_posts_suite_rate(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid, 'RSUITE', arrival=D, dep=D + P2, room_no='J-401')
    out = check_in(db, res=r, actor_id='t')
    run_night_audit(db, tenant_id=tid, actor_id='t')
    totals = folio_totals(db, tid, out['folio_id'])
    assert totals['charges'] == Decimal('300')      # سعر RSUITE الأساسي


# ═══ CRUD الأنواع + تغيير السعر الأساسي ينعكس فوراً ويوثَّق ═══
def test_room_types_crud_and_pricing(client, db_session, auth_hdr):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = client.post('/api/hotel/room-types', headers=auth_hdr, json={
        'code': 'TWN', 'name_ar': 'توأم بإطلالة', 'base_rate': '95'})
    assert r.status_code == 201
    r = client.post('/api/hotel/room-types', headers=auth_hdr, json={
        'code': 'TWN', 'name_ar': 'مكرر', 'base_rate': '1'})
    assert r.status_code == 400
    assert r.json()['error']['code'] == 'HOTEL.RTYPE_EXISTS'
    rid = _rt(db, tid, 'TWN').id
    r = client.patch(f'/api/hotel/room-types/{rid}', headers=auth_hdr,
                     json={'base_rate': '120', 'beds': 'سريران توأم'})
    assert r.status_code == 200 and Decimal(r.json()['base_rate']) == 120
    rate, origin = resolve_night_rate(db, tid, rid, None, D)
    assert rate == Decimal('120') and origin == 'BASE'
    acts = [a for (a,) in db.execute(select(m.AuditLog.action).where(
        m.AuditLog.entity == 'room_types')).all()]
    assert 'roomtype.create' in acts and 'roomtype.update' in acts


# ═══ خطط الأسعار: CRUD + التسعير (الخطة تهزم الأساس) ═══
def test_rate_plans_crud_and_plan_beat_base(client, db_session, auth_hdr):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = client.post('/api/hotel/rate-plans', headers=auth_hdr, json={
        'code': 'HB', 'name_ar': 'نصف إقامة', 'ref_rate': '30',
        'cancel_policy': 'غير قابل للاسترداد', 'meals_included': ['عشاء']})
    assert r.status_code == 201
    pid = [p for p in client.get('/api/hotel/rate-plans',
                                 headers=auth_hdr).json()
           if p['code'] == 'HB'][0]['id']
    rt = _rt(db, tid, 'DBL')   # أساس 85
    rate, origin = resolve_night_rate(db, tid, rt.id, pid, D)
    assert rate == Decimal('115') and origin == 'PLAN'   # 85 + 30
    r = client.patch(f'/api/hotel/rate-plans/{pid}', headers=auth_hdr,
                     json={'ref_rate': '20', 'min_nights': 2})
    assert r.status_code == 200
    rate, _ = resolve_night_rate(db, tid, rt.id, pid, D)
    assert rate == Decimal('105')   # 85 + 20
    r = client.post('/api/hotel/rate-plans', headers=auth_hdr, json={
        'code': 'HB', 'name_ar': 'مكررة'})
    assert r.status_code == 400
    assert r.json()['error']['code'] == 'HOTEL.RPLAN_EXISTS'


# ═══ تقويم الأسعار: تعبئة مدى + upsert + التقويم يهزم الجميع ═══
def test_rate_calendar_bulk_and_resolution(client, db_session, auth_hdr):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    payload = {'room_type_code': 'RSUITE', 'date_from': str(D),
               'date_to': str(D + timedelta(4)), 'price': '450',
               'day_type': 'EEKEND'}
    r = client.post('/api/hotel/rate-calendar/bulk', headers=auth_hdr,
                    json=payload)
    assert r.status_code == 201 and r.json() == {
        'days': 5, 'created': 5, 'updated': 0}
    # upsert: نفس المدى بسعر مختلف = تحديث بلا تكرار
    payload['price'] = '500'
    r = client.post('/api/hotel/rate-calendar/bulk', headers=auth_hdr,
                    json=payload)
    assert r.json() == {'days': 5, 'created': 0, 'updated': 5}
    priced = price_stay(db, tid, _rt(db, tid, 'RSUITE').id, None,
                        D, D + timedelta(5))
    assert all(p['origin'] == 'CALENDAR' for p in priced)
    assert sum(p['rate'] for p in priced) == Decimal('2500')
    # الحذف موثق
    rows = client.get('/api/hotel/rate-calendar', headers=auth_hdr,
                      params={'room_type': 'RSUITE', 'date_from': str(D),
                              'date_to': str(D + timedelta(4))}).json()
    assert len(rows) == 5 and rows[0]['day_type'] == 'EEKEND'
    r = client.delete(f"/api/hotel/rate-calendar/{rows[0]['id']}",
                      headers=auth_hdr)
    assert r.status_code == 200 and r.json()['deleted']
    # مدى > 92 يوماً مرفوض
    payload['date_to'] = str(D + timedelta(120))
    r = client.post('/api/hotel/rate-calendar/bulk', headers=auth_hdr,
                    json=payload)
    assert r.status_code == 400
    assert r.json()['error']['code'] == 'HOTEL.RANGE_TOO_LONG'


# ═══ الخدمات الإضافية CRUD ═══
def test_extras_crud(client, db_session, auth_hdr):
    r = client.post('/api/hotel/extras', headers=auth_hdr, json={
        'code': 'MINIBAR_VIP', 'name_ar': 'ميني بار فاخر', 'price': '18',
        'revenue_account_code': '4201'})
    assert r.status_code == 201
    eid = r.json()['id']
    r = client.patch(f'/api/hotel/extras/{eid}', headers=auth_hdr,
                     json={'price': '21', 'is_active': False})
    assert r.status_code == 200 and Decimal(r.json()['price']) == 21
    rows = client.get('/api/hotel/extras?all=true',
                      headers=auth_hdr).json()
    row = [x for x in rows if x['code'] == 'MINIBAR_VIP'][0]
    assert row['is_active'] is False
    active = client.get('/api/hotel/extras', headers=auth_hdr).json()
    assert 'MINIBAR_VIP' not in [x['code'] for x in active]


# ═══ RBAC: موظف استقبال يقرأ ولا يدير الأسعار ═══
def test_rbac_receptionist_cannot_manage_rates(client, db_session,
                                               auth_hdr):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    role = db.execute(select(m.Role).where(
        m.Role.tenant_id == tid, m.Role.code == 'RECEPTIONIST')).scalar_one()
    u = m.User(id=new_uuid(), tenant_id=tid, username='recep1',
               full_name='موظف استقبال', is_active=True,
               password_hash=hash_password('rec123!Change'),
               created_at=utcnow())
    db.add(u)
    db.flush()
    db.add(m.UserRole(user_id=u.id, role_id=role.id))
    db.commit()
    tok = client.post('/api/auth/login', json={
        'username': 'recep1', 'password': 'rec123!Change'}).json()['access_token']
    hdr = {'Authorization': f'Bearer {tok}'}
    # قراءة: مسموحة (frontdesk.view)
    assert client.get('/api/hotel/rooms', headers=hdr).status_code == 200
    assert client.get('/api/hotel/rate-plans', headers=hdr).status_code == 200
    # إدارة: ممنوعة (لا rooms.manage ولا rates.manage ولا extras.manage)
    assert client.post('/api/hotel/rooms', headers=hdr, json={
        'room_no': '999', 'room_type_code': 'DBL'}).status_code == 403
    assert client.post('/api/hotel/rate-plans', headers=hdr, json={
        'code': 'X1', 'name_ar': 'خطة'}).status_code == 403
    assert client.post('/api/hotel/rate-calendar/bulk', headers=hdr, json={
        'room_type_code': 'DBL', 'date_from': str(D), 'date_to': str(D),
        'price': '1'}).status_code == 403


# ═══ لقط المزامنة: حقول الجناح ضمن حمولة الغرفة ═══
def test_sync_room_payload_includes_suite_fields(db_session):
    db, factory, seed = db_session
    assert {'kind', 'parent_room_id'} <= set(SK.SYNC_REGISTRY['ROOM']['fields'])
    suite = _room(db, 'J-401')
    payload = SK._master_payload(suite, SK.SYNC_REGISTRY['ROOM']['fields'])
    assert payload['kind'] == 'SUITE_UNIT'
    child = _room(db, '401')
    payload2 = SK._master_payload(child, SK.SYNC_REGISTRY['ROOM']['fields'])
    assert payload2['parent_room_id'] == suite.id
    assert payload2['kind'] == 'STANDARD'


# ═══ انحدار بنيوي (ADR-0035): إلغاء الحجز لا يعيد تعيين غرفته — وإلا
# فتح التسكين المباشر باب الحجز المزدوج المستحيل منذ G2 ═══
def test_cancel_keeps_room_assignment(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    r = _rsv(db, tid, 'DBL', arrival=D, dep=D + P2, room_no='102')
    cancel_reservation(db, res=r, actor_id='t', reason='إلغاء اختبار')
    db.flush()
    assert r.room_id == _room(db, '102').id, \
        'الإلغاء أسقط الغرفة — درع التسكين المضاد للحجز المزدوج انكسر'


# ═══ الحالة المشتقة: suite_block_reason يعيد السبب العربي الموثق ═══
def test_suite_block_reason_messages(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    _rsv(db, tid, 'RSUITE', arrival=D, dep=D + P2, room_no='J-401')
    reason = suite_block_reason(db, tid, _room(db, '401'), D, D + P2)
    assert reason and 'الجناح J-401' in reason
    assert suite_block_reason(db, tid, _room(db, '401'),
                              D + P2, D + P3) is None
