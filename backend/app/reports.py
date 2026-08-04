"""التقارير المالية من المرحَّل فقط (ملف 02 §10) + سيناريو شهر فندقي (بوابة G1)."""
import calendar
from datetime import date
from decimal import Decimal

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from . import models as m
from .posting import D, PostingError


def account_sums(db: Session, tenant_id: str, as_of: date,
                 up_to: date | None = None, from_date: date | None = None):
    """مجاميع (مدين، دائن) لكل حساب ورقي من القيود POSTED (+REVERSED تاريخياً:
    القيد المعكوس وعكسه يظهران كلاهما — فالأثر الصافي دقيق)."""
    q = (select(m.JournalLine.account_id,
                func.sum(m.JournalLine.debit_base),
                func.sum(m.JournalLine.credit_base))
         .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
         .where(m.JournalLine.tenant_id == tenant_id,
                m.JournalEntry.status.in_(['POSTED', 'REVERSED'])))
    if from_date:
        q = q.where(m.JournalEntry.entry_date >= from_date)
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
                       party_type='CORPORATE', party_id='corp-101',
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
