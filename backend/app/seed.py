"""الزرع الأولي: دليل الحسابات القياسي للفنادق (ملف 02 §2.2 حرفياً)،
خريطة ربط افتراضية (ملف 02 §8)، أدوار النظام، مستأجر تجريبي، سنة مالية جارية."""
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .security import new_uuid, hash_password, utcnow


# (code, name_ar, parent_code, type, nature, postable, party_required, system)
COA = [
 ('1000', 'الأصول', None, 'ASSET', 'DEBIT', False, False, True),
 ('1100', 'الأصول المتداولة', '1000', 'ASSET', 'DEBIT', False, False, True),
 ('1101', 'الصندوق الرئيسي', '1100', 'ASSET', 'DEBIT', True, False, False),
 ('1102', 'صناديق نقاط البيع', '1100', 'ASSET', 'DEBIT', True, False, False),
 ('1103', 'البنك — الحساب الجاري', '1100', 'ASSET', 'DEBIT', True, False, False),
 ('1104', 'المحفظة الإلكترونية', '1100', 'ASSET', 'DEBIT', True, False, False),
 ('1110', 'ذمم النزلاء داخل الفندق (Guest Ledger)', '1100', 'ASSET', 'DEBIT', True, True, False),
 ('1120', 'ذمم المدينة — الشركات (City Ledger)', '1100', 'ASSET', 'DEBIT', True, True, False),
 ('1130', 'سلف الموظفين', '1100', 'ASSET', 'DEBIT', True, True, False),
 ('1140', 'مصروفات مدفوعة مقدماً', '1100', 'ASSET', 'DEBIT', True, False, False),
 ('1150', 'ضريبة مشتريات قابلة للاسترداد', '1100', 'ASSET', 'DEBIT', True, False, False),
 ('1200', 'المخزون', '1000', 'ASSET', 'DEBIT', False, False, True),
 ('1210', 'مخزون أغذية ومشروبات', '1200', 'ASSET', 'DEBIT', True, False, False),
 ('1220', 'مخزون مستلزمات تشغيل الغرف', '1200', 'ASSET', 'DEBIT', True, False, False),
 ('1230', 'مخزون صيانة وقطع غيار', '1200', 'ASSET', 'DEBIT', True, False, False),
 ('1240', 'مخزون مطبخ قيد التشغيل', '1200', 'ASSET', 'DEBIT', True, False, False),
 ('1500', 'الأصول الثابتة', '1000', 'ASSET', 'DEBIT', False, False, True),
 ('1510', 'أراضٍ ومباني', '1500', 'ASSET', 'DEBIT', True, False, False),
 ('1520', 'أثاث وتجهيزات الغرف (FF&E)', '1500', 'ASSET', 'DEBIT', True, False, False),
 ('1530', 'أجهزة ومعدات', '1500', 'ASSET', 'DEBIT', True, False, False),
 ('1540', 'وسائل نقل', '1500', 'ASSET', 'DEBIT', True, False, False),
 ('1590', 'مجمع الإهلاك', '1500', 'ASSET', 'CREDIT', True, False, False),
 ('2000', 'الخصوم', None, 'LIABILITY', 'CREDIT', False, False, True),
 ('2100', 'الخصوم المتداولة', '2000', 'LIABILITY', 'CREDIT', False, False, True),
 ('2101', 'ذمم الموردين', '2100', 'LIABILITY', 'CREDIT', True, True, False),
 ('2110', 'أمانات/عربون الحجوزات', '2100', 'LIABILITY', 'CREDIT', True, True, False),
 ('2120', 'إيراد مؤجل غير مستهلك', '2100', 'LIABILITY', 'CREDIT', True, False, False),
 ('2210', 'ضريبة المخرجات المستحقة', '2100', 'LIABILITY', 'CREDIT', True, False, False),
 ('2220', 'ضرائب واستقطاعات رواتب مستحقة', '2100', 'LIABILITY', 'CREDIT', True, False, False),
 ('2230', 'ضمانات اجتماعية وتأمينات مستحقة', '2100', 'LIABILITY', 'CREDIT', True, False, False),
 ('2310', 'رواتب مستحقة الدفع', '2100', 'LIABILITY', 'CREDIT', True, False, False),
 ('2320', 'مصروفات مستحقة', '2100', 'LIABILITY', 'CREDIT', True, False, False),
 ('2410', 'قروض وتمويل', '2100', 'LIABILITY', 'CREDIT', True, False, False),
 ('2420', 'مستحقات المالك/الشركاء', '2100', 'LIABILITY', 'CREDIT', True, False, False),
 ('3000', 'حقوق الملكية', None, 'EQUITY', 'CREDIT', False, False, True),
 ('3101', 'رأس المال المدفوع', '3000', 'EQUITY', 'CREDIT', True, False, False),
 ('3102', 'جاري المالك/الشركاء', '3000', 'EQUITY', 'CREDIT', True, False, False),
 ('3201', 'الأرباح المبقاة', '3000', 'EQUITY', 'CREDIT', True, False, False),
 ('3202', 'أرباح/خسائر العام الجاري (إقفال وسيط)', '3000', 'EQUITY', 'CREDIT', True, False, True),
 ('4000', 'الإيرادات', None, 'REVENUE', 'CREDIT', False, False, True),
 ('4100', 'إيرادات الغرف', '4000', 'REVENUE', 'CREDIT', False, False, True),
 ('4101', 'إيراد الإقامة — الغرف', '4100', 'REVENUE', 'CREDIT', True, False, False),
 ('4102', 'إيراد الإلغاء وعدم الحضور', '4100', 'REVENUE', 'CREDIT', True, False, False),
 ('4103', 'إيراد المغادرة المتأخرة/الوصول المبكر', '4100', 'REVENUE', 'CREDIT', True, False, False),
 ('4190', 'خصومات مسموحة على الغرف', '4100', 'REVENUE', 'DEBIT', True, False, False),
 ('4200', 'إيرادات الأغذية والمشروبات', '4000', 'REVENUE', 'CREDIT', False, False, True),
 ('4201', 'إيراد المطعم', '4200', 'REVENUE', 'CREDIT', True, False, False),
 ('4202', 'إيراد الكافيه', '4200', 'REVENUE', 'CREDIT', True, False, False),
 ('4203', 'إيراد خدمة الغرف', '4200', 'REVENUE', 'CREDIT', True, False, False),
 ('4204', 'إيراد المناسبات والقاعات', '4200', 'REVENUE', 'CREDIT', True, False, False),
 ('4300', 'إيرادات أقسام تشغيلية أخرى', '4000', 'REVENUE', 'CREDIT', False, False, True),
 ('4301', 'إيراد المغسلة', '4300', 'REVENUE', 'CREDIT', True, False, False),
 ('4302', 'إيراد السبا والنادي', '4300', 'REVENUE', 'CREDIT', True, False, False),
 ('4303', 'إيراد المواقف', '4300', 'REVENUE', 'CREDIT', True, False, False),
 ('4900', 'إيرادات أخرى', '4000', 'REVENUE', 'CREDIT', False, False, True),
 ('4901', 'عمولات وإيرادات متنوعة', '4900', 'REVENUE', 'CREDIT', True, False, False),
 ('4902', 'فروقات عملة دائنة', '4900', 'REVENUE', 'CREDIT', True, False, False),
 ('5000', 'تكلفة المبيعات والتشغيل المباشر', None, 'COGS', 'DEBIT', False, False, True),
 ('5101', 'تكلفة مبيعات الأغذية والمشروبات', '5000', 'COGS', 'DEBIT', True, False, False),
 ('5102', 'تكلفة مستلزمات الغرف المستهلكة', '5000', 'COGS', 'DEBIT', True, False, False),
 ('5110', 'تكلفة خدمات خارجية لصالح نزيل', '5000', 'COGS', 'DEBIT', True, False, False),
 ('6000', 'مصروفات تشغيلية', None, 'EXPENSE', 'DEBIT', False, False, True),
 ('6100', 'مصروفات قسم الغرف', '6000', 'EXPENSE', 'DEBIT', False, False, True),
 ('6110', 'رواتب الاستقبال والهوسكيبينج', '6100', 'EXPENSE', 'DEBIT', True, False, False),
 ('6120', 'مستلزمات قسم الغرف', '6100', 'EXPENSE', 'DEBIT', True, False, False),
 ('6200', 'مصروفات الأغذية والمشروبات', '6000', 'EXPENSE', 'DEBIT', False, False, True),
 ('6210', 'رواتب المطبخ والمطعم', '6200', 'EXPENSE', 'DEBIT', True, False, False),
 ('6300', 'مصروفات إدارية وعمومية', '6000', 'EXPENSE', 'DEBIT', False, False, True),
 ('6310', 'رواتب الإدارة والعمومية', '6300', 'EXPENSE', 'DEBIT', True, False, False),
 ('6320', 'قرطاسية ومطبوعات', '6300', 'EXPENSE', 'DEBIT', True, False, False),
 ('6330', 'اتصالات وإنترنت', '6300', 'EXPENSE', 'DEBIT', True, False, False),
 ('6400', 'تسويق ومبيعات', '6000', 'EXPENSE', 'DEBIT', False, False, True),
 ('6410', 'إعلانات وتسويق', '6400', 'EXPENSE', 'DEBIT', True, False, False),
 ('6420', 'عمولات منصات الحجز (OTA)', '6400', 'EXPENSE', 'DEBIT', True, False, False),
 ('6500', 'صيانة وطاقة', '6000', 'EXPENSE', 'DEBIT', False, False, True),
 ('6510', 'كهرباء', '6500', 'EXPENSE', 'DEBIT', True, False, False),
 ('6520', 'ماء', '6500', 'EXPENSE', 'DEBIT', True, False, False),
 ('6530', 'وقود ومولدات', '6500', 'EXPENSE', 'DEBIT', True, False, False),
 ('6540', 'صيانة وإصلاحات', '6500', 'EXPENSE', 'DEBIT', True, False, False),
 ('6600', 'مصروفات أخرى', '6000', 'EXPENSE', 'DEBIT', False, False, True),
 ('6610', 'رسوم حكومية وتراخيص', '6600', 'EXPENSE', 'DEBIT', True, False, False),
 ('6620', 'تأمين', '6600', 'EXPENSE', 'DEBIT', True, False, False),
 ('7000', 'بنود غير تشغيلية', None, 'EXPENSE', 'DEBIT', False, False, True),
 ('7100', 'غير تشغيلية', '7000', 'EXPENSE', 'DEBIT', False, False, True),
 ('7101', 'مصروف الإهلاك', '7100', 'EXPENSE', 'DEBIT', True, False, False),
 ('7102', 'مصروفات تمويل وفوائد', '7100', 'EXPENSE', 'DEBIT', True, False, False),
 ('7103', 'فروقات عملة مدينة', '7100', 'EXPENSE', 'DEBIT', True, False, False),
 ('7104', 'خسائر ومسحقات استثنائية', '7100', 'EXPENSE', 'DEBIT', True, False, False),
 ('8000', 'حسابات نظام داخلية', None, 'SYSTEM', 'DEBIT', False, False, True),
 ('8001', 'حساب مرحلي للمزامنة', '8000', 'SYSTEM', 'DEBIT', True, False, True),
 ('8002', 'حساب افتتاحي مرحلي للترحيل', '8000', 'SYSTEM', 'DEBIT', True, False, True),
]

