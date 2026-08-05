"""إعدادات التطبيق — تُقرأ من متغيرات البيئة (لا أسرار في الكود).
المبدأ: نفس الإعدادات تعمل محلياً (SQLite) وسحابياً (PostgreSQL)."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8',
                                      extra='ignore', case_sensitive=False)

    app_name: str = 'Atheer Hospitality ERP'
    version: str = '0.8.0'
    deployment_mode: str = 'local'            # local | cloud | hybrid

    # قاعدة البيانات: افتراضي SQLite ملف بجوار المشروع، والإنتاج PostgreSQL
    database_url: str = 'sqlite:///./atheer_dev.db'

    # الأمن — يجب ضبطها في الإنتاج (يمنع الشحن بقيم افتراضية في وضع cloud)
    jwt_secret: str = 'dev-only-insecure-secret-change-me'
    jwt_issuer: str = 'atheer'
    access_token_minutes: int = 15
    refresh_token_days: int = 7

    # Bootstrap
    seed_on_startup: bool = True
    admin_username: str = 'admin'
    admin_password: str = 'admin123!Change'   # محلي فقط — cloud يتطلب تجاوزها
    demo_tenant_name: str = 'فندق النموذج التجريبي'

    # الترخيص (ملف 07) — المفتاح الخاص لا يمر عبر الإعدادات أبداً (شركة فقط)
    license_public_key_pem: str = ''     # حقن مباشر (اختبارات/نشر سحابي)
    license_public_key_path: str = ''    # أو مسار ملف PEM خارجي
    license_check_hours: int = 6         # الفحص الدوري (07 §3)
    license_trial_days: int = 90         # تثبيت بلا ترخيص = تجريبي كامل
    license_grace_days: int = 30         # مهلة التجديد الافتراضية (07 §1)
    license_fingerprint_salt: str = 'atheer-dev-salt-change-me'
    emergency_export_users: str = 'admin'  # حساب الطوارئ المالي (07 §3)


@lru_cache
def get_settings() -> Settings:
    return Settings()
