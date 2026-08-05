"""صحة الأسطول (ملف 08 §6 — بهجين/سحابي وبموافقة تعاقدية): نبض يجمع آخر
اتصال/نسخة/مزامنة/نسخ احتياطي/قرص بمؤشرات خضراء-صفراء-حمراء موحدة،
وعلم بصمة الجهاز الغريبة (07 §4-5)، وحلقات تحديث Canary ← تعميم."""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .clock import vnow

STALE_YELLOW_H = 1
STALE_RED_H = 24
DISK_YELLOW_GB = Decimal('20')
DISK_RED_GB = Decimal('5')
LAG_YELLOW = 100


def ingest_heartbeat(db: Session, client: m.Client, *,
                     site_id: str, product_version: str, outbox_lag: int,
                     backup_ok: bool, disk_free_gb,
                     fingerprint_hash: str, payload: dict | None = None
                     ) -> m.Heartbeat:
    hb = m.Heartbeat(client_id=client.id, site_id=site_id,
                     product_version=product_version,
                     outbox_lag=int(outbox_lag or 0), backup_ok=bool(backup_ok),
                     disk_free_gb=Decimal(str(disk_free_gb or 0)),
                     fingerprint_hash=fingerprint_hash or '',
                     payload=payload or {})
    db.add(hb)
    db.flush()
    # 07 §4-5: بصمة جهاز تظهر فجأة على عميل آخر = علم
    if fingerprint_hash:
        others = db.execute(select(m.Heartbeat).where(
            m.Heartbeat.fingerprint_hash == fingerprint_hash,
            m.Heartbeat.client_id != client.id).limit(1)).first()
        if others:
            alert = m.FingerprintAlert(
                fingerprint_hash=fingerprint_hash,
                seen_on=[client.code, db.get(m.Client, others[0].client_id
                                             ).code])
            db.add(alert)
            db.add(m.Notification(
                role='LIC_OPERATOR', kind='FINGERPRINT_DRIFT',
                payload={'hash': fingerprint_hash[:16],
                         'clients': alert.seen_on}))
            db.flush()
    return hb


def fleet_health(db: Session) -> dict:
    clients = db.execute(select(m.Client).where(
        m.Client.status != 'TERMINATED').order_by(m.Client.code)
        ).scalars().all()
    rows = []
    counts = {'GREEN': 0, 'YELLOW': 0, 'RED': 0, 'DARK': 0}
    for c in clients:
        hb = db.execute(select(m.Heartbeat).where(
            m.Heartbeat.client_id == c.id)
            .order_by(m.Heartbeat.at.desc()).limit(1)).scalar_one_or_none()
        if hb is None:
            color = 'DARK'
            reasons = ['لا نبض بعد (محلي معزول أو لم يُفعَّل النبض)']
        else:
            age = vnow() - hb.at
            reasons = []
            if age > timedelta(hours=STALE_RED_H):
                reasons.append(f'آخر نبض قبل {age.days} يوم')
            if not hb.backup_ok:
                reasons.append('آخر نسخة احتياطية فاشلة')
            if Decimal(hb.disk_free_gb) < DISK_RED_GB:
                reasons.append(f'قرص حرج {hb.disk_free_gb}GB')
            if reasons:
                color = 'RED'
            else:
                if age > timedelta(hours=STALE_YELLOW_H):
                    reasons.append('نبض متأخر عن ساعة')
                if hb.outbox_lag > LAG_YELLOW:
                    reasons.append(f'تراكم مزامنة {hb.outbox_lag}')
                if Decimal(hb.disk_free_gb) < DISK_YELLOW_GB:
                    reasons.append(f'قرص منخفض {hb.disk_free_gb}GB')
                color = 'YELLOW' if reasons else 'GREEN'
        counts[color] += 1
        rows.append({'code': c.code, 'legal_name': c.legal_name,
                     'status': c.status, 'package': c.package,
                     'color': color, 'reasons': reasons,
                     'last_beat': hb.at.isoformat() if hb else None,
                     'product_version': hb.product_version if hb else '',
                     'outbox_lag': hb.outbox_lag if hb else None,
                     'backup_ok': hb.backup_ok if hb else None,
                     'disk_free_gb': str(hb.disk_free_gb) if hb else None})
    return {'counts': counts, 'rows': rows}
