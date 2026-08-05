"""اختبارات لوحة الشركة (ملف 08) — معايير القبول §8:
1) تحصيل تجديد ← ترخيص جديد يصل فوراً عبر Edge (بلا خطوة يدوية إضافية)
2) MRR يطابق مجموع اشتراكات نشطة حسابياً بلا انحراف (Decimal)
3) تذكرة P1 ← إشعار المناوب خلال 60 ثانية
4) مستخدم دعم لا يستطيع إصدار ترخيص (RBAC سلبي — وأقل امتياز §7)
5) كل تغيير حالة اشتراك له سبب + مستخدم + طابع — بلا ثغرة
+ MFA إلزامي بلا استثناء (§7)، اعتماد ثانٍ لتجاوز الخطة (§4)، SLA/تصعيد
  وسير التذاكر (§5)، صحة الأسطول وأعلام البصمة (§6+07§4-5)، Edge محدودة (§1).
"""
import base64
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
import pyotp
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

os.environ.setdefault('VENDOR_DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('VENDOR_JWT_SECRET', 'vendor-test-secret-0123456789abcdef')
os.environ.setdefault('VENDOR_MFA_REQUIRED', 'true')

from cryptography.hazmat.primitives import serialization  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import licensing as lic  # noqa: E402
import vendor.models as m  # noqa: E402
from vendor.config import get_vendor_settings  # noqa: E402
from vendor.db import VendorBase, get_vdb  # noqa: E402
from vendor.main import create_vendor_app  # noqa: E402
from vendor.seed import seed_vendor  # noqa: E402

ADMIN = {'username': 'director', 'password': 'vendor123!Change'}
ADMIN_TOTP = 'JBSWY3DPEHPK3PXP'


# ═══ تجهيزات ═══
@pytest.fixture(scope='module')
def signing_keys(tmp_path_factory):
    """مفتاح توقيع اختباري — يُولّد ويُرمى، لا يُخزَّن بالمستودع (07 §7-5)."""
    d = tmp_path_factory.mktemp('vkeys')
    priv = lic.gen_private_pem()
    p = d / 'license_private.pem'
    p.write_bytes(priv)
    return {'priv': priv, 'path': str(p),
            'pub': lic.public_pem_from_private(priv)}


@pytest.fixture()
def vdb(signing_keys, monkeypatch, tmp_path):
    monkeypatch.setenv('VENDOR_LICENSE_PRIVATE_KEY_PATH',
                       signing_keys['path'])
    get_vendor_settings.cache_clear()
    engine = create_engine(f'sqlite:///{tmp_path}/v.db',
                           connect_args={'check_same_thread': False,
                                         'timeout': 15})

    @event.listens_for(engine, 'connect')
    def _fk(conn, _):
        cur = conn.cursor()
        cur.execute('PRAGMA foreign_keys=ON')
        cur.close()

    VendorBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                           future=True)
    db = factory()
    seed_vendor(db)
    yield db, factory
    db.close()
    engine.dispose()


@pytest.fixture()
def vclient(vdb):
    db, factory = vdb
    app = create_vendor_app()

    def override():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_vdb] = override
    with TestClient(app) as c:
        c.vdb = db
        yield c


def _login_director(c):
    r = c.post('/api/v1/auth/login', json={**ADMIN,
               'totp_code': pyotp.TOTP(ADMIN_TOTP).now()})
    assert r.status_code == 200, r.text
    return {'X-Vendor': '1', 'Authorization':
            f'Bearer {r.json()["access_token"]}'}


def _enroll_and_login(c, username, password='vendor123!Change'):
    """أول دخول: تسجيل TOTP إجباري ثم دخول كامل (§7 بلا استثناء)."""
    r = c.post('/api/v1/auth/login',
               json={'username': username, 'password': password})
    assert r.status_code == 200 and r.json()['mfa_required']
    secret = r.json()['totp_secret']
    r2 = c.post('/api/v1/auth/mfa/confirm',
                json={'enroll_token': r.json()['enroll_token'],
                      'totp_code': pyotp.TOTP(secret).now()})
    assert r2.status_code == 200, r2.text
    return {'Authorization': f'Bearer {r2.json()["access_token"]}'}


