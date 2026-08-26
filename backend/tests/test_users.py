"""إدارة المستخدمون والصلاحيات (ADR-0037 + طلب المالك 2026-08-06).

القصة: مالك فندق ينشئ لكل موظف استقبال حساباً مستقلاً (صباحي/مسائي)،
يتحكم كاملاً بالصلاحيات (أدوار/مخصصة/استثناءات حجب-منح لشخص بعينه)،
ويقيد الدخول بنافذة الدوام، ويعرف من فعل ماذا — كل ذلك مثبت هنا عبر HTTP.
"""
from datetime import datetime, timedelta


def _login(client, u, p):
    return client.post('/api/auth/login', json={'username': u, 'password': p})


def _mk_user(client, hdr, username='recep1', password='rec123!Change',
             roles=('RECEPTIONIST',), **kw):
    body = {'username': username, 'full_name': kw.pop('name', 'موظف استقبال'),
            'password': password, 'role_codes': list(roles)}
    body.update(kw)
    r = client.post('/api/org/users', json=body, headers=hdr)
    assert r.status_code == 201, r.text
    return r.json()['id']


def _uid(client, hdr, username):
    users = client.get('/api/org/users', headers=hdr).json()
    return {u['username']: u['id'] for u in users}[username]


def test_create_user_min10_dup_and_windows(client, auth_hdr):
    # كلمة قصيرة عن 10 مرفوضة
    r = client.post('/api/org/users', json={
        'username': 'w1', 'full_name': 'قصير', 'password': 'short12!',
        'role_codes': ['RECEPTIONIST']}, headers=auth_hdr)
    assert r.status_code == 422
    uid = _mk_user(client, auth_hdr, login_windows=[{'from': '08:00',
                                                     'to': '16:00'}])
    # تكرار الاسم 409
    r = client.post('/api/org/users', json={
        'username': 'recep1', 'full_name': 'مكرر', 'password': 'rec123!Change',
        'role_codes': ['RECEPTIONIST']}, headers=auth_hdr)
    assert r.status_code == 409 and 'ORG.USER_EXISTS' in r.text
    # النافذة محفوظة وتظهر بالقائمة
    u = [x for x in client.get('/api/org/users', headers=auth_hdr).json()
         if x['id'] == uid][0]
    assert u['login_windows'] == [{'from': '08:00', 'to': '16:00'}]


def test_new_user_forced_change_then_own_change(client, auth_hdr):
    _mk_user(client, auth_hdr)  # must_change_password=True افتراضياً
    r = _login(client, 'recep1', 'rec123!Change')
    assert r.status_code == 200 and r.json()['user']['must_change_password']
    tok = {'Authorization': 'Bearer ' + r.json()['access_token']}
    # حالية خاطئة
    r = client.post('/api/auth/change-password',
                    json={'current_password': 'nope-nope!', 'new_password':
                          'rec123!Change2'}, headers=tok)
    assert r.status_code == 400 and 'AUTH.WRONG_PASSWORD' in r.text
    # تغيير صحيح ← الجلسات كلها ماتت (auth_version) والعلم زال
    r = client.post('/api/auth/change-password',
                    json={'current_password': 'rec123!Change',
                          'new_password': 'rec123!Change2'}, headers=tok)
    assert r.status_code == 200, r.text
    assert client.get('/api/auth/me', headers=tok).status_code == 401
    r = _login(client, 'recep1', 'rec123!Change2')
    assert r.status_code == 200
    assert not r.json()['user']['must_change_password']


def test_admin_reset_password_kills_everything(client, auth_hdr):
    uid = _mk_user(client, auth_hdr)
    tok_old = {'Authorization':
               'Bearer ' + _login(client, 'recep1', 'rec123!Change')
               .json()['access_token']}
    r = client.post(f'/api/org/users/{uid}/reset-password',
                    json={'new_password': 'rec123!Change9'}, headers=auth_hdr)
    assert r.status_code == 200 and r.json()['sessions_revoked'] >= 1
    # الوصول القديم ميت فوراً (لا انتظار انقضاء الرمز) والكلمة القديمة ماتت
    assert client.get('/api/auth/me', headers=tok_old).status_code == 401
    assert _login(client, 'recep1', 'rec123!Change').status_code == 401
    assert _login(client, 'recep1', 'rec123!Change9').status_code == 200


