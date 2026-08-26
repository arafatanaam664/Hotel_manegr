#!/usr/bin/env python3
"""استعادة نسخة SQLite في وضع الصيانة.

الاستخدام:
  python3 scripts/restore_backup.py --backup backups/file.sqlite3 \
      --target backend/sijill_dev.sqlite

أوقف خدمة الويب أولاً، وتأكد من أن الملف الهدف نسخة احتياطية منه. لا يوجد
استبدال فوق الملف المصدر، وتُحفظ نسخة .before-restore قبل التغيير.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_sqlite(path: Path) -> None:
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        result = con.execute('PRAGMA integrity_check').fetchone()
        if not result or result[0] != 'ok':
            raise SystemExit(f'فشل فحص سلامة SQLite: {result!r}')
    finally:
        con.close()


def main() -> int:
    p = argparse.ArgumentParser(description='استعادة نسخة SQLite في وضع الصيانة')
    p.add_argument('--backup', required=True, type=Path)
    p.add_argument('--target', required=True, type=Path)
    p.add_argument('--sha256', default='', help='البصمة المتوقعة اختيارياً')
    p.add_argument('--yes', action='store_true', help='تأكيد الاستبدال')
    args = p.parse_args()

    backup = args.backup.expanduser().resolve()
    target = args.target.expanduser().resolve()
    if not backup.is_file():
        raise SystemExit('ملف النسخة غير موجود')
    if backup == target:
        raise SystemExit('لا يمكن أن يكون المصدر والهدف نفس الملف')
    digest = sha256(backup)
    if args.sha256 and digest.lower() != args.sha256.lower():
        raise SystemExit('فشل مطابقة SHA-256 للنسخة')
    verify_sqlite(backup)
    if not args.yes:
        raise SystemExit(f'النسخة سليمة ({digest})، أعد التشغيل مع --yes لتأكيد الاستعادة')

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        before = target.with_name(target.name + '.before-restore')
        shutil.copy2(target, before)
    tmp = target.with_name(target.name + '.restore.tmp')
    shutil.copy2(backup, tmp)
    os.replace(tmp, target)
    verify_sqlite(target)
    print(f'تمت الاستعادة بنجاح: {target}')
    print(f'SHA-256: {digest}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
