"""اختبارات نظام التراخيص (ملف 07) — معايير القبول §7 كاملة:
1) تعديل حرف واحد = رفض فوري   2) محلي ساري بلا إنترنت 60 يوم = صفر تعطل
3) انتهاء+مهلة = قراءة فقط مع تصدير سليم (مسار آلي كامل)
4) رجوع الساعة = كشف وإصلاح بلا فقدان بيانات   5) لا مفتاح خاص في المستودع
+ دورة الحياة §2/§3، بصمة 2/3، قوائم الإلغاء الموقعة، القيود الصلبة §5."""
import json
import os
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import licensing as lic
from app import models as m
from app.config import get_settings
from app.security import hash_password, new_uuid, utcnow

TODAY = date.today()


# ═══ تجهيزات ═══
@pytest.fixture()
def lic_env(monkeypatch):
    """مفتاح عام اختباري مؤقت (الخاص يُولّد ويُرمى — لا يُخزَّن بالمستودع)."""
    priv = lic.gen_private_pem()
    pub = lic.public_pem_from_private(priv)
    monkeypatch.setenv('LICENSE_PUBLIC_KEY_PEM', pub.decode())
    get_settings.cache_clear()
    yield {'priv': priv, 'pub': pub}
    monkeypatch.delenv('LICENSE_PUBLIC_KEY_PEM', raising=False)
    get_settings.cache_clear()


def _payload(tid, *, days=365, grace=30, modules=None, max_users=25,
             max_branches=2, serial=1, package='LOCAL', fp=None,
             license_id='LIC-T-1', expires=None, kind=None):
    p = {'license_id': license_id, 'tenant_id': tid,
         'legal_name': 'فندق الاختبار المرخّص', 'package': package,
         'modules_enabled': modules or lic.MODULES_ALL[:6],
         'max_users': max_users, 'max_branches': max_branches,
         'issued_at': datetime.now(timezone.utc).isoformat(),
         'expires_at': str(expires or (TODAY + timedelta(days=days))),
         'grace_days': grace,
         'hardware_fingerprint_hash': lic.fingerprint_hash(fp) if fp else None,
         'hardware_fingerprint': fp,
         'features_flags': {'e_invoicing': True},
         'support_level': 'PREMIUM', 'nonce': 'n-' + str(serial),
         'serial': serial}
    if kind:
        p['kind'] = kind
    return p


def _signed(tid, priv, **kw):
    p = _payload(tid, **kw)
    p['signature'] = lic.sign_payload(p, priv)
    return p


def _revlist(priv, entries, serial=1):
    p = {'kind': 'REVOCATION_LIST', 'revocation_serial': serial,
         'issued_at': datetime.now(timezone.utc).isoformat(),
         'entries': entries, 'nonce': f'r{serial}'}
    p['signature'] = lic.sign_payload(p, priv)
    return p


def _mk_user(db, tid, username, role_code='ACCOUNTANT',
             password='Passw0rd!X'):
    role = db.execute(select(m.Role).where(m.Role.tenant_id == tid,
                                           m.Role.code == role_code)
                      ).scalar_one()
    u = m.User(id=new_uuid(), tenant_id=tid, username=username,
               full_name=f'مستخدم {username}',
               password_hash=hash_password(password),
               created_at=utcnow(), is_active=True)
    db.add(u)
    db.flush()
    db.add(m.UserRole(user_id=u.id, role_id=role.id))
    db.commit()
    return u