ROLES = [
 ('OWNER', 'مالك', 'كل الصلاحيات', ['*']),
 ('GM', 'مدير عام', 'إدارة التشغيل والتقارير والاعتمادات',
  ['reports.view', 'accounts.view', 'journals.view', 'journals.post',
   'journals.reverse', 'periods.close', 'settings.manage']),
 ('FINANCE_MANAGER', 'مدير مالي', 'المحاسبة الكاملة والإغلاق',
  ['reports.view', 'accounts.view', 'accounts.manage', 'journals.view',
   'journals.manual', 'journals.post', 'journals.reverse', 'periods.close']),
 ('ACCOUNTANT', 'محاسب', 'إدخال ومراجعة',
  ['reports.view', 'accounts.view', 'journals.view', 'journals.manual']),
 ('AUDITOR', 'مدقق داخلي', 'قراءة وتدقيق فقط',
  ['reports.view', 'accounts.view', 'journals.view', 'audit.view']),
 ('RECEPTIONIST', 'موظف استقبال', 'حجوزات وتحصيل', []),
]

POSTING_MAPS = [
 ('GUEST_DEPOSIT', 'استلام عربون حجز',
  [{'account': '1101', 'side': 'D', 'from': 'amount', 'desc': 'عربون نقدي'},
   {'account': '2110', 'side': 'C', 'from': 'amount', 'party': True,
    'party_type': 'GUEST', 'desc': 'أمان حجز'}]),
 ('ROOM_NIGHT', 'ترحيل ليلة إقامة (تدقيق ليلي)',
  [{'account': '1110', 'side': 'D', 'from': 'gross', 'party': True,
    'party_type': 'GUEST', 'desc': 'شحنة ليلة'},
   {'account': '4101', 'side': 'C', 'from': 'net', 'desc': 'إيراد غرفة صافي'},
   {'account': '2210', 'side': 'C', 'from': 'tax', 'desc': 'ضريبة مخرجات'}]),
 ('POS_SALE', 'بيع نقطة بيع نقدي',
  [{'account': '1102', 'side': 'D', 'from': 'gross', 'desc': 'تحصيل POS نقدي'},
   {'account': '4201', 'side': 'C', 'from': 'net', 'desc': 'إيراد مطعم صافي'},
   {'account': '2210', 'side': 'C', 'from': 'tax', 'desc': 'ضريبة'}]),
 ('POS_COGS', 'قيد تكلفة مبيعات تلقائي',
  [{'account': '5101', 'side': 'D', 'from': 'cost', 'desc': 'تكلفة المبيعات'},
   {'account': '1210', 'side': 'C', 'from': 'cost', 'desc': 'خفض المخزون'}]),
 ('PURCHASE_CREDIT', 'شراء مخزون بالأجل',
  [{'account': '1210', 'side': 'D', 'from': 'amount', 'desc': 'إدخال مخزون'},
   {'account': '2101', 'side': 'C', 'from': 'amount', 'party': True,
    'party_type': 'SUPPLIER', 'desc': 'ذمة مورد'}]),
 ('SUPPLIER_PAYMENT', 'سداد مورد',
  [{'account': '2101', 'side': 'D', 'from': 'amount', 'party': True,
    'party_type': 'SUPPLIER', 'desc': 'سداد مورد'},
   {'account': '1103', 'side': 'C', 'from': 'amount', 'desc': 'سداد بنكي'}]),
 ('PAYROLL_ACCRUAL', 'استحقاق رواتب شهرية',
  [{'account': '6110', 'side': 'D', 'from': 'rooms_gross', 'desc': 'رواتب قسم الغرف'},
   {'account': '6310', 'side': 'D', 'from': 'admin_gross', 'desc': 'رواتب الإدارة'},
   {'account': '2310', 'side': 'C', 'from': 'net', 'desc': 'صافي الرواتب'},
   {'account': '2220', 'side': 'C', 'from': 'withholdings', 'desc': 'استقطاعات نظامية'}]),
 ('DEPRECIATION', 'إهلاك شهري',
  [{'account': '7101', 'side': 'D', 'from': 'amount', 'desc': 'مصروف إهلاك'},
   {'account': '1590', 'side': 'C', 'from': 'amount', 'desc': 'مجمع إهلاك'}]),
 ('FOLIO_PAYMENT', 'تحصيل من نزيل على الفوليو',
  [{'account': '1101', 'side': 'D', 'from': 'amount', 'desc': 'تحصيل نقدي'},
   {'account': '1110', 'side': 'C', 'from': 'amount', 'party': True,
    'party_type': 'GUEST', 'desc': 'سداد ذمة نزيل'}]),
 ('CITY_LEDGER_TRANSFER', 'نقل ذمة نزيل إلى شركة عند الخروج',
  [{'account': '1120', 'side': 'D', 'from': 'amount', 'party': True,
    'party_type': 'CORPORATE', 'desc': 'ذمة شركة'},
   {'account': '1110', 'side': 'C', 'from': 'amount', 'party': True,
    'party_type': 'GUEST', 'desc': 'إقفال ذمة نزيل'}]),
]


