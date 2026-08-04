"""سجل تدقيق مقاوم للتلاعب: سلسلة تجزئة لكل مستأجر.
row_hash = SHA256(سلسلة الحقول القانونية + prev_hash) — كسر أي سجل قديم يكسر السلسلة.
(ملف 13 من الدراسة)"""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from . import models as m
from .security import utcnow, new_uuid


def _canon(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), default=str)


def _iso(dt) -> str | None:
    """تطبيع حتمي: النايف UTC — التجزئة يجب أن تتطابق قبل التخزين وبعده."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return dt.isoformat()


def canonical_hash(*, tenant_id: str, at, actor, module, action, entity,
                   entity_id, before, after, business_date, prev_hash) -> str:
    payload = {
        'tenant': tenant_id, 'at': _iso(at),
        'actor': actor, 'module': module, 'action': action,
        'entity': entity, 'entity_id': entity_id,
        'before': before, 'after': after, 'bd': _iso(business_date),
        'prev': prev_hash,
    }
    return hashlib.sha256(_canon(payload).encode('utf-8')).hexdigest()


def _last_hash(db: Session, tenant_id: str) -> str:
    row = db.execute(
        select(m.AuditLog.row_hash).where(m.AuditLog.tenant_id == tenant_id)
        .order_by(m.AuditLog.id.desc()).limit(1)).first()
    return row[0] if row else 'GENESIS'


def audit(db: Session, *, tenant_id: str, actor_id: str | None,
          actor_type: str, module: str, action: str, entity: str,
          entity_id: str | None = None, before: dict | None = None,
          after: dict | None = None, business_date=None,
          ip: str | None = None) -> m.AuditLog:
    at = utcnow()
    prev = _last_hash(db, tenant_id)
    rh = canonical_hash(tenant_id=tenant_id, at=at, actor=actor_id,
                        module=module, action=action, entity=entity,
                        entity_id=entity_id, before=before, after=after,
                        business_date=business_date, prev_hash=prev)
    entry = m.AuditLog(
        row_uuid=new_uuid(), tenant_id=tenant_id, at_utc=at,
        actor_user_id=actor_id,
        actor_type=actor_type, module=module, action=action, entity=entity,
        entity_id=entity_id, before=before, after=after, ip=ip,
        business_date=business_date, prev_hash=prev, row_hash=rh)
    db.add(entry)
    return entry


def verify_chain(db: Session, tenant_id: str, limit: int = 100000) -> dict:
    """فاحص السلامة: يعيد حساب السلسلة كاملة ويحدد مكان أول كسر إن وُجد."""
    rows = db.execute(
        select(m.AuditLog).where(m.AuditLog.tenant_id == tenant_id)
        .order_by(m.AuditLog.id.asc()).limit(limit)).scalars().all()
    prev = 'GENESIS'
    for i, r in enumerate(rows):
        if r.prev_hash != prev:
            return {'ok': False, 'broken_at': r.row_uuid,
                    'detail': 'prev_hash mismatch', 'checked': i}
        expect = canonical_hash(
            tenant_id=r.tenant_id, at=r.at_utc, actor=r.actor_user_id,
            module=r.module, action=r.action, entity=r.entity,
            entity_id=r.entity_id, before=r.before, after=r.after,
            business_date=r.business_date, prev_hash=r.prev_hash)
        if expect != r.row_hash:
            return {'ok': False, 'broken_at': r.row_uuid,
                    'detail': 'row_hash mismatch', 'checked': i}
        prev = r.row_hash
    return {'ok': True, 'checked': len(rows)}


def audit_count(db: Session, tenant_id: str) -> int:
    return db.execute(
        select(func.count(m.AuditLog.id))
        .where(m.AuditLog.tenant_id == tenant_id)).scalar_one()
