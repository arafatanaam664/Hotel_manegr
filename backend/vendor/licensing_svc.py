"""خدمة الترخيص في اللوحة (تكامل 08 §4 مع 07): إصدار/تجديد/إيقاف/إلغاء،
تجاوز حدود الخطة = اعتماد ثانٍ إلزامي (مكافحة خطأ/عبث داخلي)، قوائم
إلغاء موقعة بأرقام تسلسلية، والمفتاح الخاص لا يغادر هذه البيئة أبداً."""
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..')))
from app import licensing as lic  # مكتبة التوقيع المشتركة (جانب الشركة)
from . import models as m
from .audit import vaudit
from .clock import vnow
from .clock import vnow
from .config import get_vendor_settings
from .security import vdeny


def _private_pem() -> bytes:
    path = get_vendor_settings().license_private_key_path
    if not path or not os.path.isfile(path):
        vdeny('VND.NO_SIGNING_KEY',
              'مفتاح التوقيع غير متوفر في بيئة الشركة — راجع مدير النظام',
              500)
    with open(path, 'rb') as f:
        blob = f.read()
    if b'PRIVATE KEY' not in blob:
        vdeny('VND.NO_SIGNING_KEY', 'الملف المضبوط ليس مفتاحاً خاصاً', 500)
    return blob


def next_serial(db: Session, client: m.Client) -> int:
    mx = db.execute(select(func.max(m.LicenseRecord.serial)).where(
        m.LicenseRecord.client_id == client.id)).scalar()
    return int(mx or 0) + 1


def _over_plan(plan: m.Plan | None, modules: list, max_users: int,
               max_branches: int) -> str:
    """تجاوز حدود الخطة = اعتماد ثانٍ إلزامي (§4)."""
    if plan is None:
        return ''
    reasons = []
    plan_modules = set(plan.module_prices.keys())
    extra_modules = [x for x in modules
                     if x not in plan_modules and x not in ('ACCOUNTING',)]
    if extra_modules:
        reasons.append(f'وحدات خارج الخطة: {extra_modules}')
    if max_users > plan.included_users * 2:
        reasons.append(
            f'مستخدمون {max_users} يتجاوزون ضعف مستخدمي الخطة '
            f'({plan.included_users})')
    if max_branches > plan.included_branches * 3:
        reasons.append('فروع تتجاوز سقف الخطة')
    return '؛ '.join(reasons)


def build_payload(client: m.Client, *, serial: int, modules: list,
                  max_users: int, max_branches: int, expires: date,
                  grace_days: int, fingerprint: dict | None,
                  features: dict | None, support: str, kind: str) -> dict:
    return {
        'license_id': f'LIC-{client.code}',
        'tenant_id': client.tenant_id or client.code,
        'legal_name': client.legal_name,
        'package': client.package,
        'modules_enabled': modules,
        'max_users': max_users,
        'max_branches': max_branches,
        'issued_at': vnow().isoformat(),
        'expires_at': str(expires),
        'grace_days': grace_days,
        'hardware_fingerprint': fingerprint or None,
        'hardware_fingerprint_hash':
            lic.fingerprint_hash(fingerprint) if fingerprint else None,
        'features_flags': features or {},
        'support_level': support,
        'nonce': os.urandom(16).hex(),
        'serial': serial,
        'kind': kind,
    }


def issue_license(db: Session, client: m.Client, *, actor: m.VendorUser,
                  kind: str = 'ISSUE', modules: list | None = None,
                  max_users: int = 10, max_branches: int = 1,
                  expires: date | None = None, days: int = 365,
                  grace_days: int | None = None, fingerprint: dict | None = None,
                  features: dict | None = None, support: str = 'STANDARD',
                  auto_approve: bool = False,
                  ip: str | None = None) -> m.LicenseRecord:
    """يوقّع ويخزّن ملف ترخيص. تجاوز الخطة ← PENDING_APPROVAL (لا يصل
    العميل إلا باعتماد مدير ثانٍ — §4)."""
    plan = db.execute(select(m.Plan).where(
        m.Plan.code == client.plan_code)).scalar_one_or_none()
    serial = next_serial(db, client)
    expires = expires or (date.today() + timedelta(days=days))
    over = _over_plan(plan, modules or client.modules, max_users, max_branches)
    needs_approval = bool(over) and not auto_approve

    payload = build_payload(
        client, serial=serial, modules=modules or client.modules,
        max_users=max_users, max_branches=max_branches, expires=expires,
        grace_days=grace_days if grace_days is not None else client.grace_days,
        fingerprint=fingerprint, features=features, support=support,
        kind=kind)
    payload['signature'] = lic.sign_payload(payload, _private_pem())

    rec = m.LicenseRecord(
        client_id=client.id, license_id=payload['license_id'], serial=serial,
        kind=kind, payload_signed=payload,
        status='PENDING_APPROVAL' if needs_approval else 'ACTIVE',
        needs_second_approval=needs_approval, over_plan_reason=over,
        issued_by=actor.id, expires_at=expires)
    db.add(rec)
    db.flush()
    if not needs_approval:
        _supersede_others(db, rec)
    vaudit(db, actor_id=actor.id, module='licensing',
           action=f'LICENSE_{kind}', entity='vendor_licenses',
           entity_id=rec.id,
           after={'client': client.code, 'serial': serial,
                  'expires': str(expires), 'status': rec.status,
                  'over_plan': over}, ip=ip)
    return rec