def _verify_sig(pub_pem: bytes, payload: dict) -> bool:
    pub = serialization.load_pem_public_key(pub_pem)
    pub.verify(base64.b64decode(payload['signature']), lic._canon(payload))
    return True


# ═══ §7 MFA إلزامي بلا استثناء ═══
def test_mfa_mandatory_enroll_flow(vclient):
    # دخول بلا رمز ثنائي لمستخدم مفعّل = رفض
    r = vclient.post('/api/v1/auth/login', json=ADMIN)
    assert r.status_code == 401
    assert r.json()['error']['code'] == 'VND.MFA_REQUIRED'
    # تسجيل إجباري أول مرة: سر مرة واحدة + otpauth + تأكيد برمز
    r = vclient.post('/api/v1/auth/login',
                     json={'username': 'support1',
                           'password': 'vendor123!Change'})
    j = r.json()
    assert j['mfa_required'] and not j['enrolled']
    assert 'otpauth://' in j['otpauth'] and len(j['totp_secret']) >= 16
    # رمز خاطئ يُرفض
    r = vclient.post('/api/v1/auth/mfa/confirm',
                     json={'enroll_token': j['enroll_token'],
                           'totp_code': '000000'})
    assert r.status_code == 400
    # رمز صحيح = تفعيل + وصول
    code = pyotp.TOTP(j['totp_secret']).now()
    r = vclient.post('/api/v1/auth/mfa/confirm',
                     json={'enroll_token': j['enroll_token'],
                           'totp_code': code})
    assert r.status_code == 200 and r.json()['enabled']
    hdr = {'Authorization': f'Bearer {r.json()["access_token"]}'}
    assert vclient.get('/api/v1/clients', headers=hdr).status_code == 200


