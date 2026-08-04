"""التقارير المالية — من القيود المرحَّلة فقط (ملف 02 §10):
ميزان المراجعة • دفتر الأستاذ • سيناريو الشهر الفندقي التجريبي (بوابة G1)."""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..db import get_db
from ..deps import Principal, require_perm
from ..reports import ledger, run_g1_month_scenario, trial_balance
from ..schemas import LedgerOut, TrialBalanceOut

router = APIRouter(prefix='/api', tags=['reports'])


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
