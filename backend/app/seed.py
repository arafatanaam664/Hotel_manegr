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

# صلاحيات الفندق (ملف 03 — فصل المهام SoD)
HOTEL_OPS_PERMS = ['frontdesk.view', 'reservations.view', 'guests.view',
                   'corporates.view', 'reports.hotel', 'rooms.view']
FRONTDESK_WORK = ['reservations.create', 'reservations.modify',
                  'reservations.cancel', 'guests.manage', 'checkin.do',
                  'checkout.do', 'folio.charge', 'folio.pay', 'folio.view']

# صلاحيات نقاط البيع (ملف 04 — §3 قواعد صارمة: void/خصم فوق الحد بصلاحية)
POS_OPS_PERMS = ['pos.view', 'pos.tables.view', 'pos.zreport.view',
                 'pos.reports']
POS_WORK = ['pos.sell', 'pos.shift.open', 'pos.shift.close']
POS_SUPERVISOR_EXTRA = ['pos.void', 'pos.approve', 'pos.return',
                        'pos.catalog.manage', 'pos.tables.manage',
                        'pos.stock.manage']

ROLES = [
 ('OWNER', 'مالك', 'كل الصلاحيات', ['*']),
 ('GM', 'مدير عام', 'إدارة التشغيل والتقارير والاعتمادات',
  ['reports.view', 'accounts.view', 'journals.view', 'journals.post',
   'journals.reverse', 'periods.close', 'settings.manage']
  + HOTEL_OPS_PERMS + FRONTDESK_WORK + POS_OPS_PERMS + POS_WORK
  + POS_SUPERVISOR_EXTRA
  + ['corporates.manage', 'checkout.credit_transfer', 'discounts.approve',
     'nightaudit.run', 'hk.manage', 'rooms.manage', 'rates.manage',
     'extras.manage', 'checkin.dirty_override', 'audit.view']),
 ('FINANCE_MANAGER', 'مدير مالي', 'المحاسبة الكاملة والإغلاق',
  ['reports.view', 'accounts.view', 'accounts.manage', 'journals.view',
   'journals.manual', 'journals.post', 'journals.reverse', 'periods.close']
  + HOTEL_OPS_PERMS + POS_OPS_PERMS + ['pos.stock.manage']
  + ['discounts.approve', 'checkout.credit_transfer', 'corporates.manage',
     'folio.view']),
 ('ACCOUNTANT', 'محاسب', 'إدخال ومراجعة',
  ['reports.view', 'accounts.view', 'journals.view', 'journals.manual',
   'reports.hotel', 'folio.view', 'pos.reports', 'pos.zreport.view']),
 ('AUDITOR', 'مدقق داخلي', 'قراءة وتدقيق فقط',
  ['reports.view', 'accounts.view', 'journals.view', 'audit.view',
   'reports.hotel', 'folio.view', 'frontdesk.view', 'pos.view',
   'pos.reports', 'pos.zreport.view']),
 ('RECEPTIONIST', 'موظف استقبال', 'حجوزات وتسكين وتحصيل',
  HOTEL_OPS_PERMS + FRONTDESK_WORK + ['folio.discount']),
 ('NIGHT_AUDITOR', 'مدقق ليلي', 'إجراء إقفال يوم العمل',
  HOTEL_OPS_PERMS + ['nightaudit.run', 'journals.view', 'folio.view']),
 ('HOUSEKEEPING', 'موظفة طابق', 'تنظيف الغرف: Dirty→Cleaning→Clean',
  ['frontdesk.view', 'rooms.view', 'hk.cleaning']),
 ('HK_SUPERVISOR', 'مشرف طوابق', 'فحص الغرف ومناطق التعطيل',
  ['frontdesk.view', 'rooms.view', 'hk.cleaning', 'hk.manage']),
 ('POS_CASHIER', 'كاشير نقطة بيع', 'بيع وتسديد وفتح/إقفال ورديته',
  POS_OPS_PERMS + POS_WORK),
 ('POS_SUPERVISOR', 'مشرف نقاط بيع',
  'إلغاء البنود، اعتماد الخصومات والمجاني، إدارة الكتالوج والمخزون',
  POS_OPS_PERMS + POS_WORK + POS_SUPERVISOR_EXTRA),
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
 ('POS_COGS', 'قيد تكلفة مبيعات تلقائي',  # #13
  [{'account': '5101', 'side': 'D', 'from': 'cost', 'desc': 'تكلفة المبيعات'},
   {'account': '1210', 'side': 'C', 'from': 'cost', 'desc': 'خفض المخزون'}]),
 ('CASH_OVER', 'زيادة عهدة صندوق نقطة بيع ضمن التسامح (Z-Report)',
  [{'account': '1102', 'side': 'D', 'from': 'amount', 'desc': 'فرق عهدة زيادة'},
   {'account': '4901', 'side': 'C', 'from': 'amount',
    'desc': 'إيراد فرق صندوق'}]),
 ('CASH_SHORT', 'نقص عهدة صندوق نقطة بيع ضمن التسامح (Z-Report)',
  [{'account': '7104', 'side': 'D', 'from': 'amount',
    'desc': 'خسارة فرق صندوق'},
   {'account': '1102', 'side': 'C', 'from': 'amount', 'desc': 'فرق عهدة نقص'}]),
 ('STOCK_OPEN_POS', 'رصيد مخزون افتتاحي لنقطة بيع (ترحيل بلا فقدان)',
  [{'account': '1210', 'side': 'D', 'from': 'amount', 'desc': 'رصيد افتتاحي'},
   {'account': '8002', 'side': 'C', 'from': 'amount',
    'desc': 'مقابل افتتاحي مرحلي'}]),
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
  [{'account': '1120', 'side': 'D', 'from': 'amount',
    'party_key': 'corporate', 'desc': 'ذمة شركة'},
   {'account': '1110', 'side': 'C', 'from': 'amount',
    'party_key': 'folio', 'desc': 'إقفال ذمة نزيل'}]),
]

