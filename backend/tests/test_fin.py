# اختبارات المرحلة 7 — ملف 02 §5 إقفال السنة + §8 حدث #24 الإهلاك + §10 القوائم
# قبول-7/1: قسط الإهلاك = حساب يدوي موقع بالهللة (#24 متوازن Dr7101/Cr1590)
# قبول-7/2: إقفال يصفّر الإيرادات والمصروفات عبر 3202 والصافي إلى 3201
# قبول-7/3: الافتتاحية = ميزانية ما بعد الإقفال وبأرصدة الأطراف مدورة
# قبول-7/4: قائمة دخل USALI + ميزانية متوازنة + تدفقات بهوية Δ نقدية + أعمار = أستاذ
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import assets as FA
from app import closing as CL
from app import models as m
from app import reports as R
from app.posting import D, PostingError, create_and_post_journal
from app.security import hash_password, new_uuid, utcnow

Y = date.today().year
D0 = Decimal('0')


# ═══ أدوات ═══
def _mk_asset(db, tid, actor='t-admin', name='جهاز اختبار', acc='1520',
              cost='12000', salvage='0', life=4, method='STRAIGHT',
              pdate=None):
    return FA.create_asset(
        db, tenant_id=tid, actor_id=actor, name=name, category='اختبار',
        purchase_date=pdate or date(Y, 1, 10), cost=Decimal(cost),
        salvage=Decimal(salvage), useful_life_months=life, method=method,
        asset_account_code=acc, accum_account_code='1590',
        expense_account_code='7101')


def _bid(db_session):
    db, _, seed = db_session
    return seed['branch_id']


def _jv(db, tid, bid, d, lines, narration='اختبار'):
    return create_and_post_journal(
        db, tenant_id=tid, branch_id=bid, journal_type='MANUAL', entry_date=d,
        narration=narration,
        raw_lines=[{'account': a, 'debit': Decimal(dr), 'credit': Decimal(cr),
                    'description': 't',
                    **({'party_type': pt, 'party_id': pid} if pt else {})}
                   for a, dr, cr, pt, pid in lines],
        actor_id='t-admin')


def _acct_net(db, tid, code, d1=date(2000, 1, 1), d2=date(2099, 12, 31)):
    v = db.execute(
        select(func.coalesce(func.sum(
            m.JournalLine.debit_base - m.JournalLine.credit_base), 0))
        .join(m.JournalEntry, m.JournalLine.entry_id == m.JournalEntry.id)
        .join(m.Account, m.JournalLine.account_id == m.Account.id)
        .where(m.JournalLine.tenant_id == tid, m.Account.code == code,
               m.JournalEntry.status == 'POSTED',
               m.JournalEntry.entry_date.between(d1, d2))).scalar_one()
    return D(v)


def _period(db, tid, no, year_no=None):
    y = db.execute(select(m.FiscalYear).where(
        m.FiscalYear.tenant_id == tid,
        m.FiscalYear.year_no == (year_no or date.today().year))).scalar_one()
    return db.execute(select(m.FiscalPeriod).where(
        m.FiscalPeriod.fiscal_year_id == y.id,
        m.FiscalPeriod.period_no == no)).scalar_one()


def _mk_user(db, tid, role_code, username, password='Pass!12345'):
    role = db.execute(select(m.Role).where(
        m.Role.tenant_id == tid, m.Role.code == role_code)).scalar_one()
    u = m.User(id=new_uuid(), tenant_id=tid, username=username,
               full_name=username, password_hash=hash_password(password),
               created_at=utcnow())
    db.add(u)
    db.flush()
    db.add(m.UserRole(user_id=u.id, role_id=role.id))
    db.commit()
    return u


