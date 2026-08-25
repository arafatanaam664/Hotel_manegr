"""التقارير المالية — من القيود المرحَّلة فقط (ملف 02 §10):
ميزان المراجعة • دفتر الأستاذ • سيناريو الشهر الفندقي التجريبي (بوابة G1)."""
from datetime import date

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from .. import reports as R
from ..db import get_db
from ..deps import Principal, require_perm
from ..reports import ledger, run_g1_month_scenario, trial_balance
from ..schemas import LedgerOut, TrialBalanceOut

router = APIRouter(prefix='/api', tags=['reports'])


def _scoped_branch(pr: Principal, branch_id: str | None) -> str | None:
    """حماية التقارير الجديدة من تسريب بيانات فرع غير مسند للمستخدم."""
    if '*' in pr.perms:
        return branch_id
    if branch_id and branch_id not in pr.branch_ids:
        raise HTTPException(403, {'error': {
            'code': 'RBAC.BRANCH_FORBIDDEN',
            'message_ar': 'لا تملك صلاحية عرض هذا الفرع'}})
    if branch_id:
        return branch_id
    if len(pr.branch_ids) == 1:
        return pr.branch_ids[0]
    return None


@router.get('/reports/trial-balance', response_model=TrialBalanceOut)
def get_trial_balance(as_of: date | None = None,
                      db: Session = Depends(get_db),
                      pr: Principal = Depends(require_perm('reports.view'))):
    tb = trial_balance(db, pr.tenant_id, as_of or date.today())
    return TrialBalanceOut(
        as_of=tb['as_of'], total_debit=tb['total_debit'],
        total_credit=tb['total_credit'], balanced=tb['balanced'],
        net_balance_zero=tb['net_balance_zero'], rows=tb['rows'])


@router.get('/reports/ledger', response_model=LedgerOut)
def get_ledger(account_code: str, date_from: date, date_to: date,
               db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('reports.view'))):
    out = ledger(db, pr.tenant_id, account_code, date_from, date_to)
    return LedgerOut(**out)


@router.post('/demo/run-month')
def run_demo_month(year: int | None = None, month: int | None = None,
                   reset: bool = False,
                   db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('demo.run'))):
    """يشغّل شهراً فندقياً كاملاً عبر محرك الترحيل (أحداث ذات مفاتيح
    Idempotency — إعادة التشغيل آمنة ولا تكرر القيود)."""
    today = date.today()
    y, mo = year or today.year, month or today.month
    out = run_g1_month_scenario(db, tenant_id=pr.tenant_id, year=y, month=mo,
                                actor_id=pr.id)
    db.commit()
    out['trial_balance'] = {'as_of': str(date(y, mo,
                                              __import__('calendar').monthrange(y, mo)[1]))}
    return out


# ─── القوائم المالية الكاملة (02 §10) ──────────────────
from ..schemas import (AgingOut, BalanceSheetOut, CashFlowOut,  # noqa: E402
                       HotelDailyReportOut, HotelRangeReportOut,
                       IncomeStatementOut)


@router.get('/reports/income-statement', response_model=IncomeStatementOut)
def get_income_statement(from_: date = Query(alias='from'),
                         to: date = Query(),
                         db: Session = Depends(get_db),
                         pr: Principal = Depends(require_perm('reports.view'))):
    """قائمة الدخل بمنهج USALI — دخل كل قسم ثم غير الموزعة ثم GOP ثم الصافي."""
    db.commit()
    return R.income_statement(db, pr.tenant_id, from_, to)


@router.get('/reports/balance-sheet', response_model=BalanceSheetOut)
def get_balance_sheet(as_of: date = Query(),
                      db: Session = Depends(get_db),
                      pr: Principal = Depends(require_perm('reports.view'))):
    db.commit()
    return R.balance_sheet(db, pr.tenant_id, as_of)


@router.get('/reports/cash-flow', response_model=CashFlowOut)
def get_cash_flow(from_: date = Query(alias='from'), to: date = Query(),
                  db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('reports.view'))):
    db.commit()
    return R.cash_flow(db, pr.tenant_id, from_, to)


@router.get('/reports/aging', response_model=AgingOut)
def get_aging(account: str = Query(pattern='^(1110|1120|2101)$'),
              as_of: date = Query(),
              db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('reports.view'))):
    db.commit()
    return R.aging_report(db, pr.tenant_id, account, as_of)


@router.get('/reports/hotel/daily', response_model=HotelDailyReportOut)
def get_hotel_daily(business_day: date = Query(),
                    branch_id: str | None = Query(default=None),
                    db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('reports.view'))):
    return R.hotel_daily_report(db, pr.tenant_id, business_day,
                                _scoped_branch(pr, branch_id))


@router.get('/reports/hotel/range', response_model=HotelRangeReportOut)
def get_hotel_range(from_: date = Query(alias='from'), to: date = Query(),
                   branch_id: str | None = Query(default=None),
                   db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('reports.view'))):
    return R.hotel_daily_range(db, pr.tenant_id, from_, to,
                               _scoped_branch(pr, branch_id))