# خرائط أحداث الفندق — ملف 02 §8 بالأرقام المرجعية #01..#08 والملحقات
# (event_type, context_key, وصف, القالب) — السياق None = الافتراضي
HOTEL_POSTING_MAPS = [
 # #03 عدم حضور — نزيل مباشر (من عربونه المعلّق)
 ('NO_SHOW', 'GUEST', 'عدم حضور باحتساب ليلة (نزيل مباشر)',
  [{'account': '2110', 'side': 'D', 'from': 'amount', 'party': True,
    'party_type': 'GUEST', 'desc': 'إعدام عربون'},
   {'account': '4102', 'side': 'C', 'from': 'net', 'desc': 'إيراد عدم الحضور'},
   {'account': '2210', 'side': 'C', 'from': 'tax', 'desc': 'ضريبة'}]),
 # #03 عدم حضور — مؤكد بشركة (الذمة على الشركة)
 ('NO_SHOW', 'CORPORATE', 'عدم حضور باحتساب ليلة (مؤكد بشركة)',
  [{'account': '1120', 'side': 'D', 'from': 'amount', 'party': True,
    'party_type': 'CORPORATE', 'desc': 'ذمة شركة — عدم حضور'},
   {'account': '4102', 'side': 'C', 'from': 'net', 'desc': 'إيراد عدم الحضور'},
   {'account': '2210', 'side': 'C', 'from': 'tax', 'desc': 'ضريبة'}]),
 # إلغاء حجز مع غرامة
 ('CANCEL_FEE', None, 'إلغاء حجز مع غرامة',
  [{'account': '2110', 'side': 'D', 'from': 'amount', 'party': True,
    'party_type': 'GUEST', 'desc': 'خصم غرامة من العربون'},
   {'account': '4102', 'side': 'C', 'from': 'net', 'desc': 'إيراد إلغاء'},
   {'account': '2210', 'side': 'C', 'from': 'tax', 'desc': 'ضريبة'}]),
 # #05 شحنات الفوليو حسب نوع الخدمة (السياق = كود الخدمة)
 ('FOLIO_CHARGE', 'LAUNDRY', 'مغسلة على الفوليو',
  [{'account': '1110', 'side': 'D', 'from': 'gross', 'party': True,
    'party_type': 'GUEST', 'desc': 'شحنة مغسلة'},
   {'account': '4301', 'side': 'C', 'from': 'net', 'desc': 'إيراد مغسلة'},
   {'account': '2210', 'side': 'C', 'from': 'tax', 'desc': 'ضريبة'}]),
 ('FOLIO_CHARGE', 'SPA', 'سبا ونادي على الفوليو',
  [{'account': '1110', 'side': 'D', 'from': 'gross', 'party': True,
    'party_type': 'GUEST', 'desc': 'شحنة سبا'},
   {'account': '4302', 'side': 'C', 'from': 'net', 'desc': 'إيراد سبا'},
   {'account': '2210', 'side': 'C', 'from': 'tax', 'desc': 'ضريبة'}]),
 ('FOLIO_CHARGE', 'PARKING', 'مواقف على الفوليو',
  [{'account': '1110', 'side': 'D', 'from': 'gross', 'party': True,
    'party_type': 'GUEST', 'desc': 'شحنة مواقف'},
   {'account': '4303', 'side': 'C', 'from': 'net', 'desc': 'إيراد مواقف'},
   {'account': '2210', 'side': 'C', 'from': 'tax', 'desc': 'ضريبة'}]),
 ('FOLIO_CHARGE', 'ROOM_SERVICE', 'خدمة الغرف على الفوليو',
  [{'account': '1110', 'side': 'D', 'from': 'gross', 'party': True,
    'party_type': 'GUEST', 'desc': 'شحنة خدمة غرفة'},
   {'account': '4203', 'side': 'C', 'from': 'net', 'desc': 'إيراد خدمة الغرف'},
   {'account': '2210', 'side': 'C', 'from': 'tax', 'desc': 'ضريبة'}]),
 ('FOLIO_CHARGE', 'MINIBAR', 'ميني بار على الفوليو',
  [{'account': '1110', 'side': 'D', 'from': 'gross', 'party': True,
    'party_type': 'GUEST', 'desc': 'شحنة ميني بار'},
   {'account': '4201', 'side': 'C', 'from': 'net', 'desc': 'إيراد ميني بار'},
   {'account': '2210', 'side': 'C', 'from': 'tax', 'desc': 'ضريبة'}]),
 ('FOLIO_CHARGE', 'EXTRA_BED', 'سرير إضافي على الفوليو',
  [{'account': '1110', 'side': 'D', 'from': 'gross', 'party': True,
    'party_type': 'GUEST', 'desc': 'شحنة سرير إضافي'},
   {'account': '4101', 'side': 'C', 'from': 'net', 'desc': 'إيراد سرير إضافي'},
   {'account': '2210', 'side': 'C', 'from': 'tax', 'desc': 'ضريبة'}]),
 ('FOLIO_CHARGE', 'GENERIC', 'خدمة متنوعة على الفوليو',
  [{'account': '1110', 'side': 'D', 'from': 'gross', 'party': True,
    'party_type': 'GUEST', 'desc': 'شحنة متنوعة'},
   {'account': '4901', 'side': 'C', 'from': 'net', 'desc': 'إيراد متنوع'},
   {'account': '2210', 'side': 'C', 'from': 'tax', 'desc': 'ضريبة'}]),
 # #06 خصم مسموح (يتطلب اعتماداً فوق حد الدور)
 ('DISCOUNT', None, 'خصم مسموح على فوليو',
  [{'account': '4190', 'side': 'D', 'from': 'amount',
    'desc': 'خصم مسموح — معتمد'},
   {'account': '1110', 'side': 'C', 'from': 'amount', 'party': True,
    'party_type': 'GUEST', 'desc': 'خفض ذمة نزيل'}]),
 # #07 دفعات النزيل حسب الوسيلة
 ('FOLIO_PAYMENT', 'CASH', 'دفعة نقدية من نزيل',
  [{'account': '1101', 'side': 'D', 'from': 'amount', 'desc': 'نقدية صندوق'},
   {'account': '1110', 'side': 'C', 'from': 'amount', 'party': True,
    'party_type': 'GUEST', 'desc': 'سداد ذمة نزيل'}]),
 ('FOLIO_PAYMENT', 'CARD', 'دفعة بنكية/بطاقة من نزيل',
  [{'account': '1103', 'side': 'D', 'from': 'amount', 'desc': 'تحصيل بنكي'},
   {'account': '1110', 'side': 'C', 'from': 'amount', 'party': True,
    'party_type': 'GUEST', 'desc': 'سداد ذمة نزيل'}]),
 ('FOLIO_PAYMENT', 'EWALLET', 'دفعة محفظة إلكترونية من نزيل',
  [{'account': '1104', 'side': 'D', 'from': 'amount', 'desc': 'تحصيل محفظة'},
   {'account': '1110', 'side': 'C', 'from': 'amount', 'party': True,
    'party_type': 'GUEST', 'desc': 'سداد ذمة نزيل'}]),
 # مغادرة متأخرة (#4103)
 ('LATE_CHECKOUT', None, 'رسوم مغادرة متأخرة',
  [{'account': '1110', 'side': 'D', 'from': 'gross', 'party': True,
    'party_type': 'GUEST', 'desc': 'رسوم مغادرة متأخرة'},
   {'account': '4103', 'side': 'C', 'from': 'net', 'desc': 'إيراد مغادرة متأخرة'},
   {'account': '2210', 'side': 'C', 'from': 'tax', 'desc': 'ضريبة'}]),
 # تطبيق العربون على الفوليو عند Check-in
 ('DEPOSIT_APPLY', None, 'تطبيق عربون الحجز على فوليو النزيل',
  [{'account': '2110', 'side': 'D', 'from': 'amount',
    'party_key': 'reservation', 'desc': 'إنزال العربون'},
   {'account': '1110', 'side': 'C', 'from': 'amount',
    'party_key': 'folio', 'desc': 'تخفيض ذمة الفوليو'}]),
 # رد العربون (إلغاء بدون غرامة)
 ('DEPOSIT_REFUND', None, 'رد عربون حجز',
  [{'account': '2110', 'side': 'D', 'from': 'amount', 'party': True,
    'party_type': 'GUEST', 'desc': 'إلغاء أمانة'},
   {'account': '1101', 'side': 'C', 'from': 'amount', 'desc': 'رد نقدي'}]),
 # رد فائض مدفوع عند إقفال الفوليو
 ('GUEST_REFUND', None, 'رد فائض مدفوعات نزيل',
  [{'account': '1110', 'side': 'D', 'from': 'amount', 'party': True,
    'party_type': 'GUEST', 'desc': 'تصفية فائض'},
   {'account': '1101', 'side': 'C', 'from': 'amount', 'desc': 'رد نقدي للنزيل'}]),
 # تحويل شحنة بين نافذتي الفوليو (شخصي ↔ شركة) — نفس الحساب بطرفين
 ('FOLIO_TRANSFER', None, 'تحويل شحنة بين نوافذ الفوليو',
  [{'account': '1110', 'side': 'D', 'from': 'amount',
    'party_key': 'to_window', 'desc': 'شحنة محولة لنافذة الشركة'},
   {'account': '1110', 'side': 'C', 'from': 'amount',
    'party_key': 'from_window', 'desc': 'إنزال شحنة من النافذة الشخصية'}]),
]