def test_rbac_employee_cannot_manage_users(client, auth_hdr):
    _mk_user(client, auth_hdr)
    tok = {'Authorization':
           'Bearer ' + _login(client, 'recep1', 'rec123!Change')
           .json()['access_token']}
    assert client.get('/api/org/users', headers=tok).status_code == 403
    for path in ('/api/org/users', '/api/org/roles'):
        r = client.post(path, json={}, headers=tok)
        assert r.status_code == 403, (path, r.text)
        assert 'RBAC.FORBIDDEN' in r.text


def test_role_change_updates_perms_immediately(client, auth_hdr):
    _mk_user(client, auth_hdr, username='acc1', name='محاسب',
             password='acc123!Change', roles=('ACCOUNTANT',))
    tok = {'Authorization':
           'Bearer ' + _login(client, 'acc1', 'acc123!Change')
           .json()['access_token']}
    assert client.get('/api/journals', headers=tok).status_code == 200
    uid = _uid(client, auth_hdr, 'acc1')
    r = client.patch(f'/api/org/users/{uid}',
                     json={'role_codes': ['HOUSEKEEPING']}, headers=auth_hdr)
    assert r.status_code == 200, r.text
    # الصلاحيات تُحسب لحظياً من القاعدة — نفس الرمز القديم يفقد القيود فوراً
    assert client.get('/api/journals', headers=tok).status_code == 403
    assert client.get('/api/hotel/rooms', headers=tok).status_code == 200


def test_overrides_grant_and_deny_beats_role(client, auth_hdr):
    _mk_user(client, auth_hdr, username='acc9', name='محاسب9',
             password='acc123!Change', roles=('ACCOUNTANT',))
    _mk_user(client, auth_hdr)  # recep1
    uid = _uid(client, auth_hdr, 'acc9')
    uid2 = _uid(client, auth_hdr, 'recep1')
    # حجب فردي يغلّب الدور
    r = client.patch(f'/api/org/users/{uid}', json={'denies': ['journals.view']},
                     headers=auth_hdr)
    assert r.status_code == 200
    tok = {'Authorization':
           'Bearer ' + _login(client, 'acc9', 'acc123!Change')
           .json()['access_token']}
    assert client.get('/api/journals', headers=tok).status_code == 403
    # منح فردي يضيف فوق الدور لموظف استقبال
    r = client.patch(f'/api/org/users/{uid2}', json={'grants': ['journals.view']},
                     headers=auth_hdr)
    assert r.status_code == 200
    tok2 = {'Authorization':
            'Bearer ' + _login(client, 'recep1', 'rec123!Change')
            .json()['access_token']}
    assert client.get('/api/journals', headers=tok2).status_code == 200
    # صلاحية غير معروفة بالكتالوج مرفوضة
    r = client.patch(f'/api/org/users/{uid}', json={'grants': ['hack.all']},
                     headers=auth_hdr)
    assert r.status_code == 400 and 'ORG.UNKNOWN_PERM' in r.text


def test_star_owner_sacred_and_self_guards(client, auth_hdr):
    uid_admin = _uid(client, auth_hdr, 'admin')
    # حجب جزئي على المالك لا يؤثر — «*» مقدّسة
    r = client.patch(f'/api/org/users/{uid_admin}',
                     json={'denies': ['accounts.view']}, headers=auth_hdr)
    assert r.status_code == 200
    assert client.get('/api/hotel/rooms', headers=auth_hdr).status_code == 200
    assert client.get('/api/accounts', headers=auth_hdr).status_code == 200
    # سحب المالك من نفسه ممنوع، وإيقاف نفسه ممنوع
    r = client.patch(f'/api/org/users/{uid_admin}',
                     json={'role_codes': ['RECEPTIONIST']}, headers=auth_hdr)
    assert r.status_code == 400 and 'ORG.SELF_STRIP' in r.text
    r = client.post(f'/api/org/users/{uid_admin}/toggle-active',
                  headers=auth_hdr)
    assert r.status_code == 400 and 'ORG.SELF_LOCKOUT' in r.text


