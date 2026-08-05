"""التقارير المالية من المرحَّل فقط (ملف 02 §10) + سيناريو شهر فندقي (بوابة G1)."""
import calendar
from datetime import date
from decimal import Decimal

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from . import models as m
from .posting import D, PostingError


def opening_anchor(db: Session, tenant_id: str, as_of: date) -> date | None:
    """تاريخ أحدث قيد افتتاحي (OPENING) عند أو قبل as_of.

    البنية الدفترية (ADR-0031): الافتتاحية تستبدل تراكم العام القديم —
    أي جمع موازين عابر للسنة يبدأ من آخر افتتاحية، فلا تتضاعف الأرصدة."""
    d = db.execute(
        select(func.max(m.JournalEntry.entry_date))
        .where(m.JournalEntry.tenant_id == tenant_id,
               m.JournalEntry.journal_type == 'OPENING',
               m.JournalEntry.status == 'POSTED',
               m.JournalEntry.entry_date <= as_of)).scalar_one()
    return d


def account_sums(db: Session, tenant_id: str, as_of: date,
                 up_to: date | None = None, from_date: date | None = None):
    """مجاميع (مدين، دائن) لكل حساب ورقي من القيود POSTED (+REVERSED تاريخياً:
    القيد المعكوس وعكسه يظهران كلاهما — فالأثر الصافي دقيق).
    إن وُجدت افتتاحية أحدث من from_date يبدأ الجمع منها (ADR-0031)."""
    lower = from_date
    anchor = opening_anchor(db, tenant_id, as_of)
    if anchor is not None and (lower is None or anchor > lower):
        lower = anchor
    q = (select(m.JournalLine.account_id,
                func.sum(m.JournalLine.debit_base),
                func.sum(m.JournalLine.credit_base))
         .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
         .where(m.JournalLine.tenant_id == tenant_id,
                m.JournalEntry.status.in_(['POSTED', 'REVERSED'])))
    if lower:
        q = q.where(m.JournalEntry.entry_date >= lower)
    q = q.where(m.JournalEntry.entry_date <= as_of)
    q = q.group_by(m.JournalLine.account_id)
    return {aid: (D(td or 0), D(tc or 0)) for aid, td, tc in db.execute(q).all()}


def trial_balance(db: Session, tenant_id: str, as_of: date) -> dict:
    accounts = db.execute(
        select(m.Account).where(m.Account.tenant_id == tenant_id)
        .order_by(m.Account.code)).scalars().all()
    sums = account_sums(db, tenant_id, as_of)
    rows, tot_d, tot_c = [], Decimal('0'), Decimal('0')
    leaf_rows = {}
    for a in accounts:
        if not a.is_postable:
            continue
        td, tc = sums.get(a.id, (Decimal('0'), Decimal('0')))
        leaf_rows[a.code] = (td, tc, td - tc, a)
        tot_d += td
        tot_c += tc
    for a in accounts:
        if a.is_postable:
            td, tc, bal, _ = leaf_rows[a.code]
        else:
            kids = [k for k in leaf_rows if _under(k, a.code, accounts)]
            td = sum(leaf_rows[k][0] for k in kids)
            tc = sum(leaf_rows[k][1] for k in kids)
            bal = td - tc
        rows.append({'account_code': a.code, 'account_name': a.name_ar,
                     'level': a.level, 'nature': a.nature,
                     'debit_sum': td, 'credit_sum': tc, 'balance': bal,
                     'balance_side': 'DEBIT' if bal > 0 else ('CREDIT' if bal < 0 else 'ZERO')})
    # فحص الصفريـة الصافي: مجموع (مدين-دائن) لكل الأوراق يجب أن يكون صفراً تماماً
    net = sum(v[2] for v in leaf_rows.values())
    return {'as_of': as_of, 'total_debit': tot_d, 'total_credit': tot_c,
            'balanced': tot_d == tot_c, 'rows': rows,
            'net_balance_zero': net == 0}