# أنواع غرف تجريبية (الأسعار تطابق سيناريو G1)
HOTEL_ROOM_TYPES = [
 ('SGL', 'غرفة مفردة', 'Single Room', 1, 1, 'سرير مفرد', 60, 1),
 ('DBL', 'غرفة مزدوجة', 'Double Room', 2, 1, 'سريران', 85, 2),
 ('SUITE', 'جناح', 'Suite', 3, 2, 'سرير كبير + صالة', 140, 3),
]

HOTEL_ROOMS = [  # (room_no, type, floor)
 ('101', 'SGL', 1), ('103', 'SGL', 1), ('104', 'SGL', 1), ('105', 'SGL', 1),
 ('102', 'DBL', 1), ('201', 'DBL', 2), ('202', 'DBL', 2), ('203', 'DBL', 2),
 ('204', 'DBL', 2), ('301', 'SUITE', 3), ('302', 'SUITE', 3),
]

HOTEL_EXTRAS = [  # (code, name, price, revenue_account) — السياق = الكود
 ('LAUNDRY', 'مغسلة', 8, '4301'), ('SPA', 'سبا ونادي', 25, '4302'),
 ('PARKING', 'مواقف سيارات', 5, '4303'), ('ROOM_SERVICE', 'خدمة الغرف', 12, '4203'),
 ('MINIBAR', 'ميني بار', 6, '4201'), ('EXTRA_BED', 'سرير إضافي', 15, '4101'),
 ('GENERIC', 'خدمة متنوعة', 10, '4901'),
]

