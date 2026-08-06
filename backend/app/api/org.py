"""إدارة الجهة (Tenant): معلومات، مستخدمون، أدوار مخصصة، استثناءات ونوافذ دوام
(ملف 10 + ADR-0037 — إدارة المستخدمون والصلاحيات الكاملة).

المبادئ الحمراء:
- رفض افتراضي + حارس users.manage على كل فعل إدارة (لا يمسه موظف عادي).
- لا حذف للمستخدمين أبداً (إيقاف فقط) — الإسناد التاريخي مقدّس.
- المالك «*» مقدّس: لا يُحجب ولا يُقِلّ بنفسه، ولا يُترك الفندق بلا مالك نشط.
- كل تغيير موثّق بسلسلة التدقيق (فاعل/قبل/بعد/زمن).
"""
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..audit import audit
from ..db import get_db
from ..deps import Principal, require_perm, user_perms
from ..security import hash_password, new_uuid, utcnow

router = APIRouter(prefix='/api/org', tags=['org'])

MANAGE = 'users.manage'

# ═══ كتالوج الصلاحيات العربي المصنّف — مصدر واجهة الأدوار والاستثناءات ═══
PERMISSION_CATALOG = [
 {'key': 'frontdesk', 'name': 'الفندق — الاستقبال والحجوزات', 'perms': [
  ('frontdesk.view', 'شاشة مكتب الاستقبال (براك الغرف)'),
  ('reservations.view', 'عرض الحجوزات'),
  ('reservations.create', 'إنشاء حجز'),
  ('reservations.modify', 'تعديل حجز'),
  ('reservations.cancel', 'إلغاء حجز'),
  ('guests.view', 'عرض ملفات النزلاء'),
  ('guests.manage', 'إنشاء وتعديل ملفات النزلاء'),
  ('corporates.view', 'عرض الشركات'),
  ('corporates.manage', 'إدارة الشركات وحدود ائتمانها'),
  ('checkin.do', 'تسكين نزيل في غرفة'),
  ('checkin.dirty_override', 'استثناء: تسكين بغرفة غير نظيفة'),
  ('checkout.do', 'إتمام مغادرة وإصدار الفاتورة'),
  ('checkout.credit_transfer', 'تحويل رصيد الفوليو إلى مدينة عامة'),
  ('folio.view', 'عرض الفوليو'),
  ('folio.charge', 'إضافة شحن إلى الفوليو'),
  ('folio.pay', 'تحصيل دفعة على الفوليو'),
  ('folio.discount', 'منح خصم على الفوليو'),
  ('discounts.approve', 'اعتماد خصم فوق الحد المسموح'),
  ('nightaudit.run', 'تشغيل التدقيق الليلي وإقفال يوم العمل'),
 ]},
 {'key': 'rooms', 'name': 'الفندق — الغرف والأسعار والخدمات', 'perms': [
  ('rooms.view', 'عرض الغرف وحالاتها'),
  ('rooms.manage', 'إدارة الغرف والأنواع والأجنحة المركبة'),
  ('hk.cleaning', 'تحديث حالة تنظيف الغرفة'),
  ('hk.manage', 'إدارة الهوسكيبينج والتعطيل (OOO)'),
  ('rates.manage', 'إدارة خطط الأسعار وتقويم الأسعار'),
  ('extras.manage', 'إدارة الخدمات الإضافية'),
 ]},
 {'key': 'pos', 'name': 'نقاط البيع', 'perms': [
  ('pos.view', 'عرض شاشة البيع والطلبات'),
  ('pos.sell', 'تنفيذ عملية بيع وتسديد'),
  ('pos.void', 'إلغاء بند في طلب (مشرف/بسبب)'),
  ('pos.return', 'مرتجع بعد التسديد'),
  ('pos.approve', 'اعتماد مشرف POS بالرقم السري (خصم فوق الحد/مجاني)'),
  ('pos.shift.open', 'فتح وردية صندوق'),
  ('pos.shift.close', 'إقفال وردية وإصدار Z'),
  ('pos.zreport.view', 'عرض تقارير Z الأرشيفية'),
  ('pos.tables.view', 'عرض الطاولات'),
  ('pos.tables.manage', 'إدارة الطاولات'),
  ('pos.catalog.manage', 'إدارة كتالوج البيع (أصناف/أسعار/وصفات)'),
  ('pos.stock.manage', 'إدارة مخزون منفذ البيع'),
  ('pos.reports', 'تقارير مبيعات نقاط البيع'),
 ]},
 {'key': 'inv', 'name': 'المخزون والمشتريات', 'perms': [
  ('inv.view', 'عرض كتالوج المخزون والأرصدة'),
  ('inv.catalog.manage', 'إدارة الأصناف والتصنيفات والوحدات'),
  ('inv.suppliers.manage', 'إدارة الموردين والأسعار التعاقدية'),
  ('inv.pr.create', 'إنشاء طلب شراء'),
  ('inv.pr.approve', 'اعتماد طلب شراء'),
  ('inv.po.create', 'إنشاء/اعتماد أمر شراء (حسب السلّم)'),
  ('inv.grn.manage', 'إنشاء سند استلام GRN'),
  ('inv.grn.reverse', 'عكس سند استلام مرحَّل'),
  ('inv.invoice.create', 'إدخال فاتورة مورد'),
  ('inv.invoice.approve', 'اعتماد فاتورة مورد (مطابقة ثلاثية)'),
  ('inv.pay', 'سداد فواتير الموردين'),
  ('inv.variance.approve', 'اعتماد فرق سعر خارج التسامح'),
  ('inv.transfer.manage', 'تحويلات بين المستودعات'),
  ('inv.issue.create', 'إنشاء سند صرف لقسم'),
  ('inv.issue.approve', 'اعتماد سند صرف'),
  ('inv.waste.create', 'إنشاء سند هالك'),
  ('inv.waste.approve', 'اعتماد سند هالك'),
  ('inv.count.manage', 'جرد دوري (تجميد/عدّ/إقفال)'),
  ('inv.return.manage', 'مرتجع إلى مورد'),
  ('inv.reports', 'تقارير المخزون'),
  ('inv.alerts', 'عرض تنبيهات المخزون'),
  ('inv.policy.manage', 'إدارة سياسة المخزون والتنبيهات'),
 ]},
 {'key': 'hr', 'name': 'الموارد البشرية والرواتب', 'perms': [
  ('hr.view', 'عرض شؤون الموظفين'),
  ('hr.employees.manage', 'إدارة ملفات الموظفين والأقسام والوظائف'),
  ('hr.changes.manage', 'إعداد خطابات التغيير (ترقية/نقل/راتب)'),
  ('hr.changes.approve', 'اعتماد خطابات التغيير'),
  ('hr.attendance.manage', 'رصد الحضور اليومي'),
  ('hr.attendance.approve', 'اعتماد الحضور (شرط الاحتساب)'),
  ('hr.roster.manage', 'إعداد جداول الورديات Roster'),
  ('hr.leave.manage', 'إعداد طلبات الإجازات'),
  ('hr.leave.approve', 'اعتماد الإجازات'),
  ('hr.penalty.manage', 'إعداد الجزاءات التأديبية'),
  ('hr.penalty.approve', 'اعتماد الجزاءات'),
  ('hr.advance.request', 'طلب سلفة'),
  ('hr.advance.approve', 'اعتماد سلفة'),
  ('hr.payroll.prepare', 'تجهيز مسير الرواتب (HR)'),
  ('hr.payroll.approve', 'اعتماد مسير الرواتب (مالية)'),
  ('hr.pay', 'صرف الرواتب'),
  ('hr.policy.manage', 'ضبط سياسة الرواتب والبدلات'),
  ('hr.salary.view', 'عرض الرواتب (غير مقنَّعة)'),
  ('hr.salary.confidential', 'كشف رواتب الأقسام السرية 🔒'),
  ('hr.reports', 'تقارير التوظيف'),
 ]},
 {'key': 'fa', 'name': 'الأصول الثابتة', 'perms': [
  ('fa.view', 'عرض سجل الأصول وجداول الإهلاك'),
  ('fa.manage', 'إدارة الأصول وتشغيل الإهلاك الشهري'),
 ]},
 {'key': 'acct', 'name': 'المحاسبة والمالية', 'perms': [
  ('accounts.view', 'عرض دليل الحسابات'),
  ('accounts.manage', 'إنشاء وتعديل الحسابات'),
  ('journals.view', 'عرض القيود اليومية'),
  ('journals.manual', 'إنشاء قيد يدوي'),
  ('journals.post', 'ترحيل قيد'),
  ('journals.reverse', 'عكس قيد مرحَّل'),
  ('periods.close', 'إقفال الفترات (لين/صلب)'),
  ('periods.adjust', 'قيد تسوية داخل فترة مغلقة ليناً'),
  ('reports.view', 'التقارير والقوائم المالية'),
  ('reports.hotel', 'التقارير التشغيلية الفندقية (إشغال/ADR/RevPAR)'),
 ]},
 {'key': 'system', 'name': 'الإدارة والنظام', 'perms': [
  ('settings.manage', 'إعدادات الجهة والفروع'),
  (MANAGE, 'إدارة المستخدمين والأدوار والصلاحيات'),
  ('audit.view', 'عرض سجل التدقيق وفحص سلسلته'),
  ('license.manage', 'إدارة ملف الترخيص'),
  ('sync.view', 'عرض مركز المزامنة'),
  ('sync.manage', 'إدارة المزامنة (اقتران/دفع/استدراك)'),
  ('demo.run', 'تشغيل بيانات تجريبية (بيئات عرض فقط)'),
 ]},
]
KNOWN_PERMS = {c for g in PERMISSION_CATALOG for c, _ in g['perms']}