def _login(client, username, password='Pass!12345'):
    r = client.post('/api/auth/login',
                    json={'username': username, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': f'Bearer {r.json()["access_token"]}'}


# ═══════════════════════ الأصول الثابتة والإهلاك #24 ═══════════════════════
def test_charge_straight_golden(db_session):
    """قبول-7/1: (التكلفة − الخردة)/العمر شهرياً بالهللة، وأرضية الخردة."""
    db, _, seed = db_session
    tid = seed['tenant_id']
    a = _mk_asset(db, tid, cost='12400', salvage='400', life=48)
    ch = FA.charge_for(a, f'{Y}-02')
    assert ch == Decimal('250.0000')  # (12400-400)/48 = 250 بالضبط


def test_charge_declining_progression_and_floor(db_session):
    db, _, seed = db_session
    tid = seed['tenant_id']
    a = _mk_asset(db, tid, cost='900', salvage='100', life=6,
                  method='DECLINING')
    seq = []
    dep = D0
    for mm in ['02', '03', '04', '05', '06', '07', '08']:
        a.depreciated_total = dep
        ch = FA.charge_for(a, f'{Y}-{mm}')
        seq.append(ch)
        dep += ch
    # 300، 200، 133.3333، 88.8889، 59.2593، ثم أرضية الخردة → 18.5185، ثم صفر
    assert seq[:2] == [Decimal('300.0000'), Decimal('200.0000')]
    assert seq[2] == Decimal('133.3333')
    assert seq[5] == Decimal('18.5185')      # الهبوط للخردة 100 فقط
    assert seq[6] == Decimal('0')


def test_run_month_posts_balanced_24(db_session):
    db, _, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    mine = _mk_asset(db, tid, cost='12400', salvage='400', life=48)
    db.flush()
    month = f'{Y}-02'
    # المتوقع = شحنة كل أصل فعّال مستحق (المزروع + الجديد) مع قاعدة
    # «الإهلاك من الشهر التالي للشراء» نفسها
    expected = {}
    for a in FA.list_assets(db, tid):
        if FA._months_between(a.purchase_date, month) < 1:
            continue
        c = FA.charge_for(a, month)
        if c > 0:
            expected[a.id] = c
    assert mine.id in expected
    run = FA.run_depreciation(db, tenant_id=tid, actor_id='t-admin',
                              branch_id=bid, month=month)
    db.flush()
    assert run.asset_count == len(expected)
    assert run.total == sum(expected.values(), D0)
    entry = db.get(m.JournalEntry, run.posted_entry_id)
    td = sum((D(l.debit_base) for l in entry.lines), D0)
    tc = sum((D(l.credit_base) for l in entry.lines), D0)
    assert td == tc == run.total               # متوازن بناؤه V1
    assert entry.journal_type == 'AUTO_DEPRECIATION'
    codes = {db.get(m.Account, l.account_id).code for l in entry.lines}
    assert codes == {'7101', '1590'}
    db.refresh(mine)
    assert mine.last_run_month == month
    assert mine.depreciated_total == Decimal('250.0000')


def test_run_once_per_month_and_idempotent(db_session):
    db, _, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    FA.run_depreciation(db, tenant_id=tid, actor_id='t-admin',
                        branch_id=bid, month=f'{Y}-03')
    db.flush()
    with pytest.raises(PostingError) as ei:
        FA.run_depreciation(db, tenant_id=tid, actor_id='t-admin',
                            branch_id=bid, month=f'{Y}-03')
    assert ei.value.code == 'FA.RUN_EXISTS'


def test_no_charge_in_purchase_month(db_session):
    """الإهلاك يبدأ من الشهر التالي للشراء (ADR-0029)."""
    db, _, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    late = _mk_asset(db, tid, name='شراء منتصف الشهر', cost='600', life=3,
                     pdate=date(Y, 6, 15))
    db.flush()
    run = FA.run_depreciation(db, tenant_id=tid, actor_id='t-admin',
                              branch_id=bid, month=f'{Y}-06')
    db.flush()
    assert all(l['asset_id'] != late.id for l in run.lines)
    run2 = FA.run_depreciation(db, tenant_id=tid, actor_id='t-admin',
                               branch_id=bid, month=f'{Y}-07')
    db.flush()
    mine = [l for l in run2.lines if l['asset_id'] == late.id]
    assert mine and Decimal(mine[0]['charge']) == Decimal('200.0000')


def test_salvage_floor_then_zero_and_dispose(db_session):
    db, _, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    tiny = _mk_asset(db, tid, cost='100', salvage='20', life=2)
    db.flush()
    m2 = FA.charge_for(tiny, f'{Y}-02')
    tiny.depreciated_total = m2
    m3 = FA.charge_for(tiny, f'{Y}-03')
    assert (m2, m3) == (Decimal('40.0000'), Decimal('40.0000'))  # 100-20=80/2
    tiny.depreciated_total = m2 + m3
    assert FA.charge_for(tiny, f'{Y}-04') == Decimal('0')        # NBV=الخردة
    # الإعدام يخرج الأصل من التشغيلات القادمة
    FA.dispose_asset(db, tenant_id=tid, actor_id='t-admin', asset_id=tiny.id,
                     disposed_at=date(Y, 4, 1), reason='بيع وهمي للاختبار')
    assert tiny.status == 'DISPOSED'


def test_create_validations(db_session):
    db, _, seed = db_session
    tid = seed['tenant_id']
    with pytest.raises(PostingError) as e1:
        _mk_asset(db, tid, cost='100', salvage='100', life=5)
    assert e1.value.code == 'FA.BAD_SALVAGE'
    with pytest.raises(PostingError) as e2:
        FA.create_asset(db, tenant_id=tid, actor_id='t', name='حساب خاطئ',
                        category='', purchase_date=date(Y, 1, 1),
                        cost=Decimal('500'), salvage=Decimal('0'),
                        useful_life_months=12, method='STRAIGHT',
                        asset_account_code='1510', accum_account_code='1590',
                        expense_account_code='2310')
    assert e2.value.code == 'FA.BAD_ACCOUNT_TYPE'
    with pytest.raises(PostingError) as e3:
        FA.create_asset(db, tenant_id=tid, actor_id='t', name='أب ممنوع',
                        category='', purchase_date=date(Y, 1, 1),
                        cost=Decimal('500'), salvage=Decimal('0'),
                        useful_life_months=12, method='STRAIGHT',
                        asset_account_code='1500', accum_account_code='1590',
                        expense_account_code='7101')
    assert e3.value.code == 'FA.PARENT_ACCOUNT'


def test_register_matches_gl_after_posted_purchases(db_session):
    """سجل الأصل+قيد شرائه موثقاً ⇐ NBV السجل = 15xx − 1590 بالضبط."""
    db, _, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    rep0 = FA.register_report(db, tid)
    assert rep0['matches_gl'] is True   # المزروع أُثبت بقيود اقتناء افتتاحية
    # أصل جديد بلا قيد اقتناء ⇐ العلم ينطفئ حتى يُوثَّق شراؤه
    mine = _mk_asset(db, tid, cost='12400', salvage='400', life=48)
    db.flush()
    rep0b = FA.register_report(db, tid)
    assert rep0b['matches_gl'] is False
    _jv(db, tid, bid, date(Y, 1, 5),
        [('1520', '12400', '0', None, None),
         ('8002', '0', '12400', None, None)], 'شراء أصل اختبار')
    rep1 = FA.register_report(db, tid)
    assert rep1['matches_gl'] is True
    month = f'{Y}-02'
    FA.run_depreciation(db, tenant_id=tid, actor_id='t-admin',
                        branch_id=bid, month=month)
    db.flush()
    rep2 = FA.register_report(db, tid)
    assert rep2['matches_gl'] is True    # ما زال متطابقاً بعد #24
    assert Decimal(rep2['totals']['nbv']) == Decimal(rep2['gl']['nbv'])


def test_schedule_preview(db_session):
    db, _, seed = db_session
    tid = seed['tenant_id']
    a = _mk_asset(db, tid, cost='12400', salvage='400', life=48)
    sch = FA.asset_schedule(a, f'{Y}-02')
    assert len(sch) == 12
    assert all(Decimal(s['charge']) == Decimal('250.0000') for s in sch)
    assert Decimal(sch[-1]['nbv']) == Decimal('12400') - Decimal('250') * 12


# ═══════════════════════ القوائم المالية — 02 §10 ═══════════════════════
def _post_is_fixtures(db, tid, bid):
    d = date(Y, 6, 10)
    _jv(db, tid, bid, d, [('1101', '10000', '0', None, None),
                          ('4101', '0', '10000', None, None)], 'إيراد غرف')
    _jv(db, tid, bid, d, [('1101', '4000', '0', None, None),
                          ('4201', '0', '4000', None, None)], 'إيراد مطعم')
    _jv(db, tid, bid, d, [('5101', '1500', '0', None, None),
                          ('1101', '0', '1500', None, None)], 'تكلفة مبيعات')
    _jv(db, tid, bid, d, [('6210', '800', '0', None, None),
                          ('1101', '0', '800', None, None)], 'رواتب مطبخ')
    _jv(db, tid, bid, d, [('6110', '3000', '0', None, None),
                          ('1101', '0', '3000', None, None)], 'رواتب استقبال')
    _jv(db, tid, bid, d, [('6310', '500', '0', None, None),
                          ('1101', '0', '500', None, None)], 'مصروف إداري')
    _jv(db, tid, bid, d, [('7101', '250', '0', None, None),
                          ('1101', '0', '250', None, None)], 'إهلاك يدوي')


def test_income_statement_usali_golden(db_session):
    """قبول-7/4(أ): دخل الغرف 7000، F&B 1700، غير موزعة 500، GOP 8200، صاف 7950."""
    db, _, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    _post_is_fixtures(db, tid, bid)
    rep = R.income_statement(db, tid, date(Y, 6, 1), date(Y, 6, 30))
    rooms = next(x for x in rep['departments'] if x['key'] == 'ROOMS')
    fnb = next(x for x in rep['departments'] if x['key'] == 'FNB')
    assert rooms['revenue_total'] == 10000 and rooms['expense_total'] == 3000
    assert rooms['dept_income'] == 7000
    assert fnb['dept_income'] == Decimal('1700')   # 4000 − (1500+800)
    assert rep['undistributed_total'] == 500
    assert rep['gop'] == Decimal('8200')
    assert rep['non_operating_total'] == 250
    assert rep['net_income'] == Decimal('7950')


def test_balance_sheet_always_balanced(db_session):
    db, _, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    _post_is_fixtures(db, tid, bid)
    bs = R.balance_sheet(db, tid, date(Y, 6, 30))
    assert bs['balanced'] is True and bs['diff'] == 0
    # ربح العام غير المُقفل يظهر ضمن حقوق الملكية
    assert bs['current_year_earnings'] == Decimal('7950')
    assert bs['total_equity'] >= Decimal('7950')


def test_cash_flow_identity_holds(db_session):
    """قبول-7/4(ب): تشغيلي+استثماري+تمويلي+تحويلات = Δ النقدية حرفياً."""
    db, _, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    _post_is_fixtures(db, tid, bid)
    FA.run_depreciation(db, tenant_id=tid, actor_id='t-admin',
                        branch_id=bid, month=f'{Y}-06')
    db.flush()
    cf = R.cash_flow(db, tid, date(Y, 6, 1), date(Y, 6, 30))
    assert cf['identity_holds'] is True
    assert cf['reconciliation_diff'] == 0
    # النافذة: نقدية +14000 إيراد − 6050 مصاريف = 7950 (الإهلاك لا نقد فيه)
    assert cf['cash_delta_actual'] == Decimal('7950')
    assert cf['operating'] + cf['investing'] + cf['financing'] == \
        Decimal('7950') - cf['equity_and_system_transfers']
    assert cf['depreciation_addback'] > 0   # حركة 1590 ضمن النافذة أُعيدت


def test_aging_ar_fifo_and_gl_match(db_session):
    """قبول-7/4(ج): سداد جزئي FIFO يبقي 1800 بعمر 31–60 والمجموع = الأستاذ."""
    db, _, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    g = m.Guest(id=new_uuid(), tenant_id=tid, full_name='نزيل اختبار',
                phone='', id_number_enc='', nationality='', vip=False,
                blacklist=False, notes='', created_at=utcnow())
    db.add(g)
    db.flush()
    _jv(db, tid, bid, date(Y, 4, 10),
        [('1110', '3000', '0', 'GUEST', g.id), ('4101', '0', '3000', None, None)],
        'شحنة نزيل')
    _jv(db, tid, bid, date(Y, 5, 2),
        [('1101', '1200', '0', None, None), ('1110', '0', '1200', 'GUEST', g.id)],
        'سداد جزئي')
    rep = R.aging_report(db, tid, '1110', date(Y, 6, 1))
    assert rep['matches_gl'] is True
    row = rep['rows'][0]
    assert row['party_name'] == 'نزيل اختبار'
    assert row['buckets']['31-60'] == Decimal('1800')   # 52 يوماً
    assert row['buckets']['0-30'] == Decimal('0')
    assert rep['grand_total'] == Decimal('1800')


def test_aging_ap_buckets(db_session):
    db, _, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    sup = db.execute(select(m.InvSupplier).where(
        m.InvSupplier.tenant_id == tid)).scalars().first()
    _jv(db, tid, bid, date(Y, 3, 1),
        [('1210', '2000', '0', None, None),
         ('2101', '0', '2000', 'SUPPLIER', sup.id)], 'شراء آجل')
    _jv(db, tid, bid, date(Y, 4, 5),
        [('2101', '500', '0', 'SUPPLIER', sup.id),
         ('1101', '0', '500', None, None)], 'سداد جزئي مورد')
    rep = R.aging_report(db, tid, '2101', date(Y, 6, 1))
    assert rep['matches_gl'] is True
    row = rep['rows'][0]
    assert row['buckets']['+90'] == Decimal('1500')     # 92 يوماً
    assert rep['grand_total'] == Decimal('1500')


# ═══════════════════════ الفترات اللينة/الصلبة — 02 §5 ═══════════════════════
def test_soft_close_blocks_normal_allows_soft_adjust(db_session):
    db, _, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    p = _period(db, tid, 1)
    p.status = 'SOFT_CLOSED'
    db.flush()
    with pytest.raises(PostingError) as e1:
        _jv(db, tid, bid, date(Y, 1, 15),
            [('1101', '50', '0', None, None), ('4101', '0', '50', None, None)])
    assert e1.value.code == 'ACCOUNTING.CLOSED_PERIOD'
    ok = create_and_post_journal(
        db, tenant_id=tid, branch_id=bid, journal_type='MANUAL',
        entry_date=date(Y, 1, 16), narration='تسوية مدير مالي',
        raw_lines=[{'account': '1101', 'debit': Decimal('60'),
                    'credit': D0, 'description': 'a'},
                   {'account': '4101', 'debit': D0,
                    'credit': Decimal('60'), 'description': 'b'}],
        actor_id='t-fm', allow_soft=True)
    assert ok.status == 'POSTED'


def test_hard_close_blocks_everything(db_session):
    db, _, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    p = _period(db, tid, 2)
    p.status = 'HARD_CLOSED'
    db.flush()
    for soft in (False, True):
        with pytest.raises(PostingError):
            create_and_post_journal(
                db, tenant_id=tid, branch_id=bid, journal_type='MANUAL',
                entry_date=date(Y, 2, 10), narration='x',
                raw_lines=[{'account': '1101', 'debit': Decimal('1'),
                            'credit': D0, 'description': 'a'},
                           {'account': '4101', 'debit': D0,
                            'credit': Decimal('1'), 'description': 'b'}],
                actor_id='t', allow_soft=soft)


# ═══════════════════════ إقفال السنة — 02 §5 ═══════════════════════
def _close_periods_1_11(db, tid):
    for no in range(1, 12):
        p = _period(db, tid, no)
        p.status = 'SOFT_CLOSED'
    db.flush()


def test_year_close_golden_flow(db_session):
    """قبول-7/2+7/3: صفرية الإيراد/المصروف، صافٍ 7000→3201، افتتاحية بأطرافها."""
    db, _, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    _jv(db, tid, bid, date(Y, 6, 15),
        [('1101', '10000', '0', None, None), ('4101', '0', '10000', None, None)])
    _jv(db, tid, bid, date(Y, 6, 15),
        [('6110', '3000', '0', None, None), ('1101', '0', '3000', None, None)])
    _close_periods_1_11(db, tid)

    pre = CL.precheck(db, tid, date.today().year)
    assert pre['ready'] is True
    res = CL.close_fiscal_year(db, tenant_id=tid, actor_id='t-fm',
                               branch_id=bid, year_no=date.today().year)
    db.flush()
    assert Decimal(res['net_income']) == 7000
    # 1) الإيرادات والمصروفات صُفِّرت في السنة القديمة
    assert _acct_net(db, tid, '4101', date(Y, 1, 1), date(Y, 12, 31)) == 0
    assert _acct_net(db, tid, '6110', date(Y, 1, 1), date(Y, 12, 31)) == 0
    # 2) 3202 عاد صفراً و3201 استلم الربح (حركة السنة القديمة فقط — الافتتاحية
    # تعيد إثبات الرصيد ذاته في السنة الجديدة والتقارير ترسي منها ADR-0031)
    assert _acct_net(db, tid, '3202') == 0
    assert _acct_net(db, tid, '3201', date(Y, 1, 1), date(Y, 12, 31)) == \
        Decimal('-7000')
    # والميزانية بعد الافتتاحية تُظهر 7000 مرة واحدة (مرساة الافتتاح)
    bs_new = R.balance_sheet(db, tid, date(Y + 1, 1, 1))
    re_line = [r for r in bs_new['equity'] if r['code'] == '3201']
    assert re_line and re_line[0]['amount'] == 7000
    # 3) قيد الإقفال متوازن
    closing = db.get(m.JournalEntry, res['closing_entry_id'])
    assert closing.journal_type == 'CLOSING'
    assert sum(D(l.debit_base) for l in closing.lines) == \
        sum(D(l.credit_base) for l in closing.lines)
    # 4) الافتتاحية في السنة الجديدة بأرصدة الأطراف (سلفة الموظف 500)
    opening = db.get(m.JournalEntry, res['opening_entry_id'])
    assert opening.journal_type == 'OPENING'
    assert str(opening.entry_date) == f'{date.today().year + 1}-01-01'
    party_lines = [l for l in opening.lines if l.party_type == 'EMPLOYEE']
    assert len(party_lines) == 1 and D(party_lines[0].debit_base) == 500
    assert sum(D(l.debit_base) for l in opening.lines) == \
        sum(D(l.credit_base) for l in opening.lines)
    # 5) افتتاحية = ميزانية ما بعد الإقفال: إيراد/مصروف بلا أرصدة أبداً
    bs = R.balance_sheet(db, tid, date(Y, 12, 31))
    assert bs['balanced'] is True and bs['current_year_earnings'] == 0
    new_bs = R.balance_sheet(db, tid, date(Y + 1, 1, 1))
    assert new_bs['balanced'] is True
    # 6) حالات: سنة قديمة موصدة، فترتها 12 صلبة، سنة جديدة بـ 12 فترة مفتوحة
    y_old = db.execute(select(m.FiscalYear).where(
        m.FiscalYear.tenant_id == tid,
        m.FiscalYear.year_no == date.today().year)).scalar_one()
    assert y_old.status == 'CLOSED'
    p12 = db.execute(select(m.FiscalPeriod).where(
        m.FiscalPeriod.fiscal_year_id == y_old.id,
        m.FiscalPeriod.period_no == 12)).scalar_one()
    assert p12.status == 'HARD_CLOSED'
    y_new = db.execute(select(m.FiscalYear).where(
        m.FiscalYear.tenant_id == tid,
        m.FiscalYear.year_no == date.today().year + 1)).scalar_one()
    assert len(y_new.periods) == 12
    assert all(p.status == 'OPEN' for p in y_new.periods)
    # 7) لا ترحيل في السنة الموصدة حتى كتسوية
    with pytest.raises(PostingError):
        create_and_post_journal(
            db, tenant_id=tid, branch_id=bid, journal_type='MANUAL',
            entry_date=date(Y, 6, 20), narration='بعد الإقفال',
            raw_lines=[{'account': '1101', 'debit': Decimal('1'),
                        'credit': D0, 'description': 'a'},
                       {'account': '4101', 'debit': D0,
                        'credit': Decimal('1'), 'description': 'b'}],
            actor_id='t', allow_soft=True)


def test_year_close_idempotent_and_blocked_when_open(db_session):
    db, _, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    with pytest.raises(PostingError) as e0:
        CL.close_fiscal_year(db, tenant_id=tid, actor_id='t',
                             branch_id=bid, year_no=date.today().year)
    assert e0.value.code == 'FIN.YEAR_NOT_READY'
    _jv(db, tid, bid, date(Y, 3, 3),
        [('1101', '500', '0', None, None), ('4101', '0', '500', None, None)])
    _close_periods_1_11(db, tid)
    CL.close_fiscal_year(db, tenant_id=tid, actor_id='t',
                         branch_id=bid, year_no=date.today().year)
    db.flush()
    with pytest.raises(PostingError) as e1:
        CL.close_fiscal_year(db, tenant_id=tid, actor_id='t',
                             branch_id=bid, year_no=date.today().year)
    assert e1.value.code == 'FIN.YEAR_NOT_READY'   # مفتاح close:{fy} موجد


def test_year_close_nothing_to_close(db_session):
    db, _, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    _close_periods_1_11(db, tid)
    with pytest.raises(PostingError) as e:
        CL.close_fiscal_year(db, tenant_id=tid, actor_id='t',
                             branch_id=bid, year_no=date.today().year)
    assert e.value.code == 'FIN.NOTHING_TO_CLOSE'


# ═══════════════════════ RBAC عبر HTTP ═══════════════════════
def test_http_fa_cycle_and_rbac(client, db_session):
    db, _, seed = db_session
    tid = seed['tenant_id']
    _mk_user(db, tid, 'FINANCE_MANAGER', 'fm.g7')
    _mk_user(db, tid, 'POS_CASHIER', 'cashier.g7')
    fm = _login(client, 'fm.g7')
    cash = _login(client, 'cashier.g7')
    r = client.get('/api/fa/assets', headers=fm)
    assert r.status_code == 200 and len(r.json()) == 3       # المزروع
    r = client.get('/api/fa/assets', headers=cash)
    assert r.status_code == 403
    r = client.post('/api/fa/assets', headers=fm, json={
        'name': 'مصعد نزلاء', 'category': 'معدات',
        'purchase_date': f'{Y}-01-10', 'cost': '8400', 'salvage': '400',
        'useful_life_months': 40, 'method': 'STRAIGHT'})
    assert r.status_code == 201, r.text
    r = client.post('/api/fa/runs', headers=fm, json={'month': f'{Y}-02'})
    assert r.status_code == 201, r.text
    body = r.json()
    # المؤهلون في فبراير: FA-001 + FA-002 (المزروعان الأقدم) + الجديد —
    # أصل المزروع بشراء مارس لا يُهلك قبل الشهر التالي لشرائه
    assert body['asset_count'] == 3
    assert Decimal(body['total']) > 0
    aid = body['posted_entry_id']
    r = client.get(f'/api/journals/{aid}', headers=fm)
    assert r.json()['journal_type'] == 'AUTO_DEPRECIATION'
    r = client.post('/api/fa/runs', headers=fm, json={'month': f'{Y}-02'})
    assert r.status_code == 400 and 'RUN_EXISTS' in r.text


def test_http_statements_and_close(client, db_session):
    db, _, seed = db_session
    tid = seed['tenant_id']
    _mk_user(db, tid, 'FINANCE_MANAGER', 'fm.g7b')
    _mk_user(db, tid, 'ACCOUNTANT', 'acc.g7b')
    _mk_user(db, tid, 'POS_CASHIER', 'cash.g7b')
    fm = _login(client, 'fm.g7b')
    acc = _login(client, 'acc.g7b')
    cash = _login(client, 'cash.g7b')
    # حركة بسيطة عبر API
    r = client.post('/api/journals/manual', headers=fm, json={
        'branch_code': 'MAIN', 'entry_date': f'{Y}-06-12',
        'narration': 'إيراد اختبار HTTP', 'lines': [
            {'account_code': '1101', 'debit': '2000', 'credit': '0',
             'description': 'a'},
            {'account_code': '4101', 'debit': '0', 'credit': '2000',
             'description': 'b'}]})
    assert r.status_code == 201, r.text
    # القوائم
    r = client.get(f'/api/reports/income-statement?from={Y}-06-01&to={Y}-06-30',
                   headers=acc)
    assert r.status_code == 200
    assert Decimal(r.json()['net_income']) == 2000
    r = client.get(f'/api/reports/balance-sheet?as_of={Y}-06-30', headers=acc)
    assert r.json()['balanced'] is True
    r = client.get(f'/api/reports/cash-flow?from={Y}-06-01&to={Y}-06-30',
                   headers=acc)
    assert r.json()['identity_holds'] is True
    r = client.get(f'/api/reports/aging?account=1120&as_of={Y}-06-30',
                   headers=acc)
    assert r.json()['matches_gl'] is True
    r = client.get(f'/api/reports/income-statement?from={Y}-06-01&to={Y}-06-30',
                   headers=cash)
    assert r.status_code == 403
    # إغلاق لين عبر API ثم تسوية FM فقط ثم صلب
    years = client.get('/api/years', headers=fm).json()
    p1id = years[0]['periods'][0]['id']
    r = client.post(f'/api/periods/{p1id}/close', headers=fm)
    assert r.json()['status'] == 'SOFT_CLOSED'
    adj = {'branch_code': 'MAIN', 'entry_date': f'{Y}-01-20',
           'narration': 'تسوية', 'lines': [
               {'account_code': '1101', 'debit': '10', 'credit': '0',
                'description': 'a'},
               {'account_code': '4101', 'debit': '0', 'credit': '10',
                'description': 'b'}]}
    r = client.post('/api/journals/adjust', headers=acc, json=adj)
    assert r.status_code == 403              # المحاسب بلا periods.adjust
    r = client.post('/api/journals/adjust', headers=fm, json=adj)
    assert r.status_code == 201, r.text
    r = client.post('/api/journals/manual', headers=fm, json=adj)
    assert r.status_code == 400              # عادي ممنوع في فترة لينة
    r = client.post(f'/api/periods/{p1id}/hard-close', headers=fm)
    assert r.json()['status'] == 'HARD_CLOSED'
    r = client.post('/api/journals/adjust', headers=fm, json=adj)
    assert r.status_code == 400              # الصلب نهائي مطلقاً


def test_http_year_close_full(client, db_session):
    db, _, seed = db_session
    tid = seed['tenant_id']
    _mk_user(db, tid, 'FINANCE_MANAGER', 'fm.g7c')
    _mk_user(db, tid, 'POS_CASHIER', 'cash.g7c')
    fm = _login(client, 'fm.g7c')
    cash = _login(client, 'cash.g7c')
    client.post('/api/journals/manual', headers=fm, json={
        'branch_code': 'MAIN', 'entry_date': f'{Y}-05-10',
        'narration': 'إيراد قبل الإقفال', 'lines': [
            {'account_code': '1101', 'debit': '7000', 'credit': '0',
             'description': 'a'},
            {'account_code': '4101', 'debit': '0', 'credit': '7000',
             'description': 'b'}]})
    r = client.get(f'/api/years/{date.today().year}/close-precheck', headers=fm)
    assert r.status_code == 200 and r.json()['ready'] is False
    for no in range(1, 12):
        pid = client.get('/api/years', headers=fm).json()[0]['periods'][no - 1]['id']
        client.post(f'/api/periods/{pid}/close', headers=fm)
    r = client.get(f'/api/years/{date.today().year}/close-precheck', headers=fm)
    assert r.json()['ready'] is True
    r = client.post(f'/api/years/{date.today().year}/close', headers=cash)
    assert r.status_code == 403
    r = client.post(f'/api/years/{date.today().year}/close', headers=fm)
    assert r.status_code == 201, r.text
    body = r.json()
    assert Decimal(body['net_income']) == 7000
    assert body['next_year_no'] == date.today().year + 1
    r = client.post(f'/api/years/{date.today().year}/close', headers=fm)
    assert r.status_code == 400              # لا إقفال مزدوج أبداً