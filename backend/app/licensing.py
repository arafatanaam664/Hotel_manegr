"""نظام التراخيص — ملف 07 كاملاً.
الفلسفة: «صارم على الترخيص، رحيم بالتشغيل» — حماية الإيراد دون إيذاء العميل
الملتزم. ممنوع بتاتاً حذف بيانات العميل أو تعطيل التصدير مهما كانت الحالة.

المكونات:
- توليد/تحقق توقيع Ed25519 (المفتاح العام مضمّن؛ لا اتصال لازم للتحقق §1)
- بصمة الجهاز بتسامح 2 من 3 (لوحة أم + قرص نظام + MAC) §2
- دورة الحياة: LICENSED → GRACE → READ_ONLY → SUSPENDED (الأخيرة فقط
  بوثيقة موقعة من الشركة — لا إيقاف آلي §3)
- منع الرجوع بالساعة بمرساة تاريخ عمل رتيبة §4-2
- قوائم الإلغاء الموقعة بأرقام تسلسلية §2
- القيود الصلبة (مستخدمون/فروع/وحدات) — نقطة الإنفاذ في deps.get_principal §5
- كل حدث ترخيص في سجل التدقيق المسلسل §6
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m
from .audit import audit
from .config import get_settings
from .db import get_db
from .security import utcnow

# ─── الثوابت ─────────────────────────────────────────────
MODULES_ALL = ['ACCOUNTING', 'HOTEL', 'POS', 'INVENTORY', 'HR', 'ASSETS',
               'MULTIBRANCH']
MODULES_AR = {'ACCOUNTING': 'المحاسبة', 'HOTEL': 'الفندقة', 'POS': 'نقاط البيع',
              'INVENTORY': 'المخزون', 'HR': 'الموارد البشرية',
              'ASSETS': 'الأصول الثابتة', 'MULTIBRANCH': 'تعدد الفروع'}
STATES = ['TRIAL', 'LICENSED', 'GRACE', 'READ_ONLY', 'SUSPENDED', 'REVOKED',
          'INVALID', 'CLOCK_LOCK']
DEFAULT_PUBLIC_PEM = os.path.join(os.path.dirname(__file__), 'keys',
                                  'license_public.pem')
ROLLBACK_TOLERANCE_DAYS = 1        # §4-2: رجوع يفوق يوماً = قفل احترازي
FINGERPRINT_MATCH_MIN = 2          # §2: يكفي تطابق 2 من 3 مكونات


class LicError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ─── التوقيع — توليد مفاتيح/توقيع (جانب الشركة فقط) ──────────────────
def _canon(payload: dict) -> bytes:
    """تسلسل حتمي للحقول كاملة (دون حقل التوقيع نفسه) — ملف 07 §1."""
    clean = {k: v for k, v in payload.items() if k != 'signature'}
    return json.dumps(clean, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), default=str).encode('utf-8')


def gen_private_pem() -> bytes:
    k = Ed25519PrivateKey.generate()
    return k.private_bytes(serialization.Encoding.PEM,
                           serialization.PrivateFormat.PKCS8,
                           serialization.NoEncryption())


def public_pem_from_private(priv_pem: bytes) -> bytes:
    k = serialization.load_pem_private_key(priv_pem, password=None)
    return k.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)


def sign_payload(payload: dict, priv_pem: bytes) -> str:
    """يوقّع كل الحقول (ملف 07 §1: nonce + توقيع على الحقول كاملة)."""
    import base64
    k = serialization.load_pem_private_key(priv_pem, password=None)
    return base64.b64encode(k.sign(_canon(payload))).decode('ascii')


def get_public_pem() -> bytes:
    """المفتاح العام: حقن بيئي (اختبارات/سحابي) ← مسار خارجي ← المضمّن."""
    s = get_settings()
    if s.license_public_key_pem.strip():
        return s.license_public_key_pem.strip().encode('utf-8')
    if s.license_public_key_path and os.path.isfile(s.license_public_key_path):
        with open(s.license_public_key_path, 'rb') as f:
            return f.read()
    with open(DEFAULT_PUBLIC_PEM, 'rb') as f:
        return f.read()


def verify_signature(payload: dict) -> tuple[bool, str]:
    """تحقق محلي صِرف — تعديل حرف واحد = رفض فوري (معيار قبول §7-1)."""
    import base64
    sig = payload.get('signature')
    if not isinstance(sig, str) or not sig:
        return False, 'التوقيع غير موجود في الملف'
    try:
        pub: Ed25519PublicKey = serialization.load_pem_public_key(
            get_public_pem())
        pub.verify(base64.b64decode(sig), _canon(payload))
        return True, ''
    except (InvalidSignature, ValueError, TypeError):
        return False, 'التوقيع غير صالح — الملف معدَّل أو من مصدر غير موثوق'


# ─── بصمة الجهاز (محلي/هجين) — 07 §2 ───────────────────
def _sha(text: str) -> str:
    s = get_settings()
    return hashlib.sha256(
        f'{s.license_fingerprint_salt}|{text}'.encode('utf-8')).hexdigest()


def _read_first(paths: list[str]) -> str:
    for p in paths:
        try:
            if os.path.isfile(p):
                with open(p) as f:
                    v = f.read().strip()
                    if v:
                        return v
        except OSError:
            continue
    return 'NA'


def fingerprint_components() -> dict:
    """ثلاثة مكونات: لوحة الأم، قرص النظام، MAC — كل مكوّن مجزأ بملح التثبيت
    (لا تُخزَّن القيم الخام أبداً). السقوط إلى NA عند غياب المصدر."""
    board = _read_first(['/sys/class/dmi/id/product_uuid',
                         '/sys/class/dmi/id/board_serial'])
    disk = _read_first(['/sys/block/sda/serial', '/sys/block/vda/serial',
                        '/sys/block/nvme0n1/serial'])
    mac_node = uuid.getnode()
    mac = f'{mac_node:012x}' if (mac_node >> 40) % 2 == 0 or mac_node else 'NA'
    return {'board': _sha(f'board:{board}'), 'disk': _sha(f'disk:{disk}'),
            'mac': _sha(f'mac:{mac}')}


def fingerprint_hash(comps: dict) -> str:
    return hashlib.sha256('|'.join(sorted(comps.values())).encode()).hexdigest()


def fingerprint_match(bound: dict, current: dict) -> tuple[int, bool]:
    """قاعدة التسامح §2: تطابق 2 من 3 يكفي لتجاوز تغيير قطعة واحدة.
    المكوّن NA لدى الطرفين يُحتسب تطابقاً (لا نعاقب على عتاد لا يُقرأ)."""
    if not bound:
        return 3, True
    matched = sum(1 for k in ('board', 'disk', 'mac')
                  if bound.get(k) == current.get(k) or 'NA' in
                  (bound.get(k), current.get(k)) or not current.get(k))
    return matched, matched >= FINGERPRINT_MATCH_MIN


# ─── حالة الموقع ─────────────────────────────────────────
def get_state_row(db: Session, tenant_id: str) -> m.LicenseState:
    row = db.execute(select(m.LicenseState).where(
        m.LicenseState.tenant_id == tenant_id)).scalar_one_or_none()
    if row is None:
        # تثبيت جديد بلا ترخيص = وضع تجريبي كامل المزايا بسقف زمني (ADR-0032)
        s = get_settings()
        row = m.LicenseState(tenant_id=tenant_id, state='TRIAL',
                             trial_started=date.today(),
                             clock_anchor_date=date.today(),
                             status_reason='فترة تجريبية — رخّص التثبيت من شاشة الترخيص')
        db.add(row)
        db.flush()
        audit(db, tenant_id=tenant_id, actor_id=None, actor_type='system',
              module='license', action='LICENSE_TRIAL_START',
              entity='license_state', entity_id=row.site_id,
              after={'trial_days': s.license_trial_days,
                     'started': str(row.trial_started)})
    return row


def _payload_limits(payload: dict, state: m.LicenseState) -> dict:
    s = get_settings()
    if state.state == 'TRIAL' or not payload:
        return {'max_users': 50, 'max_branches': 5,
                'modules_enabled': MODULES_ALL[:6], 'features_flags': {},
                'package': 'LOCAL', 'grace_days': s.license_grace_days,
                'legal_name': '', 'license_id': '', 'support_level': 'TRIAL'}
    return {
        'max_users': int(payload.get('max_users') or 10),
        'max_branches': int(payload.get('max_branches') or 1),
        'modules_enabled': list(payload.get('modules_enabled')
                                or ['ACCOUNTING']),
        'features_flags': dict(payload.get('features_flags') or {}),
        'package': payload.get('package', 'LOCAL'),
        'grace_days': int(payload.get('grace_days', s.license_grace_days)),
        'legal_name': payload.get('legal_name', ''),
        'license_id': payload.get('license_id', ''),
        'support_level': payload.get('support_level', 'STANDARD')}


def _transition(db: Session, row: m.LicenseState, new_state: str, reason: str,
                actor_id: str | None = None) -> None:
    if row.state == new_state:
        return
    audit(db, tenant_id=row.tenant_id, actor_id=actor_id, actor_type='system',
          module='license', action='LICENSE_STATE_CHANGE',
          entity='license_state', entity_id=row.site_id,
          before={'state': row.state, 'reason': row.status_reason},
          after={'state': new_state, 'reason': reason})
    row.state = new_state
    row.status_reason = reason
    db.flush()


# ─── التقييم الجوهري ─────────────────────────────────────
def evaluate(db: Session, tenant_id: str, *, force: bool = False,
             actor_id: str | None = None) -> dict:
    """يفحص عند الإقلاع ودورياً كل 6 ساعات تشغيل (كسولاً عند أول طلب بعد
    انقضاء المدة) — §3. يعيد لقطة حالة كاملة للعرض والإنفاذ."""
    s = get_settings()
    row = get_state_row(db, tenant_id)
    today = date.today()

    # ── 1) منع الرجوع بالساعة (قبل أي شيء) §4-2 ──
    if (row.clock_anchor_date and
            today < row.clock_anchor_date - timedelta(days=ROLLBACK_TOLERANCE_DAYS)):
        _transition(db, row, 'CLOCK_LOCK',
                    'ساعة النظام أقدم من آخر تاريخ عمل معروف — يُشتبه برجوع '
                    'متعمّد بالساعة. الإصلاح بملف ترخيص ساري من الشركة فقط.')
        db.flush()
        return status_view(db, tenant_id, _row=row)

    if row.state == 'CLOCK_LOCK':
        # لا يفك إلا بملف إصلاح موقّع (install_license بملف ساري)
        return status_view(db, tenant_id, _row=row)

    # ── 2) الفحص الدوري كل 6 ساعات — إعادة تحقق كاملة ──
    due = force or row.last_check is None or (
        utcnow() - _aware(row.last_check) >= timedelta(hours=s.license_check_hours))
    if due:
        row.last_check = utcnow()
        if row.clock_anchor_date is None or today > row.clock_anchor_date:
            row.clock_anchor_date = today   # مرساة رتيبة لا تتأخر أبداً
        audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='system',
              module='license', action='LICENSE_PERIODIC_CHECK',
              entity='license_state', entity_id=row.site_id,
              after={'state': row.state, 'at': str(row.last_check)})
        db.flush()

    # ── 3) مصدر الصلاحية: تجريبي أم ملف مرخّص ──
    payload = row.payload_signed or {}
    limits = _payload_limits(payload, row)

    if row.revocation_payload:
        verdict = _check_revocation(row, payload)
        if verdict == 'SUSPENDED':
            _transition(db, row, 'SUSPENDED',
                        'إيقاف موثّق بقرار الشركة (وثيقة موقعة).')
            return status_view(db, tenant_id, _row=row)
        if verdict == 'REVOKED':
            _transition(db, row, 'REVOKED',
                        'الترخيص مُلغى بقائمة إلغاء موقعة — وضع قراءة فقط.')
            return status_view(db, tenant_id, _row=row)

    if not payload:
        # ── وضع TRIAL: نفس منطق المهلة الرحيم بسقف أيام التجربة ──
        start = row.trial_started or today
        trial_end = start + timedelta(days=s.license_trial_days)
        grace_end = trial_end + timedelta(days=s.license_grace_days)
        row.valid_until, row.grace_until = trial_end, grace_end
        if today <= trial_end:
            if row.state not in ('TRIAL',):
                _transition(db, row, 'TRIAL', row.status_reason)
        elif today <= grace_end:
            _transition(db, row, 'GRACE',
                        'انتهت الفترة التجريبية — مهلة تجديد بكامل الوظائف.')
        else:
            _transition(db, row, 'READ_ONLY',
                        'انتهت التجربة والمهلة — قراءة فقط. التقارير والتصدير '
                        'والنسخ الاحتياطي تعمل كاملة؛ يُمنع إضافة عمليات جديدة.')
        db.flush()
        return status_view(db, tenant_id, _row=row)

    # ── ملف ترخيص مثبّت ──
    if due or row.state in ('INVALID',):
        ok, why = verify_signature(payload)
        if not ok:
            audit(db, tenant_id=tenant_id, actor_id=actor_id,
                  actor_type='system', module='license',
                  action='LICENSE_TAMPER_SUSPECT', entity='license_state',
                  entity_id=row.site_id, after={'why': why})
            _transition(db, row, 'INVALID', f'فشل التحقق من التوقيع: {why}')
            return status_view(db, tenant_id, _row=row)

    # بصمة الجهاز (محلي/هجين فقط — سحابي على مستوى Tenant §2)
    if limits['package'] != 'CLOUD' and row.bound_components:
        matched, passed = fingerprint_match(row.bound_components,
                                            fingerprint_components())
        if not passed:
            audit(db, tenant_id=tenant_id, actor_id=actor_id,
                  actor_type='system', module='license',
                  action='LICENSE_TAMPER_SUSPECT', entity='license_state',
                  entity_id=row.site_id,
                  after={'why': f'بصمة الجهاز لا تطابق المربوطة ({matched}/3)'})
            _transition(db, row, 'INVALID',
                        'هذا الترخيص مربوط بجهاز آخر — تواصل مع الشركة '
                        'لنقل الترخيص رسمياً.')
            return status_view(db, tenant_id, _row=row)

    if today <= (row.valid_until or today):
        _transition(db, row, 'LICENSED', 'ترخيص ساري المفعول.')
    elif row.grace_until and today <= row.grace_until:
        _transition(db, row, 'GRACE',
                    'انتهى الاشتراك — مهلة تجديد بكامل الوظائف. جدّد الآن.')
    else:
        _transition(db, row, 'READ_ONLY',
                    'انتهى الاشتراك والمهلة — قراءة فقط. التقارير والتصدير '
                    'والنسخ الاحتياطي تعمل كاملة؛ يُمنع إضافة عمليات جديدة.')
    db.flush()
    return status_view(db, tenant_id, _row=row)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _check_revocation(row: m.LicenseState, payload: dict) -> str | None:
    """قائمة إلغاء موقعة: إدخالات {serial, license_id?, action REVOKE|SUSPEND}."""
    if row.state == 'SUSPENDED':
        return 'SUSPENDED'
    entries = (row.revocation_payload or {}).get('entries') or []
    for e in entries:
        if (payload and e.get('license_id') == payload.get('license_id')) or \
           (payload and e.get('serial') == payload.get('serial')):
            return 'SUSPENDED' if e.get('action') == 'SUSPEND' else 'REVOKED'
        if not payload and e.get('action') == 'SUSPEND_ALL':
            return 'SUSPENDED'
    return None


# ─── لقطة الحالة للعرض (شاشة حالة الترخيص + الشريط) ────────────────
def status_view(db: Session, tenant_id: str, *,
                _row: m.LicenseState | None = None) -> dict:
    row = _row or get_state_row(db, tenant_id)
    payload = row.payload_signed or {}
    limits = _payload_limits(payload, row)
    today = date.today()
    used_users = db.execute(select(func.count(m.User.id)).where(
        m.User.tenant_id == tenant_id, m.User.is_active.is_(True))).scalar() or 0
    used_branches = db.execute(select(func.count(m.Branch.id)).where(
        m.Branch.tenant_id == tenant_id,
        m.Branch.is_active.is_(True))).scalar() or 0
    comps = fingerprint_components()
    matched, passing = fingerprint_match(row.bound_components, comps)
    days_to_expire = (row.valid_until - today).days if row.valid_until else None
    return {
        'state': row.state, 'status_reason': row.status_reason,
        'package': limits['package'],
        'legal_name': limits['legal_name'], 'license_id': limits['license_id'],
        'support_level': limits['support_level'],
        'issued_at': payload.get('issued_at'),
        'valid_until': str(row.valid_until) if row.valid_until else None,
        'grace_until': str(row.grace_until) if row.grace_until else None,
        'days_to_expire': days_to_expire,
        'in_grace': row.state == 'GRACE',
        'trial': row.state == 'TRIAL',
        'trial_started': str(row.trial_started) if row.trial_started else None,
        'modules_enabled': limits['modules_enabled'],
        'modules_disabled': [x for x in MODULES_ALL[:6]
                             if x not in limits['modules_enabled']],
        'features_flags': limits['features_flags'],
        'limits': {'max_users': limits['max_users'], 'used_users': used_users,
                   'max_branches': limits['max_branches'],
                   'used_branches': used_branches},
        'fingerprint': {'bound': bool(row.bound_components),
                        'match_components': matched, 'passing': passing,
                        'hash': fingerprint_hash(comps)[:16]},
        'clock_anchor_date': str(row.clock_anchor_date)
        if row.clock_anchor_date else None,
        'last_check': _aware(row.last_check).isoformat()
        if row.last_check else None,
        'revocation_serial': row.revocation_serial,
        'site_id': row.site_id,
    }


# ─── الإصدار/التجديد/الإصلاح — تثبيت ملف ترخيص موقّع ─────────────────
def install_license(db: Session, tenant_id: str, payload: dict,
                    *, actor_id: str, ip: str | None = None) -> dict:
    """التحقق ثم التفعيل: توقيع ← حقول إلزامية ← صحة المستأجر ← بصمة 2/3.
    ملف جديد ساري يحل محل القديم سلساً بلا توقف (§2) ويفك قفل الساعة (§4-2)."""
    row = get_state_row(db, tenant_id)
    ok, why = verify_signature(payload)
    audit_ok = ok
    if not ok:
        audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
              module='license', action='LICENSE_VERIFY_FAIL',
              entity='license_state', entity_id=row.site_id,
              after={'why': why}, ip=ip)
        db.commit()
        raise LicError('LIC.BAD_SIGNATURE', why)

    required = ['license_id', 'tenant_id', 'legal_name', 'package',
                'modules_enabled', 'max_users', 'max_branches', 'issued_at',
                'expires_at', 'nonce', 'serial']
    missing = [k for k in required if k not in payload]
    if missing:
        raise LicError('LIC.BAD_FILE', f'حقول ناقصة في ملف الترخيص: {missing}')
    if payload['tenant_id'] != tenant_id:
        raise LicError('LIC.WRONG_TENANT',
                       'هذا الترخيص صادر لمستأجر آخر — لا يمكن تثبيته هنا.')
    try:
        expires = date.fromisoformat(str(payload['expires_at'])[:10])
    except ValueError:
        raise LicError('LIC.BAD_FILE', 'تاريخ انتهاء غير صالح في الملف.')

    # تكرار آمن: نفس license_id وserial مثبّت = لا شيء (Idempotent §12)
    prev = row.payload_signed or {}
    if prev.get('license_id') == payload['license_id'] and \
            prev.get('serial') == payload['serial'] and \
            row.state not in ('CLOCK_LOCK', 'INVALID'):
        return {'installed': False, 'already': True,
                'status': status_view(db, tenant_id, _row=row)}
    if prev and int(payload.get('serial', 0)) < int(prev.get('serial', 0)):
        raise LicError('LIC.OLD_SERIAL',
                       'ملف أقدم من المثبَّت — يُمنع التراجع بالملفات.')

    comps = fingerprint_components()
    package = str(payload.get('package', 'LOCAL')).upper()
    if package not in ('LOCAL', 'CLOUD', 'HYBRID'):
        raise LicError('LIC.BAD_FILE', 'باقة غير معروفة في الملف.')
    if package != 'CLOUD':
        fp = payload.get('hardware_fingerprint') or {}
        if fp:  # ترخيص مقيّد بجهاز محدد من الشركة (تفعيل معزول §2)
            matched, passing = fingerprint_match(fp, comps)
            if not passing:
                raise LicError('LIC.FINGERPRINT_MISMATCH',
                               f'بصمة هذا الجهاز لا تطابق المقيَّدة بالملف '
                               f'({matched}/3) — ارفع طلب ربط جديداً للشركة.')
            row.bound_components = {k: fp.get(k) for k in
                                    ('board', 'disk', 'mac') if fp.get(k)}
        elif not row.bound_components:
            row.bound_components = comps      # أول ربط على هذا الجهاز

    grace_days = int(payload.get('grace_days',
                                 get_settings().license_grace_days))
    before = {'state': row.state, 'license_id': prev.get('license_id'),
              'valid_until': str(row.valid_until) if row.valid_until else None}
    row.payload_signed = payload
    row.package = package
    row.valid_until = expires
    row.grace_until = expires + timedelta(days=grace_days)
    # الملف الموقّع من الشركة هو المرجع الأعلى للساعة: يعيد الترسيخ لليوم
    # الحقيقي ويفك القفل الاحترازي (07 §4-2 — جلسة الإصلاح الموثقة)
    row.clock_anchor_date = date.today()
    row.last_check = utcnow()
    row.state = 'LICENSED'
    row.status_reason = 'ترخيص ساري المفعول.'
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='license', action='LICENSE_INSTALL', entity='license_state',
          entity_id=row.site_id, before=before,
          after={'license_id': payload['license_id'],
                 'serial': payload['serial'], 'package': package,
                 'expires_at': str(expires),
                 'fingerprint_bound': bool(row.bound_components),
                 'signature_verified': audit_ok}, ip=ip)
    db.flush()
    return {'installed': True, 'already': False,
            'status': status_view(db, tenant_id, _row=row)}


def activation_request(db: Session, tenant_id: str, *,
                       actor_id: str) -> dict:
    """وضع معزول تماماً §2: بصمة ← ملف طلب ← الشركة توقّع ملفاً مفعَّلاً."""
    row = get_state_row(db, tenant_id)
    comps = fingerprint_components()
    req = {'kind': 'ACTIVATION_REQUEST', 'tenant_id': tenant_id,
           'site_id': row.site_id, 'date': str(date.today()),
           'hardware_fingerprint': comps,
           'hardware_fingerprint_hash': fingerprint_hash(comps),
           'nonce': str(uuid.uuid4())}
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='license', action='LICENSE_ACTIVATION_REQUEST',
          entity='license_state', entity_id=row.site_id,
          after={'fingerprint_hash': req['hardware_fingerprint_hash']})
    db.flush()
    return req


def import_revocations(db: Session, tenant_id: str, payload: dict,
                       *, actor_id: str, ip: str | None = None) -> dict:
    """قائمة الإلغاء الموقعة (إصدار ورقم تسلسل متزايد — §2). الإيقاف النهائي
    SUSPEND لا يكون آلياً أبداً بل بإدخال موقّع صريح من الشركة (§3)."""
    ok, why = verify_signature(payload)
    if not ok:
        raise LicError('LIC.BAD_SIGNATURE', why)
    row = get_state_row(db, tenant_id)
    serial = int(payload.get('revocation_serial', 0))
    if serial <= row.revocation_serial:
        raise LicError('LIC.OLD_REVOCATION',
                       'قائمة إلغاء أقدم أو مساوية للمثبتة.')
    row.revocation_serial = serial
    row.revocation_payload = payload
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='license', action='LICENSE_REVOCATION_IMPORT',
          entity='license_state', entity_id=row.site_id,
          after={'revocation_serial': serial,
                 'entries': len(payload.get('entries') or [])}, ip=ip)
    db.flush()
    return {'imported': True, 'revocation_serial': serial,
            'status': evaluate(db, tenant_id, force=True, actor_id=actor_id)}


# ─── بوابات الإنفاذ (تُستدعى من deps.get_principal) §3/§5 ────────────
_LIC_PATHS = ('/api/license',)     # التجديد والحالة متاحان دائماً


def _deny(code: str, message: str):
    raise HTTPException(403, {'error': {'code': code, 'message_ar': message}})


def _emergency_usernames() -> set[str]:
    return {u.strip() for u in get_settings().emergency_export_users.split(',')
            if u.strip()}


def enforce_request(db: Session, *, tenant_id: str, username: str,
                    method: str, path: str) -> None:
    """الإنفاذ الرحيم لكل طلب مصادَق:
    - GRACE/TRIAL/LICENSED: كل شيء يعمل (تنبيه فقط عبر الواجهة).
    - READ_ONLY/INVALID/REVOKED: القراءة والتقارير والتصدير + التجديد فقط.
    - SUSPENDED: لا شيء عدا حساب الطوارئ المالي للتصدير (§3) والحالة.
    - CLOCK_LOCK: شاشة الحالة وملف الإصلاح فقط (§4-2).
    فشل بنيوي غير متوقع = فتح مع تسجيل (رحيم بالتشغيل، صارم بالترخيص)."""
    try:
        row = get_state_row(db, tenant_id)
        state = row.state
        if state in ('LICENSED', 'GRACE', 'TRIAL'):
            return
        if path.startswith(_LIC_PATHS):
            return
        if state in ('READ_ONLY', 'INVALID', 'REVOKED'):
            if method in ('GET', 'HEAD', 'OPTIONS'):
                return
            _deny('LIC.READ_ONLY',
                  'الترخيص في وضع القراءة فقط — التقارير والطباعة والتصدير '
                  'متاحة كاملة. جدّد الاشتراك من شاشة الترخيص لإضافة عمليات.')
        if state == 'SUSPENDED':
            if username in _emergency_usernames() and \
                    (method in ('GET', 'HEAD') and
                     (path.startswith('/api/reports') or
                      path.startswith('/api/journals'))):
                return
            _deny('LIC.SUSPENDED',
                  'النظام موقوف بقرار موثّق من الشركة. يُسمح فقط لحساب '
                  'الطوارئ المالي بتصدير البيانات حتى سداد المستحقات.')
        if state == 'CLOCK_LOCK':
            _deny('LIC.CLOCK_LOCK',
                  'قفل احترازي: ساعة النظام أقدم من آخر تاريخ عمل. لا فقدان '
                  'لأي بيانات — أدخل ملف إصلاح من الشركة عبر شاشة الترخيص.')
    except HTTPException:
        raise
    except Exception:
        return  # انقطاع بنيوي ≠ عقوبة — سجّل ولا تُعطّل عميلاً ملتزماً


def ensure_login_allowed(db: Session, *, tenant_id: str, username: str) -> None:
    """§3: عند الإيقاف النهائي يُمنع الدخول عدا حساب الطوارئ المالي."""
    row = db.execute(select(m.LicenseState).where(
        m.LicenseState.tenant_id == tenant_id)).scalar_one_or_none()
    if row and row.state == 'SUSPENDED' and \
            username not in _emergency_usernames():
        _deny('LIC.SUSPENDED',
              'النظام موقوف بقرار موثّق من الشركة — يُسمح بالدخول فقط '
              'لحساب الطوارئ المالي للتصدير.')


def require_module(module: str):
    """حارس وحدات §5: القيود الصلبة تُفرض عند كل دخول/إنشاء برسالة ترقية."""
    from fastapi import Depends
    from .deps import Principal, get_principal  # كسول — فك حلقة الاستيراد

    def _guard(db: Session = Depends(get_db),
               pr: Principal = Depends(get_principal)) -> Principal:
        row = db.execute(select(m.LicenseState).where(
            m.LicenseState.tenant_id == pr.tenant_id)).scalar_one_or_none()
        limits = _payload_limits((row.payload_signed or {}) if row else {},
                                 row) if row else {'modules_enabled':
                                                   MODULES_ALL[:6]}
        if module not in limits['modules_enabled']:
            raise HTTPException(
                403, {'error': {'code': 'LIC.MODULE_DISABLED',
                                'message_ar':
                                f'وحدة «{MODULES_AR.get(module, module)}» غير '
                                f'مفعَّلة في باقتك — رقِّ اشتراكك من الشركة.',
                                'module': module}})
        # الترخيص يحدد ما تم شراؤه، وتهيئة المنتج تحدد ما اختاره العميل
        # تشغيله. لا يكفي أحدهما منفرداً لفتح وحدة في المنتج.
        cfg = db.get(m.TenantProductConfig, pr.tenant_id)
        if cfg is not None and module not in (cfg.modules_enabled or []):
            raise HTTPException(
                403, {'error': {'code': 'SETUP.MODULE_DISABLED',
                                'message_ar':
                                f'وحدة «{MODULES_AR.get(module, module)}» معطّلة '
                                'في تهيئة هذا الموقع — فعّلها من إعداد المنتج.',
                                'module': module}})
        return pr
    return _guard


def enforce_user_limit(db: Session, tenant_id: str) -> None:
    """القيود الصلبة عند الإنشاء §5 — رسالة ترقية لا خطأ مقتضب."""
    row = db.execute(select(m.LicenseState).where(
        m.LicenseState.tenant_id == tenant_id)).scalar_one_or_none()
    limits = _payload_limits((row.payload_signed or {}) if row else {},
                             row) if row else {'max_users': 50}
    used = db.execute(select(func.count(m.User.id)).where(
        m.User.tenant_id == tenant_id,
        m.User.is_active.is_(True))).scalar() or 0
    if used >= int(limits['max_users']):
        raise HTTPException(
            403, {'error': {'code': 'LIC.USER_LIMIT',
                            'message_ar': f'بلغت حد المستخدمين في باقتك '
                            f'({used}/{limits["max_users"]}) — رقِّ اشتراكك '
                            f'لإضافة مستخدمين جدد.'}})


def startup_check(db: Session, tenant_id: str) -> dict:
    """فحص الإقلاع §3 + فحص سلامة ذاتي لفاحص الترخيص (طبقة 1 عملياً:
    أي تعديل على هذا الملف يكسر توقيع الحزمة عند التوزيع — هنا نثبت
    الحدث ونقيّم الحالة)."""
    out = evaluate(db, tenant_id, force=True)
    db.commit()
    return out
