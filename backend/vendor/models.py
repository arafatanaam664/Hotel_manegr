"""نماذج لوحة الشركة (ملف 08). كل الأموال Decimal/Numeric(19,4) — ممنوع float.
لا تُخزَّن أي بيانات تشغيلية للعملاء (صفر ثقة عكسية §1): وصف/أرقام مراجع فقط."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (JSON, Boolean, Date, DateTime, ForeignKey, Integer,
                        Numeric, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import VendorBase
from .clock import vnow

import uuid


def _uuid() -> str:
    return str(uuid.uuid4())


JSONType = JSON

CLIENT_STATES = ['TRIAL', 'ACTIVE', 'GRACE', 'READ_ONLY', 'SUSPENDED',
                 'TERMINATED']
VENDOR_ROLES = ['DIRECTOR', 'SALES', 'FINANCE', 'SUPPORT_L1', 'SUPPORT_L2',
                'LIC_OPERATOR']


class VendorUser(VendorBase):
    """مستخدمو الشركة فقط — MFA إلزامي بلا استثناء (§7)."""
    __tablename__ = 'vendor_users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_uuid)
    username: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret: Mapped[str] = mapped_column(String(64), default='')  # TOTP
    duty_manager: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=vnow)


class Client(VendorBase):
    """ملف العميل (CRM تشغيلي §2)."""
    __tablename__ = 'vendor_clients'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_uuid)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    legal_name: Mapped[str] = mapped_column(String(200))
    trade_name: Mapped[str] = mapped_column(String(200), default='')
    contacts: Mapped[dict] = mapped_column(JSONType, default=dict)
    hotel_name: Mapped[str] = mapped_column(String(200), default='')
    rooms_count: Mapped[int] = mapped_column(Integer, default=0)
    branches_count: Mapped[int] = mapped_column(Integer, default=1)
    sales_channel: Mapped[str] = mapped_column(String(60), default='DIRECT')
    contract_ref: Mapped[str] = mapped_column(String(120), default='')
    package: Mapped[str] = mapped_column(String(10), default='LOCAL')
    modules: Mapped[list] = mapped_column(JSONType, default=list)
    property_type: Mapped[str] = mapped_column(String(30), default='HOTEL')
    feature_flags: Mapped[dict] = mapped_column(JSONType, default=dict)
    product_revision: Mapped[int] = mapped_column(Integer, default=1)
    plan_code: Mapped[str] = mapped_column(String(40), default='')
    billing_period: Mapped[str] = mapped_column(String(10), default='YEARLY')
    monthly_value: Mapped[Decimal] = mapped_column(Numeric(19, 4),
                                                   default=Decimal('0'))
    tenant_id: Mapped[str] = mapped_column(String(64), default='', index=True)
    activation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    grace_days: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(12), default='TRIAL',
                                        index=True)
    edge_token: Mapped[str] = mapped_column(String(80), default='')
    remind_at: Mapped[list] = mapped_column(JSONType, default=list)
    notes: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=vnow)


class ClientStatusHistory(VendorBase):
    """سجل حالة زمني كامل: سبب + مستخدم + طابع — بلا ثغرة (قبول §8-5)."""
    __tablename__ = 'vendor_client_history'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_uuid)
    client_id: Mapped[str] = mapped_column(ForeignKey('vendor_clients.id'),
                                           index=True)
    from_status: Mapped[str] = mapped_column(String(12), default='')
    to_status: Mapped[str] = mapped_column(String(12))
    reason: Mapped[str] = mapped_column(Text)
    changed_by: Mapped[str] = mapped_column(String(36))
    at: Mapped[datetime] = mapped_column(DateTime, default=vnow)


class Plan(VendorBase):
    """خطة سعر §3: رسوم تأسيس + اشتراك + أسعار إضافات + سقف خصم اعتماد."""
    __tablename__ = 'vendor_plans'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_uuid)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name_ar: Mapped[str] = mapped_column(String(120))
    billing_period: Mapped[str] = mapped_column(String(10), default='YEARLY')
    setup_fee: Mapped[Decimal] = mapped_column(Numeric(19, 4),
                                               default=Decimal('0'))
    base_price: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    module_prices: Mapped[dict] = mapped_column(JSONType, default=dict)
    included_users: Mapped[int] = mapped_column(Integer, default=5)
    included_branches: Mapped[int] = mapped_column(Integer, default=1)
    extra_user_price: Mapped[Decimal] = mapped_column(Numeric(19, 4),
                                                      default=Decimal('0'))
    extra_branch_price: Mapped[Decimal] = mapped_column(Numeric(19, 4),
                                                        default=Decimal('0'))
    discount_max_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2),
                                                      default=Decimal('15'))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=vnow)


class SubscriptionInvoice(VendorBase):
    __tablename__ = 'vendor_invoices'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_uuid)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey('vendor_clients.id'),
                                           index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey('vendor_plans.id'))
    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2),
                                                  default=Decimal('0'))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4),
                                                     default=Decimal('0'))
    total: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    status: Mapped[str] = mapped_column(String(10), default='ISSUED')
    kind: Mapped[str] = mapped_column(String(10), default='RENEWAL')
    notes: Mapped[str] = mapped_column(Text, default='')
    issued_by: Mapped[str] = mapped_column(String(36))
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=vnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Collection(VendorBase):
    """تسجيل تحصيل يدوي موثّق (نقد/تحويل) — بوابات الدفع مرحلة 2 (§3)."""
    __tablename__ = 'vendor_collections'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_uuid)
    invoice_id: Mapped[str] = mapped_column(ForeignKey('vendor_invoices.id'),
                                            index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    method: Mapped[str] = mapped_column(String(12), default='TRANSFER')
    reference: Mapped[str] = mapped_column(String(120))
    collected_by: Mapped[str] = mapped_column(String(36))
    at: Mapped[datetime] = mapped_column(DateTime, default=vnow)
    notes: Mapped[str] = mapped_column(Text, default='')


class LicenseRecord(VendorBase):
    """كل ملف ترخيص أصدرته الشركة — الحمولة الموقعة مخزنة كصندوق."""
    __tablename__ = 'vendor_licenses'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_uuid)
    client_id: Mapped[str] = mapped_column(ForeignKey('vendor_clients.id'),
                                           index=True)
    license_id: Mapped[str] = mapped_column(String(40), index=True)
    serial: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10), default='ISSUE')
    payload_signed: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(18), default='ACTIVE')
    needs_second_approval: Mapped[bool] = mapped_column(Boolean,
                                                        default=False)
    approved_by: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime,
                                                         nullable=True)
    over_plan_reason: Mapped[str] = mapped_column(Text, default='')
    issued_by: Mapped[str] = mapped_column(String(36))
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=vnow)
    expires_at: Mapped[date] = mapped_column(Date)
    __table_args__ = (UniqueConstraint('client_id', 'license_id', 'serial',
                                       name='uq_vlic_serial'),)


class RevocationListRec(VendorBase):
    __tablename__ = 'vendor_revocations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_uuid)
    revocation_serial: Mapped[int] = mapped_column(Integer, unique=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    issued_by: Mapped[str] = mapped_column(String(36))
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=vnow)


class FingerprintAlert(VendorBase):
    """بصمة جهاز ظهرت فجأة على Tenant آخر = علم (ملف 07 §4-5)."""
    __tablename__ = 'vendor_fp_alerts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_uuid)
    fingerprint_hash: Mapped[str] = mapped_column(String(80), index=True)
    seen_on: Mapped[list] = mapped_column(JSONType, default=list)
    at: Mapped[datetime] = mapped_column(DateTime, default=vnow)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class Ticket(VendorBase):
    __tablename__ = 'vendor_tickets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_uuid)
    number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey('vendor_clients.id'),
                                           index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default='')
    category: Mapped[str] = mapped_column(String(12))      # BUG/QUESTION/…
    priority: Mapped[str] = mapped_column(String(3), index=True)
    module: Mapped[str] = mapped_column(String(30), default='GENERAL')
    channel: Mapped[str] = mapped_column(String(12), default='PHONE')
    status: Mapped[str] = mapped_column(String(16), default='NEW', index=True)
    assignee_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sla_due: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    root_cause: Mapped[str] = mapped_column(Text, default='')
    kb_article: Mapped[str] = mapped_column(String(200), default='')
    attachments: Mapped[list] = mapped_column(JSONType, default=list)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=vnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime,
                                                       nullable=True)


class TicketEvent(VendorBase):
    __tablename__ = 'vendor_ticket_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_uuid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey('vendor_tickets.id'),
                                           index=True)
    action: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(Text, default='')
    actor_id: Mapped[str] = mapped_column(String(36))
    at: Mapped[datetime] = mapped_column(DateTime, default=vnow)


class Notification(VendorBase):
    """تنبيهات اللوحة (مهام مبيعات، P1 للمناوب، إلخ) — تسليم فوري داخلي."""
    __tablename__ = 'vendor_notifications'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True,
                                                index=True)
    role: Mapped[str] = mapped_column(String(20), default='')
    kind: Mapped[str] = mapped_column(String(24), index=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    delivered_at: Mapped[datetime] = mapped_column(DateTime, default=vnow)
    state: Mapped[str] = mapped_column(String(10), default='UNREAD')


class Heartbeat(VendorBase):
    """نبض عملاء هجين/سحابي (§6) — مجمَّعة تعاقدية فقط، لا بيانات تشغيل."""
    __tablename__ = 'vendor_heartbeats'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_uuid)
    client_id: Mapped[str] = mapped_column(ForeignKey('vendor_clients.id'),
                                           index=True)
    site_id: Mapped[str] = mapped_column(String(36), default='')
    at: Mapped[datetime] = mapped_column(DateTime, default=vnow, index=True)
    product_version: Mapped[str] = mapped_column(String(20), default='')
    outbox_lag: Mapped[int] = mapped_column(Integer, default=0)
    backup_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    disk_free_gb: Mapped[Decimal] = mapped_column(Numeric(10, 2),
                                                  default=Decimal('0'))
    fingerprint_hash: Mapped[str] = mapped_column(String(80), default='')
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)


class Release(VendorBase):
    __tablename__ = 'vendor_releases'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_uuid)
    version: Mapped[str] = mapped_column(String(20), unique=True)
    ring: Mapped[str] = mapped_column(String(10), default='CANARY')
    notes: Mapped[str] = mapped_column(Text, default='')
    released_by: Mapped[str] = mapped_column(String(36))
    released_at: Mapped[datetime] = mapped_column(DateTime, default=vnow)


class ClientUpdate(VendorBase):
    __tablename__ = 'vendor_client_updates'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_uuid)
    release_id: Mapped[str] = mapped_column(ForeignKey('vendor_releases.id'),
                                            index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey('vendor_clients.id'),
                                           index=True)
    state: Mapped[str] = mapped_column(String(10), default='PENDING')
    error: Mapped[str] = mapped_column(Text, default='')
    at: Mapped[datetime] = mapped_column(DateTime, default=vnow)


class VendorAudit(VendorBase):
    __tablename__ = 'vendor_audit'
    id: Mapped[int] = mapped_column(Integer, primary_key=True,
                                    autoincrement=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    module: Mapped[str] = mapped_column(String(30), index=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime)
    prev_hash: Mapped[str] = mapped_column(String(64))
    row_hash: Mapped[str] = mapped_column(String(64))
    ip: Mapped[str] = mapped_column(String(45), default='')
