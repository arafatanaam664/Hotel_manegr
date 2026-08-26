"""أمن اللوحة (ملف 08 §7): JWT مستقل + MFA إلزامي (TOTP) + أقل امتياز.
الدعم لا يرى مفاتيح التوقيع، والمالية لا تعدّل تذاكر الدعم — حرفياً."""
from datetime import datetime, timedelta, timezone

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .config import get_vendor_settings
from .db import get_vdb

_ph = PasswordHasher()
_bearer = HTTPBearer(auto_error=True)

ROLE_AR = {'DIRECTOR': 'مدير الشركة', 'SALES': 'مبيعات', 'FINANCE': 'مالية',
           'SUPPORT_L1': 'دعم L1', 'SUPPORT_L2': 'دعم L2',
           'LIC_OPERATOR': 'مشغّل تراخيص'}

# مصفوفة أقل امتياز (§7) — الدور ← الأفعال المسموحة
ROLE_PERMS = {
    'DIRECTOR': {'*'},
    'SALES': {'clients.view', 'clients.manage', 'invoices.create',
              'tickets.view', 'revenue.view'},
    'FINANCE': {'clients.view', 'invoices.view', 'invoices.issue',
                'collections.manage', 'revenue.view', 'licenses.view'},
    'SUPPORT_L1': {'clients.view', 'tickets.view', 'tickets.work',
                   'health.view'},
    'SUPPORT_L2': {'clients.view', 'tickets.view', 'tickets.work',
                   'tickets.escalate', 'tickets.close', 'health.view',
                   'releases.view'},
    'LIC_OPERATOR': {'clients.view', 'licenses.view', 'licenses.issue',
                     'licenses.revoke', 'fingerprints.view', 'health.view'},
}


def vdeny(code: str, msg: str, status: int = 403):
    raise HTTPException(status, {'error': {'code': code, 'message_ar': msg}})


class VPrincipal:
    def __init__(self, user: m.VendorUser):
        self.user = user

    @property
    def id(self) -> str:
        return self.user.id

    @property
    def role(self) -> str:
        return self.user.role

    def has(self, perm: str) -> bool:
        perms = ROLE_PERMS.get(self.user.role, set())
        return '*' in perms or perm in perms


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except VerifyMismatchError:
        return False


def create_token(*, user_id: str, kind: str = 'access',
                 minutes: int | None = None) -> str:
    s = get_vendor_settings()
    mins = minutes if minutes is not None else s.access_token_minutes
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {'sub': user_id, 'type': kind, 'iss': s.jwt_issuer,
         'iat': now, 'exp': now + timedelta(minutes=mins)},
        s.jwt_secret, algorithm='HS256')


def decode_token(token: str) -> dict:
    s = get_vendor_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=['HS256'],
                      issuer=s.jwt_issuer)


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_ok(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code.strip().replace(' ', ''),
                                     valid_window=1)


def get_vprincipal(cred: HTTPAuthorizationCredentials = Depends(_bearer),
                   db: Session = Depends(get_vdb)) -> VPrincipal:
    try:
        payload = decode_token(cred.credentials)
    except jwt.PyJWTError:
        vdeny('VND.INVALID_TOKEN', 'رمز غير صالح أو منتهي', 401)
    if payload.get('type') != 'access':
        vdeny('VND.WRONG_TYPE', 'نوع الرمز غير صحيح', 401)
    user = db.get(m.VendorUser, payload.get('sub'))
    if user is None or not user.is_active:
        vdeny('VND.USER_INACTIVE', 'المستخدم غير نشط', 401)
    # §7: MFA إلزامي بلا استثناء — لا وصول قبل إكمال التسجيل
    s = get_vendor_settings()
    if s.mfa_required and not user.mfa_enabled:
        vdeny('VND.MFA_ENROLL_REQUIRED',
              'يجب تفعيل التحقق الثنائي أولاً (إلزامي لكل مستخدمي الشركة)',
              401)
    return VPrincipal(user)


def require_perm(*perms: str):
    def _check(pr: VPrincipal = Depends(get_vprincipal)) -> VPrincipal:
        if any(pr.has(p) for p in perms):
            return pr
        vdeny('VND.FORBIDDEN',
              f'صلاحية غير كافية — يتطلب: {" أو ".join(perms)}')
    return _check


def authenticate_edge(db: Session, client_code: str, token: str
                      ) -> m.Client:
    """واجهة العميل المحدودة (§1): رمز Edge الخاص بالعميل فقط — لا أكثر."""
    c = db.execute(select(m.Client).where(
        m.Client.code == client_code)).scalar_one_or_none()
    if c is None or not c.edge_token or c.edge_token != token:
        vdeny('EDGE.AUTH', 'رمز واجهة العميل غير صالح', 401)
    return c
