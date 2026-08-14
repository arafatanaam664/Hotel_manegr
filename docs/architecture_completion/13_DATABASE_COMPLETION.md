# 13 — مراجعة اكتمال قاعدة البيانات (Database Completion)

> **المرحلة الثانية — تصميم فقط؛ لم تُعدَّل قاعدة.** فحص 2026-08-07:
> **119 جدولاً** (103 فندق + 16 شركة) · 64 قيد فريدة/فهرساً · **صفر CHECK** · **صفر Views/Materialized** · **صفر triggers** · Numeric(19,4) ملتزم · تواريخ UTC بمناطق ✅.

## A. الحكم المعماري على الموجود
سليم: فصل ملكية (money لحظي مشتق)، قيود تفرد بالأماكن الصحيحة (نافذة فوليو مثلاً `uq_folio_window` ✅)، فهارس على المسارات الساخنة، additive-migrations لترقية بلا توقف ✅. الملاحظات الجوهرية: (1) الإنفاذ «توازن القيد» برمجي فقط لا DB (مقبول SQLite؛ يُستكمل بملف PostgreSQL الإنتاجي)، (2) الجداول الحدثية (audit_log/sync_*) بلا سياسة احتفاظ/تقسيم، (3) لا Objects مشتقة (Views) — يجعل التقارير حسابات متكررة مبعثرة.

## B. الجداول الناقصة — 28 جدولاً مستهدفاً
| الجدول | الحزمة/المرحلة | المفاتيح والعلاقات الحاكمة |
|---|---|---|
| groups · group_rooms 🆕 P2 | مجموعات | group→tenant/branch/corporate/منسق؛ ربط حجوزات بـgroup_id + دور (MASTER/مستقل) |
| waitlist 🆕 P2 | انتظار | طلب+نزيل+نوع+أولوية+حالة+انقضاء |
| agents · agent_commissions 🆕 P2 | وكلاء | وكيل→corporate-like party؛ عمولة←حجز بنسبة، حالة تسوية |
| minibar_items · minibar_postings 🆕 P2 | ميني بار | صنف افتراضي لكل غرفة/ترحيل يومي مربوط فوليو+صرف مخزن |
| fd_shifts 🆕 P1 | كاشير الاستقبال | مثل pos_shifts مع managed_by/إحصاء/توريد |
| hk_tasks 🆕 P2 | هوسكيبينج | غرفة+موظفة+وردية+حالة assigned→inspected |
| mnt_work_orders · mnt_pm_schedules 🆕 P2/P3 | صيانة | موقع (room/asset/عام)+فني+حالات SLA+ربط inv_issue للقطع+OOO اقتران |
| budgets · budget_lines 🆕 P2 | موازنات | سنة+حساب/مركز×شهر؛ نسخ (مسودة/معتمدة/مجمدة) |
| bank_statements · bank_statement_lines 🆕 P2 | بنوك | كشف مستورد+سطور بحالة مطابقة |
| cheques 🆕 P2 | شيكات | طرف/بنك/استحقاق/حالة+قيود مسار (أمانات→مقاصة) |
| tax_return_runs 🆕 P1 | ضرائب | فترة+نوع+لقطة تصنيف ضريبي موقعة |
| notifications · notification_rules · notification_deliveries 🆕 **P1** | إشعارات | قاعدة→حدث/شرط/قنوات؛ تسليم idempotent بمفتاح حدث |
| attachments 🆕 P2 | ملفات | كيان متعدد الأشكال (entity_type/entity_id)+mime/sha/حجم+سرية |
| help_articles · help_categories 🆕 P2 | مساعدة | محتوى إصدار-مرتبط+بحث نصي |
| backup_jobs · restore_tests 🆕 **P0** | نسخ | وجهة/جدولة/نتيجة/hash/مدة؛ اختبار استعادة دوري نتائجه P1-حرجة عند الفشل |
| archive_policies 🆕 P1 · archive_frozen (مخزن بارد) 🆕 P1 | أرشفة | جدول/مدة احتفاظ/وجهة تجميد+فهرس استرجاع |
| print_printers · print_templates 🆕 **P1** | طباعة | جهاز(D-scope)/نوع/توجيه تصنيف؛ قالب كيان+نسخة |
| pos_promos 🆕 P2 | عروض | نطاق/نافذة زمنية/سقف/أولوية تعارض |
| delivery_orders 🆕 P3 | توصيل | طلب POS←عنوان/مندوب/حالة |
| api_keys · webhook_endpoints 🆕 P3 | شركاء | مفتاح بصلاحيات مضيّقة+توقيع HMAC+تعليق فوري |
| import_batches 🆕 P1 | ترحيل | نوع حزمة+أرقام سطور+تقرير قرار لكل سطر |
| onboarding_progress 🆕 P1 | تهيئة | خطوة/حالة/محضر ختم موقّع |
| user_prefs 🆕 P2 | تجربة | لغة/قنوات إشعار/كثافة عرض/مفضلة تقارير |
| loyalty_accounts · loyalty_txns · guest_feedback 🆕 P3 | CRM | نقاط/مستويات/شكاوى SLA |