def _under(child_code: str, parent_code: str, accounts) -> bool:
    """هل الحساب الورقي تحت الأب هرمياً عبر سلسلة parent_id؟"""
    by_code = {a.code: a for a in accounts}
    node = by_code.get(child_code)
    guard = 0
    while node and node.parent_id and guard < 12:
        parent = next((x for x in accounts if x.id == node.parent_id), None)
        if parent is None:
            return False
        if parent.code == parent_code:
            return True
        node = parent
        guard += 1
    return False


def ledger(db: Session, tenant_id: str, account_code: str,
           date_from: date, date_to: date) -> dict:
    acc = db.execute(
        select(m.Account).where(m.Account.tenant_id == tenant_id,
                                m.Account.code == account_code)).scalar_one_or_none()
    if acc is None:
        raise PostingError('ACCOUNTING.UNKNOWN_ACCOUNT', f'حساب غير موجود: {account_code}')
    # رصيد افتتاحي = مجاميع ما قبل بداية الفترة
    q0 = (select(func.sum(m.JournalLine.debit_base), func.sum(m.JournalLine.credit_base))
          .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
          .where(m.JournalLine.tenant_id == tenant_id,
                 m.JournalLine.account_id == acc.id,
                 m.JournalEntry.status.in_(['POSTED', 'REVERSED']),
                 m.JournalEntry.entry_date < date_from))
    td0, tc0 = db.execute(q0).one()
    opening = D(td0 or 0) - D(tc0 or 0)

    q = (select(m.JournalEntry, m.JournalLine)
         .join(m.JournalLine, m.JournalLine.entry_id == m.JournalEntry.id)
         .where(m.JournalEntry.tenant_id == tenant_id,
                m.JournalLine.account_id == acc.id,
                m.JournalEntry.status.in_(['POSTED', 'REVERSED']),
                and_(m.JournalEntry.entry_date >= date_from,
                     m.JournalEntry.entry_date <= date_to))
         .order_by(m.JournalEntry.entry_date, m.JournalEntry.entry_no,
                   m.JournalLine.line_no))
    rows, running = [], opening
    for je, ln in db.execute(q).all():
        running = running + D(ln.debit_base) - D(ln.credit_base)
        rows.append({'entry_no': je.entry_no, 'entry_date': je.entry_date,
                     'journal_type': je.journal_type, 'narration': je.narration,
                     'debit': D(ln.debit_base), 'credit': D(ln.credit_base),
                     'running_balance': running})
    return {'account_code': acc.code, 'account_name': acc.name_ar,
            'opening_balance': opening, 'closing_balance': running,
            'rows': rows}


