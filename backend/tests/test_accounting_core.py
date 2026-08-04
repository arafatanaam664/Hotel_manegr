"""اختبارات نواة المحاسبة — القواعد الحمراء في ملف 02:
توازن إلزامي • لا ترحيل على أب • فترة مفتوحة • طرف مطلوب • ثبات المرحَّل
• التصحيح بالعكس فقط • Idempotency • سلسلة تدقيق سليمة."""
from datetime import date

import pytest
from sqlalchemy import select

from app import models as m
from app.audit import verify_chain
from app.posting import ensure_not_mutating_posted, post_event, PostingError

TODAY = date.today().isoformat()


def _err(r):
    return r.json()['error']['code']


def _balanced_body(**over):
    body = {
        'entry_date': TODAY,
        'branch_code': 'MAIN',
        'narration': 'قيد اختبار متوازن',
        'lines': [
            {'account_code': '1101', 'debit': '100.00', 'credit': '0'},
            {'account_code': '3101', 'debit': '0', 'credit': '100.00'},
        ],
    }
    body.update(over)
    return body


# ─── التحققات V1..V5 ─────────────────────────────────
def test_unbalanced_entry_rejected(client, auth_hdr):
    body = _balanced_body()
    body['lines'][1]['credit'] = '99.00'
    r = client.post('/api/journals/manual', json=body, headers=auth_hdr)
    assert r.status_code == 400
    assert _err(r) == 'ACCOUNTING.UNBALANCED_ENTRY'


def test_parent_account_rejected(client, auth_hdr):
    body = _balanced_body()
    body['lines'][0]['account_code'] = '1100'  # حساب أب تجميعي
    r = client.post('/api/journals/manual', json=body, headers=auth_hdr)
    assert r.status_code == 400
    assert _err(r) == 'ACCOUNTING.PARENT_ACCOUNT'


def test_single_line_rejected(client, auth_hdr):
    body = _balanced_body()
    body['lines'] = body['lines'][:1]
    r = client.post('/api/journals/manual', json=body, headers=auth_hdr)
    assert r.status_code in (400, 422)


def test_party_required_rejected(client, auth_hdr):
    body = _balanced_body()
    body['lines'][0] = {'account_code': '1110', 'debit': '100.00',
                        'credit': '0'}  # يتطلب طرفاً (نزيل)
    r = client.post('/api/journals/manual', json=body, headers=auth_hdr)
    assert r.status_code == 400
    assert _err(r) == 'ACCOUNTING.PARTY_REQUIRED'


def test_unknown_account_rejected(client, auth_hdr):
    body = _balanced_body()
    body['lines'][0]['account_code'] = '9999'
    r = client.post('/api/journals/manual', json=body, headers=auth_hdr)
    assert r.status_code == 400
    assert _err(r) == 'ACCOUNTING.UNKNOWN_ACCOUNT'


# ─── الترحيل والتسلسل والعكس ─────────────────────────
def test_manual_journal_posts_with_sequential_number(client, auth_hdr):
    r = client.post('/api/journals/manual', json=_balanced_body(),
                    headers=auth_hdr)
    assert r.status_code == 201
    je = r.json()
    assert je['status'] == 'POSTED'
    assert je['journal_type'] == 'MANUAL'
    assert je['entry_no'].startswith('JV-MA-')
    assert je['total_debit'] == je['total_credit'] == '100.0000'
    assert len(je['lines']) == 2


def test_reversal_creates_mirror_and_marks_source(client, auth_hdr):
    r = client.post('/api/journals/manual', json=_balanced_body(),
                    headers=auth_hdr)
    je = r.json()
    rv = client.post(f"/api/journals/{je['id']}/reverse",
                     json={'reason': 'إدخال خاطئ'}, headers=auth_hdr)
    assert rv.status_code == 201
    rev = rv.json()
    assert rev['journal_type'] == 'REVERSAL'
    assert rev['total_debit'] == rev['total_credit']
    # الأصل أصبح REVERSED والعكس يشير إليه
    after = client.get(f"/api/journals/{je['id']}", headers=auth_hdr).json()
    assert after['status'] == 'REVERSED'
    assert after['reversed_entry_id'] == rev['id']
    assert rev['reversal_of_entry_id'] == je['id']
    # الأصل والعكس متوازنان ويظهران تاريخياً — والصافي صفري تماماً
    tb = client.get('/api/reports/trial-balance', headers=auth_hdr).json()
    assert tb['balanced'] is True
    assert tb['net_balance_zero'] is True
    assert tb['total_debit'] == tb['total_credit'] == '200.0000'


