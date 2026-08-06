"""إعدادات لوحة الشركة — بيئة مستقلة (VENDOR_*) بلا أي مشاركة مع العملاء."""
import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                          '..', '..'))


class VendorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='VENDOR_', env_file='.env',
                                      env_file_encoding='utf-8',
                                      extra='ignore', case_sensitive=False)

    app_name: str = 'MantiqSoft Vendor Control Panel'
    version: str = '0.9.0'
    database_url: str = 'sqlite:///./vendor_dev.db'
    jwt_secret: str = 'vendor-dev-only-insecure-change-me'
    jwt_issuer: str = 'mantiqsoft-vendor'
    access_token_minutes: int = 30

    # سلطة التوقيع (ملف 07 §1): المفتاح الخاص يعيش هنا فقط — لا يُشحن للعملاء
    license_private_key_path: str = os.path.join(_REPO_ROOT, 'dev_keys',
                                                 'license_private.pem')

    # Bootstrap الشركة (تطوير فقط — الإنتاج يلزم تجاوزها وثنائية التحكم)
    seed_on_startup: bool = True
    admin_username: str = 'director'
    admin_password: str = 'vendor123!Change'
    # سر TOTP إنمائي مثبت للمعاينة فقط — الإنتاج: تسجيل عبر شاشة اللوحة
    admin_totp_secret: str = 'JBSWY3DPEHPK3PXP'
    mfa_required: bool = True            # ملف 08 §7: MFA إلزامي بلا استثناء

    # سياسات الدعم (ساعات SLA حسب الأولوية P1..P4) — قابلة للضبط بالعقد
    sla_hours_p1: int = 4
    sla_hours_p2: int = 24
    sla_hours_p3: int = 72
    sla_hours_p4: int = 168


@lru_cache
def get_vendor_settings() -> VendorSettings:
    return VendorSettings()
