"""محرك الترحيل (Posting Engine) — الملف 02 §4/§6/§11:
- تحقق V1..V8 • ترحيل ذري • Idempotency بالـ event_key • لا تعديل للمرحَّل
- التصحيح بالعكس فقط • Outbox لكل حدث (أساس المزامنة)"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models as m
from .security import utcnow, new_uuid
from .audit import audit

Q4 = Decimal('0.0001')


class PostingError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def D(v) -> Decimal:
    return Decimal(str(v)).quantize(Q4)


def get_account(db: Session, tenant_id: str, code: str) -> m.Account:
    acc = db.execute(
        select(m.Account).where(m.Account.tenant_id == tenant_id,
                                m.Account.code == code)).scalar_one_or_none()
    if acc is None:
        raise PostingError('ACCOUNTING.UNKNOWN_ACCOUNT',
                           f'حساب غير موجود: {code}')
    return acc


def period_for_date(db: Session, tenant_id: str, d: date) -> m.FiscalPeriod:
    p = db.execute(
        select(m.FiscalPeriod).join(m.FiscalYear)
        .where(m.FiscalYear.tenant_id == tenant_id,
               m.FiscalPeriod.start_date <= d,
               m.FiscalPeriod.end_date >= d)).scalar_one_or_none()
    if p is None:
        raise PostingError('ACCOUNTING.NO_PERIOD',
                           f'لا توجد فترة محاسبية تغطي التاريخ {d}')
    return p


def next_entry_no(db: Session, tenant_id: str, jtype: str,
                  d: date) -> str:
    prefixes = {'MANUAL': 'JV-MA', 'REVERSAL': 'JV-RV', 'OPENING': 'JV-OP',
                'CLOSING': 'JV-CL', 'AUTO_ROOM': 'JV-AR', 'AUTO_POS': 'JV-PS',
                'AUTO_PURCHASE': 'JV-PU', 'AUTO_PAYROLL': 'JV-HR',
                'AUTO_DEPRECIATION': 'JV-DP', 'AUTO_TAX': 'JV-TX'}
    prefix = prefixes.get(jtype, 'JV-XX')
    year = d.year
    row = db.execute(
        select(m.SequenceCounter)
        .where(m.SequenceCounter.tenant_id == tenant_id,
               m.SequenceCounter.kind == jtype,
               m.SequenceCounter.year == year)
        .with_for_update()).scalar_one_or_none()
    if row is None:
        row = m.SequenceCounter(tenant_id=tenant_id, kind=jtype, year=year,
                                next_no=1)
        db.add(row)
        db.flush()
    no = row.next_no
    row.next_no = no + 1
    db.flush()
    return f'{prefix}-{year}-{no:06d}'


def _validate_and_build_lines(db: Session, tenant_id: str,
                              raw_lines: list[dict]) -> tuple[list[dict], Decimal, Decimal]:
    """يطبق V2,V3,V4 + حُكم الطرف، ويرجع الأسطر الجاهزة ومجاميعها."""
    if len(raw_lines) < 2:
        raise PostingError('ACCOUNTING.MIN_LINES', 'القيد يتطلب سطرين على الأقل')
    built, td, tc = [], Decimal('0'), Decimal('0')
    for i, rl in enumerate(raw_lines, 1):
        acc = get_account(db, tenant_id, rl['account'])
        if not acc.is_postable:
            raise PostingError('ACCOUNTING.PARENT_ACCOUNT',
                               f'يمنع الترحيل على حساب أب: {acc.code} {acc.name_ar}')
        if not acc.is_active:
            raise PostingError('ACCOUNTING.INACTIVE_ACCOUNT',
                               f'حساب موقوف: {acc.code}')
        debit, credit = D(rl.get('debit', 0)), D(rl.get('credit', 0))
        if debit < 0 or credit < 0:
            raise PostingError('ACCOUNTING.NEGATIVE',
                               'يمنع المبالغ السالبة — بدّل الطرف مدين/دائن')
        if debit > 0 and credit > 0:
            raise PostingError('ACCOUNTING.DOUBLE_SIDED',
                               f'سطر {i}: يجب أن يكون أحد الطرفين صفراً')
        if debit == 0 and credit == 0:
            raise PostingError('ACCOUNTING.ZERO_LINE', f'سطر {i} بمبلغ صفر')
        if acc.party_required and not rl.get('party_id'):
            raise PostingError('ACCOUNTING.PARTY_REQUIRED',
                               f'الحساب {acc.code} يتطلب طرفاً (نزيل/شركة/مورد/موظف)')
        built.append({'line_no': i, 'account_id': acc.id,
                      'account_code': acc.code, 'account_name': acc.name_ar,
                      'debit': debit, 'credit': credit,
                      'party_type': rl.get('party_type'),
                      'party_id': rl.get('party_id'),
                      'cost_center': rl.get('cost_center'),
                      'description': rl.get('description', '')})
        td, tc = td + debit, tc + credit
    if td != tc:  # V1
        raise PostingError('ACCOUNTING.UNBALANCED_ENTRY',
                           f'قيد غير متوازن: مدين {td} ≠ دائن {tc}')
    return built, td, tc


def create_and_post_journal(db: Session, *, tenant_id: str, branch_id: str,
                            journal_type: str, entry_date: date,
                            narration: str, raw_lines: list[dict],
                            actor_id: str, source_type=None, source_id=None,
                            reference=None, event_key=None,
                            currency: str = 'BASE') -> m.JournalEntry:
    """إنشاء وترحيل قيد ذرياً — للأنواع MANUAL والآلية معاً."""
    settings_base = db.execute(
        select(m.Tenant.base_currency).where(m.Tenant.id == tenant_id)).scalar_one()
    ccy = settings_base if currency == 'BASE' else currency
    period = period_for_date(db, tenant_id, entry_date)
    if period.status != 'OPEN':  # V5
        raise PostingError('ACCOUNTING.CLOSED_PERIOD',
                           f'الفترة {period.period_no} {period.status} — يمنع الترحيل')
    if journal_type != 'MANUAL' and not source_type and not event_key:
        raise PostingError('ACCOUNTING.SOURCE_REQUIRED',
                           'القيد الآلي يتطلب مصدراً')
    built, td, tc = _validate_and_build_lines(db, tenant_id, raw_lines)

    if event_key:  # Idempotency بالمفتاح المبكر
        exists = db.execute(
            select(m.OutboxEvent).where(m.OutboxEvent.event_key == event_key)
        ).scalar_one_or_none()
        if exists:
            if exists.state == 'PROCESSED':
                je = db.get(m.JournalEntry, exists.journal_entry_id)
                return je
            raise PostingError('ACCOUNTING.DUPLICATE_EVENT',
                               f'حدث مكرر بحالة {exists.state}: {event_key}')

    entry = m.JournalEntry(
        id=new_uuid(), tenant_id=tenant_id, branch_id=branch_id,
        journal_type=journal_type,
        entry_no=next_entry_no(db, tenant_id, journal_type, entry_date),
        entry_date=entry_date, period_id=period.id, currency_code=ccy,
        status='POSTED', narration=narration, reference=reference,
        source_type=source_type, source_id=source_id, event_key=event_key,
        created_by=actor_id, posted_by=actor_id,
        created_at=utcnow(), posting_date=utcnow(), posted_at=utcnow())
    db.add(entry)
    db.flush()
    for b in built:
        db.add(m.JournalLine(
            id=new_uuid(), entry_id=entry.id, tenant_id=tenant_id,
            line_no=b['line_no'], account_id=b['account_id'],
            debit_base=b['debit'], credit_base=b['credit'],
            party_type=b['party_type'], party_id=b['party_id'],
            description=b['description']))
    db.flush()

    if event_key:
        db.add(m.OutboxEvent(event_key=event_key, tenant_id=tenant_id,
                             event_type=source_type or journal_type,
                             payload={}, occurred_at=utcnow(),
                             state='PROCESSED', journal_entry_id=entry.id))
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user' if journal_type == 'MANUAL' else 'system',
          module='accounting', action='journal.post', entity='journal_entries',
          entity_id=entry.id,
          after={'entry_no': entry.entry_no, 'type': journal_type,
                 'debit': str(td), 'date': str(entry_date)},
          business_date=entry_date)
    return entry


def _amount(payload_amounts: dict, key: str) -> Decimal:
    if key not in payload_amounts:
        raise PostingError('ACCOUNTING.MAP_MISSING_AMOUNT',
                           f'القالب يطلب مبلغاً غير موجود بالحدث: {key}')
    return D(payload_amounts[key])


def post_event(db: Session, *, tenant_id: str, branch_code: str,
               event_type: str, event_key: str, entry_date: date,
               amounts: dict, narration: str = '', party_type=None,
               party_id=None, actor_id: str | None = None,
               context_key: str | None = None) -> m.JournalEntry:
    """نقطة دخول الأحداث التشغيلية (ملف 02 §6): خريطة ← تحقق ← ترحيل."""
    branch = db.execute(
        select(m.Branch).where(m.Branch.tenant_id == tenant_id,
                               m.Branch.code == branch_code)).scalar_one_or_none()
    if branch is None:
        raise PostingError('ORG.UNKNOWN_BRANCH', f'فرع غير معروف: {branch_code}')

    q = select(m.PostingMap).where(
        m.PostingMap.tenant_id == tenant_id,
        m.PostingMap.event_type == event_type,
        m.PostingMap.is_active.is_(True),
        m.PostingMap.effective_from <= entry_date,
        (m.PostingMap.effective_to.is_(None)) | (m.PostingMap.effective_to >= entry_date))
    if context_key:
        q = q.where(m.PostingMap.context_key == context_key)
    else:
        q = q.where(m.PostingMap.context_key.is_(None))
    pmap = db.execute(q).scalar_one_or_none()
    if pmap is None:
        raise PostingError('ACCOUNTING.NO_POSTING_MAP',
                           f'لا خريطة ربط فعالة للحدث {event_type}')

    raw_lines = []
    for t in pmap.template:
        amt = _amount(amounts, t['from'])
        if amt == 0:
            continue  # بند قالب صفري (مثل ضريبة معطلة) — لا يولّد سطراً
        line = {'account': t['account'],
                'debit': amt if t['side'] == 'D' else Decimal('0'),
                'credit': amt if t['side'] == 'C' else Decimal('0'),
                'description': t.get('desc', '')}
        if t.get('party'):
            line['party_type'] = party_type or t.get('party_type')
            line['party_id'] = party_id
        raw_lines.append(line)

    try:
        return create_and_post_journal(
            db, tenant_id=tenant_id, branch_id=branch.id,
            journal_type=pmap.template_journal_type if hasattr(pmap, 'template_journal_type') else _JTYPE.get(event_type, 'AUTO_ROOM'),
            entry_date=entry_date,
            narration=narration or pmap.description or event_type,
            raw_lines=raw_lines,
            actor_id=actor_id or 'system',
            source_type=event_type, source_id=event_key,
            event_key=event_key)
    except PostingError:
        raise


_JTYPE = {'ROOM_NIGHT': 'AUTO_ROOM', 'POS_SALE': 'AUTO_POS',
          'PURCHASE_CREDIT': 'AUTO_PURCHASE', 'PURCHASE_CASH': 'AUTO_PURCHASE',
          'SUPPLIER_PAYMENT': 'AUTO_PURCHASE', 'PAYROLL_ACCRUAL': 'AUTO_PAYROLL',
          'DEPRECIATION': 'AUTO_DEPRECIATION', 'GUEST_DEPOSIT': 'AUTO_ROOM',
          'GUEST_PAYMENT': 'AUTO_ROOM', 'FOLIO_PAYMENT': 'AUTO_ROOM',
          'CITY_LEDGER_TRANSFER': 'AUTO_ROOM'}


def reverse_entry(db: Session, *, tenant_id: str, entry_id: str,
                  reason: str, actor_id: str,
                  reversal_date: date | None = None) -> m.JournalEntry:
    """عكس قيد مرحَّل بقيد جديد مطابق معكوس الأطراف (ملف 02 §4)."""
    src = db.get(m.JournalEntry, entry_id)
    if src is None or src.tenant_id != tenant_id:
        raise PostingError('ACCOUNTING.NOT_FOUND', 'القيد غير موجود')
    if src.status != 'POSTED':
        raise PostingError('ACCOUNTING.NOT_POSTED',
                           f'لا يمكن عكس قيد بحالة {src.status}')
    prior = db.execute(
        select(func.count(m.JournalEntry.id)).where(
            m.JournalEntry.reversal_of_entry_id == src.id)).scalar_one()
    if prior:
        raise PostingError('ACCOUNTING.ALREADY_REVERSED',
                           'القيد معكوس مسبقاً بقيد آخر')
    lines = db.execute(
        select(m.JournalLine).where(m.JournalLine.entry_id == src.id)
        .order_by(m.JournalLine.line_no)).scalars().all()
    raw = []
    for ln in lines:
        acc = db.get(m.Account, ln.account_id)
        raw.append({'account': acc.code, 'debit': ln.credit_base,
                    'credit': ln.debit_base, 'party_type': ln.party_type,
                    'party_id': ln.party_id,
                    'description': f'عكس: {ln.description}'})
    rev = create_and_post_journal(
        db, tenant_id=tenant_id, branch_id=src.branch_id,
        journal_type='REVERSAL',
        entry_date=reversal_date or date.today(),
        narration=f'عكس القيد {src.entry_no} — السبب: {reason}',
        raw_lines=raw, actor_id=actor_id, reference=src.entry_no,
        source_type='REVERSAL', source_id=src.id)
    # الانتقال الوحيد المرخص للمرحَّل: وسم الحالة (موثق في DECISIONS.md)
    src.status = 'REVERSED'
    rev.reversal_of_entry_id = src.id
    src.reversed_entry_id = rev.id
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='accounting', action='journal.reverse', entity='journal_entries',
          entity_id=src.id, after={'reversal': rev.entry_no, 'reason': reason},
          business_date=rev.entry_date)
    return rev


def ensure_not_mutating_posted(entry: m.JournalEntry, mutation: str):
    """حارس المركزية: أي محاولة تعديل/حذف لمرحَّل تُرفض هنا (ملف 02 §11)."""
    if entry.status in ('POSTED', 'REVERSED'):
        raise PostingError('ACCOUNTING.IMMUTABLE_POSTED',
                           f'يمنع {mutation} قيداً مرحلّاً — التصحيح بالعكس فقط')