_WINDOW_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


class LoginWindow(BaseModel):
    from_: str = Field(alias='from')
    to: str

    @field_validator('from_', 'to')
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _WINDOW_RE.match(v):
            raise ValueError('صيغة الوقت يجب أن تكون HH:MM')
        return v


def _err(status: int, code: str, message_ar: str):
    raise HTTPException(status, {'error': {'code': code,
                                           'message_ar': message_ar}})


def _get_user(db: Session, tenant_id: str, user_id: str) -> m.User:
    u = db.get(m.User, user_id)
    if u is None or u.tenant_id != tenant_id:
        _err(404, 'GENERAL.NOT_FOUND', 'المستخدم غير موجود')
    return u


def _user_is_owner(db: Session, u: m.User) -> bool:
    rids = [ur.role_id for ur in u.roles]
    if not rids:
        return False
    return db.execute(select(m.Role).where(
        m.Role.id.in_(rids), m.Role.permissions.contains('*'))).first() is not None


def _active_owners(db: Session, tenant_id: str) -> int:
    cnt = 0
    for u in db.execute(select(m.User).where(
            m.User.tenant_id == tenant_id, m.User.is_active.is_(True))).scalars():
        if _user_is_owner(db, u):
            cnt += 1
    return cnt


def _guard_last_owner(db: Session, u: m.User, removing: bool):
    """استحالة ترك الفندق بلا مالك «*» نشط (ORG.LAST_OWNER).
    يعنى فقط بإنقاص عدّاد المالكين «النشطين»: هدف موقوف أصلاً لا يغيّر العدّاد."""
    if (removing and u.is_active and _user_is_owner(db, u)
            and _active_owners(db, u.tenant_id) <= 1):
        _err(409, 'ORG.LAST_OWNER',
             'لا يمكن سحب/إيقاف آخر مالك صلاحيات كاملة نشط في المنشأة')


