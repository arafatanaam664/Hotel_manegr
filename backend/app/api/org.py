"""إدارة الجهة (Tenant): معلومات، مستخدمون وأدوار RBAC (ملف 10)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..audit import audit
from ..db import get_db
from ..deps import Principal, require_perm
from ..security import hash_password, new_uuid, utcnow

router = APIRouter(prefix='/api/org', tags=['org'])


@router.get('/tenant')
def get_tenant(db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('reports.view'))):
    t = db.get(m.Tenant, pr.tenant_id)
    branches = db.execute(
        select(m.Branch).where(m.Branch.tenant_id == pr.tenant_id)).scalars().all()
    return {'id': t.id, 'legal_name': t.legal_name, 'trade_name': t.trade_name,
            'country': t.country, 'base_currency': t.base_currency,
            'timezone': t.timezone, 'status': t.status,
            'branches': [{'id': b.id, 'code': b.code, 'name': b.name}
                         for b in branches]}


@router.get('/roles')
def list_roles(db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('reports.view'))):
    rows = db.execute(
        select(m.Role).where(m.Role.tenant_id == pr.tenant_id)
        .order_by(m.Role.code)).scalars().all()
    return [{'code': r.code, 'name': r.name, 'description': r.description,
             'permissions': r.permissions} for r in rows]


@router.get('/users')
def list_users(db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('settings.manage'))):
    rows = db.execute(
        select(m.User).where(m.User.tenant_id == pr.tenant_id)
        .order_by(m.User.username)).scalars().all()
    return [{'id': u.id, 'username': u.username, 'full_name': u.full_name,
             'is_active': u.is_active, 'mfa_enabled': u.mfa_enabled,
             'last_login_at': u.last_login_at,
             'roles': [ur.role.code for ur in u.roles]} for u in rows]


class CreateUserIn(BaseModel):
    username: str = Field(min_length=2, max_length=60)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role_codes: list[str] = Field(min_length=1)


@router.post('/users', status_code=201)
def create_user(body: CreateUserIn, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('settings.manage'))):
    # القيد الصلب لعدد المستخدمين (ملف 07 §5) — رسالة ترقية واضحة
    from .. import licensing as lic
    lic.enforce_user_limit(db, pr.tenant_id)
    exists = db.execute(
        select(m.User).where(m.User.tenant_id == pr.tenant_id,
                             m.User.username == body.username)).scalar_one_or_none()
    if exists:
        raise HTTPException(409, {'error': {'code': 'ORG.USER_EXISTS',
                                            'message_ar': 'اسم المستخدم مستخدم مسبقاً'}})
    roles = db.execute(
        select(m.Role).where(m.Role.tenant_id == pr.tenant_id,
                             m.Role.code.in_(body.role_codes))).scalars().all()
    if len(roles) != len(set(body.role_codes)):
        raise HTTPException(400, {'error': {'code': 'ORG.UNKNOWN_ROLE',
                                            'message_ar': 'دور غير معروف ضمن القائمة'}})
    u = m.User(id=new_uuid(), tenant_id=pr.tenant_id, username=body.username,
               full_name=body.full_name, password_hash=hash_password(body.password),
               created_at=utcnow())
    db.add(u)
    db.flush()
    for r in roles:
        db.add(m.UserRole(user_id=u.id, role_id=r.id))
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='org', action='user.create', entity='users', entity_id=u.id,
          after={'username': u.username, 'roles': body.role_codes})
    db.commit()
    return {'id': u.id, 'username': u.username}


@router.post('/users/{user_id}/toggle-active')
def toggle_user(user_id: str, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('settings.manage'))):
    u = db.get(m.User, user_id)
    if u is None or u.tenant_id != pr.tenant_id:
        raise HTTPException(404, {'error': {'code': 'GENERAL.NOT_FOUND',
                                            'message_ar': 'المستخدم غير موجود'}})
    if u.id == pr.id:
        raise HTTPException(400, {'error': {'code': 'ORG.SELF_LOCKOUT',
                                            'message_ar': 'لا يمكنك إيقاف حسابك الخاص'}})
    u.is_active = not u.is_active
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='org', action='user.toggle_active', entity='users',
          entity_id=u.id, after={'is_active': u.is_active})
    db.commit()
    return {'id': u.id, 'is_active': u.is_active}
