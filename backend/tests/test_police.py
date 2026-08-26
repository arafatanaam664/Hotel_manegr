"""اختبارات وحدة «المعلومية اليومية» للبحث الجنائي (0.14.0 — ADR-0038):
النطاق «كل من لامس الفندق». المرافقون صفاً صفاً. مطابقة القالب خلية
بخلية. الأرشيف يعيد الملف كما أُرسل. لا PII صريحة خارج الملف نفسه. RBAC."""
import io
from datetime import date, timedelta

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app import models as m
from app.hotel import create_reservation
from app.police_report import (WEEKDAYS_AR, collect_payload, payload_sha256)
from app.security import encrypt_pii, new_uuid, utcnow

TODAY = date.today()
Y = TODAY - timedelta(1)
T2 = TODAY + timedelta(2)


# ── مساعدات ──────────────────────────────────────────────
def _rt(db, tid, code):
    return db.execute(select(m.RoomType).where(
        m.RoomType.tenant_id == tid, m.RoomType.code == code)).scalar_one()


def _branch(db, tid):
    return db.execute(select(m.Branch).where(
        m.Branch.tenant_id == tid)).scalar_one()


def _mk_guest(db, tid, name='نزيل الاختبار الفني', *, id_number='55512345',
              id_type='شخصية', phone='771000111'):
    g = m.Guest(id=new_uuid(), tenant_id=tid, full_name=name, phone=phone,
                id_number_enc=encrypt_pii(id_number) if id_number else '',
                id_type=id_type, id_issue_place='تعز',
                id_issue_date=date(2020, 1, 15), nationality='يمني',
                created_at=utcnow())
    db.add(g)
    db.flush()
    return g


def _stay(db, tid, *, guest, arrival=Y, dep=T2, room_type='SGL',
          status='CHECKED_IN', purpose='علاج', room_no=None):
    r = create_reservation(
        db, tenant_id=tid, branch_id=_branch(db, tid).id, guest_id=guest.id,
        room_type_id=_rt(db, tid, room_type).id, arrival=arrival,
        departure=dep, actor_id='police-test',
        room_id=None if not room_no else db.execute(
            select(m.Room).where(m.Room.room_no == room_no)).scalar_one().id,
        trip={'purpose': purpose, 'origin_gov': 'إب',
              'origin_district': 'العدين', 'vehicle_note': '',
              'police_notes': 'مع العائلة'})
    r.status = status
    if status in ('CHECKED_IN', 'CHECKED_OUT'):
        r.checked_in_at = utcnow()
    db.flush()
    return r


def _companion(db, tid, rid, name, *, id_number='77788899', order=1):
    c = m.ReservationCompanion(
        id=new_uuid(), tenant_id=tid, reservation_id=rid, full_name=name,
        id_type='جواز', id_number_enc=encrypt_pii(id_number),
        id_issue_place='جدة', id_issue_date=date(2022, 5, 30),
        origin_gov='السعودية', origin_district='جدة',
        sort_order=order, created_at=utcnow())
    db.add(c)
    db.flush()
    return c


def _xlsx(resp):
    assert resp.status_code == 200, resp.text[:400]
    wb = load_workbook(io.BytesIO(resp.content))
    return wb.worksheets[0]


# ═══ الصلاحيات مزروعة ═══
def test_catalog_and_roles_have_police_report(client, db_session, auth_hdr):
    _, _, seed = db_session
    r = client.get('/api/org/permissions', headers=auth_hdr)
    assert r.status_code == 200
    flat = [(g['name'], p['code']) for g in r.json() for p in g['perms']]
    assert any(c == 'police.report' for _, c in flat)
    name = next(g for g, c in flat if c == 'police.report')
    assert 'الاستقبال' in name  # ضمن مجموعة الاستقبال لا الإدارة
    for role in client.get('/api/org/roles', headers=auth_hdr).json():
        if role['code'] in ('RECEPTIONIST', 'NIGHT_AUDITOR', 'GM'):
            assert 'police.report' in role['permissions'], role['code']