def _revoke_sessions(db: Session, u: m.User) -> int:
    now = utcnow()
    n = 0
    for s in db.execute(select(m.RefreshSession).where(
            m.RefreshSession.user_id == u.id,
            m.RefreshSession.revoked_at.is_(None))).scalars():
        s.revoked_at = now
        n += 1
    # قتل رموز الوصول القائمة فوراً أيضاً (لا انتظار 15 دقيقة)
    u.auth_version = (u.auth_version or 0) + 1
    return n


def _roles_by_codes(db: Session, tenant_id: str, codes: list[str]) -> list[m.Role]:
    roles = db.execute(select(m.Role).where(
        m.Role.tenant_id == tenant_id,
        m.Role.code.in_(codes))).scalars().all()
    if len({r.code for r in roles}) != len(set(codes)):
        _err(400, 'ORG.UNKNOWN_ROLE', 'دور غير معروف ضمن القائمة')
    return roles


def _validate_perms(codes: list[str]) -> list[str]:
    bad = [c for c in codes if c not in KNOWN_PERMS]
    if bad:
        _err(400, 'ORG.UNKNOWN_PERM',
             'صلاحيات غير معروفة بالكتالوج: ' + '، '.join(bad))
    return sorted(set(codes))


def _user_out(db: Session, u: m.User) -> dict:
    return {'id': u.id, 'username': u.username, 'full_name': u.full_name,
            'email': u.email, 'is_active': u.is_active,
            'mfa_enabled': u.mfa_enabled,
            'must_change_password': u.must_change_password,
            'last_login_at': u.last_login_at,
            'locked_until': u.locked_until,
            'roles': sorted(ur.role.code for ur in u.roles),
            'grants': sorted(u.grants or []), 'denies': sorted(u.denies or []),
            'login_windows': u.login_windows or [],
            'branch_ids': u.branch_ids or []}