def seed_if_empty(db: Session, *, tenant_name: str, admin_username: str,
                  admin_password: str) -> dict:
    if db.execute(select(m.Tenant.id)).first():
        return {'seeded': False}

    tid = new_uuid()
    db.add(m.Tenant(id=tid, legal_name=tenant_name, trade_name=tenant_name,
                    base_currency='YER', created_at=utcnow()))
    db.flush()  # ترتيب إدراج حتمي: المستأجر قبل كل ما يتبعه (FK مرجعية)
    bid = new_uuid()
    db.add(m.Branch(id=bid, tenant_id=tid, code='MAIN', name='الفرع الرئيسي'))
    db.flush()

    # عملات
    for c in [('YER', 'ريال يمني', '﷼', 2), ('USD', 'دولار أمريكي', '$', 2),
              ('SAR', 'ريال سعودي', 'ر.س', 2)]:
        db.add(m.Currency(code=c[0], name=c[1], symbol=c[2],
                          decimal_places=c[3]))

    # دليل الحسابات
    ids = {}
    for code, name, parent, typ, nature, postable, party_req, is_sys in COA:
        aid = new_uuid()
        lvl = 1 if parent is None else (2 if len(parent) == 4 and parent.endswith('000') else 3)
        db.add(m.Account(id=aid, tenant_id=tid, code=code, name_ar=name,
                         parent_id=ids.get(parent), level=lvl, type=typ,
                         nature=nature, is_postable=postable,
                         party_required=party_req, is_system=is_sys))
        db.flush()  # الأب قبل الأبناء (COA مرتب هرمياً)
        ids[code] = aid

    # مراكز تكلفة
    for code, name in [('CC-ROOMS', 'قسم الغرف'), ('CC-FB', 'الأغذية والمشروبات'),
                       ('CC-ADMIN', 'الإدارة والعمومية'), ('CC-MKT', 'التسويق'),
                       ('CC-MNT', 'الصيانة والطاقة')]:
        db.add(m.CostCenter(id=new_uuid(), tenant_id=tid, code=code, name=name))

    # ضريبة افتراضية (معطلة — قرار العميل يوثق عند التفعيل)
    db.add(m.Tax(id=new_uuid(), tenant_id=tid, code='GST',
                 name='ضريبة عامة (معطلة افتراضياً)', rate=0,
                 inclusive=False, liability_account_code='2210', is_active=False))

    # سنة ودورات مالية للعام الجاري
    today = date.today()
    fy = m.FiscalYear(id=new_uuid(), tenant_id=tid, year_no=today.year,
                      start_date=date(today.year, 1, 1),
                      end_date=date(today.year, 12, 31))
    db.add(fy)
    db.flush()
    import calendar
    for mo in range(1, 13):
        last = calendar.monthrange(today.year, mo)[1]
        db.add(m.FiscalPeriod(id=new_uuid(), fiscal_year_id=fy.id,
                              period_no=mo,
                              start_date=date(today.year, mo, 1),
                              end_date=date(today.year, mo, last)))

    # خريطة الربط
    for etype, desc, tpl in POSTING_MAPS:
        db.add(m.PostingMap(id=new_uuid(), tenant_id=tid, event_type=etype,
                            description=desc, template=tpl,
                            effective_from=date(2020, 1, 1),
                            effective_to=None))

    # أدوار ومستخدم مدير
    role_ids = {}
    for code, name, desc, perms in ROLES:
        rid = new_uuid()
        db.add(m.Role(id=rid, tenant_id=tid, code=code, name=name,
                      description=desc, permissions=perms))
        role_ids[code] = rid
    uid = new_uuid()
    admin = m.User(id=uid, tenant_id=tid, username=admin_username,
                   full_name='مدير النظام (تجريبي)',
                   password_hash=hash_password(admin_password),
                   created_at=utcnow(), branch_ids=[bid])
    db.add(admin)
    db.flush()
    db.add(m.UserRole(user_id=uid, role_id=role_ids['OWNER']))

    db.commit()
    return {'seeded': True, 'tenant_id': tid, 'branch_id': bid,
            'admin_id': uid}
