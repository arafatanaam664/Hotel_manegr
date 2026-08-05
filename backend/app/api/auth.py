"""الهوية والجلسات — ملف 10 (SECURITY_POLICY):
- قفل الحساب بعد 5 محاولات فاشلة لمدة 10 دقائق
- رموز تحديث دوّارة بعائلات مع كشف إعادة الاستخدام (سرقة رمز ← إلغاء العائلة كلها)
- كل حدث مصادقة يُسجَّل في سجل التدقيق المقيَّد بالتجزئة"""
from datetime import timedelta, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..audit import audit
from ..config import get_settings
from ..db import get_db
from ..deps import Principal, get_principal, user_perms
from ..schemas import LoginIn, MeOut, RefreshIn, TokenPair, UserOut
from ..security import (create_access_token, new_refresh_token, new_uuid,
                        refresh_fingerprint, utcnow, verify_password)

router = APIRouter(prefix='/api/auth', tags=['auth'])

MAX_FAILED = 5
LOCK_MINUTES = 10


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite يعيد datetime بلا منطقة زمنية — نعامله كـ UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _err(status: int, code: str, message_ar: str):
    raise HTTPException(status, {'error': {'code': code, 'message_ar': message_ar}})


def _pick_user(db: Session, username: str, tenant_code: str | None) -> m.User:
    q = select(m.User).where(m.User.username == username)
    users = db.execute(q).scalars().all()
    if not users:
        _err(401, 'AUTH.INVALID_CREDENTIALS', 'بيانات الدخول غير صحيحة')
    if len(users) > 1:
        # بيئة متعددة المستأجرين: يجب تحديد رمز المستأجر
        if tenant_code:
            for u in users:
                if u.tenant_id == tenant_code:
                    return u
        _err(400, 'AUTH.TENANT_REQUIRED', 'حدد الجهة (المستأجر) لتسجيل الدخول')
    return users[0]


def _issue_pair(db: Session, user: m.User, request: Request,
                family_id: str | None = None) -> TokenPair:
    s = get_settings()
    perms = user_perms(db, user)
    access = create_access_token(user_id=user.id, tenant_id=user.tenant_id,
                                 perms=perms, branch_ids=user.branch_ids or [])
    raw, fp, fam = new_refresh_token()
    if family_id:  # دوران داخل نفس العائلة
        fam = family_id
    db.add(m.RefreshSession(
        id=new_uuid(),
        user_id=user.id, tenant_id=user.tenant_id, family_id=fam,
        fingerprint_hash=fp,
        device_info=(request.headers.get('user-agent') or '')[:290],
        ip=request.client.host if request.client else '',
        issued_at=utcnow(),
        expires_at=utcnow() + timedelta(days=s.refresh_token_days)))
    roles = [ur.role.code for ur in user.roles]
    return TokenPair(
        access_token=access, refresh_token=raw,
        expires_in=s.access_token_minutes * 60,
        user=UserOut(id=user.id, username=user.username,
                     full_name=user.full_name, tenant_id=user.tenant_id,
                     roles=roles, perms=perms,
                     branches=user.branch_ids or []))


@router.post('/login', response_model=TokenPair)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = _pick_user(db, body.username, body.tenant_code)
    now = utcnow()
    if not user.is_active:
        _err(403, 'AUTH.USER_INACTIVE', 'الحساب موقوف — راجع المدير')
    locked = _aware(user.locked_until)
    if locked and locked > now:
        mins = max(1, int((locked - now).total_seconds() // 60) + 1)
        _err(401, 'AUTH.LOCKED',
             f'الحساب مقفل مؤقتاً — أعد المحاولة بعد {mins} دقيقة')
    if not verify_password(body.password, user.password_hash):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= MAX_FAILED:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_attempts = 0
        audit(db, tenant_id=user.tenant_id, actor_id=user.id,
              actor_type='user', module='security', action='auth.login.failed',
              entity='users', entity_id=user.id,
              ip=request.client.host if request.client else '')
        db.commit()
        _err(401, 'AUTH.INVALID_CREDENTIALS', 'بيانات الدخول غير صحيحة')
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    # ملف 07 §3: عند الإيقاف النهائي لا دخول إلا لحساب الطوارئ المالي
    from .. import licensing as lic
    lic.ensure_login_allowed(db, tenant_id=user.tenant_id,
                             username=user.username)
    pair = _issue_pair(db, user, request)
    audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_type='user',
          module='security', action='auth.login.success', entity='users',
          entity_id=user.id,
          ip=request.client.host if request.client else '')
    db.commit()
    return pair


@router.post('/refresh', response_model=TokenPair)
def refresh(body: RefreshIn, request: Request, db: Session = Depends(get_db)):
    fp = refresh_fingerprint(body.refresh_token)
    sess = db.execute(
        select(m.RefreshSession)
        .where(m.RefreshSession.fingerprint_hash == fp)).scalar_one_or_none()
    if sess is None:
        _err(401, 'AUTH.INVALID_REFRESH', 'رمز التحديث غير معروف')
    now = utcnow()
    if sess.revoked_at is not None or sess.reused_detected:
        # إعادة استخدام رمز مُدوَّر = احتمال سرقة ← إلغاء العائلة كاملة
        family = db.execute(
            select(m.RefreshSession)
            .where(m.RefreshSession.family_id == sess.family_id)).scalars().all()
        for s2 in family:
            if s2.revoked_at is None:
                s2.revoked_at = now
            s2.reused_detected = True
        audit(db, tenant_id=sess.tenant_id, actor_id=sess.user_id,
              actor_type='user', module='security', action='auth.refresh.reuse_detected',
              entity='sessions', entity_id=str(sess.id),
              after={'family': sess.family_id},
              ip=request.client.host if request.client else '')
        db.commit()
        _err(401, 'AUTH.REUSE_DETECTED',
             'اكتُشف استخدام مكرر لرمز — أُلغيت الجلسة، سجّل الدخول من جديد')
    if _aware(sess.expires_at) < now:
        _err(401, 'AUTH.REFRESH_EXPIRED', 'انتهت الجلسة — سجّل الدخول من جديد')
    user = db.get(m.User, sess.user_id)
    if user is None or not user.is_active:
        _err(401, 'AUTH.USER_INACTIVE', 'المستخدم غير نشط')
    sess.revoked_at = now  # الرمز القديم يُدوَّر ولا يصلح بعد الآن
    pair = _issue_pair(db, user, request, family_id=sess.family_id)
    db.commit()
    return pair


@router.post('/logout')
def logout(body: RefreshIn, request: Request, db: Session = Depends(get_db)):
    fp = refresh_fingerprint(body.refresh_token)
    sess = db.execute(
        select(m.RefreshSession)
        .where(m.RefreshSession.fingerprint_hash == fp)).scalar_one_or_none()
    if sess is not None and sess.revoked_at is None:
        sess.revoked_at = utcnow()
        audit(db, tenant_id=sess.tenant_id, actor_id=sess.user_id,
              actor_type='user', module='security', action='auth.logout',
              entity='sessions', entity_id=str(sess.id))
        db.commit()
    return {'detail': 'تم تسجيل الخروج'}


@router.get('/me', response_model=MeOut)
def me(pr: Principal = Depends(get_principal)):
    u = pr.user
    return MeOut(id=u.id, username=u.username, full_name=u.full_name,
                 tenant_id=u.tenant_id,
                 roles=[ur.role.code for ur in u.roles],
                 perms=sorted(pr.perms), branches=u.branch_ids or [],
                 mfa_enabled=u.mfa_enabled)