# ─────────────────── معلومات الجهة والكتالوج ───────────────────
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


@router.get('/permissions')
def permission_catalog(pr: Principal = Depends(require_perm(MANAGE))):
    """الكتالوج العربي المصنّف — يبني واجهة الأدوار والاستثناءات."""
    return [{'key': g['key'], 'name': g['name'],
             'perms': [{'code': c, 'name': n} for c, n in g['perms']]}
            for g in PERMISSION_CATALOG]


# ─────────────────── المستخدمون ───────────────────
@router.get('/users')
def list_users(db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm(MANAGE))):
    rows = db.execute(
        select(m.User).where(m.User.tenant_id == pr.tenant_id)
        .order_by(m.User.username)).scalars().all()
    return [_user_out(db, u) for u in rows]


class CreateUserIn(BaseModel):
    username: str = Field(min_length=2, max_length=60,
                          pattern=r'^[A-Za-z0-9._-]+$')
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=128)
    role_codes: list[str] = Field(min_length=1)
    email: str | None = None
    login_windows: list[LoginWindow] = Field(default_factory=list)
    must_change_password: bool = True


@router.post('/users', status_code=201)
def create_user(body: CreateUserIn, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm(MANAGE))):
    # القيد الصلب لعدد المستخدمين (ملف 07 §5) — رسالة ترقية واضحة
    from .. import licensing as lic
    lic.enforce_user_limit(db, pr.tenant_id)
    exists = db.execute(
        select(m.User).where(m.User.tenant_id == pr.tenant_id,
                             m.User.username == body.username)).scalar_one_or_none()
    if exists:
        _err(409, 'ORG.USER_EXISTS', 'اسم المستخدم مستخدم مسبقاً')
    roles = _roles_by_codes(db, pr.tenant_id, body.role_codes)
    u = m.User(id=new_uuid(), tenant_id=pr.tenant_id, username=body.username,
               full_name=body.full_name, email=body.email,
               password_hash=hash_password(body.password),
               must_change_password=body.must_change_password,
               login_windows=[w.model_dump(by_alias=True)
                              for w in body.login_windows],
               created_at=utcnow())
    db.add(u)
    db.flush()
    for r in roles:
        db.add(m.UserRole(user_id=u.id, role_id=r.id))
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='org', action='user.create', entity='users', entity_id=u.id,
          after={'username': u.username, 'roles': body.role_codes,
                 'windows': u.login_windows})
    db.commit()
    return {'id': u.id, 'username': u.username}


class PatchUserIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: str | None = None
    role_codes: list[str] | None = None
    branch_ids: list[str] | None = None
    login_windows: list[LoginWindow] | None = None
    grants: list[str] | None = None
    denies: list[str] | None = None