HOTEL_RATE_PLANS = [
 ('BAR', 'إقامة فقط', None, False, 'إلغاء مجاني حتى 48 ساعة', 1),
 ('BB', 'شامل إفطار', 10, True, 'إلغاء مجاني حتى 24 ساعة', 1),
]

# ════════════════════════════════════════════════════════════════════
# بيانات زرع نقطة البيع التجريبية — ملف 04 §1/§2
# ════════════════════════════════════════════════════════════════════
POS_OUTLETS = [  # (code, name_ar, name_en, cash_acct, revenue_acct, cost_center)
 ('REST', 'المطعم الرئيسي', 'Main Restaurant', '1102', '4201', 'CC-FB'),
 ('CAFE', 'كافيه اللوبي', 'Lobby Cafe', '1102', '4202', 'CC-FB'),
]

POS_CATEGORIES = [  # (code, name_ar, name_en, color, station, sort)
 ('FOOD', 'الأطباق الرئيسية', 'Mains', '#b45309', 'KITCHEN', 1),
 ('GRILL', 'مشويات', 'Grill', '#991b1b', 'KITCHEN', 2),
 ('APPT', 'مقبلات وسلطات', 'Starters', '#15803d', 'KITCHEN', 3),
 ('BEER', 'مشروبات ساخنة وباردة', 'Beverages', '#0369a1', 'BAR', 4),
 ('DSRT', 'حلويات', 'Desserts', '#a21caf', 'KITCHEN', 5),
]