# ─── سيناريو شهر فندقي كامل (بوابة G1 في ملف 02 §12) ─────────────
def run_g1_month_scenario(db: Session, *, tenant_id: str, year: int,
                          month: int, actor_id: str) -> dict:
    """يحاكي شهراً كاملاً: عربون، ليالٍ يومية، مبيعات POS، مشتريات، سداد،
    رواتب، إهلاك — بأحداث عبر محرك الترحيل فقط، ومع فحص التوازن اليومي."""
    from .posting import post_event
    days = calendar.monthrange(year, month)[1]
    occ_rooms = {'101': ('غرفة مفردة', 60), '102': ('غرفة مزدوجة', 85),
                 '201': ('جناح', 140)}
    log, day_balanced = [], True
    tax_pct = Decimal('0')  # الضريبة معطلة في الوضع الافتراضي التجريبي

    # عربون حجز يوم 1
    post_event(db, tenant_id=tenant_id, branch_code='MAIN',
               event_type='GUEST_DEPOSIT',
               event_key=f'g1:dep:{year}{month:02d}:1',
               entry_date=date(year, month, 1),
               amounts={'amount': '100'}, actor_id=actor_id,
               party_type='GUEST', party_id='guest-101',
               narration='عربون حجز الغرفة 101')

    for d in range(1, days + 1):
        dt = date(year, month, d)
        # ليالي 3 غرف
        for room, (_, rate) in occ_rooms.items():
            rate_dec = D(rate)
            tax = (rate_dec * tax_pct).quantize(Decimal('0.01'))
            net = rate_dec - tax
            post_event(db, tenant_id=tenant_id, branch_code='MAIN',
                       event_type='ROOM_NIGHT',
                       event_key=f'g1:night:{year}{month:02d}:{d}:{room}',
                       entry_date=dt, amounts={'gross': str(rate_dec),
                                               'net': str(net), 'tax': str(tax)},
                       actor_id=actor_id, party_type='GUEST',
                       party_id=f'guest-{room}',
                       narration=f'ليلة {d} — غرفة {room}')
        # مبيعات مطعم يومية + تكلفتها
        if d % 2 == 0:
            gross = D(45 + (d % 7) * 5)
            post_event(db, tenant_id=tenant_id, branch_code='MAIN',
                       event_type='POS_SALE',
                       event_key=f'g1:pos:{year}{month:02d}:{d}',
                       entry_date=dt, actor_id=actor_id,
                       amounts={'gross': str(gross), 'net': str(gross),
                                'tax': '0'},
                       narration=f'مبيعات مطعم يوم {d}')
            post_event(db, tenant_id=tenant_id, branch_code='MAIN',
                       event_type='POS_COGS',
                       event_key=f'g1:cogs:{year}{month:02d}:{d}',
                       entry_date=dt, actor_id=actor_id,
                       amounts={'cost': str((gross * Decimal('0.4')).quantize(Decimal('0.01')))},
                       narration=f'تكلفة مبيعات يوم {d}')
        # مشتريات أسبوعية + سداد جزئي
        if d == 8:
            post_event(db, tenant_id=tenant_id, branch_code='MAIN',
                       event_type='PURCHASE_CREDIT',
                       event_key=f'g1:pur:{year}{month:02d}:{d}',
                       entry_date=dt, actor_id=actor_id,
                       amounts={'amount': '800'}, party_type='SUPPLIER',
                       party_id='supp-01', narration='شراء مخزون أسبوعي بالأجل')
        if d == 15:
            post_event(db, tenant_id=tenant_id, branch_code='MAIN',
                       event_type='SUPPLIER_PAYMENT',
                       event_key=f'g1:pay:{year}{month:02d}:{d}',
                       entry_date=dt, actor_id=actor_id,
                       amounts={'amount': '300'}, party_type='SUPPLIER',
                       party_id='supp-01', narration='سداد جزئي للمورد 01')
        # تحصيل نقدي من النزلاء أيام 5/10/20
        if d in (5, 10, 20):
            post_event(db, tenant_id=tenant_id, branch_code='MAIN',
                       event_type='FOLIO_PAYMENT',
                       event_key=f'g1:collect:{year}{month:02d}:{d}',
                       entry_date=dt, actor_id=actor_id,
                       amounts={'amount': '200'}, party_type='GUEST',
                       party_id='guest-101',
                       narration=f'تحصيل من النزيل 101 يوم {d}')
        # خروج نزيل 102 وتحويل ذمته لشركة يوم 25
        if d == 25:
            post_event(db, tenant_id=tenant_id, branch_code='MAIN',
                       event_type='CITY_LEDGER_TRANSFER',
                       event_key=f'g1:city:{year}{month:02d}:{d}',
                       entry_date=dt, actor_id=actor_id,
                       amounts={'amount': str(D(85) * 25)},
                       parties={'corporate': ('CORPORATE', 'corp-101'),
                                'folio': ('GUEST', 'guest-102')},
                       narration='نقل ذمة الغرفة 102 لشركة النخبة')
        tb = trial_balance(db, tenant_id, dt)
        if not tb['balanced'] or not tb['net_balance_zero']:
            day_balanced = False
            log.append(f'⚠ خلل توازن يوم {d}')

    # رواتب نهاية الشهر + إهلاك
    post_event(db, tenant_id=tenant_id, branch_code='MAIN',
               event_type='PAYROLL_ACCRUAL',
               event_key=f'g1:payroll:{year}{month:02d}',
               entry_date=date(year, month, days), actor_id=actor_id,
               amounts={'rooms_gross': '1200', 'admin_gross': '900',
                        'net': '1900', 'withholdings': '200'},
               narration='استحقاق رواتب الشهر')
    post_event(db, tenant_id=tenant_id, branch_code='MAIN',
               event_type='DEPRECIATION',
               event_key=f'g1:dep:{year}{month:02d}',
               entry_date=date(year, month, days), actor_id=actor_id,
               amounts={'amount': '150'}, narration='إهلاك الشهر')

    final = trial_balance(db, tenant_id, date(year, month, days))
    entries = db.execute(
        select(func.count(m.JournalEntry.id))
        .where(m.JournalEntry.tenant_id == tenant_id)).scalar_one()
    return {'year': year, 'month': month, 'days': days,
            'entries_posted': entries,
            'daily_balance_ok': day_balanced and not log,
            'issues': log,
            'total_debit': str(final['total_debit']),
            'total_credit': str(final['total_credit']),
            'balanced': final['balanced'],
            'net_zero': final['net_balance_zero']}