# ═══ بيانات الرحلة + المرافقون عبر API ═══
def test_trip_fields_capture_and_companions(client, db_session, auth_hdr):
    db, _, seed = db_session
    tid = seed['tenant_id']
    g = client.post('/api/hotel/guests', headers=auth_hdr, json={
        'full_name': 'ضيف وكالة اختبارية رباعي الاسم', 'phone': '700111222',
        'id_number': '12345678', 'id_type': 'جواز', 'id_issue_place': 'صنعاء',
        'id_issue_date': '2021-03-04'}).json()
    assert g['has_id'] and g['id_type'] == 'جواز'

    r = client.post('/api/hotel/reservations', headers=auth_hdr, json={
        'guest_id': g['id'], 'room_type_code': 'SGL',
        'arrival_date': str(Y), 'departure_date': str(T2),
        'purpose': 'زيارة', 'origin_gov': 'تعز', 'origin_district': 'خدير',
        'vehicle_note': 'هايلوكس أبيض 1234'})
    assert r.status_code == 201, r.text
    rid = r.json()['id']
    assert r.json()['purpose'] == 'زيارة'
    assert r.json()['origin_district'] == 'خدير'

    c1 = client.post(f'/api/hotel/reservations/{rid}/companions',
                     headers=auth_hdr, json={
                         'full_name': 'مرافق أول خيالي', 'id_type': 'شخصية',
                         'id_number': '999888777', 'origin_gov': 'إب'})
    assert c1.status_code == 201, c1.text
    assert c1.json()['id_masked'].startswith('****')

    detail = client.get(f'/api/hotel/reservations/{rid}',
                        headers=auth_hdr).json()
    assert len(detail['companions']) == 1
    assert detail['companions'][0]['full_name'] == 'مرافق أول خيالي'
    assert '999888777' not in str(detail)  # لا يظهر رقم صريح في أي رد

    cid = detail['companions'][0]['id']
    p = client.patch(f'/api/hotel/companions/{cid}', headers=auth_hdr,
                     json={'origin_district': 'النادرة'})
    assert p.json()['origin_district'] == 'النادرة'
    d = client.delete(f'/api/hotel/companions/{cid}', headers=auth_hdr)
    assert d.json()['deleted'] is True
    assert client.get(f'/api/hotel/reservations/{rid}',
                      headers=auth_hdr).json()['companions'] == []


def test_id_type_validation_rejects_free_text(client, db_session, auth_hdr):
    r = client.post('/api/hotel/guests', headers=auth_hdr, json={
        'full_name': 'نزيل تجريبي فقط', 'id_type': 'بطاقة مدرسية'})
    assert r.status_code == 422


def test_guest_patch_updates_police_fields(client, db_session, auth_hdr):
    g = client.post('/api/hotel/guests', headers=auth_hdr,
                    json={'full_name': 'نزيل قبل التحديث'}).json()
    p = client.patch(f"/api/hotel/guests/{g['id']}", headers=auth_hdr,
                     json={'id_type': 'جواز', 'id_number': 'P7654',
                           'id_issue_place': 'عدن',
                           'id_issue_date': '2019-11-20'})
    assert p.status_code == 200, p.text
    body = p.json()
    assert body['id_type'] == 'جواز' and body['has_id'] is True
    assert 'P7654' not in str(body)
    glist = client.get('/api/hotel/guests', headers=auth_hdr).json()
    mine = next(x for x in glist if x['id'] == g['id'])
    assert mine['id_issue_place'] == 'عدن'


