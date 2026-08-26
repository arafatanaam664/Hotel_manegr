#!/usr/bin/env python3
"""إنشاء نسخ لكل المستأجرين المحليين وتطبيق سياسة الاحتفاظ.

يُشغّل من cron/systemd timer بعد ضبط بيئة التطبيق، مثلاً:
  0 2 * * * cd /opt/sijill && /usr/bin/python3 scripts/backup_all.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from sqlalchemy import select

from app.backup import create_backup, prune_backups
from app.db import SessionLocal
from app import models as m


def main() -> int:
    db = SessionLocal()
    try:
        tenants = db.execute(select(m.Tenant).where(m.Tenant.status == 'ACTIVE')).scalars().all()
        created = 0
        expired = 0
        for tenant in tenants:
            create_backup(db, tenant.id, None)
            created += 1
            expired += prune_backups(db, tenant.id)
            db.commit()
        print(f'تم إنشاء {created} نسخة وتطبيق الاحتفاظ على {expired} نسخة قديمة')
        return 0
    finally:
        db.close()


if __name__ == '__main__':
    raise SystemExit(main())