# (code, name_ar, name_en, category, price, type, cost, revenue_acct)
POS_ITEMS = [
 ('BURGER-CL', 'برجر كلاسيك', 'Classic Burger', 'FOOD', 9.5, 'COMPOSITE', 0, '4201'),
 ('BURGER-CH', 'برجر دجاج مقرمش', 'Crispy Chicken Burger', 'FOOD', 8.5, 'COMPOSITE', 0, '4201'),
 ('PASTA-ALF', 'باستا ألفريدو', 'Pasta Alfredo', 'FOOD', 11, 'SERVICE', 0, '4201'),
 ('PIZZA-MRG', 'بيتزا مارغريتا', 'Pizza Margherita', 'FOOD', 10, 'SERVICE', 0, '4201'),
 ('KEBAB', 'كباب حلبي (سيخان)', 'Kebab Plate', 'GRILL', 14, 'SERVICE', 0, '4201'),
 ('TIKA', 'تكة دجاج', 'Chicken Tikka', 'GRILL', 12, 'SERVICE', 0, '4201'),
 ('FATOUSH', 'فتوش', 'Fattoush', 'APPT', 4.5, 'SERVICE', 0, '4201'),
 ('HUMMUS', 'حمص بالطحينة', 'Hummus', 'APPT', 4, 'SERVICE', 0, '4201'),
 ('SOUP-DAY', 'شوربة اليوم', 'Soup of the Day', 'APPT', 3.5, 'SERVICE', 0, '4201'),
 ('TEA-ADANI', 'شاي عدني', 'Adani Tea', 'BEER', 1.5, 'SERVICE', 0, '4202'),
 ('COFFEE-AR', 'قهوة عربية', 'Arabic Coffee', 'BEER', 2, 'SERVICE', 0, '4202'),
 ('ESPRESSO', 'إسبريسو', 'Espresso', 'BEER', 2.5, 'SERVICE', 0, '4202'),
 ('LATTE', 'كافيه لاتيه', 'Cafe Latte', 'BEER', 3.5, 'SERVICE', 0, '4202'),
 ('JUICE-OR', 'عصير برتقال طازج', 'Fresh Orange Juice', 'BEER', 3, 'COMPOSITE', 0, '4202'),
 ('WATER', 'مياه معدنية', 'Mineral Water', 'BEER', 1, 'STOCK', 0.45, '4202'),
 ('SODA', 'مشروب غازي', 'Soft Drink', 'BEER', 1.5, 'STOCK', 0.7, '4202'),
 ('KUNAFA', 'كنافة نابلسية', 'Kunafa', 'DSRT', 5, 'SERVICE', 0, '4201'),
 ('ICECREAM', 'آيس كريم (3 سكوب)', 'Ice Cream', 'DSRT', 4, 'SERVICE', 0, '4201'),
 # مكونات الوصفات (مخزونية — لا تُباع منفردة لكنها متاحة كأصناف)
 ('BUN', 'خبز برجر', 'Burger Bun', 'FOOD', 0, 'STOCK', 0.35, '4201'),
 ('BEEF-PAT', 'قطعة لحم برجر', 'Beef Patty', 'FOOD', 0, 'STOCK', 2.2, '4201'),
 ('CHKN-FIL', 'فيليه دجاج', 'Chicken Fillet', 'FOOD', 0, 'STOCK', 1.9, '4201'),
 ('CHEESE-SL', 'شريحة جبن', 'Cheese Slice', 'FOOD', 0, 'STOCK', 0.3, '4201'),
 ('FRIES-PT', 'بطاطس (حصة)', 'Fries Portion', 'FOOD', 0, 'STOCK', 0.8, '4201'),
 ('ORANGE-KG', 'برتقال (كجم)', 'Oranges KG', 'BEER', 0, 'STOCK', 1.2, '4202'),
]

# وصفات: (الصنف المركب, [(المكون, الكمية لكل وحدة), ...]) — قبول #3 حرفية
POS_RECIPES = [
 ('BURGER-CL', [('BUN', 1), ('BEEF-PAT', 1), ('CHEESE-SL', 1), ('FRIES-PT', 1)]),
 ('BURGER-CH', [('BUN', 1), ('CHKN-FIL', 1), ('CHEESE-SL', 1), ('FRIES-PT', 1)]),
 ('JUICE-OR', [('ORANGE-KG', 0.4)]),
]

