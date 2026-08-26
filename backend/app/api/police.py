"""نقاط «المعلومية اليومية» للبحث الجنائي (0.14.0 — طلب المالك، ADR-0038).

باستثناء المعاينة المصمَّمة بلا PII صريحة، كل تنزيل محفوظ في أرشيف
الإرسالات بحمولته وبصمته وموثق في سجل التدقيق باسم فاعله — فالسؤال
الأمني «ماذا أرسلتم يوم كذا؟» تُجيب عنه إعادة التنزيل الحرفية."""
from datetime import date as _date
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
import io

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..audit import audit
from ..db import get_db
from ..deps import Principal, require_perm
from ..police_report import (build_xlsx, collect_payload, payload_sha256,
                             rows_public)
from ..security import new_uuid, utcnow

router = APIRouter(prefix='/api/hotel/police-report', tags=['police-report'])

MEDIA = ('application/vnd.openxmlformats-'
         'officedocument.spreadsheetml.sheet')


def _filename(header: dict) -> str:
    base = f"معلومية {header['hotel']} {header['weekday']} {header['date']}.xlsx"
    return f"attachment; filename=\"police-report.xlsx\"; " \
           f"filename*=UTF-8''{quote(base)}"


def _xlsx_response(data: bytes, header: dict) -> StreamingResponse:
    return StreamingResponse(
        io.BytesIO(data), media_type=MEDIA,
        headers={'Content-Disposition': _filename(header)})


@router.get('/preview')
def preview(day: _date = Query(alias='date'),
            db: Session = Depends(get_db),
            pr: Principal = Depends(require_perm('police.report'))):
    """معاينة أسماء اليوم قبل الإرسال — بلا أرقام هوية صريحة إطلاقاً."""
    p = collect_payload(db, pr.tenant_id, day)
    return {'header': p['header'], 'rows': rows_public(p['rows']),
            'warnings': p['warnings'], 'stays_count': p['stays_count'],
            'rows_count': p['rows_count']}


@router.get('/download')
def download(day: _date = Query(alias='date'),
             db: Session = Depends(get_db),
             pr: Principal = Depends(require_perm('police.report'))):
    """تنزيل الملف + أرشفة «ما أُرسل» + توثيق الفعل باسم الموظف."""
    p = collect_payload(db, pr.tenant_id, day)
    if not p['rows']:
        raise HTTPException(404, {'error': {
            'code': 'POLICE.EMPTY_DAY',
            'message_ar': 'لا نزلاء في هذا اليوم — لم تسجّل أي إقامة فعلية '
                          'تتداخل معه (الملغي وعدم الحضور لا يظهران أبداً)'}})
    payload = {'header': p['header'], 'rows': p['rows']}
    run = m.PoliceReportRun(
        id=new_uuid(), tenant_id=pr.tenant_id, report_date=day,
        generated_by=pr.user.username, generated_at=utcnow(),
        rows_count=p['rows_count'], stays_count=p['stays_count'],
        header=p['header'], payload=payload,
        sha256=payload_sha256(payload))
    db.add(run)
    db.flush()
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='police.report.generate',
          entity='police_report_runs', entity_id=run.id,
          after={'date': str(day), 'rows': p['rows_count'],
                 'sha256': run.sha256[:16]}, business_date=day)
    db.commit()
    return _xlsx_response(build_xlsx(p['header'], p['rows']), p['header'])


@router.get('/runs')
def list_runs(date_from: _date | None = None, date_to: _date | None = None,
              db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('police.report'))):
    """أرشيف الإرسالات — أحدث أولاً (لإثبات ما أُرسل فعلاً)."""
    q = select(m.PoliceReportRun).where(
        m.PoliceReportRun.tenant_id == pr.tenant_id)
    if date_from:
        q = q.where(m.PoliceReportRun.report_date >= date_from)
    if date_to:
        q = q.where(m.PoliceReportRun.report_date <= date_to)
    runs = db.execute(q.order_by(m.PoliceReportRun.generated_at.desc())
                      .limit(200)).scalars().all()
    return [{'id': r.id, 'report_date': r.report_date,
             'generated_by': r.generated_by, 'generated_at': r.generated_at,
             'rows_count': r.rows_count, 'stays_count': r.stays_count,
             'sha256': r.sha256} for r in runs]


@router.get('/runs/{run_id}/download')
def redownload(run_id: str, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('police.report'))):
    """إعادة تنزيل الملف كما أُرسل حرفياً (الحمولة المؤرشفة لا تتغير)."""
    run = db.get(m.PoliceReportRun, run_id)
    if not run or run.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'GEN.NOT_FOUND',
                                            'message_ar': 'إرسال غير موجود'}})
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='hotel', action='police.report.redownload',
          entity='police_report_runs', entity_id=run.id,
          after={'date': str(run.report_date)},
          business_date=run.report_date)
    db.commit()
    header = run.payload['header']
    return _xlsx_response(build_xlsx(header, run.payload['rows']), header)
