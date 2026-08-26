"""تدقيق اللوحة: سلسلة تجزئة مستقلة (ملف 08 §7 — Audit مستقل على كل فعل
حساس: إصدار ترخيص، تغيير حالة، فتح تذكرة لعميل، تصدير بيانات)."""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select

from .clock import vnow


from sqlalchemy.orm import Session

from . import models as m


def _canon(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), default=str)


def _aware(dt) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return str(dt)



    return datetime.now(timezone.utc).replace(tzinfo=None)


def vaudit(db: Session, *, actor_id: str | None, module: str, action: str,
           entity: str, entity_id: str | None = None,
           before: dict | None = None, after: dict | None = None,
           ip: str | None = None) -> m.VendorAudit:
    db.flush()
    prev_row = db.execute(select(m.VendorAudit.row_hash)
                          .order_by(m.VendorAudit.id.desc())
                          .limit(1)).first()
    prev = prev_row[0] if prev_row else 'GENESIS'
    at = vnow()
    payload = {'actor': actor_id, 'module': module, 'action': action,
               'entity': entity, 'entity_id': entity_id, 'before': before,
               'after': after, 'at': _aware(at), 'prev': prev,
               'ip': ip or ''}
    row = m.VendorAudit(actor_id=actor_id, module=module, action=action,
                        entity=entity, entity_id=entity_id, before=before,
                        after=after, at=at, prev_hash=prev,
                        row_hash=hashlib.sha256(
                            _canon(payload).encode('utf-8')).hexdigest(),
                        ip=ip or '')
    db.add(row)
    db.flush()
    return row