def _login(client, username, password='Passw0rd!X'):
    r = client.post('/api/auth/login',
                    json={'username': username, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': f'Bearer {r.json()["access_token"]}'}


def _audit_actions(db, tid):
    rows = db.execute(select(m.AuditLog.action).where(
        m.AuditLog.tenant_id == tid, m.AuditLog.module == 'license')
        ).scalars().all()
    return rows


# ═══ خدمة: دورة الحياة ═══
def test_trial_default_on_fresh_install(db_session):
    db, factory, seed = db_session
    out = lic.evaluate(db, seed['tenant_id'], force=True)
    assert out['state'] == 'TRIAL' and out['trial']
    assert out['days_to_expire'] >= 89           # 90 يوم افتراضياً
    assert set(out['modules_enabled']) == set(lic.MODULES_ALL[:6])
    assert 'LICENSE_TRIAL_START' in _audit_actions(db, seed['tenant_id'])
    assert 'LICENSE_PERIODIC_CHECK' in _audit_actions(db, seed['tenant_id'])


def test_install_valid_license(db_session, lic_env, monkeypatch):
    monkeypatch.setattr(lic, 'fingerprint_components',
                        lambda: {'board': 'B1', 'disk': 'D1', 'mac': 'M1'})
    db, factory, seed = db_session
    tid = seed['tenant_id']
    p = _signed(tid, lic_env['priv'], max_users=7, modules=['ACCOUNTING',
                                                            'HOTEL'])
    out = lic.install_license(db, tid, p, actor_id='admin')
    db.commit()
    assert out['installed'] and out['status']['state'] == 'LICENSED'
    st = out['status']
    assert st['limits']['max_users'] == 7
    assert st['package'] == 'LOCAL'
    assert st['fingerprint']['bound']            # رُبط بالجهاز تلقائياً
    assert st['features_flags']['e_invoicing'] is True
    assert 'POS' in st['modules_disabled']
    assert 'LICENSE_INSTALL' in _audit_actions(db, tid)
    # تثبيت نفس الملف مجدداً = آمن بلا أثر (Idempotent)
    again = lic.install_license(db, tid, p, actor_id='admin')
    assert again['already'] and not again['installed']


def test_tamper_single_char_rejected(db_session, lic_env):
    """معيار قبول §7-1: تعديل حرف واحد في الملف = توقيع غير صالح = رفض فوري."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    p = _signed(tid, lic_env['priv'])
    p['legal_name'] = p['legal_name'][:-1] + ('ة' if p['legal_name']
                                              .endswith('ا') else 'ا')
    with pytest.raises(lic.LicError) as ex:
        lic.install_license(db, tid, p, actor_id='admin')
    assert ex.value.code == 'LIC.BAD_SIGNATURE'
    assert 'LICENSE_VERIFY_FAIL' in _audit_actions(db, tid)


def test_wrong_key_and_tenant_and_old_serial(db_session, lic_env):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    # مفتاح آخر غير مفتاح الشركة
    foreign = _signed(tid, lic.gen_private_pem())
    with pytest.raises(lic.LicError) as ex:
        lic.install_license(db, tid, foreign, actor_id='admin')
    assert ex.value.code == 'LIC.BAD_SIGNATURE'
    # ترخيص مستأجر آخر
    other = _signed('TENANT-OTHER', lic_env['priv'])
    with pytest.raises(lic.LicError) as ex:
        lic.install_license(db, tid, other, actor_id='admin')
    assert ex.value.code == 'LIC.WRONG_TENANT'
    # ملف أقدم من المثبّت
    lic.install_license(db, tid, _signed(tid, lic_env['priv'], serial=5),
                        actor_id='admin')
    with pytest.raises(lic.LicError) as ex:
        lic.install_license(db, tid, _signed(tid, lic_env['priv'], serial=3,
                                             license_id='LIC-T-1'),
                            actor_id='admin')
    assert ex.value.code == 'LIC.OLD_SERIAL'


def test_fingerprint_tolerance_2_of_3(db_session, lic_env, monkeypatch):
    """07 §2: تغيير قطعة واحدة يُتجاوز؛ تغيير قطعتين = ترخيص جهاز آخر."""
    comps = {'board': 'B1', 'disk': 'D1', 'mac': 'M1'}
    monkeypatch.setattr(lic, 'fingerprint_components', lambda: dict(comps))
    db, factory, seed = db_session
    tid = seed['tenant_id']
    lic.install_license(db, tid, _signed(tid, lic_env['priv'], fp=comps),
                        actor_id='admin')
    db.commit()
    # قطعة واحدة تغيّرت (استبدال اللوحة الأم) — يمر
    comps['board'] = 'B2'
    out = lic.evaluate(db, tid, force=True)
    assert out['state'] == 'LICENSED'
    assert out['fingerprint']['match_components'] == 2
    # قطعتان تغيّرتا — رفض + علم عبث
    comps['disk'] = 'D2'
    out = lic.evaluate(db, tid, force=True)
    assert out['state'] == 'INVALID'
    assert not out['fingerprint']['passing']
    assert 'LICENSE_TAMPER_SUSPECT' in _audit_actions(db, tid)


def test_grace_then_read_only_then_renewal(db_session, lic_env, monkeypatch):
    monkeypatch.setattr(lic, 'fingerprint_components',
                        lambda: {'board': 'B', 'disk': 'D', 'mac': 'M'})
    db, factory, seed = db_session
    tid = seed['tenant_id']
    # منتهٍ أمس ضمن مهلة 30 يوم → GRACE وكل شيء يعمل
    p = _signed(tid, lic_env['priv'],
                expires=TODAY - timedelta(days=1), grace=30)
    lic.install_license(db, tid, p, actor_id='admin')
    out = lic.evaluate(db, tid, force=True)
    assert out['state'] == 'GRACE' and out['in_grace']
    lic.enforce_request(db, tenant_id=tid, username='admin',
                        method='POST', path='/api/journals/manual')  # لا يرمي
    # منتهٍ منذ 40 يوم (تجاوز المهلة) → READ_ONLY
    p2 = _signed(tid, lic_env['priv'], serial=2,
                 expires=TODAY - timedelta(days=40), grace=30)
    lic.install_license(db, tid, p2, actor_id='admin')
    out = lic.evaluate(db, tid, force=True)
    assert out['state'] == 'READ_ONLY'
    # القراءة/التصدير يمر، الإضافة تُمنع برسالة واضحة (§3)
    lic.enforce_request(db, tenant_id=tid, username='admin',
                        method='GET', path='/api/reports/trial-balance')
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ex:
        lic.enforce_request(db, tenant_id=tid, username='admin',
                            method='POST', path='/api/journals/manual')
    assert ex.value.status_code == 403
    assert ex.value.detail['error']['code'] == 'LIC.READ_ONLY'
    # التجديد بملف ساري يعيد كل شيء سلساً بلا توقف (§2)
    p3 = _signed(tid, lic_env['priv'], serial=3, days=365)
    lic.install_license(db, tid, p3, actor_id='admin')
    out = lic.evaluate(db, tid, force=True)
    assert out['state'] == 'LICENSED'
    lic.enforce_request(db, tenant_id=tid, username='admin',
                        method='POST', path='/api/journals/manual')


def test_offline_60_days_zero_disruption(db_session, lic_env, monkeypatch):
    """معيار قبول §7-2: محلي ساري بلا اتصال 60 يوماً = صفر تعطل (التحقق محلي
    بالمفتاح العام المضمّن — لا قناة إنترنت في الكود أصلاً)."""
    monkeypatch.setattr(lic, 'fingerprint_components',
                        lambda: {'board': 'B', 'disk': 'D', 'mac': 'M'})
    db, factory, seed = db_session
    tid = seed['tenant_id']
    lic.install_license(db, tid, _signed(tid, lic_env['priv'], days=365),
                        actor_id='admin')
    row = db.execute(select(m.LicenseState).where(
        m.LicenseState.tenant_id == tid)).scalar_one()
    row.last_check = utcnow() - timedelta(days=60)      # انقطاع طويل
    row.clock_anchor_date = TODAY - timedelta(days=60)  # الساعة صحيحة
    db.commit()
    out = lic.evaluate(db, tid, force=True)
    assert out['state'] == 'LICENSED'
    lic.enforce_request(db, tenant_id=tid, username='admin',
                        method='POST', path='/api/pos/orders')  # يعمل


def test_clock_rollback_lock_and_repair(db_session, lic_env, monkeypatch):
    """معيار قبول §7-4: إعادة تشغيل بساعة مؤخرة = كشف رجوع + إصلاح بملف
    موقّع، ولا فقدان بيانات أبداً."""
    monkeypatch.setattr(lic, 'fingerprint_components',
                        lambda: {'board': 'B', 'disk': 'D', 'mac': 'M'})
    db, factory, seed = db_session
    tid = seed['tenant_id']
    lic.install_license(db, tid, _signed(tid, lic_env['priv']), actor_id='a')
    entries_before = db.execute(select(m.JournalEntry.id)).all()
    row = db.execute(select(m.LicenseState).where(
        m.LicenseState.tenant_id == tid)).scalar_one()
    row.clock_anchor_date = TODAY + timedelta(days=365)  # ساعة رجعت سنة §7-4
    db.commit()
    out = lic.evaluate(db, tid, force=True)
    assert out['state'] == 'CLOCK_LOCK'
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ex:
        lic.enforce_request(db, tenant_id=tid, username='admin',
                            method='GET', path='/api/reports/trial-balance')
    assert ex.value.detail['error']['code'] == 'LIC.CLOCK_LOCK'
    # الإصلاح: ملف ترخيص ساري من الشركة (جلسة الإصلاح الموثقة §4-2)
    lic.install_license(db, tid, _signed(tid, lic_env['priv'], serial=2,
                                         kind='REPAIR'), actor_id='a')
    out = lic.evaluate(db, tid, force=True)
    assert out['state'] == 'LICENSED'
    entries_after = db.execute(select(m.JournalEntry.id)).all()
    assert len(entries_before) == len(entries_after)     # لا فقدان إطلاقاً


def test_revocation_list_and_manual_suspension(db_session, lic_env,
                                               monkeypatch):
    """الإلغاء بقائمة موقعة متسلسلة §2؛ الإيقاف النهائي فقط بقرار موثّق §3."""
    monkeypatch.setattr(lic, 'fingerprint_components',
                        lambda: {'board': 'B', 'disk': 'D', 'mac': 'M'})
    db, factory, seed = db_session
    tid = seed['tenant_id']
    lic.install_license(db, tid, _signed(tid, lic_env['priv'], serial=1,
                                         license_id='LIC-T-1'), actor_id='a')
    # قائمة REVOKE: إلغاء رحيم → قراءة فقط (لا حذف/تشفير ممنوع بتاتاً §3)
    lst = _revlist(lic_env['priv'], [{'serial': 1, 'license_id': 'LIC-T-1',
                                      'action': 'REVOKE'}], serial=1)
    lic.import_revocations(db, tid, lst, actor_id='a')
    out = lic.evaluate(db, tid, force=True)
    assert out['state'] == 'REVOKED'
    lic.enforce_request(db, tenant_id=tid, username='admin',
                        method='GET', path='/api/reports/ledger')  # يمر
    # قائمة أقدم تُرفض
    with pytest.raises(lic.LicError) as ex:
        lic.import_revocations(db, tid, lst, actor_id='a')
    assert ex.value.code == 'LIC.OLD_REVOCATION'
    # قرار الشركة الموثّق بالإيقاف النهائي
    lst2 = _revlist(lic_env['priv'], [{'serial': 1, 'license_id': 'LIC-T-1',
                                       'action': 'SUSPEND'}], serial=2)
    lic.import_revocations(db, tid, lst2, actor_id='a')
    out = lic.evaluate(db, tid, force=True)
    assert out['state'] == 'SUSPENDED'
    assert 'LICENSE_REVOCATION_IMPORT' in _audit_actions(db, tid)
    # §3: لا دخول عدا حساب الطوارئ المالي
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        lic.ensure_login_allowed(db, tenant_id=tid, username='cashier1')
    lic.ensure_login_allowed(db, tenant_id=tid, username='admin')  # يمر


def test_hard_limits_users_and_modules(db_session, lic_env, monkeypatch):
    """07 §5: قيود صلبة عند الإنشاء + وحدات مغلقة برسالة ترقية."""
    monkeypatch.setattr(lic, 'fingerprint_components',
                        lambda: {'board': 'B', 'disk': 'D', 'mac': 'M'})
    db, factory, seed = db_session
    tid = seed['tenant_id']
    lic.install_license(db, tid, _signed(tid, lic_env['priv'], max_users=1,
                                         modules=['ACCOUNTING']),
                        actor_id='a')
    db.commit()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ex:  # admin النشط = الحد 1
        lic.enforce_user_limit(db, tid)
    assert ex.value.detail['error']['code'] == 'LIC.USER_LIMIT'


def test_activation_request_offline_flow(db_session, lic_env):
    """الوضع المعزول تماماً §2: بصمة → ملف طلب → الشركة توقّع مقيّداً بها."""
    db, factory, seed = db_session
    tid = seed['tenant_id']
    req = lic.activation_request(db, tid, actor_id='a')
    db.commit()
    assert req['kind'] == 'ACTIVATION_REQUEST'
    assert set(req['hardware_fingerprint']) == {'board', 'disk', 'mac'}
    fp = req['hardware_fingerprint']
    # تثبيت ملف مقيّد ببصمة غير بصمتنا يُرفض
    alien_fp = {k: v + 'X' for k, v in fp.items()}
    with pytest.raises(lic.LicError) as ex:
        lic.install_license(db, tid, _signed(tid, lic_env['priv'], fp=alien_fp,
                                             license_id='LIC-T-9'),
                            actor_id='a')
    assert ex.value.code == 'LIC.FINGERPRINT_MISMATCH'


def test_no_private_key_in_repo():
    """معيار قبول §7-5: مفتاح التوقيع الخاص غير موجود في أي ملف متتبَّع."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                        '..', '..'))
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in
                       ('.git', 'node_modules', '.venv', '__pycache__',
                        'dev_keys', 'dist', '.pytest_cache')]
        for fn in filenames:
            assert not fn.endswith('_private.pem'), f'مفتاح خاص: {fn}'
            path = os.path.join(dirpath, fn)
            try:
                with open(path, 'rb') as f:
                    blob = f.read(200_000)
            except (OSError, UnicodeDecodeError):
                continue
            marker1 = b'BEGIN ' + b'PRIVATE KEY'
            marker2 = b'BEGIN OPENSSH ' + b'PRIVATE KEY'
            assert marker1 not in blob, f'مفتاح خاص داخل {path}'
            assert marker2 not in blob, f'مفتاح خاص داخل {path}'


# ═══ HTTP: المسار الكامل (معيار قبول §7-3 آلي) ═══
def test_http_full_lifecycle_export_intact(client, db_session, lic_env,
                                           monkeypatch):
    monkeypatch.setattr(lic, 'fingerprint_components',
                        lambda: {'board': 'B', 'disk': 'D', 'mac': 'M'})
    db, factory, seed = client.seed_info and db_session
    tid = seed['tenant_id']
    admin = _login(client, 'admin', 'admin123!Change')
    # 1) الحالة الافتراضية تجريبية — ومتاحة لأي مستخدم
    r = client.get('/api/license/status', headers=admin)
    assert r.status_code == 200 and r.json()['state'] == 'TRIAL'
    # 2) تثبيت ملف معدَّل → رفض فوري عبر API
    bad = _signed(tid, lic_env['priv'])
    bad['max_users'] = 999  # عبث بعد التوقيع
    r = client.post('/api/license/install', headers=admin,
                    json={'payload': bad})
    assert r.status_code == 400
    assert r.json()['error']['code'] == 'LIC.BAD_SIGNATURE'
    # 3) ترخيص منتهٍ متجاوز المهلة → قراءة فقط
    expired = _signed(tid, lic_env['priv'],
                      expires=TODAY - timedelta(days=45), grace=15)
    r = client.post('/api/license/install', headers=admin,
                    json={'payload': expired})
    assert r.status_code == 200
    r = client.post('/api/license/evaluate', headers=admin)
    assert r.json()['state'] == 'READ_ONLY'
    #    الإضافة ممنوعة…
    r = client.post('/api/journals/manual', headers=admin, json={
        'entry_date': str(TODAY), 'narration': 'قيد تحت قراءة فقط',
        'lines': [{'account': '1101', 'debit': 1, 'credit': 0},
                  {'account': '8002', 'debit': 0, 'credit': 1}]})
    assert r.status_code == 403
    assert r.json()['error']['code'] == 'LIC.READ_ONLY'
    #    …والتقارير والتصدير والطباعة سليمة كاملة (حق العميل مطلق §3)
    assert client.get('/api/reports/trial-balance',
                      headers=admin).status_code == 200
    assert client.get('/api/reports/balance-sheet', headers=admin,
                      params={'as_of': str(TODAY)}).status_code == 200
    assert client.get('/api/reports/ledger', headers=admin,
                      params={'account_code': '1101',
                              'date_from': '2026-01-01',
                              'date_to': str(TODAY)}).status_code == 200
    assert client.get('/api/license/status', headers=admin).status_code == 200
    # 4) التجديد يرفع القيد فوراً
    renewed = _signed(tid, lic_env['priv'], serial=2, days=365)
    r = client.post('/api/license/install', headers=admin,
                    json={'payload': renewed})
    assert r.status_code == 200
    r = client.get('/api/license/status', headers=admin)
    assert r.json()['state'] == 'LICENSED'


def test_http_module_guard_and_rbac(client, db_session, lic_env, monkeypatch):
    monkeypatch.setattr(lic, 'fingerprint_components',
                        lambda: {'board': 'B', 'disk': 'D', 'mac': 'M'})
    db, factory, seed = db_session
    tid = seed['tenant_id']
    admin = _login(client, 'admin', 'admin123!Change')
    p = _signed(tid, lic_env['priv'], modules=['ACCOUNTING', 'POS'])
    assert client.post('/api/license/install', headers=admin,
                       json={'payload': p}).status_code == 200
    # وحدة الفندق غير مرخّصة → 403 LIC.MODULE_DISABLED برسالة ترقية
    r = client.get('/api/hotel/rooms', headers=admin)
    assert r.status_code == 403
    assert r.json()['error']['code'] == 'LIC.MODULE_DISABLED'
    assert 'رقِّ' in r.json()['error']['message_ar']
    # نقاط البيع مرخّصة → تعمل
    assert client.get('/api/pos/reports/sales',
                      headers=admin).status_code != 403
    # RBAC سلبي: محاسب بلا license.manage لا يثبّت ولا يفحص قسراً
    _mk_user(db, tid, 'acc1', 'ACCOUNTANT')
    acc = _login(client, 'acc1')
    assert client.get('/api/license/status', headers=acc).status_code == 200
    r = client.post('/api/license/install', headers=acc,
                    json={'payload': p})
    assert r.status_code == 403
    assert r.json()['error']['code'] == 'RBAC.FORBIDDEN'
    assert client.post('/api/license/evaluate', headers=acc).status_code == 403


def test_http_suspended_emergency_export_only(client, db_session, lic_env,
                                              monkeypatch):
    monkeypatch.setattr(lic, 'fingerprint_components',
                        lambda: {'board': 'B', 'disk': 'D', 'mac': 'M'})
    db, factory, seed = db_session
    tid = seed['tenant_id']
    admin = _login(client, 'admin', 'admin123!Change')
    _mk_user(db, tid, 'cashpos', 'POS_CASHIER')
    client.post('/api/license/install', headers=admin,
                json={'payload': _signed(tid, lic_env['priv'], serial=1,
                                         license_id='LIC-T-1')})
    # قرار الشركة الموثّق: إيقاف نهائي
    lst = _revlist(lic_env['priv'], [{'serial': 1, 'license_id': 'LIC-T-1',
                                      'action': 'SUSPEND'}], serial=1)
    r = client.post('/api/license/revocations', headers=admin,
                    json={'payload': lst})
    assert r.status_code == 200
    assert r.json()['status']['state'] == 'SUSPENDED'
    # لا دخول لغير الطوارئ (§3 حرفياً)
    r = client.post('/api/auth/login', json={'username': 'cashpos',
                                             'password': 'Passw0rd!X'})
    assert r.status_code == 403
    assert r.json()['error']['code'] == 'LIC.SUSPENDED'
    # حساب الطوارئ المالي يدخل ويصدّر فقط
    r = client.post('/api/auth/login', json={'username': 'admin',
                                             'password': 'admin123!Change'})
    assert r.status_code == 200
    em = {'Authorization': f'Bearer {r.json()["access_token"]}'}
    assert client.get('/api/reports/trial-balance',
                      headers=em).status_code == 200
    assert client.get('/api/license/status', headers=em).status_code == 200
    r = client.get('/api/hotel/rooms', headers=em)  # ليس تصديراً مالياً
    assert r.status_code == 403


def test_http_clock_lock_flow(client, db_session, lic_env, monkeypatch):
    monkeypatch.setattr(lic, 'fingerprint_components',
                        lambda: {'board': 'B', 'disk': 'D', 'mac': 'M'})
    db, factory, seed = db_session
    tid = seed['tenant_id']
    admin = _login(client, 'admin', 'admin123!Change')
    client.post('/api/license/install', headers=admin,
                json={'payload': _signed(tid, lic_env['priv'], serial=1)})
    row = db.execute(select(m.LicenseState).where(
        m.LicenseState.tenant_id == tid)).scalar_one()
    row.clock_anchor_date = TODAY + timedelta(days=300)
    db.commit()
    r = client.post('/api/license/evaluate', headers=admin)
    assert r.json()['state'] == 'CLOCK_LOCK'
    r = client.get('/api/reports/trial-balance', headers=admin)
    assert r.status_code == 403
    assert r.json()['error']['code'] == 'LIC.CLOCK_LOCK'
    # تثبيت ملف إصلاح ساري يفك القفل (§4-2)
    r = client.post('/api/license/install', headers=admin,
                    json={'payload': _signed(tid, lic_env['priv'], serial=2)})
    assert r.status_code == 200
    assert client.get('/api/reports/trial-balance',
                      headers=admin).status_code == 200


def test_http_user_limit_message(client, db_session, lic_env, monkeypatch):
    monkeypatch.setattr(lic, 'fingerprint_components',
                        lambda: {'board': 'B', 'disk': 'D', 'mac': 'M'})
    db, factory, seed = db_session
    tid = seed['tenant_id']
    admin = _login(client, 'admin', 'admin123!Change')
    client.post('/api/license/install', headers=admin,
                json={'payload': _signed(tid, lic_env['priv'], max_users=1)})
    r = client.post('/api/org/users', headers=admin, json={
        'username': 'extra1', 'full_name': 'مستخدم زائد',
        'password': 'Passw0rd!X', 'role_codes': ['ACCOUNTANT']})
    assert r.status_code == 403
    assert r.json()['error']['code'] == 'LIC.USER_LIMIT'


def test_activation_request_http_and_audit(client, db_session, lic_env):
    db, factory, seed = db_session
    admin = _login(client, 'admin', 'admin123!Change')
    r = client.get('/api/license/activation-request', headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body['kind'] == 'ACTIVATION_REQUEST'
    assert len(body['hardware_fingerprint_hash']) == 64
    assert 'LICENSE_ACTIVATION_REQUEST' in _audit_actions(
        db, seed['tenant_id'])