## C. العلاقات الناقصة (FKs يجب إضافتها عند تنفيذ الحزم)
`reservations.group_id→groups` · `hk_tasks.room_id/assignee_id` · `mnt_work_orders.room_id|asset_id` + `mnt_parts.issue_line_id→inv_issue_lines` · `budget_lines.account_id/cost_center_id` · `cheques.journal_entry_id` (مسار القيد) · `attachments(entity)` · `notifications.recipient_user_id` · `fd_shifts.user_id/branch_id` — كلها `ON DELETE RESTRICT` (المالي/التشغيلي لا يُحذف أبداً — كتالوج 07).

## D. الفهارس الناقصة (إلزامية عند التنفيذ)
`guests(tenant_id, phone)` وبحث بالاسم (فهرس نصي) · `journal_lines(party_type, party_id, entry_date)` — يخدم RPT-FIN-008 · `pos_order_lines(created_at, outlet)` خريطة ساعات البيع · `audit_log(tenant_id, occurred_at)` مركب والتقسيم الشهري · `sync_events_out(state, seq)` · `reservations(branch_id, arrival_date)` موجود جزئياً — يراجع بالفحص الحملي · كل جدول جديد أعلاه بفهارس (tenant_id, +مفتاح فرزه الرئيسي).

## E. الطرق والطرق المجسدة (Views/MV) — تخدم التقارير P0 مباشرة
| الاسم | النوع | الغرض/التجديد |
|---|---|---|
| v_folio_balance | View | رصيد طرف لحظي من 1110/1120 (يعمم نمط «الفوليو=ذمة» على كل التقارير) |
| v_room_status_now | View | الحالة المركبة غرفة (نظافة+إشغال+OOO+حجز اليوم) للبراك والتقارير |
| v_open_positions | View | شراء مفتوح/متأخر (RPT-INV-010) |
| mv_occupancy_daily | **Materialized** | إشغال/ADR/RevPAR يومي لكل فرع — تُحدّث بإقفال التدقيق (RPT-HTL-003) |
| mv_sales_daily_pos | MV | مبيعات يومية صنف/منفذ/ساعة (RPT-POS-006) — تجديد ليلي |

## F. قيود/تريجرات/وظائف — ملف PostgreSQL الإنتاجي (قرار مؤجل موثق)
> اليوم SQLite يفي للموقع المفرد؛ الملف الإنتاجي (ملف 11 يستهدفها) يستكمل:
1. **منع الحجز المزدوج بنيوياً:** `EXCLUDE USING gist (room_id WITH =, daterange(arrival,departure) WITH &&) WHERE status…active` — التطبيق يملك التحقق والقفل المتفائل ✅ والقيد صمّام نهائي.
2. CHECK: مبالغ ≥0/شروط أكواد؛ تريجر تحقق توازن القيد عند POST (defense-in-depth فوق إنفاذ الخدمة).
3. تريجر ربط سلسلة التدقيق (hash-chain) على مستوى القاعدة للمحافظة السيادية.
4. تقسيم شهري (Partitioning) لـ: audit_log · sync_events_out/in · journal_entry_lines عند اجتياز أحجام العتبات الموثقة بالأرشفة.
5. وظيفة `fn_post_journal` معاملية واحدة تُستخدم من خدمة الترحيل (موحدة بين الصلاحيات).

## G. العدّ الرسمي
الجداول: 119 موجودة + **28 مستهدفة = 147 أكبر مخطط نهائي** · Views جديدة 3 · MV جديدة 2 · قيود PG حاكمة 4 أنواع · تقسيمات 3 جداول.

سجل التغييرات: v1.0 (2026-08-07) — فريق العمارة الاستشارية.