def test_last_owner_guard(client, auth_hdr):
    """آخر مالك «*» نشط لا يُسحب ولا يُوقف — السيناريو عبر مدير عام (users.manage
    بلا «*») لأن المالك لا يستطيع العبث بنفسه أصلاً (حُرّاس الذات)."""
    bob = _mk_user(client, auth_hdr, username='boss2', name='مالك ثان',
                   password='boss123!Change', roles=('OWNER',))
    gm = _mk_user(client, auth_hdr, username='gm1', name='مدير عام',
                  password='gm123!Change', roles=('GM',))
    gm_tok = {'Authorization':
              'Bearer ' + _login(client, 'gm1', 'gm123!Change')
              .json()['access_token']}
    # سحب «*» عن bob مسموح (يبقى admin مالكاً نشطاً)
    r = client.patch(f'/api/org/users/{bob}', json={'role_codes': ['ACCOUNTANT']},
                     headers=gm_tok)
    assert r.status_code == 200, r.text
    # إيقاف admin (آخر «*» نشط) ← 409 LAST_OWNER
    uid_admin = _uid(client, auth_hdr, 'admin')
    r = client.post(f'/api/org/users/{uid_admin}/toggle-active', headers=gm_tok)
    assert r.status_code == 409 and 'ORG.LAST_OWNER' in r.text, r.text
    # وإزالة دوره عنه ← 409 كذلك
    r = client.patch(f'/api/org/users/{uid_admin}',
                     json={'role_codes': ['ACCOUNTANT']}, headers=gm_tok)
    assert r.status_code == 409 and 'ORG.LAST_OWNER' in r.text
    # إعادة «*» إلى bob ثم إيقاف admin يمر (bob نشط مالك)
    client.patch(f'/api/org/users/{bob}', json={'role_codes': ['OWNER']},
                 headers=gm_tok)
    r = client.post(f'/api/org/users/{uid_admin}/toggle-active', headers=gm_tok)
    assert r.status_code == 200, r.text


def test_toggle_off_kills_access_instantly(client, auth_hdr):
    uid = _mk_user(client, auth_hdr)
    l = _login(client, 'recep1', 'rec123!Change').json()
    tok = {'Authorization': 'Bearer ' + l['access_token']}
    assert client.get('/api/hotel/rooms', headers=tok).status_code == 200
    r = client.post(f'/api/org/users/{uid}/toggle-active', headers=auth_hdr)
    assert r.status_code == 200 and r.json()['is_active'] is False
    assert client.get('/api/hotel/rooms', headers=tok).status_code == 401
    # والدخول الجديد مرفوض برسالة عربية
    r = _login(client, 'recep1', 'rec123!Change')
    assert r.status_code == 403 and 'AUTH.USER_INACTIVE' in r.text


def _now_tenant(client, auth_hdr):
    """لحظة «الآن» بمنطقة المستأجر الزمنية — نوافذ الدوام تقيَّم بها."""
    from zoneinfo import ZoneInfo
    tz = client.get('/api/org/tenant', headers=auth_hdr).json()['timezone']
    return datetime.now(ZoneInfo(tz))


def test_shift_windows_login_enforced_and_audited(client, auth_hdr):
    now = _now_tenant(client, auth_hdr)
    in_w = [(now - timedelta(hours=1)).strftime('%H:%M'),
            (now + timedelta(hours=1)).strftime('%H:%M')]
    out_w = [(now + timedelta(hours=2)).strftime('%H:%M'),
             (now + timedelta(hours=3)).strftime('%H:%M')]
    # داخل النافذة ← دخول
    uid = _mk_user(client, auth_hdr, username='mor1', name='صباحي',
                   password='rec123!Change',
                   login_windows=[{'from': in_w[0], 'to': in_w[1]}])
    r = _login(client, 'mor1', 'rec123!Change')
    assert r.status_code == 200, r.text
    # خارج النافذة ← رفض 403 برسالة النافذة + موثّق
    client.patch(f'/api/org/users/{uid}',
                 json={'login_windows': [{'from': out_w[0], 'to': out_w[1]}]},
                 headers=auth_hdr)
    r = _login(client, 'mor1', 'rec123!Change')
    assert r.status_code == 403 and 'AUTH.OUTSIDE_SHIFT' in r.text, r.text
    assert out_w[0] in r.text  # الرسالة تعرض نافذته بوضوح
    aud = client.get('/api/audit?actor=mor1&module=security',
                     headers=auth_hdr).json()['items']
    assert any(x['action'] == 'auth.outside_shift' for x in aud)


def test_overnight_window_supported(client, auth_hdr):
    now = _now_tenant(client, auth_hdr)
    # نافذة «البداية بعد النهاية» = عابرة منتصف الليل تغطي اللحظة الحالية
    f = (now - timedelta(hours=2)).strftime('%H:%M')
    t = (now - timedelta(hours=3)).strftime('%H:%M')  # منها إليها عبر الليل
    uid = _mk_user(client, auth_hdr, username='night1', name='ليلي',
                   password='rec123!Change',
                   login_windows=[{'from': f, 'to': t}])
    r = _login(client, 'night1', 'rec123!Change')
    assert r.status_code == 200, r.text


