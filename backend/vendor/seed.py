"""زرع اللوحة: مدير الشركة (مناوب، MFA مفعّل عينياً للمعاينة بسر تطوير
موثق)، أدوار الفريق الخمسة، وخطط أسعار يمنية واقعية، وعميلان وهميان تماماً
للمعاينة (لا بيانات حقيقية إطلاقاً — ملف 15)."""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .config import get_vendor_settings
from .security import hash_password


def seed_vendor(db: Session) -> dict:
    s = get_vendor_settings()
    if db.execute(select(m.VendorUser.id)).first():
        return {'seeded': False}

    director = m.VendorUser(
        username=s.admin_username, full_name='مدير الشركة (المناوبة)',
        password_hash=hash_password(s.admin_password), role='DIRECTOR',
        is_active=True, duty_manager=True,
        # سر TOTP تطويري للمعاينة فقط — الإنتاج يلزم تغييره وإعادة التسجيل
        mfa_secret=s.admin_totp_secret, mfa_enabled=True)
    team = [
        ('sales1', 'مسؤول مبيعات أول', 'SALES', False),
        ('finance1', 'مسؤول مالية أول', 'FINANCE', False),
        ('support1', 'دعم فني مستوى أول', 'SUPPORT_L1', False),
        ('support2', 'دعم فني مستوى ثاني', 'SUPPORT_L2', True),
        ('licops1', 'مشغل تراخيص أول', 'LIC_OPERATOR', False),
    ]
    db.add(director)
    for uname, fname, role, duty in team:
        db.add(m.VendorUser(username=uname, full_name=fname,
                            password_hash=hash_password('vendor123!Change'),
                            role=role, is_active=True, duty_manager=duty,
                            mfa_enabled=False))  # تسجيل إجباري عند أول دخول
    db.flush()

    plans = [
        m.Plan(code='START-Y', name_ar='باقة انطلاقة — سنوية',
               billing_period='YEARLY', setup_fee=Decimal('300'),
               base_price=Decimal('900'),
               module_prices={'HOTEL': 400, 'POS': 300, 'INVENTORY': 250,
                              'HR': 350, 'ASSETS': 150},
               included_users=5, included_branches=1,
               extra_user_price=Decimal('40'),
               extra_branch_price=Decimal('200'), discount_max_pct=15),
        m.Plan(code='PRO-Y', name_ar='باقة احتراف — سنوية',
               billing_period='YEARLY', setup_fee=Decimal('500'),
               base_price=Decimal('1800'),
               module_prices={'HOTEL': 500, 'POS': 400, 'INVENTORY': 350,
                              'HR': 450, 'ASSETS': 200, 'MULTIBRANCH': 600},
               included_users=15, included_branches=2,
               extra_user_price=Decimal('30'),
               extra_branch_price=Decimal('150'), discount_max_pct=20),
        m.Plan(code='CITY-M', name_ar='باقة المدينة — شهرية',
               billing_period='MONTHLY', setup_fee=Decimal('0'),
               base_price=Decimal('120'),
               module_prices={'HOTEL': 45, 'POS': 35, 'INVENTORY': 30,
                              'HR': 40, 'ASSETS': 18},
               included_users=8, included_branches=1,
               extra_user_price=Decimal('5'),
               extra_branch_price=Decimal('25'), discount_max_pct=10),
    ]
    db.add_all(plans)
    db.flush()

    # عميلان وهميان: واحد نشط سنوي وواحد تجريبي شهري
    c1 = m.Client(code='CLI-001', legal_name='شركة فندق النخبة الوهمية',
                  trade_name='فندق النخبة', contacts={'phone': '700000001',
                  'email': 'demo1@example.test', 'city': 'عدن',
                  'licensed_users': 12, 'support_level': 'PREMIUM'},
                  hotel_name='فندق النخبة', rooms_count=60, branches_count=1,
                  sales_channel='PARTNER', contract_ref='CTR-2026-001',
                  package='HYBRID',
                  modules=['ACCOUNTING', 'HOTEL', 'POS', 'INVENTORY', 'HR',
                           'ASSETS'],
                  plan_code='PRO-Y', billing_period='YEARLY',
                  monthly_value=Decimal('358.3333'),
                  tenant_id='demo-tenant-001',
                  activation_date=date.today() - timedelta(days=140),
                  expiry_date=date.today() + timedelta(days=225),
                  status='ACTIVE',
                  edge_token='edge-cli001-demo-token')
    c2 = m.Client(code='CLI-002', legal_name='مؤسسة فندق الميناء الوهمية',
                  trade_name='فندق الميناء', contacts={'phone': '700000002',
                  'email': 'demo2@example.test', 'city': 'المكلا',
                  'licensed_users': 6, 'support_level': 'STANDARD'},
                  hotel_name='فندق الميناء', rooms_count=28, branches_count=1,
                  sales_channel='DIRECT', contract_ref='CTR-2026-002',
                  package='LOCAL',
                  modules=['ACCOUNTING', 'HOTEL', 'POS'],
                  plan_code='CITY-M', billing_period='MONTHLY',
                  monthly_value=Decimal('200'),
                  tenant_id='demo-tenant-002',
                  activation_date=date.today() - timedelta(days=20),
                  expiry_date=date.today() + timedelta(days=10),
                  status='TRIAL',
                  edge_token='edge-cli002-demo-token')
    db.add_all([c1, c2])
    db.flush()
    for c in (c1, c2):
        db.add(m.ClientStatusHistory(
            client_id=c.id, from_status='', to_status=c.status,
            reason=f'زرع معاينة — ملف عميل {c.trade_name}',
            changed_by='system-seed'))
    db.flush()
    db.commit()
    return {'seeded': True, 'users': 1 + len(team), 'plans': len(plans),
            'clients': 2}
