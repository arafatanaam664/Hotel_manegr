"""الأمن: تجزئة كلمات المرور Argon2id، JWT وصول/تحديث بدوران عائلي، TOTP."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

from .config import get_settings

_ph = PasswordHasher()


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except (VerifyMismatchError, VerificationError):
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(*, user_id: str, tenant_id: str, perms: list[str],
                        branch_ids: list[str], auth_version: int = 0) -> str:
    s = get_settings()
    payload = {
        'sub': user_id, 'tid': tenant_id, 'perms': perms, 'branches': branch_ids,
        'iss': s.jwt_issuer, 'type': 'access', 'av': auth_version,
        'iat': _now(), 'exp': _now() + timedelta(minutes=s.access_token_minutes),
        'jti': str(uuid.uuid4()),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm='HS256')


def decode_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=['HS256'],
                      issuer=s.jwt_issuer)


def new_refresh_token() -> tuple[str, str, str]:
    """يرجع (الرمز الظاهر، بصمته المخزنة، معرف العائلة)."""
    raw = secrets.token_urlsafe(48)
    fp = hashlib.sha256(raw.encode()).hexdigest()
    return raw, fp, str(uuid.uuid4())


def refresh_fingerprint(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def utcnow() -> datetime:
    return _now()


def new_uuid() -> str:
    return str(uuid.uuid4())


# ── تشفير بيانات الهوية الشخصية ساكنة (ملف 10 SECURITY_POLICY §Data) ──
def _pii_fernet():
    from cryptography.fernet import Fernet
    import base64
    # اشتقاق 32 بايت من سر JWT — مفاتيح PII تُدار عبر البيئة (BACKEND_PII_KEY لاحقاً)
    raw = hashlib.sha256(get_settings().jwt_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_pii(plain: str) -> str:
    """AT rest encryption لهوية النزيل؛ غير قابلة للبحث عمداً (انظر ADR)."""
    if not plain:
        return ''
    return _pii_fernet().encrypt(plain.encode('utf-8')).decode('ascii')


def decrypt_pii(token: str) -> str:
    if not token:
        return ''
    return _pii_fernet().decrypt(token.encode('ascii')).decode('utf-8')


def mask_id(token: str) -> str:
    """عرض مقنّع: آخر 4 خانات فقط (لا فك كامل في قوائم العرض)."""
    plain = decrypt_pii(token)
    return ('****' + plain[-4:]) if plain else ''
