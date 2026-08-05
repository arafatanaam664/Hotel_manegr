"""نقاط المحاسبة الأساسية — ملف 12 (API_STRUCTURE):
الحسابات • القيود (عرض/يدوي/عكس) • الفترات والإغلاق الشهري • سجل التدقيق.
لا توجد نقطة تعديل أو حذف لأي قيد مرحَّل — التصحيح بالعكس فقط (ملف 02 §11)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..audit import audit, audit_count, verify_chain
from ..db import get_db
from ..deps import Principal, require_perm
from ..posting import (PostingError, create_and_post_journal, reverse_entry)
from ..schemas import (AccountOut, AuditVerifyOut, JournalOut, ManualJournalIn,
                       PeriodOut, ReverseIn)
from ..security import utcnow

router = APIRouter(prefix='/api', tags=['accounting'])


# ─── دليل الحسابات ─────────────────────────────────────
@router.get('/accounts', response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('accounts.view'))):
    rows = db.execute(
        select(m.Account).where(m.Account.tenant_id == pr.tenant_id)
        .order_by(m.Account.code)).scalars().all()
    return [AccountOut.model_validate(a) for a in rows]


# ─── القيود ───────────────────────────────────────────
def _journal_out(db: Session, je: m.JournalEntry) -> JournalOut:
    accs = {a.id: a for a in db.execute(
        select(m.Account).where(m.Account.tenant_id == je.tenant_id)).scalars().all()}
    lines = []
    td = tc = 0
    for ln in sorted(je.lines, key=lambda x: x.line_no):
        a = accs.get(ln.account_id)
        lines.append({'line_no': ln.line_no,
                      'account_code': a.code if a else '?',
                      'account_name': a.name_ar if a else '?',
                      'debit': ln.debit_base, 'credit': ln.credit_base,
                      'party_type': ln.party_type,
                      'cost_center': ln.cost_center_id,
                      'description': ln.description})
        td += ln.debit_base
        tc += ln.credit_base
    return JournalOut(id=je.id, journal_type=je.journal_type,
                      entry_no=je.entry_no, entry_date=je.entry_date,
                      status=je.status, currency_code=je.currency_code,
                      narration=je.narration, reference=je.reference,
                      source_type=je.source_type, event_key=je.event_key,
                      reversal_of_entry_id=je.reversal_of_entry_id,
                      reversed_entry_id=je.reversed_entry_id,
                      total_debit=td, total_credit=tc,
                      created_at=je.created_at, posted_at=je.posted_at,
                      lines=lines)


@router.get('/journals')
def list_journals(date_from: date | None = None, date_to: date | None = None,
                  status: str | None = None, journal_type: str | None = None,
                  page: int = Query(default=1, ge=1),
                  page_size: int = Query(default=25, ge=1, le=100),
                  db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('journals.view'))):
    q = select(m.JournalEntry).where(m.JournalEntry.tenant_id == pr.tenant_id)
    if date_from:
        q = q.where(m.JournalEntry.entry_date >= date_from)
    if date_to:
        q = q.where(m.JournalEntry.entry_date <= date_to)
    if status:
        q = q.where(m.JournalEntry.status == status)
    if journal_type:
        q = q.where(m.JournalEntry.journal_type == journal_type)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(
        q.order_by(m.JournalEntry.entry_date.desc(),
                   m.JournalEntry.entry_no.desc())
        .offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {'total': total, 'page': page, 'page_size': page_size,
            'items': [_journal_out(db, je) for je in rows]}


@router.get('/journals/{entry_id}', response_model=JournalOut)
def get_journal(entry_id: str, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('journals.view'))):
    je = db.get(m.JournalEntry, entry_id)
    if je is None or je.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'GENERAL.NOT_FOUND',
                                            'message_ar': 'القيد غير موجود'}})
    return _journal_out(db, je)


@router.post('/journals/manual', response_model=JournalOut, status_code=201)
def post_manual_journal(body: ManualJournalIn,
                        db: Session = Depends(get_db),
                        pr: Principal = Depends(require_perm('journals.manual'))):
    branch = db.execute(
        select(m.Branch).where(m.Branch.tenant_id == pr.tenant_id,
                               m.Branch.code == body.branch_code)).scalar_one_or_none()
    if branch is None:
        raise HTTPException(400, {'error': {'code': 'ORG.UNKNOWN_BRANCH',
                                            'message_ar': f'فرع غير معروف: {body.branch_code}'}})
    raw = [{'account': ln.account_code, 'debit': ln.debit, 'credit': ln.credit,
            'party_type': ln.party_type, 'party_id': ln.party_id,
            'cost_center': ln.cost_center_code, 'description': ln.description}
           for ln in body.lines]
    je = create_and_post_journal(
        db, tenant_id=pr.tenant_id, branch_id=branch.id,
        journal_type='MANUAL', entry_date=body.entry_date,
        narration=body.narration, raw_lines=raw, actor_id=pr.id,
        reference=body.reference)
    db.commit()
    db.refresh(je)
    return _journal_out(db, je)


@router.post('/journals/{entry_id}/reverse', response_model=JournalOut,
             status_code=201)
def reverse_journal(entry_id: str, body: ReverseIn,
                    db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('journals.reverse'))):
    rev = reverse_entry(db, tenant_id=pr.tenant_id, entry_id=entry_id,
                        reason=body.reason, actor_id=pr.id)
    db.commit()
    db.refresh(rev)
    return _journal_out(db, rev)


# ─── الفترات والإغلاق الشهري ───────────────────────────
@router.get('/periods', response_model=list[PeriodOut])
def list_periods(db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('reports.view'))):
    rows = db.execute(
        select(m.FiscalPeriod, m.FiscalYear)
        .join(m.FiscalYear, m.FiscalYear.id == m.FiscalPeriod.fiscal_year_id)
        .where(m.FiscalYear.tenant_id == pr.tenant_id)
        .order_by(m.FiscalYear.year_no, m.FiscalPeriod.period_no)).all()
    return [PeriodOut(id=p.id, period_no=p.period_no, start_date=p.start_date,
                      end_date=p.end_date, status=p.status, year_no=y.year_no)
            for p, y in rows]


@router.post('/periods/{period_id}/close', response_model=PeriodOut)
def close_period(period_id: str, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('periods.close'))):
    """إغلاق لين (SOFT_CLOSED) — 02 §5: يتحقق من صفرية 8001 وترحيل كل
    المستندات (لا مسودات)، ثم يمنع الترحيل العادي ويسمح بتسويات المدير
    المالي فقط حتى الإغلاق الصلب."""
    p = db.get(m.FiscalPeriod, period_id)
    if p is None:
        raise HTTPException(404, {'error': {'code': 'GENERAL.NOT_FOUND',
                                            'message_ar': 'الفترة غير موجودة'}})
    year = db.get(m.FiscalYear, p.fiscal_year_id)
    if year.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'GENERAL.NOT_FOUND',
                                            'message_ar': 'الفترة غير موجودة'}})
    if p.status != 'OPEN':
        raise PostingError('ACCOUNTING.PERIOD_ALREADY',
                           f'الفترة بحالة {p.status} — لا يمكن إغلاقها')
    drafts = db.execute(
        select(func.count(m.JournalEntry.id)).where(
            m.JournalEntry.period_id == p.id,
            m.JournalEntry.status == 'DRAFT')).scalar_one()
    if drafts:
        raise PostingError('ACCOUNTING.DRAFTS_PENDING',
                           f'يوجد {drafts} قيد مسودة غير مرحَّل — رحّله أو احذفه أولاً')
    suspense = db.execute(
        select(func.coalesce(func.sum(
            m.JournalLine.debit_base - m.JournalLine.credit_base), 0))
        .join(m.JournalEntry, m.JournalLine.entry_id == m.JournalEntry.id)
        .join(m.Account, m.JournalLine.account_id == m.Account.id)
        .where(m.JournalEntry.tenant_id == pr.tenant_id,
               m.Account.code == '8001',
               m.JournalEntry.status.in_(['POSTED', 'REVERSED']))).scalar_one()
    from ..posting import D as _D
    if _D(suspense) != 0:
        raise PostingError('ACCOUNTING.SUSPENSE_NOT_ZERO',
                           'حساب المزامنة المرحلي 8001 ليس صفراً — سوِّه أولاً (02 §5)')
    p.status = 'SOFT_CLOSED'
    p.closed_by = pr.id
    p.closed_at = utcnow()
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='accounting', action='period.close', entity='fiscal_periods',
          entity_id=p.id,
          after={'year': year.year_no, 'period': p.period_no,
                 'mode': 'SOFT_CLOSED'},
          business_date=p.end_date)
    db.commit()
    return PeriodOut(id=p.id, period_no=p.period_no, start_date=p.start_date,
                     end_date=p.end_date, status=p.status, year_no=year.year_no)


@router.post('/periods/{period_id}/hard-close', response_model=PeriodOut)
def hard_close_period(period_id: str, db: Session = Depends(get_db),
                      pr: Principal = Depends(require_perm('periods.close'))):
    """الإغلاق الصلب النهائي — بعده لا قيد إطلاقاً (نهائي مطلقاً، 02 §5)."""
    p = db.get(m.FiscalPeriod, period_id)
    if p is None:
        raise HTTPException(404, {'error': {'code': 'GENERAL.NOT_FOUND',
                                            'message_ar': 'الفترة غير موجودة'}})
    year = db.get(m.FiscalYear, p.fiscal_year_id)
    if year.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'GENERAL.NOT_FOUND',
                                            'message_ar': 'الفترة غير موجودة'}})
    if p.status not in ('SOFT_CLOSED', 'CLOSED'):
        raise PostingError('ACCOUNTING.HARD_NEEDS_SOFT',
                           'الإغلاق الصلب يتطلب فترة مغلقة ليناً أولاً')
    p.status = 'HARD_CLOSED'
    p.closed_by = pr.id
    p.closed_at = utcnow()
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='accounting', action='period.hard_close',
          entity='fiscal_periods', entity_id=p.id,
          after={'year': year.year_no, 'period': p.period_no},
          business_date=p.end_date)
    db.commit()
    return PeriodOut(id=p.id, period_no=p.period_no, start_date=p.start_date,
                     end_date=p.end_date, status=p.status, year_no=year.year_no)


# ─── سجل التدقيق ──────────────────────────────────────
@router.get('/audit')
def list_audit(page: int = Query(default=1, ge=1),
               page_size: int = Query(default=50, ge=1, le=200),
               module: str | None = None,
               db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('audit.view'))):
    q = select(m.AuditLog).where(m.AuditLog.tenant_id == pr.tenant_id)
    if module:
        q = q.where(m.AuditLog.module == module)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(m.AuditLog.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).scalars().all()
    users = {u.id: u.username for u in db.execute(
        select(m.User).where(m.User.tenant_id == pr.tenant_id)).scalars().all()}
    return {'total': total, 'page': page, 'page_size': page_size,
            'chain_records': audit_count(db, pr.tenant_id),
            'items': [{'id': r.row_uuid, 'at': r.at_utc,
                       'actor': users.get(r.actor_user_id, r.actor_user_id or r.actor_type),
                       'actor_type': r.actor_type, 'module': r.module,
                       'action': r.action, 'entity': r.entity,
                       'entity_id': r.entity_id, 'after': r.after,
                       'business_date': r.business_date} for r in rows]}


@router.get('/audit/verify', response_model=AuditVerifyOut)
def audit_verify(db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('audit.view'))):
    return AuditVerifyOut(**verify_chain(db, pr.tenant_id))


# ─── إقفال السنة المالية (02 §5) ───────────────────────
from .. import closing as FC  # noqa: E402


@router.get('/years')
def list_years(db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('reports.view'))):
    rows = db.execute(
        select(m.FiscalYear).where(m.FiscalYear.tenant_id == pr.tenant_id)
        .order_by(m.FiscalYear.year_no)).scalars().all()
    return [{'id': y.id, 'year_no': y.year_no,
             'start_date': y.start_date.isoformat(),
             'end_date': y.end_date.isoformat(), 'status': y.status,
             'periods': [{'id': p.id, 'no': p.period_no, 'status': p.status}
                         for p in sorted(y.periods,
                                         key=lambda x: x.period_no)]}
            for y in rows]


@router.get('/years/{year_no}/close-precheck')
def year_close_precheck(year_no: int, db: Session = Depends(get_db),
                        pr: Principal = Depends(require_perm('periods.close'))):
    db.commit()
    return FC.precheck(db, pr.tenant_id, year_no)


@router.post('/years/{year_no}/close', status_code=201)
def year_close(year_no: int, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('periods.close'))):
    res = FC.close_fiscal_year(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                               branch_id=_any_branch(db, pr), year_no=year_no)
    db.commit()
    return res


def _any_branch(db: Session, pr: Principal) -> str:
    b = db.execute(
        select(m.Branch).where(m.Branch.tenant_id == pr.tenant_id)
        .order_by(m.Branch.code)).scalars().first()
    if b is None:
        raise HTTPException(400, {'error': {'code': 'ORG.NO_BRANCH',
                                            'message_ar': 'لا يوجد فرع معرف'}})
    return b.id


# ─── قيد تسوية في فترة مغلقة ليناً (02 §5: للمدير المالي) ───
@router.post('/journals/adjust', response_model=JournalOut, status_code=201)
def adjust_journal(body: ManualJournalIn, db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('periods.adjust'))):
    branch = db.execute(
        select(m.Branch).where(m.Branch.tenant_id == pr.tenant_id,
                               m.Branch.code == body.branch_code)).scalar_one_or_none()
    if branch is None:
        raise HTTPException(400, {'error': {'code': 'ORG.UNKNOWN_BRANCH',
                                            'message_ar': f'فرع غير معروف: {body.branch_code}'}})
    raw = [{'account': ln.account_code, 'debit': ln.debit, 'credit': ln.credit,
            'party_type': ln.party_type, 'party_id': ln.party_id,
            'cost_center': ln.cost_center_code, 'description': ln.description}
           for ln in body.lines]
    je = create_and_post_journal(
        db, tenant_id=pr.tenant_id, branch_id=branch.id,
        journal_type='MANUAL', entry_date=body.entry_date,
        narration='[تسوية فترة لينة] ' + body.narration,
        raw_lines=raw, actor_id=pr.id, reference=body.reference,
        allow_soft=True)
    db.commit()
    db.refresh(je)
    return _journal_out(db, je)
