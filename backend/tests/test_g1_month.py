"""بوابة G1 — سيناريو شهر فندقي كامل عبر محرك الترحيل فقط:
إشغال يومي لثلاث غرف + مطعم + مشتريات + سداد + تحصيلات + نقل ذمم
+ رواتب + إهلاك ⇒ ميزان متوازن يومياً ونهائياً وصافي صفري."""
from datetime import date

from app.reports import run_g1_month_scenario, trial_balance


def test_g1_full_month_scenario(db_session):
    db, factory, seed = db_session
    today = date.today()
    out = run_g1_month_scenario(db, tenant_id=seed['tenant_id'],
                                year=today.year, month=today.month,
                                actor_id=seed['admin_id'])
    db.commit()
    assert out['daily_balance_ok'] is True, out['issues']
    assert out['entries_posted'] > 100
    assert out['balanced'] is True
    assert out['net_zero'] is True
    # ميزان مراجعة اليوم الأخير متوازن حرفياً
    tb = trial_balance(db, seed['tenant_id'],
                       date(today.year, today.month, 28))
    assert tb['balanced'] is True and tb['net_balance_zero'] is True


def test_g1_endpoint_and_reports_api(client, auth_hdr):
    r = client.post('/api/demo/run-month', headers=auth_hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['balanced'] is True and body['net_zero'] is True
    assert body['daily_balance_ok'] is True
    # إعادة التشغيل آمنة (Idempotency): لا قيود جديدة
    n1 = body['entries_posted']
    r2 = client.post('/api/demo/run-month', headers=auth_hdr).json()
    assert r2['entries_posted'] == n1
    # ميزان المراجعة عبر الواجهة
    tb = client.get('/api/reports/trial-balance', headers=auth_hdr).json()
    assert tb['balanced'] is True
    assert float(tb['total_debit']) > 0
    assert tb['total_debit'] == tb['total_credit']
    # دفتر أستاذ حساب إيراد الغرف يعرض الليالي برصيد متحرك
    today = date.today()
    led = client.get('/api/reports/ledger',
                     params={'account_code': '4101',
                             'date_from': f'{today.year}-{today.month:02d}-01',
                             'date_to': str(today)},
                     headers=auth_hdr).json()
    assert led['account_code'] == '4101'
    assert len(led['rows']) >= today.day * 3 - 3
