"""اعتماديات FastAPI: المصادقة والتفويض RBAC (مبدأ الرفض الافتراضي)."""
from datetime import datetime, timezone

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .security import decode_token
from . import models as m

bearer = HTTPBearer(auto_error=True)


class Principal:
    def __init__(self, user: m.User, perms: list[str], branch_ids: list[str]):
        self.user = user
        self.perms = set(perms)
        self.branch_ids = branch_ids

    @property
    def id(self) -> str:
        return self.user.id

    @property
    def tenant_id(self) -> str:
        return self.user.tenant_id

    def has(self, perm: str) -> bool:
        return '*' in self.perms or perm in self.perms


def user_perms(db: Session, user: m.User) -> list[str]:
    if not user.roles:
        return []
    rids = [ur.role_id for ur in user.roles]
    roles = db.execute(select(m.Role).where(m.Role.id.in_(rids))).scalars().all()
    perms: list[str] = []
    for r in roles:
        if '*' in (r.permissions or []):
            return ['*']
        perms.extend(r.permissions or [])
    return sorted(set(perms))


def get_principal(cred: HTTPAuthorizationCredentials = Depends(bearer),
                  db: Session = Depends(get_db)) -> Principal:
    try:
        payload = decode_token(cred.credentials)
    except jwt.PyJWTError:
        raise HTTPException(401, {'error': {'code': 'AUTH.INVALID_TOKEN',
                                            'message_ar': 'رمز غير صالح أو منتهي'}})
    if payload.get('type') != 'access':
        raise HTTPException(401, {'error': {'code': 'AUTH.WRONG_TYPE',
                                            'message_ar': 'نوع الرمز غير صحيح'}})
    user = db.get(m.User, payload.get('sub'))
    if user is None or not user.is_active:
        raise HTTPException(401, {'error': {'code': 'AUTH.USER_INACTIVE',
                                            'message_ar': 'المستخدم غير نشط'}})
    return Principal(user, user_perms(db, user), user.branch_ids or [])


def require_perm(*perms: str):
    def _check(pr: Principal = Depends(get_principal)) -> Principal:
        if '*' in pr.perms or any(pr.has(p) for p in perms):
            return pr
        raise HTTPException(403, {'error': {'code': 'RBAC.FORBIDDEN',
                                            'message_ar': 'صلاحية غير كافية',
                                            'required': list(perms)}})
    return _check


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ''