# ════════════════════════════════════════════════════════════════════
# ملف 02 §10 — القوائم المالية الكاملة (من المرحَّل فقط)
# ════════════════════════════════════════════════════════════════════

def _leaf_accounts(db: Session, tenant_id: str) -> list[m.Account]:
    return db.execute(
        select(m.Account).where(m.Account.tenant_id == tenant_id,
                                m.Account.is_postable == True)  # noqa: E712
        .order_by(m.Account.code)).scalars().all()


def _in_range_net(sums: dict, accounts: list[m.Account],
                  prefixes: tuple[str, ...], types: tuple[str, ...]
                  ) -> list[tuple[m.Account, Decimal]]:
    """صافي الحركة مدين−دائن لكل حساب ورقي تحت بادئات وأنواع معينة."""
    out = []
    for a in accounts:
        if a.type not in types or not a.code.startswith(prefixes):
            continue
        td, tc = sums.get(a.id, (Decimal('0'), Decimal('0')))
        net = td - tc
        if net != 0:
            out.append((a, net))
    return out


# الأقسام التشغيلية بمنهج USALI: إيراداتها ومصروفاتها المباشرة (بادئات)
_USALI_DEPTS = [
    ('الغرف', 'ROOMS', ('41',), ('5102', '5110', '61')),
    ('الأغذية والمشروبات', 'FNB', ('42',), ('5101', '62')),
    ('أقسام تشغيلية أخرى', 'OTHER_OPS', ('43',), ('5120',)),
]
_UNDISTRIBUTED = ('63', '64', '65', '66')
_NON_OPERATING = ('7',)


def income_statement(db: Session, tenant_id: str, date_from: date,
                     date_to: date) -> dict:
    """قائمة الدخل بمنهج USALI (02 §10): دخل كل قسم ثم غير الموزعة ثم
    GOP ثم صافي الدخل بعد غير التشغيلية. الإيراد/المصروف يقرآن بإشارتهما
    الطبيعية (أرقام موجبة للعرض، والخصومات المسموحة تظهر سالبة لأن
    طبيعتها مدينة — 4190)."""
    accounts = _leaf_accounts(db, tenant_id)
    sums = account_sums(db, tenant_id, date_to, from_date=date_from)
    depts = []
    for name, key, rev_pref, exp_pref in _USALI_DEPTS:
        revs = _in_range_net(sums, accounts, rev_pref, ('REVENUE',))
        exps = _in_range_net(sums, accounts, exp_pref,
                             ('EXPENSE', 'COGS'))
        rev_total = sum(-n for _, n in revs)   # طبيعتها دائنة: net سالب
        exp_total = sum(n for _, n in exps)
        depts.append({
            'key': key, 'name': name,
            'revenues': [{'code': a.code, 'name': a.name_ar,
                          'amount': -n} for a, n in revs],
            'expenses': [{'code': a.code, 'name': a.name_ar,
                          'amount': n} for a, n in exps],
            'revenue_total': rev_total, 'expense_total': exp_total,
            'dept_income': rev_total - exp_total})
    depts_income = sum(d['dept_income'] for d in depts)
    other_rev = _in_range_net(sums, accounts, ('49',), ('REVENUE',))
    other_total = sum(-n for _, n in other_rev)
    undist = _in_range_net(sums, accounts, _UNDISTRIBUTED,
                           ('EXPENSE', 'COGS'))
    undist_total = sum(n for _, n in undist)
    gop = depts_income + other_total - undist_total
    nonop = _in_range_net(sums, accounts, _NON_OPERATING,
                          ('EXPENSE', 'COGS'))
    nonop_total = sum(n for _, n in nonop)
    # بقايا غير مصنفة (أمان: حساب ينشأ لاحقاً خارج البادئات المعروفة)
    classified = set()
    for _, _, rp, ep in _USALI_DEPTS:
        classified.update(rp + ep)
    classified.update(_UNDISTRIBUTED + _NON_OPERATING + ('49',))
    residue_rev = [(a, n) for a, n in _in_range_net(
        sums, accounts, tuple('0123456789'), ('REVENUE',))
        if not a.code.startswith(tuple(classified))]
    residue_exp = [(a, n) for a, n in _in_range_net(
        sums, accounts, tuple('0123456789'), ('EXPENSE', 'COGS'))
        if not a.code.startswith(tuple(classified))]
    residue_net = sum(-n for _, n in residue_rev) - \
        sum(n for _, n in residue_exp)
    net = gop - nonop_total + residue_net
    return {'from': date_from, 'to': date_to, 'method': 'USALI',
            'departments': depts,
            'departments_income': depts_income,
            'other_revenue': [{'code': a.code, 'name': a.name_ar,
                               'amount': -n} for a, n in other_rev],
            'other_revenue_total': other_total,
            'undistributed': [{'code': a.code, 'name': a.name_ar,
                               'amount': n} for a, n in undist],
            'undistributed_total': undist_total,
            'gop': gop,
            'non_operating': [{'code': a.code, 'name': a.name_ar,
                               'amount': n} for a, n in nonop],
            'non_operating_total': nonop_total,
            'net_income': net}


