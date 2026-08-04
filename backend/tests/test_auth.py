"""اختبارات الهوية: دخول، قفل محاولات، دوران الرموز وكشف إعادة الاستخدام."""
from tests.conftest import ADMIN


def _err(r):
    return r.json()['error']['code']


def test_login_success_returns_pair_and_user(client):
    r = client.post('/api/auth/login', json=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body['access_token'] and body['refresh_token']
    assert body['user']['username'] == 'admin'
    assert 'OWNER' in body['user']['roles']
    assert '*' in body['user']['perms']


def test_wrong_password_rejected_and_locks_after_5(client):
    bad = {'username': 'admin', 'password': 'wrong-pass-1'}
    for i in range(5):
        r = client.post('/api/auth/login', json=bad)
        assert r.status_code == 401, i
        assert _err(r) == 'AUTH.INVALID_CREDENTIALS'
    # بعد القفل: حتى كلمة المرور الصحيحة تُرفض مؤقتاً
    r = client.post('/api/auth/login', json=ADMIN)
    assert r.status_code == 401
    assert _err(r) == 'AUTH.LOCKED'


def test_me_requires_valid_bearer(client, token):
    ok = client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'})
    assert ok.status_code == 200
    assert ok.json()['username'] == 'admin'
    bad = client.get('/api/auth/me', headers={'Authorization': 'Bearer garbage'})
    assert bad.status_code == 401
    assert _err(bad) == 'AUTH.INVALID_TOKEN'


def test_refresh_rotation_and_reuse_detection(client):
    r1 = client.post('/api/auth/login', json=ADMIN).json()
    # دوران أول: الرمز القديم يستبدل بجديد من نفس العائلة
    r2 = client.post('/api/auth/refresh',
                     json={'refresh_token': r1['refresh_token']})
    assert r2.status_code == 200
    pair2 = r2.json()
    assert pair2['refresh_token'] != r1['refresh_token']
    # إعادة استخدام الرمز القديم (سرقة محتملة) ← كشف + قتل العائلة
    r3 = client.post('/api/auth/refresh',
                     json={'refresh_token': r1['refresh_token']})
    assert r3.status_code == 401
    assert _err(r3) == 'AUTH.REUSE_DETECTED'
    # حتى الرمز الأحدث في العائلة مات
    r4 = client.post('/api/auth/refresh',
                     json={'refresh_token': pair2['refresh_token']})
    assert r4.status_code == 401


def test_unknown_refresh_token_rejected(client):
    r = client.post('/api/auth/refresh', json={'refresh_token': 'nope'})
    assert r.status_code == 401
    assert _err(r) == 'AUTH.INVALID_REFRESH'