# ═══ النطاق: «كل من لامس الفندق ذلك اليوم» ═══
def test_scope_all_who_touched_the_day(db_session):
    db, _, seed = db_session
    tid = seed['tenant_id']
    in_house = _stay(db, tid, guest=_mk_guest(db, tid, 'مقيم اختبار'))
    left_today = _stay(db, tid, guest=_mk_guest(db, tid, 'غادر اختبار'),
                       arrival=Y - timedelta(1), dep=TODAY,
                       status='CHECKED_OUT')
    cancelled = _stay(db, tid, guest=_mk_guest(db, tid, 'ملغي اختبار'),
                      status='CANCELLED')
    p = collect_payload(db, tid, TODAY)
    names = [r['name'] for r in p['rows']]
    assert 'مقيم اختبار' in names      # ما زال في الفندق
    assert 'غادر اختبار' in names      # غادر في اليوم نفسه — لمس الفندق فعلاً
    assert 'ملغي اختبار' not in names  # الملغي لا يُبلَّغ عنه أبداً
    assert p['stays_count'] == 2
    _ = (in_house, left_today, cancelled)


def test_scope_day_before_arrival_shows_nothing(db_session):
    db, _, seed = db_session
    before = collect_payload(db, seed['tenant_id'], date(2000, 1, 1))
    assert before['rows'] == [] and before['stays_count'] == 0


# ═══ الملف الذهبي: مطابق للقالب خلية بخلية ═══
@pytest.fixture()
def golden(client, db_session, auth_hdr):
    db, _, seed = db_session
    tid = seed['tenant_id']
    g = _mk_guest(db, tid, 'معاذ احمد امين الجابري', id_number='11252457',
                  id_type='جواز', phone='772965329')
    r = _stay(db, tid, guest=g, purpose='مرض')
    _companion(db, tid, r.id, 'سعاد إبراهيم زين أبو الحياء', order=1)
    _companion(db, tid, r.id, 'زكيه عبده احمد ياسر', id_number='11252456',
               order=2)
    db.commit()
    resp = client.get(f'/api/hotel/police-report/download?date={TODAY}',
                      headers=auth_hdr)
    return resp, r


def test_xlsx_matches_template_structure(golden):
    resp, _ = golden
    ws = _xlsx(resp)
    assert ws.sheet_view.rightToLeft is True       # ورقة عربية RTL
    assert ws.sheet_view.showGridLines is False
    assert ws.page_setup.orientation == 'landscape'
    assert str(ws.page_setup.paperSize) == '9'     # A4
    # عرض الأعمدة كما في قالب دبي السياحي
    assert abs(ws.column_dimensions['C'].width - 27.1) < 0.2
    assert abs(ws.column_dimensions['N'].width - 29.4) < 0.2
    # الترويسة الرسمية
    assert 'وزارة' in str(ws['A3'].value)
    assert 'معلومية النزلاء ليوم' in str(ws['D5'].value)
    assert WEEKDAYS_AR[TODAY.weekday()] in str(ws['D5'].value)
    assert ws['G5'].value.date() == TODAY
    assert '10C0000' in ws['G5'].number_format     # تنسيق عربي «24 يونيو 2024»
    # رؤوس الأعمدة الـ14 بعينها
    assert ws['A6'].value == 'م'
    assert ws['B6'].value == 'رقم الغرفة'
    assert 'اسم النزيل' in str(ws['C6'].value)
    assert ws['D6'].value == 'تاريخ القدوم'
    assert ws['F6'].value == 'الجهة القادم منها'
    assert 'الهوية' in str(ws['H6'].value)
    assert ws['F7'].value == 'المحافظة' and ws['G7'].value == 'المديرية'
    assert ws['H7'].value == 'نوعها' and ws['I7'].value == 'رقمها'
    assert ws['J7'].value == 'مكان الإصدار'
    assert ws['K6'].value == 'ت الإصدار'
    assert ws['L6'].value == 'رقم التلفون'
    assert ws['M6'].value == 'وقت النزول'
    assert 'المرافقين' in str(ws['N6'].value)
    assert 'المركبات' in str(ws['O6'].value)
    assert ws.print_area.startswith("'ورقة1'!$A$1:$O$")