def balance_sheet(db: Session, tenant_id: str, as_of: date) -> dict:
    """الميزانية العمومية بتاريخ قطع — القيد: أصول = خصوم + حقوق ملكية.
    حقوق الملكية تضم تلقائياً نتيجة العام غير المُقفل (فرق الإيرادات
    والمصروفات حتى تاريخ القطع) بسطر صريح."""
    accounts = _leaf_accounts(db, tenant_id)
    sums = account_sums(db, tenant_id, as_of)

    def rows_for(types, prefixes, sign):
        out = []
        for a in accounts:
            if a.type not in types or not a.code.startswith(prefixes):
                continue
            td, tc = sums.get(a.id, (Decimal('0'), Decimal('0')))
            v = (td - tc) * sign
            if v != 0:
                out.append({'code': a.code, 'name': a.name_ar, 'amount': v})
        return out

    current = rows_for(('ASSET',), ('11', '12'), 1)
    fixed = rows_for(('ASSET',), ('15',), 1)
    system = rows_for(('ASSET', 'LIABILITY', 'SYSTEM'), ('80',), 1)  # صفرية 8001 رقابياً
    liabs = rows_for(('LIABILITY',), ('2',), -1)
    equity = rows_for(('EQUITY',), ('3',), -1)
    revs = sum((td - tc) for a in accounts if a.type == 'REVENUE'
               for td, tc in [sums.get(a.id, (Decimal('0'), Decimal('0')))])
    exps = sum((td - tc) for a in accounts if a.type in ('EXPENSE', 'COGS')
               for td, tc in [sums.get(a.id, (Decimal('0'), Decimal('0')))])
    current_earnings = -(revs + exps)  # صافي ربح العام غير المُقفل
    total_assets = sum(r['amount'] for r in current) + \
        sum(r['amount'] for r in fixed) + sum(r['amount'] for r in system)
    total_liabs = sum(r['amount'] for r in liabs)
    total_equity = sum(r['amount'] for r in equity) + current_earnings
    return {'as_of': as_of,
            'current_assets': current, 'fixed_assets': fixed,
            'system_accounts': system,
            'total_assets': total_assets,
            'liabilities': liabs, 'total_liabilities': total_liabs,
            'equity': equity, 'current_year_earnings': current_earnings,
            'total_equity': total_equity,
            'balanced': total_assets == total_liabs + total_equity,
            'diff': total_assets - total_liabs - total_equity}


