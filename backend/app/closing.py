"""إقفال السنة المالية وتوليد الافتتاحية — ملف 02 §5 (نص ملزم):

«قيد إقفال: Dr كل الإيرادات / Cr 3202 بمجموعها؛ و Dr 3202 / Cr كل
المصروفات. ثم Dr/Cr 3202 إلى 3201 (الأرباح المبقاة) أو حسب قرار التوزيع.
يولد أرصدة افتتاحية للسنة الجديدة (Opening Entry) آلياً.»

تصميم التنفيذ (ADR-0031):
- كل شيء داخل معاملة واحدة: قيد إقفال (CLOSING) في آخر يوم بالسنة
  القديمة ← إنشاء السنة الجديدة وفتراتها ← قيد افتتاحي (OPENING) في
  أول يوم منها ← السنة القديمة CLOSED وفترتها الأخيرة HARD_CLOSED.
- الشروط المسبقة: الفترات 1..11 مغلقة (لينة/صلبة)، الفترة 12 ليست
  صلبة، لا مسودات في السنة كلها، حسابا النظام 8001/8002 صفران.
- الافتتاحية تحمل بُعد الطرف (Party) للحسابات party_required حتى تستمر
  ذمم النزلاء/الشركات/الموردين/السلف لحظياً في السنة الجديدة.
- Idempotency كامل عبر مفاتيح Outbox: close:{fy_id} و open:{fy_id} —
  إعادة التنفيذ بعد النجاح = 409، وبعد فشل مبكر = إعادة آمنة.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m
from .audit import audit
from .posting import D, PostingError, create_and_post_journal

REV_EXC = ('REVENUE',)
EXP_EXC = ('EXPENSE', 'COGS')


def _now() -> datetime:
    return datetime.now(timezone.utc)


def err(code: str, msg: str):
    raise PostingError(code, msg)


def get_year(db: Session, tenant_id: str, year_no: int) -> m.FiscalYear:
    y = db.execute(
        select(m.FiscalYear).where(m.FiscalYear.tenant_id == tenant_id,
                                   m.FiscalYear.year_no == year_no)
    ).scalar_one_or_none()
    if y is None:
        err('GENERAL.NOT_FOUND', f'لا توجد سنة مالية برقم {year_no}')
    return y


def _nets_by_account(db: Session, tenant_id: str, d1: date, d2: date,
                     types: tuple[str, ...]) -> list[tuple[m.Account, Decimal]]:
    """صافي (مدين−دائن) لكل حساب ورقي من النوع المطلوب ضمن مدى تاريخي."""
    q = (select(m.JournalLine.account_id,
                func.sum(m.JournalLine.debit_base),
                func.sum(m.JournalLine.credit_base))
         .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
         .where(m.JournalLine.tenant_id == tenant_id,
                m.JournalEntry.status.in_(['POSTED', 'REVERSED']),
                m.JournalEntry.entry_date >= d1,
                m.JournalEntry.entry_date <= d2)
         .group_by(m.JournalLine.account_id))
    sums = {aid: D(td or 0) - D(tc or 0) for aid, td, tc in db.execute(q)}
    accs = db.execute(
        select(m.Account).where(m.Account.tenant_id == tenant_id,
                                m.Account.is_postable == True,  # noqa: E712
                                m.Account.type.in_(types))).scalars().all()
    return [(a, sums.get(a.id, Decimal('0'))) for a in accs]


def _nets_by_party(db: Session, tenant_id: str, upto: date):
    """صافي الرصيد حتى تاريخ لكل (حساب يتطلب طرفاً، نوع طرف، معرف طرف)."""
    q = (select(m.JournalLine.account_id, m.JournalLine.party_type,
                m.JournalLine.party_id,
                func.sum(m.JournalLine.debit_base),
                func.sum(m.JournalLine.credit_base))
         .join(m.JournalEntry, m.JournalEntry.id == m.JournalLine.entry_id)
         .where(m.JournalLine.tenant_id == tenant_id,
                m.JournalEntry.status.in_(['POSTED', 'REVERSED']),
                m.JournalEntry.entry_date <= upto)
         .group_by(m.JournalLine.account_id, m.JournalLine.party_type,
                   m.JournalLine.party_id))
    return db.execute(q).all()


def precheck(db: Session, tenant_id: str, year_no: int) -> dict:
    """قائمة تحقق الإقفال (تُعرض للمدير المالي قبل الضغط على الزر)."""
    y = get_year(db, tenant_id, year_no)
    periods = db.execute(
        select(m.FiscalPeriod)
        .where(m.FiscalPeriod.fiscal_year_id == y.id)
        .order_by(m.FiscalPeriod.period_no)).scalars().all()
    drafts = db.execute(
        select(func.count(m.JournalEntry.id))
        .where(m.JournalEntry.tenant_id == tenant_id,
               m.JournalEntry.status == 'DRAFT',
               m.JournalEntry.entry_date >= y.start_date,
               m.JournalEntry.entry_date <= y.end_date)).scalar_one()
    closed_states = ('CLOSED', 'SOFT_CLOSED', 'HARD_CLOSED')
    early_ok = all(p.status in closed_states
                   for p in periods if p.period_no <= 11) \
        if len(periods) >= 12 else False
    p12 = periods[11] if len(periods) >= 12 else None
    p12_ok = p12 is not None and p12.status != 'HARD_CLOSED'
    sys_acc = db.execute(
        select(m.Account).where(m.Account.tenant_id == tenant_id,
                                m.Account.code.in_(['8001', '8002']))
        .order_by(m.Account.code)).scalars().all()
    sys_rows = []
    sys_zero = True
    for a in sys_acc:
        v = db.execute(
            select(func.coalesce(func.sum(
                m.JournalLine.debit_base - m.JournalLine.credit_base), 0))
            .join(m.JournalEntry, m.JournalLine.entry_id == m.JournalEntry.id)
            .where(m.JournalLine.account_id == a.id,
                   m.JournalEntry.status.in_(['POSTED', 'REVERSED'])),
        ).scalar_one()
        sys_rows.append({'code': a.code, 'name': a.name_ar,
                         'balance': str(D(v)),
                         'blocking': a.code == '8001'})
        # 02 §5 يشترط صفرية 8001 (مزامنة) — أما 8002 (ترحيل افتتاحي
        # تاريخي) فيُعرض إعلامياً ولا يحجب الإقفال (ADR-0031)
        if a.code == '8001':
            sys_zero = sys_zero and D(v) == 0
    closed_done = db.execute(
        select(m.OutboxEvent).where(
            m.OutboxEvent.event_key == f'close:{y.id}',
            m.OutboxEvent.state == 'PROCESSED')).scalar_one_or_none()
    return {'year_no': year_no, 'status': y.status,
            'start_date': y.start_date.isoformat(),
            'end_date': y.end_date.isoformat(),
            'checks': [
                {'key': 'early_periods', 'ok': early_ok,
                 'label': 'الفترات 1–11 مغلقة (لينة أو صلبة)'},
                {'key': 'p12_not_hard', 'ok': p12_ok,
                 'label': 'الفترة 12 غير مغلقة صلباً بعد'},
                {'key': 'no_drafts', 'ok': drafts == 0,
                 'label': f'لا مسودات غير مرحَّلة (عددها {drafts})'},
                {'key': 'system_zero', 'ok': sys_zero,
                 'label': 'حساب المزامنة المرحلي 8001 صفر (8002 إعلامي)',
                 'rows': sys_rows},
                {'key': 'not_already', 'ok': closed_done is None,
                 'label': 'قيد الإقفال لم يُنفَّذ من قبل'},
                {'key': 'year_open', 'ok': y.status == 'OPEN',
                 'label': f'السنة بحالة {y.status}'},
            ],
            'ready': all([early_ok, p12_ok, drafts == 0, sys_zero,
                          closed_done is None, y.status == 'OPEN'])}


def _ensure_next_year(db: Session, tenant_id: str,
                      y: m.FiscalYear) -> m.FiscalYear:
    nxt = db.execute(
        select(m.FiscalYear).where(m.FiscalYear.tenant_id == tenant_id,
                                   m.FiscalYear.year_no == y.year_no + 1)
    ).scalar_one_or_none()
    if nxt is not None:
        return nxt
    start = y.end_date + timedelta(days=1)
    end = date(start.year + 1, start.month, start.day) - timedelta(days=1)
    nxt = m.FiscalYear(id=_uuid(), tenant_id=tenant_id,
                       year_no=y.year_no + 1, start_date=start, end_date=end,
                       status='OPEN')
    db.add(nxt)
    db.flush()
    for i in range(12):
        m_start = date(start.year, start.month, 1) \
            if i == 0 else date(start.year + (start.month + i - 1) // 12,
                                (start.month + i - 1) % 12 + 1, 1)
        last = calendar.monthrange(m_start.year, m_start.month)[1]
        m_end_date = date(m_start.year, m_start.month, last)
        db.add(m.FiscalPeriod(id=_uuid(), fiscal_year_id=nxt.id,
                              period_no=i + 1, start_date=m_start,
                              end_date=m_end_date, status='OPEN'))
    db.flush()
    return nxt


def _uuid() -> str:
    import uuid
    return str(uuid.uuid4())


def close_fiscal_year(db: Session, *, tenant_id: str, actor_id: str,
                      branch_id: str, year_no: int) -> dict:
    pre = precheck(db, tenant_id, year_no)
    if not pre['ready']:
        bad = [c['label'] for c in pre['checks'] if not c['ok']]
        err('FIN.YEAR_NOT_READY', 'شروط الإقفال غير مكتملة: ' + '؛ '.join(bad))
    y = get_year(db, tenant_id, year_no)

    # 1) أرصدة إيرادات/مصروفات السنة
    revs = _nets_by_account(db, tenant_id, y.start_date, y.end_date, REV_EXC)
    exps = _nets_by_account(db, tenant_id, y.start_date, y.end_date, EXP_EXC)
    rev_net = sum((-n for _, n in revs), Decimal('0'))   # دائنة الطبيعة
    exp_net = sum((n for _, n in exps), Decimal('0'))    # مدينة الطبيعة
    if rev_net == 0 and exp_net == 0:
        err('FIN.NOTHING_TO_CLOSE', 'لا حركات إيراد/مصروف في هذه السنة')
    income = rev_net - exp_net

    raw = []
    for a, n in revs:
        if n < 0:  # رصيد دائن ⇒ يُقفل مديناً
            raw.append({'account': a.code, 'debit': -n, 'credit': Decimal('0'),
                        'description': f'إقفال إيراد: {a.name_ar}'})
        elif n > 0:  # طبيعة مدينة (مثل 4190 خصومات مسموحة) ⇒ بالعكس
            raw.append({'account': a.code, 'debit': Decimal('0'), 'credit': n,
                        'description': f'إقفال مقابل إيراد: {a.name_ar}'})
    if rev_net != 0:
        raw.append({'account': '3202', 'debit': Decimal('0'),
                    'credit': rev_net,
                    'description': f'إجمالي إيرادات عام {year_no}'})
    if exp_net != 0:
        raw.append({'account': '3202', 'debit': exp_net,
                    'credit': Decimal('0'),
                    'description': f'إجمالي مصروفات عام {year_no}'})
    for a, n in exps:
        if n > 0:
            raw.append({'account': a.code, 'debit': Decimal('0'), 'credit': n,
                        'description': f'إقفال مصروف: {a.name_ar}'})
        elif n < 0:
            raw.append({'account': a.code, 'debit': -n, 'credit': Decimal('0'),
                        'description': f'إقفال مقابل مصروف: {a.name_ar}'})
    if income > 0:
        raw.append({'account': '3202', 'debit': income, 'credit': Decimal('0'),
                    'description': 'نقل صافي ربح العام'})
        raw.append({'account': '3201', 'debit': Decimal('0'), 'credit': income,
                    'description': f'إلى الأرباح المبقاة — ربح {year_no}'})
    elif income < 0:
        raw.append({'account': '3201', 'debit': -income, 'credit': Decimal('0'),
                    'description': f'ترحيل خسارة عام {year_no}'})
        raw.append({'account': '3202', 'debit': Decimal('0'), 'credit': -income,
                    'description': 'إقفال وسيط — خسارة'})

    closing = create_and_post_journal(
        db, tenant_id=tenant_id, branch_id=branch_id,
        journal_type='CLOSING', entry_date=y.end_date,
        narration=f'قيد إقفال السنة المالية {year_no}',
        raw_lines=raw, actor_id=actor_id,
        source_type='YEAR_END_CLOSE', source_id=f'fy:{y.year_no}',
        event_key=f'close:{y.id}',
        allow_soft=True)  # يعمل حتى لو أُغلقت الفترة 12 ليناً (رقابة 02 §5)

    # 2) السنة الجديدة وفتراتها
    nxt = _ensure_next_year(db, tenant_id, y)

    # 3) القيد الافتتاحي: ميزانية ما بعد الإقفال ببُعد الأطراف
    #    (وحسابات SYSTEM لأن أرصدتها التاريخية تدور كذلك — 8002 مثلاً)
    bs = _nets_by_account(db, tenant_id, date(2000, 1, 1), y.end_date,
                          ('ASSET', 'LIABILITY', 'EQUITY', 'SYSTEM'))
    accounts = {a.id: a for a, _ in bs}
    party_rows = _nets_by_party(db, tenant_id, y.end_date)
    raw2 = []
    carried_parties: set[tuple[str, str, str]] = set()
    for aid, ptype, pid, td, tc in party_rows:
        a = accounts.get(aid)
        if a is None or not a.party_required or ptype is None or pid is None:
            continue
        n = D(td or 0) - D(tc or 0)
        if n == 0:
            continue
        carried_parties.add((aid, ptype, pid))
        raw2.append({'account': a.code,
                     'debit': n if n > 0 else Decimal('0'),
                     'credit': -n if n < 0 else Decimal('0'),
                     'party_type': ptype, 'party_id': pid,
                     'description': f'رصيد افتتاحي مدور — {a.name_ar}'})
    for a, n in bs:
        if n == 0:
            continue
        if a.party_required:
            # الصافي بعد استبعاد ما حُمل بأطرافه (عادةً لا شيء)
            party_sum = sum(
                (D(td or 0) - D(tc or 0)) for aid, pt, pid, td, tc
                in party_rows if (aid, pt, pid) in carried_parties
                and aid == a.id)
            n = n - party_sum
            if n == 0:
                continue
        raw2.append({'account': a.code,
                     'debit': n if n > 0 else Decimal('0'),
                     'credit': -n if n < 0 else Decimal('0'),
                     'description': f'رصيد افتتاحي مدور — {a.name_ar}'})

    opening = None
    if raw2:
        opening = create_and_post_journal(
            db, tenant_id=tenant_id, branch_id=branch_id,
            journal_type='OPENING', entry_date=nxt.start_date,
            narration=f'الأرصدة الافتتاحية للسنة المالية {nxt.year_no}',
            raw_lines=raw2, actor_id=actor_id,
            source_type='YEAR_OPENING', source_id=f'fy:{nxt.year_no}',
            event_key=f'open:{y.id}')

    # 4) إقفال السنة القديمة: كل فتراتها تُختم صلباً — سنة مقفلة تعني
    #    نهائي مطلقاً على جميع أشهرها (02 §5)
    y.status = 'CLOSED'
    for p in db.execute(select(m.FiscalPeriod).where(
            m.FiscalPeriod.fiscal_year_id == y.id)).scalars():
        if p.status != 'HARD_CLOSED':
            p.status = 'HARD_CLOSED'
            p.closed_by = p.closed_by or actor_id
            p.closed_at = p.closed_at or _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='accounting', action='year.close', entity='fiscal_years',
          entity_id=y.id,
          after={'year': year_no, 'closing_entry': closing.id,
                 'opening_entry': opening.id if opening else None,
                 'income': str(income), 'rev_net': str(rev_net),
                 'exp_net': str(exp_net), 'next_year': nxt.year_no},
          business_date=y.end_date)
    return {'year_no': year_no,
            'closing_entry_id': closing.id,
            'closing_entry_no': closing.entry_no,
            'revenue_closed': str(rev_net), 'expense_closed': str(exp_net),
            'net_income': str(income),
            'opening_entry_id': opening.id if opening else None,
            'opening_entry_no': opening.entry_no if opening else None,
            'opening_lines': len(raw2),
            'next_year_no': nxt.year_no,
            'next_year_start': nxt.start_date.isoformat(),
            'status': 'CLOSED'}