@router.patch('/users/{user_id}')
def patch_user(user_id: str, body: PatchUserIn, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm(MANAGE))):
    u = _get_user(db, pr.tenant_id, user_id)
    before = {'roles': sorted(ur.role.code for ur in u.roles),
              'grants': sorted(u.grants or []),
              'denies': sorted(u.denies or []),
              'login_windows': u.login_windows or [],
              'full_name': u.full_name, 'branch_ids': u.branch_ids or []}
    if body.full_name is not None:
        u.full_name = body.full_name
    if body.email is not None:
        u.email = body.email or None
    if body.branch_ids is not None:
        u.branch_ids = body.branch_ids
    if body.login_windows is not None:
        u.login_windows = [w.model_dump(by_alias=True)
                           for w in body.login_windows]
    if body.grants is not None:
        u.grants = _validate_perms(body.grants)
    if body.denies is not None:
        u.denies = _validate_perms(body.denies)
    if body.role_codes is not None:
        new_roles = _roles_by_codes(db, pr.tenant_id, body.role_codes)
        losing = _user_is_owner(db, u) and not any(
            '*' in (r.permissions or []) for r in new_roles)
        if u.id == pr.id and losing:  # رسالة الذات أولاً (أدق من آخر-مالك)
            _err(400, 'ORG.SELF_STRIP',
                 'لا يمكنك سحب صلاحية المالك الكاملة من حسابك بنفسك')
        _guard_last_owner(db, u, removing=losing)
        for ur in list(u.roles):
            db.delete(ur)
        db.flush()
        for r in new_roles:
            db.add(m.UserRole(user_id=u.id, role_id=r.id))
    after = {'roles': sorted(ur.role.code for ur in u.roles),
             'grants': sorted(u.grants or []),
             'denies': sorted(u.denies or []),
             'login_windows': u.login_windows or [],
             'full_name': u.full_name, 'branch_ids': u.branch_ids or []}
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='org', action='user.update', entity='users', entity_id=u.id,
          before=before, after=after)
    db.commit()
    return _user_out(db, u)


@router.post('/users/{user_id}/toggle-active')
def toggle_user(user_id: str, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm(MANAGE))):
    u = _get_user(db, pr.tenant_id, user_id)
    if u.id == pr.id:
        _err(400, 'ORG.SELF_LOCKOUT', 'لا يمكنك إيقاف حسابك الخاص')
    if u.is_active:
        _guard_last_owner(db, u, removing=True)
    u.is_active = not u.is_active
    revoked = 0
    if not u.is_active:
        u.failed_attempts = 0
        u.locked_until = None
        revoked = _revoke_sessions(db, u)  # قطع كل جلسات الموقوف فوراً
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='org', action='user.toggle_active', entity='users',
          entity_id=u.id,
          after={'is_active': u.is_active, 'sessions_revoked': revoked})
    db.commit()
    return {'id': u.id, 'is_active': u.is_active, 'sessions_revoked': revoked}


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=10, max_length=128)


@router.post('/users/{user_id}/reset-password')
def reset_password(user_id: str, body: ResetPasswordIn,
                   db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm(MANAGE))):
    u = _get_user(db, pr.tenant_id, user_id)
    u.password_hash = hash_password(body.new_password)
    u.must_change_password = True       # المؤقتة تُغيَّر إجبارياً أول دخول
    u.failed_attempts = 0
    u.locked_until = None
    revoked = _revoke_sessions(db, u)   # كلمة جديدة = جلسات قديمة باطلة
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='org', action='user.reset_password', entity='users',
          entity_id=u.id, after={'sessions_revoked': revoked})
    db.commit()
    return {'id': u.id, 'must_change_password': True,
            'sessions_revoked': revoked}


@router.post('/users/{user_id}/unlock')
def unlock_user(user_id: str, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm(MANAGE))):
    u = _get_user(db, pr.tenant_id, user_id)
    lu = u.locked_until
    if lu is not None and lu.tzinfo is None:  # SQLite يعيد naive
        from datetime import timezone as _tz
        lu = lu.replace(tzinfo=_tz.utc)
    was = bool(lu and lu > utcnow())
    u.failed_attempts = 0
    u.locked_until = None
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='org', action='user.unlock', entity='users', entity_id=u.id,
          after={'was_locked': was})
    db.commit()
    return {'id': u.id, 'unlocked': True}