POS_MODIFIERS = [  # (name_ar, name_en, price)
 ('إكسترا جبن', 'Extra Cheese', 1), ('إكسترا لحم', 'Extra Patty', 2.5),
 ('بدون بصل', 'No Onion', 0), ('حار إضافي', 'Extra Spicy', 0),
 ('حليب شوفان', 'Oat Milk', 0.8), ('سكر أقل', 'Less Sugar', 0),
]
POS_ITEM_MODS = {  # صنف ← معدلاته
 'BURGER-CL': ['إكسترا جبن', 'إكسترا لحم', 'بدون بصل', 'حار إضافي'],
 'BURGER-CH': ['إكسترا جبن', 'بدون بصل', 'حار إضافي'],
 'LATTE': ['حليب شوفان', 'سكر أقل'], 'ESPRESSO': ['سكر أقل'],
}

POS_TABLES = [  # (outlet, name, zone, seats)
 ('REST', 'طاولة 1', 'القاعة الرئيسية', 4), ('REST', 'طاولة 2', 'القاعة الرئيسية', 4),
 ('REST', 'طاولة 3', 'القاعة الرئيسية', 6), ('REST', 'طاولة 4', 'القاعة الرئيسية', 2),
 ('REST', 'طاولة 5', 'التراس', 4), ('REST', 'طاولة 6', 'التراس', 8),
 ('CAFE', 'ركن 1', 'اللوبي', 2), ('CAFE', 'ركن 2', 'اللوبي', 2),
]