def test_no_access_before_mfa_enrollment(vclient):
    db = vclient.vdb
    u = db.execute(select(m.VendorUser).where(
        m.VendorUser.username == 'sales1')).scalar_one()
    from vendor.security import create_token
    token = create_token(user_id=u.id)  # رمز سليم لكن بلا MFA
    r = vclient.get('/api/v1/clients',
                    headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 401
    assert r.json()['error']['code'] == 'VND.MFA_ENROLL_REQUIRED'


# ═══ §2 CRM + قبول §8-5 ═══
def test_client_create_and_status_history_no_gap(vclient):
    hdr = _enroll_and_login(vclient, 'sales1')
    r = vclient.post('/api/v1/clients', headers=hdr, json={
        'legal_name': 'فندق الاختبار الجديد', 'trade_name': 'اختبار',
        'package': 'LOCAL', 'modules': ['ACCOUNTING', 'HOTEL'],
        'plan_code': 'START-Y', 'rooms_count': 30,
        'expiry_date': str(date.today() + timedelta(days=365)),
        'status': 'ACTIVE', 'open_reason': 'توقيع عقد مبدئي'})
    assert r.status_code == 201, r.text
    code = r.json()['code']
    # §8-5: سجل الحالة له سبب + مستخدم + طابع
    h = r.json()['history'][0]
    assert h['reason'] == 'توقيع عقد مبدئي' and h['by'] and h['at']
    # تغيير حالة بلا سبب = مرفوض (لا ثغرة)
    r = vclient.post(f'/api/v1/clients/{code}/status', headers=hdr,
                     json={'to_status': 'SUSPENDED', 'reason': '  '})
    assert r.status_code == 422 or r.status_code == 400
    # وبسبب موثق = يمر ويُؤرشف
    r = vclient.post(f'/api/v1/clients/{code}/status', headers=hdr,
                     json={'to_status': 'SUSPENDED',
                           'reason': 'قرار إداري موثق ١٢٣'})
    assert r.status_code == 200 and r.json()['status'] == 'SUSPENDED'
    hist = r.json()['history']
    assert hist[0]['to'] == 'SUSPENDED'
    assert hist[0]['reason'] == 'قرار إداري موثق ١٢٣'
    assert hist[0]['by'] and hist[0]['at']


# ═══ §3 فوترة + قبول §8-1/§8-2 ═══
def test_invoice_discount_ceiling(vclient):
    hdr = _enroll_and_login(vclient, 'sales1')
    r = vclient.post('/api/v1/invoices', headers=hdr, json={
        'client_code': 'CLI-001', 'plan_code': 'PRO-Y',
        'period_from': '2026-01-01', 'period_to': '2026-12-31',
        'discount_pct': '25'})   # سقف الخطة 20
    assert r.status_code == 400
    assert r.json()['error']['code'] == 'BILL.DISCOUNT_OVER_CEILING'


def test_full_payment_triggers_auto_license_edge_delivery(vclient,
                                                          signing_keys):
    """قبول §8-1: سداد كامل ← ترخيص مجدد آلي ← يصل العميل فوراً عبر Edge."""
    sales = _enroll_and_login(vclient, 'sales1')
    fin = _enroll_and_login(vclient, 'finance1')
    r = vclient.post('/api/v1/invoices', headers=sales, json={
        'client_code': 'CLI-001', 'plan_code': 'PRO-Y',
        'period_from': str(date.today()),
        'period_to': str(date.today() + timedelta(days=365)),
        'kind': 'RENEWAL'})
    assert r.status_code == 201, r.text
    inv = r.json()
    total = Decimal(inv['total'])
    assert total > 0
    # تحصيل جزئي: لا ترخيص بعد
    half = (total / 2).quantize(Decimal('0.0001'))
    r = vclient.post('/api/v1/collections', headers=fin, json={
        'invoice_number': inv['number'], 'amount': str(half),
        'method': 'TRANSFER', 'reference': 'TRX-1001'})
    assert r.status_code == 201 and not r.json()['fully_paid']
    # إتمام السداد: ترخيص مجدد آلي فوراً
    rest = total - half
    r = vclient.post('/api/v1/collections', headers=fin, json={
        'invoice_number': inv['number'], 'amount': str(rest),
        'method': 'TRANSFER', 'reference': 'TRX-1002',
        'notes': 'إتمام سداد التجديد'})
    j = r.json()
    assert r.status_code == 201 and j['fully_paid']
    assert j['license'] and j['license']['status'] == 'ACTIVE'
    assert j['license']['kind' if 'kind' in j['license'] else 'license_id']
    # العميل الهجين يسحبه فوراً عبر Edge (≤ 5 دقائق تحقق بناءً بالتصميم)
    r = vclient.get('/edge/license/latest', params={'client_code': 'CLI-001'},
                    headers={'X-Edge-Token': 'edge-cli001-demo-token'})
    assert r.status_code == 200
    payload = r.json()
    assert _verify_sig(signing_keys['pub'], payload)
    assert payload['serial'] == j['license']['serial']
    assert payload['kind'] == 'RENEW'
    assert payload['expires_at'] == str(date.today() + timedelta(days=365))
    # ملف العميل تحدّث مرة واحدة: ACTIVE وستاريخ جديد
    r = vclient.get('/api/v1/clients/CLI-001', headers=fin)
    assert r.json()['status'] == 'ACTIVE'
    assert r.json()['expiry_date'] == str(date.today() +
                                          timedelta(days=365))


def test_mrr_matches_active_subscriptions_exactly(vclient):
    """قبول §8-2: MRR = مجموع اشتراكات نشطة حسابياً بلا انحراف."""
    hdr = _login_director(vclient)
    r = vclient.get('/api/v1/revenue', headers=hdr)
    j = r.json()
    # CLI-001 ACTIVE بقيمة 358.3333 — TRIAL لا تُحتسب
    assert Decimal(j['mrr']) == Decimal('358.3333')
    assert Decimal(j['arr']) == Decimal('358.3333') * 12
    # فُعِّل CLI-002 بقيمة شهرية 200 (سبب موثق)
    vclient.post('/api/v1/clients/CLI-002/status', headers=hdr,
                 json={'to_status': 'ACTIVE',
                       'reason': 'تحويل تجربة إلى عقد مدفوع'})
    db = vclient.vdb
    c2 = db.execute(select(m.Client).where(m.Client.code == 'CLI-002')
                    ).scalar_one()
    c2.monthly_value = Decimal('200.0000')
    db.commit()
    r = vclient.get('/api/v1/revenue', headers=hdr)
    j = r.json()
    assert Decimal(j['mrr']) == Decimal('558.3333')
    proof_sum = sum(Decimal(p['monthly_value']) for p in j['mrr_proof'])
    assert proof_sum == Decimal('558.3333')
    assert j['active_clients'] == 2
    assert Decimal(j['expected_90d']) >= 0


def test_billing_cycle_grace_then_read_only_with_tasks(vclient):
    hdr = _login_director(vclient)
    db = vclient.vdb
    c2 = db.execute(select(m.Client).where(m.Client.code == 'CLI-002')
                    ).scalar_one()
    # فعّل ثم أنتهِ الأمس: الدورة تعفي إلى GRACE + مهمة مبيعات
    c2.status = 'ACTIVE'
    c2.expiry_date = date.today() - timedelta(days=1)
    c2.grace_days = 30
    db.commit()
    vclient.post('/api/v1/billing/run-cycle', headers=hdr)
    c2 = db.get(m.Client, c2.id)
    assert c2.status == 'GRACE'
    notes = db.execute(select(m.Notification).where(
        m.Notification.kind == 'TASK_RENEWAL')).scalars().all()
    assert any(n.role == 'SALES' and n.payload['client'] == 'CLI-002'
               for n in notes)
    # بعد انتهاء المهلة: READ_ONLY ذاتياً
    c2.expiry_date = date.today() - timedelta(days=45)
    db.commit()
    vclient.post('/api/v1/billing/run-cycle', headers=hdr)
    assert db.get(m.Client, c2.id).status == 'READ_ONLY'
    notes = db.execute(select(m.Notification).where(
        m.Notification.kind == 'CLIENT_READ_ONLY')).scalars().all()
    assert len(notes) >= 1


# ═══ §4 تراخيص + اعتماد ثانٍ ═══
def test_support_cannot_issue_license_acceptance_4(vclient):
    hdr = _enroll_and_login(vclient, 'support1')
    r = vclient.post('/api/v1/licenses', headers=hdr, json={
        'client_code': 'CLI-001', 'modules': ['ACCOUNTING']})
    assert r.status_code == 403
    assert r.json()['error']['code'] == 'VND.FORBIDDEN'


def test_finance_cannot_work_tickets(vclient):
    hdr = _enroll_and_login(vclient, 'finance1')
    r = vclient.post('/api/v1/tickets', headers=hdr, json={
        'client_code': 'CLI-001', 'title': 'x', 'category': 'BUG',
        'priority': 'P3'})
    assert r.status_code == 403


def test_license_issue_in_plan_active_signed(vclient, signing_keys):
    hdr = _enroll_and_login(vclient, 'licops1')
    r = vclient.post('/api/v1/licenses', headers=hdr, json={
        'client_code': 'CLI-002', 'kind': 'ISSUE',
        'modules': ['ACCOUNTING', 'HOTEL', 'POS'],  # ضمن CITY-M
        'max_users': 8, 'max_branches': 1, 'days': 30})
    j = r.json()
    assert r.status_code == 201 and j['status'] == 'ACTIVE'
    assert _verify_sig(signing_keys['pub'], j['payload'])
    assert j['payload']['max_users'] == 8


def test_over_plan_requires_second_approval_not_self(vclient):
    ops = _enroll_and_login(vclient, 'licops1')
    director = _login_director(vclient)
    r = vclient.post('/api/v1/licenses', headers=ops, json={
        'client_code': 'CLI-002', 'kind': 'MODIFY',
        'modules': ['ACCOUNTING', 'HOTEL', 'MULTIBRANCH'],  # خارج CITY-M
        'max_users': 30, 'days': 365})
    j = r.json()
    assert j['status'] == 'PENDING_APPROVAL'
    assert j['needs_second_approval'] and j['over_plan_reason']
    # المصدر نفسه لا يعتمد (مكافحة عبث داخلية §4)
    r = vclient.post(f'/api/v1/licenses/{j["id"]}/approve', headers=ops)
    assert r.status_code in (400, 403)
    # مدير ثانٍ يعتمد ← يتاح للعميل فوراً
    r = vclient.post(f'/api/v1/licenses/{j["id"]}/approve',
                     headers=director)
    assert r.status_code == 200 and r.json()['status'] == 'ACTIVE'


def test_revocation_lists_signed_sequential(vclient, signing_keys):
    hdr = _enroll_and_login(vclient, 'licops1')
    r = vclient.post('/api/v1/revocations', headers=hdr, json={
        'entries': [{'serial': 1, 'license_id': 'LIC-CLI-001',
                     'action': 'REVOKE'}]})
    assert r.status_code == 201 and r.json()['revocation_serial'] == 1
    assert _verify_sig(signing_keys['pub'], r.json()['payload'])
    r = vclient.post('/api/v1/revocations', headers=hdr, json={
        'entries': [{'serial': 1, 'license_id': 'LIC-CLI-002',
                     'action': 'SUSPEND'}]})
    assert r.json()['revocation_serial'] == 2
    # Edge يسلّم أحدث قائمة موقعة
    r = vclient.get('/edge/revocations/latest',
                    params={'client_code': 'CLI-002'},
                    headers={'X-Edge-Token': 'edge-cli002-demo-token'})
    assert r.status_code == 200
    assert r.json()['revocation_serial'] == 2


# ═══ §5 تذاكر + قبول §8-3 ═══
def test_p1_alerts_duty_within_60_seconds(vclient):
    """قبول §8-3: P1 (النظام متوقف) ← إشعار مناوب فوري أقل من 60 ثانية."""
    hdr = _enroll_and_login(vclient, 'support1')
    before = datetime.utcnow() - timedelta(seconds=2)
    r = vclient.post('/api/v1/tickets', headers=hdr, json={
        'client_code': 'CLI-001', 'title': 'النظام متوقف كلياً عند العميل',
        'category': 'BUG', 'priority': 'P1', 'module': 'ACCOUNTING',
        'channel': 'PHONE'})
    assert r.status_code == 201, r.text
    t = r.json()
    # SLA محسوب من الأولوية (افتراضي 4 ساعات لـP1)
    due = datetime.fromisoformat(t['sla_due'])
    created = datetime.fromisoformat(t['created_at'])
    assert 3.9 <= (due - created).total_seconds() / 3600 <= 4.1
    # إشعار المناوب: محتوى وتوقيت التسليم تحت 60 ثانية من الإنشاء
    db = vclient.vdb
    alerts = db.execute(select(m.Notification).where(
        m.Notification.kind == 'P1_DUTY_ALERT')).scalars().all()
    assert len(alerts) >= 1
    for a in alerts:
        delta = a.delivered_at - created
        assert delta.total_seconds() < 60, \
            f'إشعار المناوب تأخر {delta.total_seconds()} ثانية'
    # مدير الشركة يراها في قائمته
    dh = _login_director(vclient)
    notes = vclient.get('/api/v1/notifications', headers=dh).json()
    assert any(n['kind'] == 'P1_DUTY_ALERT' and
               n['payload']['ticket'] == t['number'] for n in notes)


def test_ticket_workflow_root_cause_and_transitions(vclient):
    hdr = _enroll_and_login(vclient, 'support1')
    r = vclient.post('/api/v1/tickets', headers=hdr, json={
        'client_code': 'CLI-001', 'title': 'خطأ في تقرير',
        'category': 'BUG', 'priority': 'P2', 'module': 'ACCOUNTING'})
    num = r.json()['number']
    # انتقال ممنوع مباشرة NEW→RESOLVED
    r = vclient.post(f'/api/v1/tickets/{num}/transition', headers=hdr,
                     json={'to_status': 'RESOLVED'})
    assert r.status_code == 400
    assert r.json()['error']['code'] == 'TKT.BAD_TRANSITION'
    # إسناد ← قيد المعالجة ← محلولة
    vclient.post(f'/api/v1/tickets/{num}/assign', headers=hdr,
                 json={'username': 'support1'})
    for to in ('IN_PROGRESS', 'RESOLVED'):
        r = vclient.post(f'/api/v1/tickets/{num}/transition', headers=hdr,
                         json={'to_status': to})
        assert r.status_code == 200
    # إغلاق بلا سبب جذري يُرفض (إلزامي للأعطال §5)
    l2 = _enroll_and_login(vclient, 'support2')
    r = vclient.post(f'/api/v1/tickets/{num}/transition', headers=l2,
                     json={'to_status': 'CLOSED'})
    assert r.status_code == 400
    assert r.json()['error']['code'] == 'TKT.ROOT_CAUSE_REQUIRED'
    r = vclient.post(f'/api/v1/tickets/{num}/transition', headers=l2,
                     json={'to_status': 'CLOSED',
                           'root_cause': 'خطأ تجميع شرط فترة لينة',
                           'kb_article': 'KB-101 — فحص حالات الفترات'})
    assert r.status_code == 200 and r.json()['status'] == 'CLOSED'
    assert r.json()['closed_at']
    # L1 لا يغلق (أقل امتياز §7)
    r2 = vclient.post('/api/v1/tickets', headers=hdr, json={
        'client_code': 'CLI-001', 'title': 'سؤال إعداد',
        'category': 'QUESTION', 'priority': 'P4'})
    num2 = r2.json()['number']
    vclient.post(f'/api/v1/tickets/{num2}/assign', headers=hdr,
                 json={'username': 'support1'})
    vclient.post(f'/api/v1/tickets/{num2}/transition', headers=hdr,
                 json={'to_status': 'IN_PROGRESS'})
    vclient.post(f'/api/v1/tickets/{num2}/transition', headers=hdr,
                 json={'to_status': 'RESOLVED'})
    r = vclient.post(f'/api/v1/tickets/{num2}/transition', headers=hdr,
                     json={'to_status': 'CLOSED'})
    assert r.status_code == 403


def test_escalation_l1_l2_engineering(vclient):
    hdr = _enroll_and_login(vclient, 'support2')
    r = vclient.post('/api/v1/tickets', headers=hdr, json={
        'client_code': 'CLI-001', 'title': 'بطء مزامنة',
        'category': 'BUG', 'priority': 'P2', 'module': 'SYNC'})
    num = r.json()['number']
    r = vclient.post(f'/api/v1/tickets/{num}/escalate', headers=hdr)
    assert r.json()['escalated_to'] == 'SUPPORT_L2'
    r = vclient.post(f'/api/v1/tickets/{num}/escalate', headers=hdr)
    assert r.json()['escalated_to'] == 'ENGINEERING'


# ═══ §6 صحة الأسطول + أعلام البصمة + Edge محدودة (§1) ═══
def test_edge_auth_and_heartbeat_health_colors(vclient):
    # رمز خاطئ مرفوض
    r = vclient.post('/edge/heartbeat', headers={'X-Edge-Token': 'bad'},
                     json={'client_code': 'CLI-001', 'outbox_lag': 0})
    assert r.status_code == 401
    assert r.json()['error']['code'] == 'EDGE.AUTH'
    # نبض سليم ← أخضر
    r = vclient.post('/edge/heartbeat',
                     headers={'X-Edge-Token': 'edge-cli001-demo-token'},
                     json={'client_code': 'CLI-001', 'site_id': 'site-1',
                           'product_version': '0.9.0', 'outbox_lag': 3,
                           'backup_ok': True, 'disk_free_gb': '55',
                           'fingerprint_hash': 'fp-cli001'})
    assert r.status_code == 200 and r.json()['ok']
    # نبض بنسخة احتياطية فاشلة ← أحمر
    vclient.post('/edge/heartbeat',
                 headers={'X-Edge-Token': 'edge-cli002-demo-token'},
                 json={'client_code': 'CLI-002', 'backup_ok': False,
                       'disk_free_gb': '44'})
    hdr = _enroll_and_login(vclient, 'support1')
    j = vclient.get('/api/v1/health/fleet', headers=hdr).json()
    rows = {r['code']: r for r in j['rows']}
    assert rows['CLI-001']['color'] == 'GREEN'
    assert rows['CLI-001']['product_version'] == '0.9.0'
    assert rows['CLI-002']['color'] == 'RED'
    assert rows['CLI-002']['backup_ok'] is False
    assert j['counts']['RED'] >= 1


def test_fingerprint_drift_flag(vclient):
    """07 §4-5: بصمة جهاز تظهر على عميل آخر = علم في اللوحة."""
    vclient.post('/edge/heartbeat',
                 headers={'X-Edge-Token': 'edge-cli001-demo-token'},
                 json={'client_code': 'CLI-001',
                       'fingerprint_hash': 'fp-shared-x'})
    r = vclient.post('/edge/heartbeat',
                     headers={'X-Edge-Token': 'edge-cli002-demo-token'},
                     json={'client_code': 'CLI-002',
                           'fingerprint_hash': 'fp-shared-x'})
    assert r.status_code == 200
    hdr = _enroll_and_login(vclient, 'licops1')
    alerts = vclient.get('/api/v1/fingerprint-alerts', headers=hdr).json()
    assert len(alerts) == 1
    assert set(alerts[0]['seen_on']) == {'CLI-001', 'CLI-002'}


def test_edge_ticket_and_scope(vclient):
    # فتح تذكرة من داخل تطبيق العميل (§5 قناة IN_APP)
    r = vclient.post('/edge/tickets',
                     headers={'X-Edge-Token': 'edge-cli001-demo-token'},
                     json={'client_code': 'CLI-001',
                           'title': 'سؤال عن تقفيل السنة',
                           'category': 'QUESTION', 'priority': 'P3',
                           'module': 'ACCOUNTING',
                           'description': 'كيف أفتح سنة جديدة؟'})
    assert r.status_code == 201
    assert r.json()['number'].startswith('TKT-')
    # Edge لا تسمح بـP1 (للشركة فقط — لا تصعيد ذاتي)
    r = vclient.post('/edge/tickets',
                     headers={'X-Edge-Token': 'edge-cli001-demo-token'},
                     json={'client_code': 'CLI-001', 'title': 'x',
                           'category': 'BUG', 'priority': 'P1'})
    assert r.status_code == 422
    # Edge «لا أكثر أبداً»: لا وصول لبيانات اللوحة برمز العميل
    r = vclient.get('/api/v1/revenue',
                    headers={'Authorization': 'Bearer edge-cli001-demo-token'})
    assert r.status_code == 401


def test_releases_ring_rollout(vclient):
    hdr = _login_director(vclient)
    r = vclient.post('/api/v1/releases', headers=hdr,
                     json={'version': '0.9.1', 'ring': 'CANARY',
                           'notes': 'حلقة تجريبية للمتطوعين'})
    assert r.status_code == 201
    r = vclient.get('/edge/releases/latest',
                    params={'client_code': 'CLI-001',
                            'current_version': '0.9.0'},
                    headers={'X-Edge-Token': 'edge-cli001-demo-token'})
    assert r.json()['update_available'] and r.json()['ring'] == 'CANARY'
    r = vclient.post('/edge/releases/ack',
                     params={'client_code': 'CLI-001', 'version': '0.9.1',
                             'state': 'SUCCESS'},
                     headers={'X-Edge-Token': 'edge-cli001-demo-token'})
    assert r.json()['ok']
    rel = vclient.get('/api/v1/releases', headers=hdr).json()
    assert rel[0]['updates'] == 1


# ═══ §7 تدقيق مستقل ═══
def test_vendor_audit_chained(vclient):
    hdr = _login_director(vclient)
    vclient.post('/api/v1/clients', headers=hdr, json={
        'legal_name': 'عميل تدقيق', 'open_reason': 'اختبار السلسلة'})
    rows = vclient.get('/api/v1/audit', headers=hdr).json()
    assert rows and all(len(r['row_hash']) == 16 for r in rows)
    assert any(r['action'] == 'CLIENT_CREATE' for r in rows)