def _supersede_others(db: Session, keep: m.LicenseRecord) -> None:
    others = db.execute(select(m.LicenseRecord).where(
        m.LicenseRecord.client_id == keep.client_id,
        m.LicenseRecord.status == 'ACTIVE',
        m.LicenseRecord.id != keep.id)).scalars().all()
    for o in others:
        o.status = 'SUPERSEDED'
    db.flush()


def approve_license(db: Session, rec: m.LicenseRecord, *,
                    approver: m.VendorUser, ip: str | None = None) -> None:
    """الاعتماد الثاني: شخص مختلف عن المُصدر إلزاماً (ضد العبث الداخلي)."""
    if rec.status != 'PENDING_APPROVAL':
        vdeny('VND.NOT_PENDING', 'هذا الترخيص ليس بانتظار اعتماد', 400)
    if rec.issued_by == approver.id:
        vdeny('VND.SELF_APPROVAL',
              'مكافحة العبث الداخلي: لا يجوز للمُصدر اعتماد ترخيصه بنفسه',
              400)
    rec.status = 'ACTIVE'
    rec.approved_by = approver.id
    rec.approved_at = vnow()
    db.flush()
    _supersede_others(db, rec)
    vaudit(db, actor_id=approver.id, module='licensing',
           action='LICENSE_SECOND_APPROVAL', entity='vendor_licenses',
           entity_id=rec.id,
           after={'approved_serial': rec.serial,
                  'over_plan_reason': rec.over_plan_reason}, ip=ip)


def make_revocation_list(db: Session, *, actor: m.VendorUser,
                         entries: list, ip: str | None = None
                         ) -> m.RevocationListRec:
    serial = int(db.execute(select(func.max(
        m.RevocationListRec.revocation_serial))).scalar() or 0) + 1
    payload = {'kind': 'REVOCATION_LIST', 'revocation_serial': serial,
               'issued_at': vnow().isoformat(), 'entries': entries,
               'nonce': os.urandom(16).hex()}
    payload['signature'] = lic.sign_payload(payload, _private_pem())
    rec = m.RevocationListRec(revocation_serial=serial, payload=payload,
                              issued_by=actor.id)
    db.add(rec)
    db.flush()
    vaudit(db, actor_id=actor.id, module='licensing',
           action='REVOCATION_LIST_PUBLISH', entity='vendor_revocations',
           entity_id=rec.id, after={'serial': serial, 'entries': entries},
           ip=ip)
    return rec


def latest_active_license(db: Session, client: m.Client
                          ) -> m.LicenseRecord | None:
    return db.execute(select(m.LicenseRecord).where(
        m.LicenseRecord.client_id == client.id,
        m.LicenseRecord.status == 'ACTIVE')
        .order_by(m.LicenseRecord.serial.desc()).limit(1)
        ).scalar_one_or_none()


def renew_after_collection(db: Session, client: m.Client,
                           invoice: m.SubscriptionInvoice, *,
                           actor_id: str, ip: str | None = None
                           ) -> m.LicenseRecord:
    """قبول §8-1: سداد فاتورة تجديد ← ترخيص جديد يتاح للعميل فوراً
    (هجين ≤ 5 دقائق عبر Edge؛ محلي: ملف جاهز للتنزيل)."""
    actor = db.get(m.VendorUser, actor_id)
    rec = issue_license(db, client, actor=actor, kind='RENEW',
                        modules=client.modules,
                        max_users=int((client.contacts or {}).get(
                            'licensed_users', 10)),
                        max_branches=max(1, client.branches_count),
                        expires=invoice.period_to,
                        grace_days=client.grace_days,
                        fingerprint=None, features=None,
                        support=(client.contacts or {}).get('support_level',
                                                             'STANDARD'),
                        auto_approve=True,  # التجديد الآلي ضمن الخطة = بلا إيقاف
                        ip=ip)
    n = m.Notification(role='LIC_OPERATOR', kind='LICENSE_AUTO_RENEWED',
                       payload={'client': client.code,
                                'serial': rec.serial,
                                'expires': str(invoice.period_to),
                                'invoice': invoice.number})
    db.add(n)
    db.flush()
    return rec