def cash_flow(db: Session, tenant_id: str, date_from: date,
              date_to: date) -> dict:
    """التدفقات النقدية بالطريقة غير المباشرة — مشتقة حصراً من فروقات
    مستويين (02 §10). الهوية المحاسبية: تشغيلي + استثماري + تمويلي +
    تحويلات إقفال غير نقدية = Δ النقدية بالضبط (فارق معروض كضبط)."""
    accounts = _leaf_accounts(db, tenant_id)
    day_before = date_from.fromordinal(date_from.toordinal() - 1)
    s_end = account_sums(db, tenant_id, date_to)
    s_start = account_sums(db, tenant_id, day_before)
    period = account_sums(db, tenant_id, date_to, from_date=date_from)

    def delta(prefixes, types):
        t = Decimal('0')
        for a in accounts:
            if a.type not in types or not a.code.startswith(prefixes):
                continue
            de, ce = s_end.get(a.id, (Decimal('0'), Decimal('0')))
            ds, cs = s_start.get(a.id, (Decimal('0'), Decimal('0')))
            t += (de - ce) - (ds - cs)
        return t

    def moved(prefixes, types):
        t = Decimal('0')
        for a in accounts:
            if a.type not in types or not a.code.startswith(prefixes):
                continue
            td, tc = period.get(a.id, (Decimal('0'), Decimal('0')))
            t += td - tc
        return t

    d_cash = delta(('1101', '1102', '1103', '1104'), ('ASSET',))
    rev = moved(tuple('4'), ('REVENUE',))
    exp = moved(('5', '6', '7'), ('EXPENSE', 'COGS'))
    net_income = -(rev + exp)
    dep_addback = -delta(('1590',), ('ASSET',))  # حركة المجمع (طبيعة دائنة)
    d_ar = delta(('111', '112', '113', '114', '115'), ('ASSET',))
    d_inv = delta(('12',), ('ASSET',))
    d_fa_gross = delta(('151', '152', '153', '154'), ('ASSET',))
    d_liab_ops = delta(('21', '220', '221', '222', '223', '230', '231', '232',
                        '233', '234', '235', '236', '237', '238', '239'),
                       ('LIABILITY',))
    d_loans = delta(('241',), ('LIABILITY',))
    d_owner = delta(('242',), ('LIABILITY',))
    d_capital = delta(('3101', '3102'), ('EQUITY',))
    d_reclose = delta(('320',), ('EQUITY',))  # إقفالات نقل الأرباح (غير نقدية)
    d_sys = delta(('80',), ('ASSET', 'LIABILITY', 'SYSTEM'))

    operating = net_income + dep_addback - d_ar - d_inv + d_liab_ops
    investing = -d_fa_gross
    financing = d_loans + d_owner + d_capital
    equity_transfers = -d_reclose - d_sys  # نقل أرباح/حسابات نظام — لا نقد
    residual = d_cash - (operating + investing + financing + equity_transfers)
    return {'from': date_from, 'to': date_to, 'method': 'INDIRECT',
            'net_income': net_income,
            'depreciation_addback': dep_addback,
            'delta_receivables': d_ar, 'delta_inventory': d_inv,
            'delta_operating_liabilities': d_liab_ops,
            'operating': operating,
            'delta_fixed_assets_gross': d_fa_gross, 'investing': investing,
            'delta_loans': d_loans, 'delta_owner_current': d_owner,
            'delta_capital': d_capital, 'financing': financing,
            'equity_and_system_transfers': equity_transfers,
            'net_change': operating + investing + financing,
            'cash_delta_actual': d_cash,
            'reconciliation_diff': residual,
            'identity_holds': residual == 0}


_AR_AP = {'1110', '1120', '2101'}


