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
                        branch_ids: list[str]) -> str:
    s = get_settings()
    payload = {
        'sub': user_id, 'tid': tenant_id, 'perms': perms, 'branches': branch_ids,
        'iss': s.jwt_issuer, 'type': 'access',
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
