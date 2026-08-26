"""نقاط الأصول الثابتة والإهلاك — /api/fa (ملف 11 (ز) + حدث #24)."""
from fastapi import APIRouter, Depends

from sqlalchemy.orm import Session

from .. import assets as FA
from ..db import get_db
from ..deps import Principal, require_perm
from ..schemas import FaAssetIn, FaDisposeIn, FaRunIn
from .. import models as m
from sqlalchemy import select

router = APIRouter(prefix='/api/fa', tags=['assets'])


def _branch(db: Session, pr: Principal) -> str:
    b = db.execute(
        select(m.Branch).where(m.Branch.tenant_id == pr.tenant_id)
        .order_by(m.Branch.code)).scalars().first()
    return b.id


def _asset_dict(a) -> dict:
    return {'id': a.id, 'code': a.code, 'name': a.name,
            'category': a.category,
            'purchase_date': a.purchase_date.isoformat(),
            'cost': str(a.cost), 'salvage': str(a.salvage),
            'life_months': a.useful_life_months, 'method': a.method,
            'depreciated_total': str(a.depreciated_total),
            'nbv': str(a.cost - a.depreciated_total), 'status': a.status,
            'last_run_month': a.last_run_month,
            'disposed_at': a.disposed_at.isoformat() if a.disposed_at else None}


@router.get('/assets')
def list_assets(db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('fa.view'))):
    db.commit()
    return [_asset_dict(a) for a in FA.list_assets(db, pr.tenant_id)]


@router.post('/assets', status_code=201)
def create_asset(body: FaAssetIn, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('fa.manage'))):
    a = FA.create_asset(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                        name=body.name, category=body.category,
                        purchase_date=body.purchase_date, cost=body.cost,
                        salvage=body.salvage,
                        useful_life_months=body.useful_life_months,
                        method=body.method,
                        asset_account_code=body.asset_account_code,
                        accum_account_code=body.accum_account_code,
                        expense_account_code=body.expense_account_code)
    db.commit()
    return {'id': a.id, 'code': a.code}


@router.post('/assets/{asset_id}/dispose')
def dispose_asset(asset_id: str, body: FaDisposeIn,
                  db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('fa.manage'))):
    a = FA.dispose_asset(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                         asset_id=asset_id, disposed_at=body.disposed_at,
                         reason=body.reason)
    db.commit()
    return _asset_dict(a)


@router.get('/assets/{asset_id}/schedule')
def schedule(asset_id: str, from_month: str,
             db: Session = Depends(get_db),
             pr: Principal = Depends(require_perm('fa.view'))):
    db.commit()
    a = FA.get_asset(db, pr.tenant_id, asset_id)
    return {'asset': _asset_dict(a),
            'schedule': FA.asset_schedule(a, FA._check_month(from_month))}


@router.get('/register')
def register(db: Session = Depends(get_db),
             pr: Principal = Depends(require_perm('fa.view'))):
    """سجل الأصول مقابل الأستاذ (تقرير المطابقة الدوري ملف 02 §10 روحاً)."""
    db.commit()
    return FA.register_report(db, pr.tenant_id)


@router.get('/runs')
def list_runs(db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('fa.view'))):
    db.commit()
    return [{'id': r.id, 'month': r.month, 'total': str(r.total),
             'asset_count': r.asset_count, 'lines': r.lines,
             'posted_entry_id': r.posted_entry_id,
             'created_at': r.created_at.isoformat() if r.created_at else None}
            for r in FA.list_runs(db, pr.tenant_id)]


@router.post('/runs', status_code=201)
def run_month(body: FaRunIn, db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('fa.manage'))):
    r = FA.run_depreciation(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                            branch_id=_branch(db, pr), month=body.month)
    db.commit()
    return {'id': r.id, 'month': r.month, 'total': str(r.total),
            'asset_count': r.asset_count,
            'posted_entry_id': r.posted_entry_id}