@router.post('/users/{user_id}/revoke-sessions')
def revoke_sessions(user_id: str, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm(MANAGE))):
    u = _get_user(db, pr.tenant_id, user_id)
    n = _revoke_sessions(db, u)
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='org', action='user.revoke_sessions', entity='users',
          entity_id=u.id, after={'sessions_revoked': n})
    db.commit()
    return {'id': u.id, 'sessions_revoked': n}


@router.get('/users/{user_id}/effective-perms')
def effective_perms(user_id: str, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm(MANAGE))):
    """معاينة الصلاحيات الفعلية النهائية — شفافية كاملة قبل الحفظ."""
    u = _get_user(db, pr.tenant_id, user_id)
    return {'username': u.username, 'perms': user_perms(db, u)}


# ─────────────────── الأدوار ───────────────────
@router.get('/roles')
def list_roles(db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('reports.view'))):
    rows = db.execute(
        select(m.Role).where(m.Role.tenant_id == pr.tenant_id)
        .order_by(m.Role.is_system.desc(), m.Role.code)).scalars().all()
    users_count = {}
    for ur in db.execute(select(m.UserRole)).scalars():
        users_count[ur.role_id] = users_count.get(ur.role_id, 0) + 1
    return [{'code': r.code, 'name': r.name, 'description': r.description,
             'permissions': r.permissions, 'is_system': r.is_system,
             'users_count': users_count.get(r.id, 0)} for r in rows]


class RoleIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default='', max_length=300)
    permissions: list[str] = Field(default_factory=list)

    @field_validator('permissions')
    @classmethod
    def _no_star(cls, v: list[str]) -> list[str]:
        if '*' in v:
            raise ValueError('الصلاحية المطلقة «*» حكر دور المالك النظامي')
        return v


@router.post('/roles', status_code=201)
def create_role(body: RoleIn, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm(MANAGE))):
    perms = _validate_perms(body.permissions)
    code = 'CUST-' + new_uuid()[:8].upper()
    r = m.Role(id=new_uuid(), tenant_id=pr.tenant_id, code=code,
               name=body.name, description=body.description,
               is_system=False, permissions=perms)
    db.add(r)
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='org', action='role.create', entity='roles', entity_id=r.id,
          after={'code': code, 'name': r.name, 'permissions': perms})
    db.commit()
    return {'code': code, 'name': r.name, 'permissions': perms}


@router.patch('/roles/{code}')
def patch_role(code: str, body: RoleIn, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm(MANAGE))):
    r = db.execute(select(m.Role).where(
        m.Role.tenant_id == pr.tenant_id, m.Role.code == code)).scalar_one_or_none()
    if r is None:
        _err(404, 'GENERAL.NOT_FOUND', 'الدور غير موجود')
    if r.is_system:
        _err(403, 'ORG.SYSTEM_ROLE', 'الأدوار النظامية محمية من التعديل')
    before = {'name': r.name, 'description': r.description,
              'permissions': r.permissions}
    r.name = body.name
    r.description = body.description
    r.permissions = _validate_perms(body.permissions)
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='org', action='role.update', entity='roles', entity_id=r.id,
          before=before,
          after={'name': r.name, 'permissions': r.permissions})
    db.commit()
    return {'code': r.code, 'name': r.name, 'permissions': r.permissions}


@router.delete('/roles/{code}')
def delete_role(code: str, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm(MANAGE))):
    r = db.execute(select(m.Role).where(
        m.Role.tenant_id == pr.tenant_id, m.Role.code == code)).scalar_one_or_none()
    if r is None:
        _err(404, 'GENERAL.NOT_FOUND', 'الدور غير موجود')
    if r.is_system:
        _err(403, 'ORG.SYSTEM_ROLE', 'الأدوار النظامية محمية من الحذف')
    if db.execute(select(m.UserRole).where(
            m.UserRole.role_id == r.id)).first() is not None:
        _err(409, 'ORG.ROLE_IN_USE',
             'الدور معيَّن لمستخدمين — انزعه عنهم أولاً ثم احذفه')
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='org', action='role.delete', entity='roles', entity_id=r.id,
          before={'code': r.code, 'name': r.name,
                  'permissions': r.permissions})
    db.delete(r)
    db.commit()
    return {'deleted': True, 'code': code}
