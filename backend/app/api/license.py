"""واجهات الترخيص (ملف 07):
- الحالة لكل مستخدم مصادَق (شاشة الحالة + شريط التنبيه)
- التثبيت/التجديد/الإصلاح بملف موقّع (Idempotent — نفس الملف لا يكرر أثراً)
- طلب تفعيل معزول (بصمة → الشركة توقّع) وقوائم الإلغاء الموقعة
- فحص فوري عند الطلب (يفرض دورة الـ6 ساعات يدوياً)
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import licensing as lic
from ..db import get_db
from ..deps import Principal, client_ip, get_principal, require_perm
from ..posting import PostingError
from ..schemas import LicenseInstallIn, LicenseStatusOut

router = APIRouter(prefix='/api/license', tags=['license'])


def _wrap(fn, *args, **kwargs):
    """أخطاء الترخيص عبر مغلّف الأخطاء الموحّد (PostingError متوافق)."""
    try:
        return fn(*args, **kwargs)
    except lic.LicError as e:
        raise PostingError(e.code, e.message)


@router.get('/status', response_model=LicenseStatusOut)
def license_status(db: Session = Depends(get_db),
                   pr: Principal = Depends(get_principal)):
    """حالة الترخيص — متاحة لأي مستخدم مصادَق (الشريط يحتاجها دائماً)."""
    return LicenseStatusOut(**lic.evaluate(db, pr.tenant_id,
                                           actor_id=pr.id))


@router.post('/evaluate', response_model=LicenseStatusOut)
def license_evaluate(db: Session = Depends(get_db),
                     pr: Principal = Depends(require_perm('license.manage'))):
    """فحص فوري كامل (إعادة تحقق توقيع + بصمة + ساعة) — يدوي عند الطلب."""
    out = lic.evaluate(db, pr.tenant_id, force=True, actor_id=pr.id)
    db.commit()
    return LicenseStatusOut(**out)


@router.post('/install')
def license_install(body: LicenseInstallIn, request: Request,
                    db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('license.manage'))):
    """تثبيت/تجديد ملف ترخيص موقّع. الملف الساري يحل محل القديم سلساً
    (07 §2) ويفك القفل الاحترازي للساعة (07 §4-2). تكرار نفس الملف آمن."""
    out = _wrap(lic.install_license, db, pr.tenant_id, body.payload,
                actor_id=pr.id, ip=client_ip(request))
    db.commit()
    return out


@router.get('/activation-request')
def license_activation_request(db: Session = Depends(get_db),
                               pr: Principal = Depends(
                                   require_perm('license.manage'))):
    """وضع معزول تماماً (07 §2): يولّد ملف طلب يتضمن بصمة الجهاز المجزأة —
    يُرسل للشركة فتوقّع ملفاً مفعَّلاً مقيّداً بهذه البصمة."""
    out = lic.activation_request(db, pr.tenant_id, actor_id=pr.id)
    db.commit()
    return out


@router.post('/revocations')
def license_revocations(body: LicenseInstallIn, request: Request,
                        db: Session = Depends(get_db),
                        pr: Principal = Depends(require_perm('license.manage'))):
    """استيراد قائمة إلغاء موقعة (رقم تسلسل متزايد). إدخال SUSPEND = قرار
    الشركة الموثّق بالإيقاف النهائي — لا يوجد إيقاف آلي (07 §3)."""
    out = _wrap(lic.import_revocations, db, pr.tenant_id, body.payload,
                actor_id=pr.id, ip=client_ip(request))
    db.commit()
    return out