def aging_report(db: Session, tenant_id: str, account_code: str,
                 as_of: date) -> dict:
    """تقادم أعمار الذمم 0-30/31-60/61-90/+90 (02 §10) بتخصيص FIFO:
    سدادات الطرف تُسقط أقدم فواتيره أولاً، والباقي المفتوح يُعمّر
    بتاريخ فاتورته. تجميع كل الدلاء = رصيد الحساب بالأستاذ حرفياً."""
    if account_code not in _AR_AP:
        raise PostingError('FIN.BAD_AGING_ACCOUNT',
                           'الأعمار مدعومة لـ 1110/1120 (مدينون) و2101 (دائنون)')
    acc = db.execute(
        select(m.Account).where(m.Account.tenant_id == tenant_id,
                                m.Account.code == account_code)).scalar_one()
    is_ar = account_code != '2101'
    q_select = (select(m.JournalLine, m.JournalEntry.entry_date)
        .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
        .where(m.JournalLine.tenant_id == tenant_id,
               m.JournalLine.account_id == acc.id,
               m.JournalLine.party_id.isnot(None),
               m.JournalEntry.status == 'POSTED',
               m.JournalEntry.entry_date <= as_of))
    anchor = opening_anchor(db, tenant_id, as_of)
    if anchor is not None:
        # الافتتاحية تستبدل تاريخ ما قبلها — عناصر مفتوحة مدورة تعمّر منها
        q_select = q_select.where(m.JournalEntry.entry_date >= anchor)
    lines = db.execute(
        q_select.order_by(m.JournalEntry.entry_date, m.JournalLine.id)).all()

    names = _party_names(db, tenant_id)
    buckets = [('0-30', 0, 30), ('31-60', 31, 60), ('61-90', 61, 90),
               ('+90', 91, 10**9)]
    per_party: dict[str, dict] = {}
    for ln, ed in lines:
        key = f'{ln.party_type}:{ln.party_id}'
        slot = per_party.setdefault(
            key, {'open': [],  # [(date, remaining)] فواتير مفتوحة
                  'buckets': {b[0]: Decimal('0') for b in buckets},
                  'total': Decimal('0')})
        amt = D(ln.debit_base) if is_ar else D(ln.credit_base)
        pay = D(ln.credit_base) if is_ar else D(ln.debit_base)
        if amt > 0:
            slot['open'].append([ed, amt])
        if pay > 0:  # FIFO: أسقط الأقدم أولاً
            for o in slot['open']:
                if pay <= 0:
                    break
                take = min(o[1], pay)
                o[1] -= take
                pay -= take
        slot['open'] = [o for o in slot['open'] if o[1] > 0]
    for key, slot in per_party.items():
        for ed, rem in slot['open']:
            age = (as_of - ed).days
            for bname, lo, hi in buckets:
                if lo <= age <= hi:
                    slot['buckets'][bname] += rem
                    break
            slot['total'] += rem
    rows = [{'party': key, 'party_name': names.get(key, key.split(':')[1][:8]),
             'party_type': key.split(':')[0],
             'buckets': {b: v for b, v in slot['buckets'].items()},
             'total': slot['total']}
            for key, slot in sorted(per_party.items(),
                                    key=lambda kv: -kv[1]['total'])
            if slot['total'] != 0]
    td, tc = account_sums(db, tenant_id, as_of).get(
        acc.id, (Decimal('0'), Decimal('0')))
    gl = (td - tc) if is_ar else (tc - td)
    bucket_totals = {b[0]: sum(s['buckets'][b[0]] for s in per_party.values())
                     for b in buckets}
    return {'account': account_code, 'account_name': acc.name_ar,
            'as_of': as_of, 'method': 'FIFO',
            'rows': rows,
            'totals': bucket_totals,
            'grand_total': sum(bucket_totals.values()),
            'gl_balance': gl,
            'matches_gl': sum(bucket_totals.values()) == gl}


def _party_names(db: Session, tenant_id: str) -> dict[str, str]:
    out = {}
    for g in db.execute(select(m.Guest).where(
            m.Guest.tenant_id == tenant_id)).scalars():
        out[f'GUEST:{g.id}'] = g.full_name
    for c in db.execute(select(m.Corporate).where(
            m.Corporate.tenant_id == tenant_id)).scalars():
        out[f'CORPORATE:{c.id}'] = c.name
        out[f'COMPANY:{c.id}'] = c.name
    for s in db.execute(select(m.InvSupplier).where(
            m.InvSupplier.tenant_id == tenant_id)).scalars():
        out[f'SUPPLIER:{s.id}'] = s.name
    for e in db.execute(select(m.HrEmployee).where(
            m.HrEmployee.tenant_id == tenant_id)).scalars():
        out[f'EMPLOYEE:{e.id}'] = f'{e.emp_no} — {e.full_name}'
    return out