# رصيد افتتاحي: (outlet, item, qty, unit_cost)
POS_STOCK_OPEN = [
 ('REST', 'BUN', 200, 0.35), ('REST', 'BEEF-PAT', 80, 2.2),
 ('REST', 'CHKN-FIL', 60, 1.9), ('REST', 'CHEESE-SL', 120, 0.3),
 ('REST', 'FRIES-PT', 100, 0.8), ('REST', 'ORANGE-KG', 25, 1.2),
 ('REST', 'WATER', 300, 0.45), ('REST', 'SODA', 240, 0.7),
 ('CAFE', 'ORANGE-KG', 10, 1.2), ('CAFE', 'WATER', 100, 0.45),
 ('CAFE', 'SODA', 80, 0.7),
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
    seed_hotel(db, tid, bid)
    seed_pos(db, tid, bid)

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


# ════════════════════════════════════════════════════════════════════
# زرع وحدة الفندق — يعمل إدخالاً ذرّياً ويرفع القواعد القديمة دون فقدان
# ════════════════════════════════════════════════════════════════════
def _map_exists(db: Session, tid: str, etype: str, ctx) -> bool:
    q = select(m.PostingMap).where(m.PostingMap.tenant_id == tid,
                                   m.PostingMap.event_type == etype)
    if ctx is None:
        q = q.where(m.PostingMap.context_key.is_(None))
    else:
        q = q.where(m.PostingMap.context_key == ctx)
    return db.execute(q).first() is not None


def seed_hotel(db: Session, tid: str, bid: str) -> dict:
    """إدخالات idempotent: خرائط الفندق، غرف/أنواع/خدمات/خطط، تاريخ العمل."""
    added = {'maps': 0, 'rooms': 0, 'extras': 0}
    today = date.today()

    # 1) خرائط الأحداث الفندقية
    for etype, ctx, desc, tpl in HOTEL_POSTING_MAPS:
        if not _map_exists(db, tid, etype, ctx):
            db.add(m.PostingMap(id=new_uuid(), tenant_id=tid,
                                event_type=etype, context_key=ctx,
                                description=desc, template=tpl,
                                effective_from=date(2020, 1, 1)))
            added['maps'] += 1
    db.flush()

    # 2) أنواع الغرف والغرف
    rt_ids = {}
    for code, name_ar, name_en, ad, ch, beds, rate, order in HOTEL_ROOM_TYPES:
        row = db.execute(
            select(m.RoomType).where(m.RoomType.tenant_id == tid,
                                     m.RoomType.code == code)).scalar_one_or_none()
        if not row:
            row = m.RoomType(id=new_uuid(), tenant_id=tid, code=code,
                             name_ar=name_ar, name_en=name_en,
                             capacity_adults=ad, capacity_children=ch,
                             beds=beds, base_rate=rate, display_order=order)
            db.add(row)
            db.flush()
        rt_ids[code] = row.id

    for room_no, tcode, floor in HOTEL_ROOMS:
        exists = db.execute(
            select(m.Room).where(m.Room.tenant_id == tid,
                                 m.Room.branch_id == bid,
                                 m.Room.room_no == room_no)).scalar_one_or_none()
        if not exists:
            db.add(m.Room(id=new_uuid(), tenant_id=tid, branch_id=bid,
                          room_no=room_no, floor=floor,
                          room_type_id=rt_ids[tcode], hk_status='CLEAN'))
            added['rooms'] += 1
    db.flush()

    # 3) الخدمات الإضافية
    for code, name, price, acct in HOTEL_EXTRAS:
        if not db.execute(select(m.Extra).where(
                m.Extra.tenant_id == tid, m.Extra.code == code)).first():
            db.add(m.Extra(id=new_uuid(), tenant_id=tid, code=code,
                           name_ar=name, price=price,
                           revenue_account_code=acct))
            added['extras'] += 1
    db.flush()

    # 4) خطط الأسعار
    for code, name, ref, bf, cancel, minn in HOTEL_RATE_PLANS:
        if not db.execute(select(m.RatePlan).where(
                m.RatePlan.tenant_id == tid, m.RatePlan.code == code)).first():
            db.add(m.RatePlan(id=new_uuid(), tenant_id=tid, code=code,
                              name_ar=name, ref_rate=ref,
                              includes_breakfast=bf, cancel_policy=cancel,
                              min_nights=minn))
    db.flush()

    # 5) تاريخ العمل الفندقي — مرة واحدة فقط عند أول زرع
    if not db.get(m.BusinessDateState, tid):
        from .security import utcnow as _un
        db.add(m.BusinessDateState(tenant_id=tid,
                                   current_business_date=today,
                                   updated_at=_un()))
    db.flush()
    return added


def seed_pos(db: Session, tid: str, bid: str) -> dict:
    """زرع وحدة POS (إدخالات idempotent): منفذان، كتالوج، وصفات، طاولات،
    ورصيد افتتاحي بقيد STOCK_OPEN_POS عبر المحرك (لا مخزوناً حراً أبداً)."""
    from .posting import post_event  # استيراد متأخر لتفادي الدوران
    added = {'outlets': 0, 'items': 0, 'stock': 0}
    today = date.today()

    outlet_ids = {}
    for code, name_ar, name_en, cash, rev, cc in POS_OUTLETS:
        row = db.execute(select(m.PosOutlet).where(
            m.PosOutlet.tenant_id == tid, m.PosOutlet.code == code)
        ).scalar_one_or_none()
        if not row:
            row = m.PosOutlet(id=new_uuid(), tenant_id=tid, branch_id=bid,
                              code=code, name_ar=name_ar, name_en=name_en,
                              cash_account_code=cash,
                              default_revenue_account_code=rev,
                              cost_center_code=cc, created_at=utcnow())
            db.add(row)
            db.flush()
            added['outlets'] += 1
        outlet_ids[code] = row.id

    cat_ids = {}
    for code, name_ar, name_en, color, station, so in POS_CATEGORIES:
        row = db.execute(select(m.PosCategory).where(
            m.PosCategory.tenant_id == tid, m.PosCategory.code == code)
        ).scalar_one_or_none()
        if not row:
            row = m.PosCategory(id=new_uuid(), tenant_id=tid, code=code,
                                name_ar=name_ar, name_en=name_en, color=color,
                                station=station, sort_order=so)
            db.add(row)
            db.flush()
        cat_ids[code] = row.id

    item_ids = {}
    for code, name_ar, name_en, cat, price, typ, cost, rev in POS_ITEMS:
        row = db.execute(select(m.PosItem).where(
            m.PosItem.tenant_id == tid, m.PosItem.code == code)
        ).scalar_one_or_none()
        if not row:
            row = m.PosItem(id=new_uuid(), tenant_id=tid, code=code,
                            name_ar=name_ar, name_en=name_en,
                            category_id=cat_ids[cat], price=price,
                            item_type=typ, cost=cost,
                            revenue_account_code=rev)
            db.add(row)
            db.flush()
            added['items'] += 1
        item_ids[code] = row.id

    mod_ids = {}
    for name_ar, name_en, price in POS_MODIFIERS:
        row = db.execute(select(m.PosModifier).where(
            m.PosModifier.tenant_id == tid, m.PosModifier.name_ar == name_ar)
        ).scalar_one_or_none()
        if not row:
            row = m.PosModifier(id=new_uuid(), tenant_id=tid, name_ar=name_ar,
                                name_en=name_en, price=price)
            db.add(row)
            db.flush()
        mod_ids[name_ar] = row.id

    for icode, mods in POS_ITEM_MODS.items():
        for mname in mods:
            if not db.execute(select(m.PosItemModifier).where(
                    m.PosItemModifier.item_id == item_ids[icode],
                    m.PosItemModifier.modifier_id == mod_ids[mname])).first():
                db.add(m.PosItemModifier(id=new_uuid(), tenant_id=tid,
                                         item_id=item_ids[icode],
                                         modifier_id=mod_ids[mname]))
    db.flush()

    for pcode, comps in POS_RECIPES:
        for ccode, qty in comps:
            if not db.execute(select(m.PosRecipe).where(
                    m.PosRecipe.parent_item_id == item_ids[pcode],
                    m.PosRecipe.component_item_id == item_ids[ccode])).first():
                db.add(m.PosRecipe(id=new_uuid(), tenant_id=tid,
                                   parent_item_id=item_ids[pcode],
                                   component_item_id=item_ids[ccode],
                                   qty=qty))
    db.flush()

    for ocode, name, zone, seats in POS_TABLES:
        if not db.execute(select(m.PosTable).where(
                m.PosTable.outlet_id == outlet_ids[ocode],
                m.PosTable.name == name)).first():
            db.add(m.PosTable(id=new_uuid(), tenant_id=tid,
                              outlet_id=outlet_ids[ocode], name=name,
                              zone=zone, seats=seats))
    db.flush()

    for ocode, icode, qty, cost in POS_STOCK_OPEN:
        exists = db.execute(select(m.PosStock).where(
            m.PosStock.outlet_id == outlet_ids[ocode],
            m.PosStock.item_id == item_ids[icode])).scalar_one_or_none()
        if exists:
            continue
        db.add(m.PosStock(id=new_uuid(), tenant_id=tid,
                          outlet_id=outlet_ids[ocode],
                          item_id=item_ids[icode], qty_on_hand=qty))
        db.add(m.PosStockMove(id=new_uuid(), tenant_id=tid,
                              outlet_id=outlet_ids[ocode],
                              item_id=item_ids[icode], qty_delta=qty,
                              unit_cost=cost, reason='OPEN',
                              actor_id='system', created_at=utcnow()))
        post_event(db, tenant_id=tid, branch_code='MAIN',
                   event_type='STOCK_OPEN_POS',
                   event_key=f'posstock:open:{ocode}:{icode}',
                   entry_date=today, amounts={'amount': str(qty * cost)},
                   actor_id='system',
                   narration=f'رصيد افتتاحي {icode} × {qty} @ {cost}')
        added['stock'] += 1
    db.flush()
    return added


def ensure_hotel_upgrade(db: Session) -> dict:
    """يرفع قاعدة قائمة (تحوي حسابات) بكيانات الفندق وPOS دون فقدان بيانات."""
    tenant = db.execute(select(m.Tenant).limit(1)).scalar_one_or_none()
    if tenant is None:
        return {'upgraded': False, 'reason': 'empty-db'}
    branch = db.execute(
        select(m.Branch).where(m.Branch.tenant_id == tenant.id)
        .limit(1)).scalar_one_or_none()
    if branch is None:
        return {'upgraded': False, 'reason': 'no-branch'}

    out = {'upgraded': True, 'maps': 0, 'rooms': 0, 'extras': 0,
           'roles_updated': []}

    # خرائط الربط الناقصة (من القائمتين العامة والفندقية)
    base_maps = [(e, None, d, t) for e, d, t in POSTING_MAPS]
    for etype, ctx, desc, tpl in base_maps + HOTEL_POSTING_MAPS:
        if not _map_exists(db, tenant.id, etype, ctx):
            db.add(m.PostingMap(id=new_uuid(), tenant_id=tenant.id,
                                event_type=etype, context_key=ctx,
                                description=desc, template=tpl,
                                effective_from=date(2020, 1, 1)))
            out['maps'] += 1
    db.flush()

    # أدوار: أضف الناقص، وادمج الصلاحيات الجديدة في القديم (اتحاداً)
    for code, name, desc, perms in ROLES:
        role = db.execute(
            select(m.Role).where(m.Role.tenant_id == tenant.id,
                                 m.Role.code == code)).scalar_one_or_none()
        if role is None:
            db.add(m.Role(id=new_uuid(), tenant_id=tenant.id, code=code,
                          name=name, description=desc, permissions=perms))
            out['roles_updated'].append(f'added:{code}')
        else:
            merged = sorted(set(role.permissions or []) | set(perms))
            if merged != sorted(role.permissions or []):
                role.permissions = merged
                out['roles_updated'].append(f'merged:{code}')
    db.flush()

    added = seed_hotel(db, tenant.id, branch.id)
    out['maps'] += added['maps']
    out['rooms'] = added['rooms']
    out['extras'] = added['extras']
    pos_added = seed_pos(db, tenant.id, branch.id)
    out['pos'] = pos_added
    db.commit()
    return out
