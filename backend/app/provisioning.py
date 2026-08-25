"""تهيئة المنتج التجارية والتشغيلية للمستأجر.

المبدأ: الاستحقاق التجاري يأتي من الترخيص الموقع، بينما تختزن هذه الخدمة
اختيارات العميل التشغيلية. لا تُنشئ هذه الخدمة بيانات تجريبية ولا تمنح صلاحيات
للمستخدمين من تلقاء نفسها.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .security import new_uuid, utcnow

DEPLOYMENT_MODES = {'LOCAL', 'CLOUD', 'HYBRID'}
PROPERTY_TYPES = {'HOTEL', 'INN', 'SERVICED_APARTMENTS', 'RESORT', 'OTHER'}
SETUP_STATES = {'NOT_STARTED', 'IN_PROGRESS', 'COMPLETED'}

MODULE_CATALOG = {
    'ACCOUNTING': {'name_ar': 'المحاسبة والمالية', 'required': True},
    'HOTEL': {'name_ar': 'إدارة الفندق والحجوزات', 'required': False},
    'POS': {'name_ar': 'نقاط البيع والمطعم', 'required': False},
    'INVENTORY': {'name_ar': 'المخزون والمشتريات', 'required': False},
    'HR': {'name_ar': 'الموارد البشرية والرواتب', 'required': False},
    'ASSETS': {'name_ar': 'الأصول الثابتة', 'required': False},
    'LAUNDRY': {'name_ar': 'المغسلة', 'required': False},
    'MAINTENANCE': {'name_ar': 'الصيانة', 'required': False},
    'BANQUETS': {'name_ar': 'القاعات والمناسبات', 'required': False},
    'MULTIBRANCH': {'name_ar': 'تعدد الفروع', 'required': False},
    'MESSAGING': {'name_ar': 'الرسائل والتنبيهات الخارجية', 'required': False},
}

FEATURE_CATALOG = {
    'MULTI_BRANCH': 'تعدد الفروع',
    'RESTAURANT': 'مطعم أو مقهى',
    'LAUNDRY': 'مغسلة',
    'POINT_OF_SALE': 'نقطة بيع',
    'HOUSEKEEPING': 'التدبير الفندقي',
    'MAINTENANCE': 'الصيانة',
    'MULTI_CURRENCY': 'عملات متعددة',
    'OFFLINE_POS': 'نقاط بيع دون اتصال',
    'POLICE_REPORT': 'المعلومية اليومية',
}

MODULE_DEPENDENCIES = {
    'POS': {'ACCOUNTING'},
    'INVENTORY': {'ACCOUNTING'},
    'HR': {'ACCOUNTING'},
    'HOTEL': {'ACCOUNTING'},
    'LAUNDRY': {'ACCOUNTING'},
    'MAINTENANCE': {'ACCOUNTING'},
    'BANQUETS': {'ACCOUNTING'},
}


def _error(code: str, message: str, status: int = 400):
    raise HTTPException(status, {'error': {'code': code, 'message_ar': message}})


def normalize_modules(modules: list[str] | None) -> list[str]:
    selected = {str(x).strip().upper() for x in (modules or []) if str(x).strip()}
    selected.add('ACCOUNTING')
    unknown = sorted(selected - set(MODULE_CATALOG))
    if unknown:
        _error('SETUP.UNKNOWN_MODULE', f'وحدات غير معروفة: {", ".join(unknown)}')
    missing = {
        dependency
        for module in selected
        for dependency in MODULE_DEPENDENCIES.get(module, set())
        if dependency not in selected
    }
    if missing:
        _error('SETUP.MODULE_DEPENDENCY',
               f'الوحدات التالية مطلوبة: {", ".join(sorted(missing))}')
    return sorted(selected)


def normalize_features(features: dict | None, modules: list[str],
                       multi_branch: bool) -> dict:
    raw = {str(k).upper(): bool(v) for k, v in (features or {}).items()}
    unknown = sorted(set(raw) - set(FEATURE_CATALOG))
    if unknown:
        _error('SETUP.UNKNOWN_FEATURE', f'خصائص غير معروفة: {", ".join(unknown)}')
    out = {key: False for key in FEATURE_CATALOG}
    out.update(raw)
    out['MULTI_BRANCH'] = bool(multi_branch)
    out['RESTAURANT'] = out['RESTAURANT'] and 'POS' in modules
    out['POINT_OF_SALE'] = out['POINT_OF_SALE'] and 'POS' in modules
    out['LAUNDRY'] = out['LAUNDRY'] and 'LAUNDRY' in modules
    out['MAINTENANCE'] = out['MAINTENANCE'] and 'MAINTENANCE' in modules
    out['HOUSEKEEPING'] = out['HOUSEKEEPING'] and 'HOTEL' in modules
    out['POLICE_REPORT'] = out['POLICE_REPORT'] and 'HOTEL' in modules
    if out['OFFLINE_POS'] and not out['POINT_OF_SALE']:
        _error('SETUP.FEATURE_DEPENDENCY', 'البيع دون اتصال يتطلب تفعيل نقطة البيع')
    return out


def get_or_create(db: Session, tenant_id: str) -> m.TenantProductConfig:
    cfg = db.get(m.TenantProductConfig, tenant_id)
    if cfg:
        return cfg
    now = utcnow()
    cfg = m.TenantProductConfig(
        tenant_id=tenant_id,
        deployment_mode='LOCAL',
        property_type='HOTEL',
        setup_state='NOT_STARTED',
        modules_enabled=['ACCOUNTING'],
        feature_flags=normalize_features({}, ['ACCOUNTING'], False),
        created_at=now,
        updated_at=now,
    )
    db.add(cfg)
    db.flush()
    return cfg


def serialize(cfg: m.TenantProductConfig) -> dict:
    return {
        'tenant_id': cfg.tenant_id,
        'deployment_mode': cfg.deployment_mode,
        'property_type': cfg.property_type,
        'setup_state': cfg.setup_state,
        'modules_enabled': sorted(cfg.modules_enabled or []),
        'feature_flags': cfg.feature_flags or {},
        'configured_by': cfg.configured_by,
        'completed_at': cfg.completed_at.isoformat() if cfg.completed_at else None,
        'version': cfg.version,
        'updated_at': cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


def _licensed_modules(db: Session, tenant_id: str) -> set[str]:
    # الاستحقاق التجاري لا يُقرأ من tenant_product_configs؛ مصدره ملف الترخيص
    # الموقع. الاستيراد كسول حتى لا تنشأ حلقة مع حراس المصادقة.
    from . import licensing
    row = db.execute(select(m.LicenseState).where(
        m.LicenseState.tenant_id == tenant_id)).scalar_one_or_none()
    if row is None:
        return {'ACCOUNTING'}
    limits = licensing._payload_limits(row.payload_signed or {}, row)
    return set(limits.get('modules_enabled') or ['ACCOUNTING']) | {'ACCOUNTING'}


def update_config(db: Session, tenant_id: str, actor_id: str, *,
                  deployment_mode: str, property_type: str,
                  modules_enabled: list[str], feature_flags: dict,
                  multi_branch: bool, complete: bool) -> dict:
    mode = deployment_mode.upper()
    prop = property_type.upper()
    if mode not in DEPLOYMENT_MODES:
        _error('SETUP.INVALID_DEPLOYMENT_MODE', 'نمط النشر غير صالح')
    if prop not in PROPERTY_TYPES:
        _error('SETUP.INVALID_PROPERTY_TYPE', 'نوع المنشأة غير صالح')
    modules = normalize_modules(modules_enabled)
    unlicensed = sorted(set(modules) - _licensed_modules(db, tenant_id))
    if unlicensed:
        _error('LIC.MODULE_DISABLED',
               f'الوحدات التالية غير موجودة في الباقة: {", ".join(unlicensed)}', 403)
    features = normalize_features(feature_flags, modules, multi_branch)
    if complete and 'HOTEL' not in modules:
        _error('SETUP.HOTEL_MODULE_REQUIRED',
               'يجب تفعيل وحدة الفندق قبل إكمال إعداد منشأة فندقية')
    cfg = get_or_create(db, tenant_id)
    cfg.deployment_mode = mode
    cfg.property_type = prop
    cfg.modules_enabled = modules
    cfg.feature_flags = features
    cfg.setup_state = 'COMPLETED' if complete else 'IN_PROGRESS'
    cfg.configured_by = actor_id
    cfg.completed_at = utcnow() if complete else None
    cfg.version = (cfg.version or 0) + 1
    cfg.updated_at = utcnow()
    db.flush()
    return serialize(cfg)