def test_unlock_after_lockout(client, auth_hdr):
    uid = _mk_user(client, auth_hdr)
    for _ in range(5):
        _login(client, 'recep1', 'wrong-wrong-99')
    r = _login(client, 'recep1', 'rec123!Change')
    assert r.status_code == 401 and 'AUTH.LOCKED' in r.text
    r = client.post(f'/api/org/users/{uid}/unlock', headers=auth_hdr)
    assert r.status_code == 200
    assert _login(client, 'recep1', 'rec123!Change').status_code == 200


def test_custom_roles_lifecycle(client, auth_hdr):
    # إنشاء دور مخصص «استقبال بلا حجوزات» بصلاحيات مختارة
    perms = ['frontdesk.view', 'reservations.view', 'folio.view', 'folio.pay']
    r = client.post('/api/org/roles', json={
        'name': 'استقبال تحصيل فقط', 'permissions': perms,
        'description': 'لا ينشئ ولا يلغي حجزاً'}, headers=auth_hdr)
    assert r.status_code == 201 and r.json()['code'].startswith('CUST-')
    code = r.json()['code']
    BAD = ('*',)
    r = client.post('/api/org/roles', json={'name': 'خبيث',
                                            'permissions': list(BAD)},
                    headers=auth_hdr)
    assert r.status_code == 422  # «*» حكر الدور النظامي
    # تعيينه وفعاليته الفعلية
    uid = _mk_user(client, auth_hdr, roles=(code,))
    eff = client.get(f'/api/org/users/{uid}/effective-perms',
                     headers=auth_hdr).json()['perms']
    assert sorted(eff) == sorted(perms)
    tok = {'Authorization':
           'Bearer ' + _login(client, 'recep1', 'rec123!Change')
           .json()['access_token']}
    assert client.get('/api/hotel/reservations', headers=tok).status_code == 200
    # يحاول إنشاء حجز ← 403 (ليس ضمن الدور المخصص)
    r = client.post('/api/hotel/reservations', json={}, headers=tok)
    assert r.status_code == 403
    # النظامي محمي
    r = client.patch('/api/org/roles/RECEPTIONIST',
                     json={'name': 'استقبال معدل', 'permissions': []},
                     headers=auth_hdr)
    assert r.status_code == 403 and 'ORG.SYSTEM_ROLE' in r.text
    # المعيَّن لا يُحذف
    r = client.delete(f'/api/org/roles/{code}', headers=auth_hdr)
    assert r.status_code == 409 and 'ORG.ROLE_IN_USE' in r.text
    # تعديله ينعكس فوراً، ثم نزعه وحذفه ينجح
    r = client.patch(f'/api/org/roles/{code}',
                     json={'name': 'استقبال تحصيل فقط',
                           'permissions': perms + ['reservations.create']},
                     headers=auth_hdr)
    assert r.status_code == 200 and 'reservations.create' in r.json()['permissions']
    client.patch(f'/api/org/users/{uid}', json={'role_codes': ['HOUSEKEEPING']},
                 headers=auth_hdr)
    r = client.delete(f'/api/org/roles/{code}', headers=auth_hdr)
    assert r.status_code == 200 and r.json()['deleted']


def test_audit_attribution_quick_view(client, auth_hdr):
    _mk_user(client, auth_hdr)
    items = client.get('/api/audit?actor=admin&module=org',
                       headers=auth_hdr).json()['items']
    kinds = {x['action'] for x in items}
    assert 'user.create' in kinds
    # والمستهدف ظاهر في الحمولة (من فعل ماذا + على من)
    cre = [x for x in items if x['action'] == 'user.create'][0]
    assert cre['after']['username'] == 'recep1'


def test_revoke_sessions_endpoint(client, auth_hdr):
    uid = _mk_user(client, auth_hdr)
    l = _login(client, 'recep1', 'rec123!Change').json()
    tok = {'Authorization': 'Bearer ' + l['access_token']}
    r = client.post(f'/api/org/users/{uid}/revoke-sessions', headers=auth_hdr)
    assert r.status_code == 200 and r.json()['sessions_revoked'] >= 1
    # التحديث القديم ميت والوصول القديم ميت
    assert client.post('/api/auth/refresh',
                       json={'refresh_token': l['refresh_token']}).status_code == 401
    assert client.get('/api/auth/me', headers=tok).status_code == 401
