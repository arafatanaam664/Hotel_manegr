"""نسخ احتياطي واستعادة آمنان للنسخة المحلية.

تُنفذ الاستعادة عبر سكربت صيانة خارج عملية الويب حتى لا تستبدل عملية حية
قاعدة بياناتها بنفسها. النسخ ينشئ snapshot SQLite ذرياً ويسجل بصمته في قاعدة
التطبيق. دعم pg_dump يضاف كموفر منفصل عند تجهيز نشر PostgreSQL التجاري.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models as m
from .config import get_settings
from .security import new_uuid, utcnow


def _error(code: str, message: str, status: int = 400):
    raise HTTPException(status, {'error': {'code': code, 'message_ar': message}})


def _sqlite_path(database_url: str) -> Path:
    prefix = 'sqlite:///'
    if not database_url.startswith(prefix):
        _error('BACKUP.UNSUPPORTED_DATABASE',
               'النسخ التلقائي لهذه القاعدة يحتاج موفر PostgreSQL منفصلاً', 501)
    raw = unquote(database_url[len(prefix):].split('?', 1)[0])
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_backup_dir() -> Path:
    path = Path(get_settings().backup_dir).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def create_backup(db: Session, tenant_id: str, actor_id: str | None = None) -> dict:
    source = _sqlite_path(get_settings().database_url)
    if not source.exists():
        _error('BACKUP.SOURCE_MISSING', 'ملف قاعدة البيانات غير موجود', 500)
    target_dir = _safe_backup_dir()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = target_dir / f'backup_{tenant_id[:8]}_{stamp}.sqlite3'
    tmp = target.with_suffix('.tmp')
    try:
        src = sqlite3.connect(str(source))
        dst = sqlite3.connect(str(tmp))
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        os.replace(tmp, target)
        digest = _sha256(target)
        now = utcnow()
        rec = m.BackupRecord(
            id=new_uuid(), tenant_id=tenant_id, created_at=now,
            file_name=target.name, file_path=str(target),
            storage_kind='LOCAL', size_bytes=target.stat().st_size,
            sha256=digest, status='VERIFIED', verified_at=now,
            created_by=actor_id, error='')
        db.add(rec)
        db.flush()
        return {
            'id': rec.id, 'file_name': rec.file_name,
            'storage_kind': rec.storage_kind, 'size_bytes': rec.size_bytes,
            'sha256': rec.sha256, 'status': rec.status,
            'created_at': rec.created_at.isoformat(),
        }
    except Exception as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        _error('BACKUP.CREATE_FAILED', f'فشل إنشاء النسخة: {exc}', 500)


def list_backups(db: Session, tenant_id: str, limit: int = 50) -> list[dict]:
    rows = db.query(m.BackupRecord).filter(
        m.BackupRecord.tenant_id == tenant_id).order_by(
            m.BackupRecord.created_at.desc()).limit(limit).all()
    out = []
    for rec in rows:
        path = Path(rec.file_path)
        exists = path.exists()
        out.append({
            'id': rec.id, 'file_name': rec.file_name,
            'storage_kind': rec.storage_kind, 'size_bytes': rec.size_bytes,
            'sha256': rec.sha256, 'status': rec.status,
            'created_at': rec.created_at.isoformat(),
            'verified': exists and _sha256(path) == rec.sha256,
        })
    return out


def verify_backup(db: Session, tenant_id: str, backup_id: str) -> dict:
    rec = db.get(m.BackupRecord, backup_id)
    if rec is None or rec.tenant_id != tenant_id:
        _error('BACKUP.NOT_FOUND', 'النسخة غير موجودة', 404)
    path = Path(rec.file_path)
    verified = path.exists() and _sha256(path) == rec.sha256
    rec.status = 'VERIFIED' if verified else 'CORRUPT'
    rec.verified_at = utcnow() if verified else None
    db.commit()
    if not verified:
        _error('BACKUP.CHECKSUM_MISMATCH', 'فشل التحقق من بصمة النسخة', 409)
    return {
        'id': rec.id, 'file_name': rec.file_name,
        'storage_kind': rec.storage_kind, 'size_bytes': rec.size_bytes,
        'sha256': rec.sha256, 'status': rec.status,
        'created_at': rec.created_at.isoformat(), 'verified': True,
    }
