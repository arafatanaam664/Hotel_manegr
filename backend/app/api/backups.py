"""واجهات النسخ الاحتياطي المحلية.

الاستعادة لا تنفذ عبر HTTP في هذه المرحلة؛ تتم من وضع صيانة عبر السكربت
لتفادي استبدال قاعدة بيانات عملية حية من طلب ويب.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..backup import create_backup, list_backups, verify_backup
from ..db import get_db
from ..deps import Principal, require_perm
from ..schemas import BackupOut

router = APIRouter(prefix='/api/backups', tags=['backups'])


@router.get('', response_model=list[BackupOut])
def get_backups(
        limit: int = Query(default=50, ge=1, le=200),
        db: Session = Depends(get_db),
        pr: Principal = Depends(require_perm('settings.manage'))):
    return [BackupOut(**row) for row in list_backups(db, pr.tenant_id, limit)]


@router.post('', response_model=BackupOut, status_code=201)
def post_backup(
        db: Session = Depends(get_db),
        pr: Principal = Depends(require_perm('settings.manage'))):
    result = create_backup(db, pr.tenant_id, pr.id)
    db.commit()
    result['verified'] = True
    return BackupOut(**result)


@router.post('/{backup_id}/verify', response_model=BackupOut)
def post_verify(
        backup_id: str,
        db: Session = Depends(get_db),
        pr: Principal = Depends(require_perm('settings.manage'))):
    result = verify_backup(db, pr.tenant_id, backup_id)
    return BackupOut(**result)