def test_xlsx_group_rows_and_merges(golden):
    resp, stay = golden
    ws = _xlsx(resp)
    # مجموعة واحدة: رئيسي + مرافقان = صفوف 8-10 بتسلسل م متصل
    assert [ws[f'A{r}'].value for r in (8, 9, 10)] == [1, 2, 3]
    assert ws['C8'].value == 'معاذ احمد امين الجابري'
    assert ws['C9'].value == 'سعاد إبراهيم زين أبو الحياء'
    assert ws['C10'].value == 'زكيه عبده احمد ياسر'
    # رقم الهوية يظهر صريحاً داخل الملف (هدفه) — وتاريخ قدوم النزيل
    assert ws['I8'].value == '11252457'
    assert ws['I9'].value == '77788899'
    assert ws['D8'].value.date() == Y
    assert ws['E8'].value == 'مرض'
    assert ws['F8'].value == 'إب' and ws['G8'].value == 'العدين'
    assert ws['L8'].value == '772965329'
    assert str(ws['N8'].value) == 'مع العائلة'
    assert ws['M8'].value            # وقت النزول مسجَّل
    # خلايا المجموعة مُدمجة عمودياً كما في القالب (B15:B17 نموذجاً)
    merged = {str(rng) for rng in ws.merged_cells.ranges}
    assert 'B8:B10' in merged and 'D8:D10' in merged
    assert 'N8:N10' in merged
    # صفا المرافقين بلا غرفة/قدوم مستقلين (قيمتهما في أعلى الدمج)
    assert ws['B9'].value is None and ws['D9'].value is None


def test_filename_arabic_encoded(golden):
    resp, _ = golden
    cd = resp.headers.get('content-disposition', '')
    assert "filename*=UTF-8''" in cd
    assert '%D9%85%D8%B9%D9%84%D9%88%D9%85%D9%8A%D8%A9' in cd  # «معلومية»


# ═══ الأرشيف: «ما أُرسل فعلاً» يُعاد حرفياً ═══
def test_archive_reproduces_exactly_what_was_sent(client, db_session,
                                                  auth_hdr):
    db, _, seed = db_session
    g = _mk_guest(db, seed['tenant_id'], 'اسم قبل التصحيح الرسمي')
    _stay(db, seed['tenant_id'], guest=g)
    db.commit()
    first = client.get(f'/api/hotel/police-report/download?date={TODAY}',
                       headers=auth_hdr)
    assert first.status_code == 200
    runs = client.get('/api/hotel/police-report/runs', headers=auth_hdr)
    run = runs.json()[0]
    assert run['report_date'] == str(TODAY) and run['generated_by'] == 'admin'

    # تعديل بيانات النزيل بعد الإرسال — شائع جداً
    client.patch(f"/api/hotel/guests/{g.id}", headers=auth_hdr,
                 json={'full_name': 'اسم بعد التصحيح الرسمي'})
    db.expire_all()
    again = client.get(f"/api/hotel/police-report/runs/{run['id']}/download",
                       headers=auth_hdr)
    ws = _xlsx(again)
    assert ws['C8'].value == 'اسم قبل التصحيح الرسمي'   # كما أُرسل حرفياً
    # والمعاينة الحالية تعكس الجديد — لا خلط بين «الآن» و«المرسل»
    pv = client.get(f'/api/hotel/police-report/preview?date={TODAY}',
                    headers=auth_hdr).json()
    assert pv['rows'][0]['name'] == 'اسم بعد التصحيح الرسمي'
    # بصمة الأرشيف مستقرة وتُحسب من الحمولة المخزنة نفسها
    db_run = db.get(m.PoliceReportRun, run['id'])
    assert db_run.sha256 == payload_sha256(db_run.payload)


def test_run_audit_attributed(client, db_session, auth_hdr):
    db, _, seed = db_session
    _stay(db, seed['tenant_id'], guest=_mk_guest(db, seed['tenant_id']))
    db.commit()
    client.get(f'/api/hotel/police-report/download?date={TODAY}',
               headers=auth_hdr)
    rows = db.execute(select(m.AuditLog).where(
        m.AuditLog.action == 'police.report.generate')).scalars().all()
    assert rows and rows[0].actor_user_id          # موثَّق باسم فاعله
    assert rows[0].actor_type == 'user'