def test_double_reversal_blocked(client, auth_hdr):
    je = client.post('/api/journals/manual', json=_balanced_body(),
                     headers=auth_hdr).json()
    client.post(f"/api/journals/{je['id']}/reverse",
                json={'reason': 'أول'}, headers=auth_hdr)
    r2 = client.post(f"/api/journals/{je['id']}/reverse",
                     json={'reason': 'ثانٍ'}, headers=auth_hdr)
    assert r2.status_code == 400
    assert _err(r2) == 'ACCOUNTING.NOT_POSTED'


def test_no_update_or_delete_endpoints_exist(client, auth_hdr):
    je = client.post('/api/journals/manual', json=_balanced_body(),
                     headers=auth_hdr).json()
    assert client.put(f"/api/journals/{je['id']}", json={},
                      headers=auth_hdr).status_code == 405
    assert client.patch(f"/api/journals/{je['id']}", json={},
                        headers=auth_hdr).status_code == 405
    assert client.delete(f"/api/journals/{je['id']}",
                         headers=auth_hdr).status_code == 405
    # وحارس الطبقة المركزية يرفض أي تعديل برمجي
    je_obj = client.get(f"/api/journals/{je['id']}", headers=auth_hdr).json()
    fake = m.JournalEntry(id=je_obj['id'], status='POSTED')
    with pytest.raises(PostingError):
        ensure_not_mutating_posted(fake, 'تعديل')


# ─── Idempotency والفترات ─────────────────────────────
def test_event_idempotency_returns_same_entry(db_session):
    db, factory, seed = db_session
    kw = dict(tenant_id=seed['tenant_id'], branch_code='MAIN',
              event_type='GUEST_DEPOSIT', event_key='dep:test:1',
              entry_date=date.today(), amounts={'amount': '50'},
              actor_id=seed['admin_id'], party_type='GUEST',
              party_id='g-1')
    e1 = post_event(db, **kw)
    db.commit()
    e2 = post_event(db, **kw)  # نفس المفتاح — لا تكرار
    db.commit()
    assert e1.id == e2.id
    n = db.execute(select(m.JournalEntry)
                   .where(m.JournalEntry.event_key == 'dep:test:1'))
    assert len(n.scalars().all()) == 1


def test_closed_period_rejects_posting(client, auth_hdr):
    periods = client.get('/api/periods', headers=auth_hdr).json()
    p_this = next(p for p in periods
                  if p['start_date'] <= TODAY <= p['end_date'])
    r = client.post(f"/api/periods/{p_this['id']}/close", headers=auth_hdr)
    assert r.status_code == 200
    assert r.json()['status'] == 'CLOSED'
    resp = client.post('/api/journals/manual', json=_balanced_body(),
                       headers=auth_hdr)
    assert resp.status_code == 400
    assert _err(resp) == 'ACCOUNTING.CLOSED_PERIOD'


# ─── التفويض وسجل التدقيق ─────────────────────────────
def test_rbac_denies_without_perm(client, db_session):
    """موظف استقبال (بلا صلاحيات محاسبية) يُرفض في كل نقطة محاسبية."""
    db, factory, seed = db_session
    from app.security import hash_password, new_uuid, utcnow
    rid = db.execute(select(m.Role).where(m.Role.code == 'RECEPTIONIST',
                     m.Role.tenant_id == seed['tenant_id'])).scalar_one().id
    uid = new_uuid()
    db.add(m.User(id=uid, tenant_id=seed['tenant_id'], username='recep',
                  full_name='استقبال', password_hash=hash_password('recep12345'),
                  created_at=utcnow()))
    db.add(m.UserRole(user_id=uid, role_id=rid))
    db.commit()
    r = client.post('/api/auth/login',
                    json={'username': 'recep', 'password': 'recep12345'})
    tok = r.json()['access_token']
    hdr = {'Authorization': f'Bearer {tok}'}
    assert client.get('/api/accounts', headers=hdr).status_code == 403
    assert client.post('/api/journals/manual', json=_balanced_body(),
                       headers=hdr).status_code == 403
    assert client.get('/api/audit', headers=hdr).status_code == 403


def test_audit_chain_intact_and_tamper_detected(client, db_session, auth_hdr):
    db, factory, seed = db_session
    client.post('/api/journals/manual', json=_balanced_body(),
                headers=auth_hdr)
    # سليمة بعد الترحيل
    v = client.get('/api/audit/verify', headers=auth_hdr)
    assert v.status_code == 200 and v.json()['ok'] is True
    # عبث مباشر بسطر (محاكاة هجوم على القاعدة) ← الكاشف يوقعه
    row = db.execute(select(m.AuditLog)
                     .where(m.AuditLog.tenant_id == seed['tenant_id'])
                     .order_by(m.AuditLog.id.desc())).scalars().first()
    row.after = {'forged': True}
    db.commit()
    broken = verify_chain(db, seed['tenant_id'])
    assert broken['ok'] is False