# ═══ الضمانات: نواقص، يوم فارغ، RBAC، خصوصية المعاينة ═══
def test_missing_id_warns_but_never_blocks(client, db_session, auth_hdr):
    db, _, seed = db_session
    g = _mk_guest(db, seed['tenant_id'], 'بلا هوية اختبار', id_number='')
    _stay(db, seed['tenant_id'], guest=g, purpose='')
    db.commit()
    pv = client.get(f'/api/hotel/police-report/preview?date={TODAY}',
                    headers=auth_hdr)
    assert pv.status_code == 200
    assert any('بلا رقم هوية' in w for w in pv.json()['warnings'])
    assert pv.json()['rows'][0]['has_id'] is False
    dl = client.get(f'/api/hotel/police-report/download?date={TODAY}',
                    headers=auth_hdr)
    assert dl.status_code == 200   # تنبيه لا منع — المسؤولية للفندق


def test_empty_day_download_404(client, db_session, auth_hdr):
    r = client.get('/api/hotel/police-report/download?date=2000-01-01',
                   headers=auth_hdr)
    assert r.status_code == 404
    assert r.json()['error']['code'] == 'POLICE.EMPTY_DAY'


def test_preview_never_leaks_plain_id(client, db_session, auth_hdr):
    db, _, seed = db_session
    _stay(db, seed['tenant_id'], guest=_mk_guest(
        db, seed['tenant_id'], id_number='SECRET-99887'))
    db.commit()
    pv = client.get(f'/api/hotel/police-report/preview?date={TODAY}',
                    headers=auth_hdr)
    assert pv.status_code == 200
    assert 'SECRET-99887' not in pv.text
    assert pv.json()['rows'][0]['has_id'] is True


def test_rbac_denies_without_police_report(client, db_session, auth_hdr):
    # دور مخصص بلا صلاحية المعلومية + مستخدم به
    role = client.post('/api/org/roles', headers=auth_hdr, json={
        'name': 'نظار بلا إرسال', 'permissions': ['reservations.view']}).json()
    u = client.post('/api/org/users', headers=auth_hdr, json={
        'username': 'watcher1', 'full_name': 'موظف مراقبة فقط',
        'password': 'WatchOnly#2026', 'role_codes': [role['code']]}).json()
    tk = client.post('/api/auth/login', json={
        'username': 'watcher1', 'password': 'WatchOnly#2026'})
    assert tk.status_code == 200
    hdr = {'Authorization': f"Bearer {tk.json()['access_token']}"}
    for url in (f'/api/hotel/police-report/preview?date={TODAY}',
                f'/api/hotel/police-report/download?date={TODAY}',
                '/api/hotel/police-report/runs'):
        assert client.get(url, headers=hdr).status_code == 403, url
    _ = u


# ═══ ترويسة المنشأة القابلة للضبط ═══
def test_header_from_tenant_settings(client, db_session, auth_hdr):
    db, _, seed = db_session
    _stay(db, seed['tenant_id'], guest=_mk_guest(db, seed['tenant_id']))
    db.commit()
    p = client.patch('/api/org/tenant/header', headers=auth_hdr, json={
        'address': 'شارع جمال — الاختبار', 'district': 'القاهرة',
        'office_label': 'م / تعز'})
    assert p.status_code == 200
    dl = client.get(f'/api/hotel/police-report/download?date={TODAY}',
                    headers=auth_hdr)
    ws = _xlsx(dl)
    assert 'الاختبار' in str(ws['M3'].value)
    assert 'القاهرة' in str(ws['M4'].value)
    assert ws['A4'].value == 'م / تعز'
    t = client.get('/api/org/tenant', headers=auth_hdr).json()
    assert t['district'] == 'القاهرة' and t['office_label'] == 'م / تعز'
