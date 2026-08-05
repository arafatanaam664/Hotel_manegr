"""نماذج قاعدة البيانات — تطبق مواصفة 11 (DATABASE_MASTER_SCHEMA) للنواة.
قواعد حاكمة: UUID لكل المفاتيح • tenant_id في كل جدول • مبالغ Numeric(19,4)
لا float أبداً • الماليات إلحاق-فقط (لا update/delete على المرحَّل)."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Index, Integer,
                        Numeric, String, Text, UniqueConstraint, BigInteger)
from sqlalchemy.dialects.sqlite import JSON as JSONType
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

JSONB = MutableDict.as_mutable(JSONType)
# SQLite لهجة خاصة: المفتاح الذاتي يجب أن يكون INTEGER حرفياً (alias للـ rowid)
BigId = BigInteger().with_variant(Integer, 'sqlite')


class Tenant(Base):
    __tablename__ = 'tenants'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(200))
    trade_name: Mapped[str] = mapped_column(String(200), default='')
    country: Mapped[str] = mapped_column(String(2), default='YE')
    base_currency: Mapped[str] = mapped_column(String(3), default='YER')
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, default=1)
    timezone: Mapped[str] = mapped_column(String(50), default='Asia/Aden')
    status: Mapped[str] = mapped_column(String(20), default='ACTIVE')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Branch(Base):
    __tablename__ = 'branches'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'),
                                           index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Role(Base):
    __tablename__ = 'roles'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey('tenants.id'),
                                                  nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(300), default='')
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions: Mapped[list[str]] = mapped_column(JSONType, default=list)

    __table_args__ = (UniqueConstraint('tenant_id', 'code',
                                       name='uq_role_tenant_code'),)


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'),
                                           index=True)
    username: Mapped[str] = mapped_column(String(60))
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret_enc: Mapped[str | None] = mapped_column(String(200),
                                                       nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    branch_ids: Mapped[list] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # اعتماد مدير فوري بـ PIN في نقاط البيع (ملف 04 §3) — مخزن مجزأ argon2
    pos_pin_hash: Mapped[str] = mapped_column(String(300), default='')

    roles: Mapped[list['UserRole']] = relationship(back_populates='user',
                                                   cascade='all,delete')

    __table_args__ = (UniqueConstraint('tenant_id', 'username',
                                       name='uq_user_tenant_username'),)


class UserRole(Base):
    __tablename__ = 'user_roles'
    id: Mapped[int] = mapped_column(Integer, primary_key=True,
                                    autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    role_id: Mapped[str] = mapped_column(ForeignKey('roles.id'))

    user: Mapped[User] = relationship(back_populates='roles')
    role: Mapped[Role] = relationship()

    __table_args__ = (UniqueConstraint('user_id', 'role_id',
                                       name='uq_userrole'),)


class RefreshSession(Base):
    __tablename__ = 'sessions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    family_id: Mapped[str] = mapped_column(String(36), index=True)
    fingerprint_hash: Mapped[str] = mapped_column(String(64), unique=True)
    device_info: Mapped[str] = mapped_column(String(300), default='')
    ip: Mapped[str] = mapped_column(String(50), default='')
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    reused_detected: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    """Append-Only (الإنتاج: REVOKE UPDATE/DELETE + Trigger — انظر sql/)."""
    __tablename__ = 'audit_log'
    id: Mapped[int] = mapped_column(BigId, primary_key=True,
                                    autoincrement=True)
    row_uuid: Mapped[str] = mapped_column(String(36), unique=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                             index=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(36),
                                                      nullable=True)
    actor_type: Mapped[str] = mapped_column(String(20), default='user')
    module: Mapped[str] = mapped_column(String(30), index=True)
    action: Mapped[str] = mapped_column(String(40))
    entity: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    before: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(50), nullable=True)
    business_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    row_hash: Mapped[str] = mapped_column(String(64))


class Currency(Base):
    __tablename__ = 'currencies'
    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    symbol: Mapped[str] = mapped_column(String(8), default='')
    decimal_places: Mapped[int] = mapped_column(Integer, default=2)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ExchangeRate(Base):
    __tablename__ = 'exchange_rates'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    currency_code: Mapped[str] = mapped_column(ForeignKey('currencies.code'))
    rate: Mapped[Decimal] = mapped_column(Numeric(19, 8))
    rate_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(60), default='manual')
    entered_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'currency_code',
                                       'rate_date', name='uq_fx_rate'),)


class FiscalYear(Base):
    __tablename__ = 'fiscal_years'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    year_no: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default='OPEN')
    periods: Mapped[list['FiscalPeriod']] = relationship(
        back_populates='year', cascade='all,delete')
    __table_args__ = (UniqueConstraint('tenant_id', 'year_no', name='uq_fy'),)


class FiscalPeriod(Base):
    __tablename__ = 'fiscal_periods'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fiscal_year_id: Mapped[str] = mapped_column(ForeignKey('fiscal_years.id'),
                                                index=True)
    period_no: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(14), default='OPEN')
    closed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    year: Mapped[FiscalYear] = relationship(back_populates='periods')


class Account(Base):
    __tablename__ = 'accounts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(10))
    name_ar: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120), default='')
    parent_id: Mapped[str | None] = mapped_column(ForeignKey('accounts.id'),
                                                  nullable=True, index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    type: Mapped[str] = mapped_column(String(12))      # ASSET|LIABILITY|...
    nature: Mapped[str] = mapped_column(String(8))     # DEBIT|CREDIT
    is_postable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    party_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (UniqueConstraint('tenant_id', 'code', name='uq_acct'),)


class Tax(Base):
    __tablename__ = 'taxes'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(80))
    rate: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    inclusive: Mapped[bool] = mapped_column(Boolean, default=False)
    liability_account_code: Mapped[str] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CostCenter(Base):
    __tablename__ = 'cost_centers'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(12), default='DEPARTMENT')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PostingMap(Base):
    """خريطة الربط (ملف 02 §6.2): event+context ← قالب قيد JSON."""
    __tablename__ = 'account_mappings'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    context_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    description: Mapped[str] = mapped_column(String(300), default='')
    template: Mapped[list] = mapped_column(JSONType, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'event_type',
                                       'context_key', name='uq_postmap'),)


class JournalEntry(Base):
    """Append-Only بعد POSTED — تعديل/حذف أي مرحَّل ممنوع (ملف 02 §4/§11)."""
    __tablename__ = 'journal_entries'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    branch_id: Mapped[str] = mapped_column(String(36), index=True)
    journal_type: Mapped[str] = mapped_column(String(24), index=True)
    entry_no: Mapped[str] = mapped_column(String(24))
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    posting_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    period_id: Mapped[str] = mapped_column(ForeignKey('fiscal_periods.id'))
    currency_code: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(10), default='DRAFT',
                                        index=True)  # DRAFT|POSTED|REVERSED
    narration: Mapped[str] = mapped_column(String(400), default='')
    reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_key: Mapped[str | None] = mapped_column(String(64), nullable=True,
                                                  unique=True)
    reversed_entry_id: Mapped[str | None] = mapped_column(String(36),
                                                          nullable=True)
    reversal_of_entry_id: Mapped[str | None] = mapped_column(String(36),
                                                             nullable=True)
    created_by: Mapped[str] = mapped_column(String(36))
    posted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    lines: Mapped[list['JournalLine']] = relationship(
        back_populates='entry', cascade='all,delete', order_by='JournalLine.line_no')

    __table_args__ = (UniqueConstraint('tenant_id', 'journal_type',
                                       'entry_no', name='uq_je_no'),
                      Index('ix_je_tenant_date', 'tenant_id', 'entry_date'),)


class JournalLine(Base):
    __tablename__ = 'journal_entry_lines'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entry_id: Mapped[str] = mapped_column(ForeignKey('journal_entries.id'),
                                          index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[str] = mapped_column(ForeignKey('accounts.id'),
                                            index=True)
    debit_base: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    credit_base: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    debit_fcy: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    credit_fcy: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(19, 8),
                                                    nullable=True)
    party_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    party_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cost_center_id: Mapped[str | None] = mapped_column(String(36),
                                                       nullable=True)
    description: Mapped[str] = mapped_column(String(300), default='')

    entry: Mapped[JournalEntry] = relationship(back_populates='lines')


class OutboxEvent(Base):
    """أحداث الترحيل (Outbox) — أساس Idempotency ومستقبل المزامنة (ملفات 02/09)."""
    __tablename__ = 'outbox_events'
    id: Mapped[int] = mapped_column(BigId, primary_key=True,
                                    autoincrement=True)
    event_key: Mapped[str] = mapped_column(String(64), unique=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(12), default='PROCESSED',
                                       index=True)  # PROCESSED|FAILED|DEAD
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal_entry_id: Mapped[str | None] = mapped_column(String(36),
                                                         nullable=True)


class IdempotencyKey(Base):
    __tablename__ = 'idempotency_keys'
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    response_hash: Mapped[str | None] = mapped_column(String(64),
                                                      nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SequenceCounter(Base):
    """تسلسلات الأرقام لكل (مستأجر/نوع/سنة) — تُقفل صفّياً أثناء التخصيص."""
    __tablename__ = 'sequence_counters'
    id: Mapped[int] = mapped_column(Integer, primary_key=True,
                                    autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    year: Mapped[int] = mapped_column(Integer)
    next_no: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (UniqueConstraint('tenant_id', 'kind', 'year',
                                       name='uq_seq'),)


# ════════════════════════════════════════════════════════════════════
# وحدة الفندق — ملف 03 §1 (الكيانات) وملف 11
# ════════════════════════════════════════════════════════════════════

class RoomType(Base):
    __tablename__ = 'room_types'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(16))
    name_ar: Mapped[str] = mapped_column(String(80))
    name_en: Mapped[str] = mapped_column(String(80), default='')
    capacity_adults: Mapped[int] = mapped_column(Integer, default=2)
    capacity_children: Mapped[int] = mapped_column(Integer, default=1)
    beds: Mapped[str] = mapped_column(String(60), default='')
    amenities: Mapped[list] = mapped_column(JSONType, default=list)
    base_rate: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'code', name='uq_rtype'),)


class Room(Base):
    """hk_status: CLEAN|INSPECTED|DIRTY|CLEANING|OOO|OOS (ملف 03 §5).
    الإشغال (FO) مشتق من الإقامات — لا يخزَّن منعاً للتناقض."""
    __tablename__ = 'rooms'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey('branches.id'),
                                           index=True)
    room_no: Mapped[str] = mapped_column(String(10))
    floor: Mapped[int] = mapped_column(Integer, default=1)
    room_type_id: Mapped[str] = mapped_column(ForeignKey('room_types.id'))
    features: Mapped[list] = mapped_column(JSONType, default=list)
    hk_status: Mapped[str] = mapped_column(String(12), default='CLEAN',
                                           index=True)
    ooo_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ooo_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    ooo_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(String(300), default='')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=0)  # قفل تنافسي

    __table_args__ = (UniqueConstraint('tenant_id', 'branch_id', 'room_no',
                                       name='uq_room'),)


class RatePlan(Base):
    __tablename__ = 'rate_plans'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(16))
    name_ar: Mapped[str] = mapped_column(String(80))
    ref_rate: Mapped[Decimal | None] = mapped_column(Numeric(19, 4),
                                                     nullable=True)
    includes_breakfast: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_policy: Mapped[str] = mapped_column(String(300), default='مرن')
    min_nights: Mapped[int] = mapped_column(Integer, default=1)
    for_corporate: Mapped[bool] = mapped_column(Boolean, default=False)
    tax_inclusive: Mapped[bool] = mapped_column(Boolean, default=False)
    meals_included: Mapped[list] = mapped_column(JSONType, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'code', name='uq_rplan'),)


class RateCalendar(Base):
    __tablename__ = 'rate_calendar'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    room_type_id: Mapped[str] = mapped_column(ForeignKey('room_types.id'))
    rate_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey('rate_plans.id'), nullable=True)   # None = السعر الافتراضي
    day: Mapped[date] = mapped_column(Date)
    price: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    day_type: Mapped[str] = mapped_column(String(12), default='NORMAL')

    __table_args__ = (UniqueConstraint('tenant_id', 'room_type_id',
                                       'rate_plan_id', 'day', name='uq_rcal'),)


class Extra(Base):
    """خدمة إضافية قابلة للتحميل على الفوليو (ملف 03 §1.5) — حساب إيرادها من خريطة الربط."""
    __tablename__ = 'extras'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name_ar: Mapped[str] = mapped_column(String(80))
    price: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    revenue_account_code: Mapped[str] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'code', name='uq_extra'),)


class Guest(Base):
    """هوية النزيل مشفرة ساكناً (ملف 10 §Data — لا تخزَّن صريحة أبداً)."""
    __tablename__ = 'guests'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(30), default='')
    id_number_enc: Mapped[str] = mapped_column(Text, default='')
    nationality: Mapped[str] = mapped_column(String(50), default='')
    vip: Mapped[bool] = mapped_column(Boolean, default=False)
    blacklist: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(String(300), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Corporate(Base):
    __tablename__ = 'corporates'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    contact_person: Mapped[str] = mapped_column(String(80), default='')
    phone: Mapped[str] = mapped_column(String(30), default='')
    email: Mapped[str] = mapped_column(String(120), default='')
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(19, 4),
                                                         nullable=True)
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=0)
    settlement_period: Mapped[str] = mapped_column(String(12),
                                                   default='MONTHLY')
    billing_tax_note: Mapped[str] = mapped_column(String(200), default='')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Reservation(Base):
    """State Machine (ملف 03 §2): TENTATIVE→CONFIRMED→CHECKED_IN→CHECKED_OUT
    أفرع نهائية: CANCELLED | NO_SHOW — مراكز التحويل تفرضها الخدمة فقط."""
    __tablename__ = 'reservations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey('branches.id'),
                                           index=True)
    confirmation_no: Mapped[str] = mapped_column(String(24))
    guest_id: Mapped[str] = mapped_column(ForeignKey('guests.id'), index=True)
    corporate_id: Mapped[str | None] = mapped_column(
        ForeignKey('corporates.id'), nullable=True)
    room_type_id: Mapped[str] = mapped_column(ForeignKey('room_types.id'))
    room_id: Mapped[str | None] = mapped_column(ForeignKey('rooms.id'),
                                                nullable=True)
    rate_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey('rate_plans.id'), nullable=True)
    arrival_date: Mapped[date] = mapped_column(Date, index=True)
    departure_date: Mapped[date] = mapped_column(Date, index=True)
    nights: Mapped[int] = mapped_column(Integer)
    adults: Mapped[int] = mapped_column(Integer, default=1)
    children: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(14), default='TENTATIVE',
                                        index=True)
    source: Mapped[str] = mapped_column(String(12), default='DIRECT')
    agreed_rate: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    est_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    cancel_reason: Mapped[str | None] = mapped_column(String(300),
                                                      nullable=True)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    checked_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)  # قفل تفاؤلي

    __table_args__ = (UniqueConstraint('tenant_id', 'confirmation_no',
                                       name='uq_rsv'),
                      Index('ix_rsv_room_dates', 'tenant_id', 'room_id',
                            'arrival_date', 'departure_date'),)

    # منع إقصائي زمني مطلق للحجز المزدوج (Postgres في الإنتاج):
    # انظر sql/postgres_hardening.sql — قيد exclusion على daterange.


class ReservationNightRate(Base):
    """Snapshot لسعر كل ليلة (ملف 03 §2: الليالي المنقضية بسعرها القديم)."""
    __tablename__ = 'reservation_night_rates'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    reservation_id: Mapped[str] = mapped_column(
        ForeignKey('reservations.id'), index=True)
    stay_date: Mapped[date] = mapped_column(Date)
    room_id: Mapped[str | None] = mapped_column(ForeignKey('rooms.id'),
                                                nullable=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    rate_origin: Mapped[str] = mapped_column(String(12), default='BASE')

    __table_args__ = (UniqueConstraint('reservation_id', 'stay_date',
                                       name='uq_nightrate'),)


class ReservationStay(Base):
    """شرائح الإقامة الفعلية — يدعم نقل النزيل بين الغرف بنفس الفوليو (§2)."""
    __tablename__ = 'reservation_stays'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    reservation_id: Mapped[str] = mapped_column(
        ForeignKey('reservations.id'), index=True)
    room_id: Mapped[str] = mapped_column(ForeignKey('rooms.id'))
    from_date: Mapped[date] = mapped_column(Date)
    to_date: Mapped[date] = mapped_column(Date)
    seq: Mapped[int] = mapped_column(Integer, default=1)


class Folio(Base):
    """فاتورة نزيل داخل الفندق — بلا عمود رصيد: الرصيد يُشتق لحظياً من دفتر
    1110/1120 بمطابقة الطرف (معيار القبول #2 في ملف 03)."""
    __tablename__ = 'folios'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    branch_id: Mapped[str] = mapped_column(String(36), index=True)
    reservation_id: Mapped[str] = mapped_column(
        ForeignKey('reservations.id'), index=True)
    window: Mapped[int] = mapped_column(Integer, default=1)
    type: Mapped[str] = mapped_column(String(10), default='GUEST')
    corporate_id: Mapped[str | None] = mapped_column(
        ForeignKey('corporates.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(8), default='OPEN', index=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(19, 4),
                                                         nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (UniqueConstraint('reservation_id', 'window',
                                       name='uq_folio_window'),)


class NightAuditRun(Base):
    __tablename__ = 'night_audit_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    business_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(10), default='COMPLETED')
    steps: Mapped[list] = mapped_column(JSONType, default=list)
    totals: Mapped[dict] = mapped_column(JSONType, default=dict)
    report_snapshot: Mapped[dict] = mapped_column(JSONType, default=dict)
    started_by: Mapped[str] = mapped_column(String(36))
    completed_by: Mapped[str | None] = mapped_column(String(36),
                                                     nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class BusinessDateState(Base):
    """تاريخ العمل الفندقي — يتقدم فقط بإتمام التدقيق الليلي (ملف 03 §4)."""
    __tablename__ = 'business_date_state'
    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    current_business_date: Mapped[date] = mapped_column(Date)
    last_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GuestInvoice(Base):
    """الفاتورة الضريبية النهائية عند Check-out — غير قابلة للتعديل بتاتاً
    (إعادة الفتح ممنوعة؛ التصحيح بإشعار دائن + قيد عكسي — ملف 03 §3.3)."""
    __tablename__ = 'guest_invoices'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    branch_id: Mapped[str] = mapped_column(String(36), index=True)
    reservation_id: Mapped[str] = mapped_column(
        ForeignKey('reservations.id'))
    folio_id: Mapped[str] = mapped_column(String(36))
    invoice_no: Mapped[str] = mapped_column(String(24))
    guest_name: Mapped[str] = mapped_column(String(120))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    issued_by: Mapped[str] = mapped_column(String(36))
    lines: Mapped[list] = mapped_column(JSONType, default=list)
    total_charges: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    total_payments: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    balance_settled: Mapped[Decimal] = mapped_column(Numeric(19, 4),
                                                     default=0)

    __table_args__ = (UniqueConstraint('tenant_id', 'invoice_no',
                                       name='uq_invoice'),)


# ════════════════════════════════════════════════════════════════════
# وحدة نقاط البيع POS — ملف 04 (POS_MODULE_SPEC) كقانون ملزم
# ════════════════════════════════════════════════════════════════════

class PosOutlet(Base):
    """منفذ بيع (ملف 04 §1): صندوق نقد فرعي + سياسة مخزون + تسلسل فواتير."""
    __tablename__ = 'pos_outlets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey('branches.id'),
                                           index=True)
    code: Mapped[str] = mapped_column(String(12))
    name_ar: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120), default='')
    cash_account_code: Mapped[str] = mapped_column(String(8), default='1102')
    default_revenue_account_code: Mapped[str] = mapped_column(
        String(8), default='4201')
    house_expense_account_code: Mapped[str] = mapped_column(
        String(8), default='6610')
    # منع البيع بالسالب هو الافتراضي (§3 «قواعد صارمة»)؛ السماح = تنبيه فقط
    allow_negative_stock: Mapped[bool] = mapped_column(Boolean, default=False)
    cash_variance_tolerance: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), default=10)
    cost_center_code: Mapped[str] = mapped_column(String(16), default='')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # مستودع المنفذ في وحدة المخزون (ملف 04 §1 «مستودع افتراضي» — ADR-0017)
    warehouse_id: Mapped[str | None] = mapped_column(String(36),
                                                     nullable=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'code',
                                       name='uq_pos_outlet'),)


class PosCategory(Base):
    __tablename__ = 'pos_categories'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(12))
    name_ar: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120), default='')
    color: Mapped[str] = mapped_column(String(9), default='#0e7490')
    station: Mapped[str] = mapped_column(String(12), default='KITCHEN')
    sort_order: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'code',
                                       name='uq_pos_category'),)


class PosItem(Base):
    """صنف بيع (§2): مخزوني ينقّص | خدمي لا ينقّص | مركّب له وصفة (05 §6)."""
    __tablename__ = 'pos_items'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(16))
    barcode: Mapped[str] = mapped_column(String(40), default='', index=True)
    name_ar: Mapped[str] = mapped_column(String(160))
    name_en: Mapped[str] = mapped_column(String(160), default='')
    category_id: Mapped[str] = mapped_column(ForeignKey('pos_categories.id'))
    price: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    tax_included: Mapped[bool] = mapped_column(Boolean, default=True)
    revenue_account_code: Mapped[str] = mapped_column(String(8),
                                                      default='4201')
    item_type: Mapped[str] = mapped_column(String(10), default='SERVICE')
    cost: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint('tenant_id', 'code',
                                       name='uq_pos_item'),)


class PosModifier(Base):
    """معدِّل (إضافة/بديل بسعر) يتبع الصنف في الفاتورة والتكلفة (§2)."""
    __tablename__ = 'pos_modifiers'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name_ar: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120), default='')
    price: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PosItemModifier(Base):
    __tablename__ = 'pos_item_modifiers'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('pos_items.id'),
                                         index=True)
    modifier_id: Mapped[str] = mapped_column(ForeignKey('pos_modifiers.id'))

    __table_args__ = (UniqueConstraint('item_id', 'modifier_id',
                                       name='uq_pos_item_mod'),)


class PosRecipe(Base):
    """وصفة صنف مركّب: مكوّن + كمية لكل وحدة مبيع (§2، وقبول #3 حرفية)."""
    __tablename__ = 'pos_recipes'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    parent_item_id: Mapped[str] = mapped_column(ForeignKey('pos_items.id'),
                                                index=True)
    component_item_id: Mapped[str] = mapped_column(
        ForeignKey('pos_items.id'))
    qty: Mapped[Decimal] = mapped_column(Numeric(19, 4))

    __table_args__ = (UniqueConstraint('parent_item_id', 'component_item_id',
                                       name='uq_pos_recipe'),)


class PosStock(Base):
    """رصيد تشغيلي أدنى لكل منفذ (ADR-0013) — الجرد الكامل والتقييم المتحرك
    في المرحلة 5 (ملف 05)؛ هنا يخدم قاعدة §3: منع السالب + خصم الوصفة."""
    __tablename__ = 'pos_stock'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    outlet_id: Mapped[str] = mapped_column(ForeignKey('pos_outlets.id'),
                                           index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('pos_items.id'))
    qty_on_hand: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)

    __table_args__ = (UniqueConstraint('outlet_id', 'item_id',
                                       name='uq_pos_stock'),)


class PosStockMove(Base):
    """سجل حركة إلحاقي (لا تعديل): افتتاح/بيع/مرتجع/تسوية."""
    __tablename__ = 'pos_stock_moves'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    outlet_id: Mapped[str] = mapped_column(String(36), index=True)
    item_id: Mapped[str] = mapped_column(String(36), index=True)
    qty_delta: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    reason: Mapped[str] = mapped_column(String(10))  # OPEN|SALE|RETURN|ADJUST
    ref_id: Mapped[str] = mapped_column(String(36), default='')
    actor_id: Mapped[str] = mapped_column(String(36), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PosTable(Base):
    """طاولة مطعم اختيارية (§2) — الحالة مشتقة من الطلب المفتوح عليها."""
    __tablename__ = 'pos_tables'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    outlet_id: Mapped[str] = mapped_column(ForeignKey('pos_outlets.id'),
                                           index=True)
    name: Mapped[str] = mapped_column(String(40))
    zone: Mapped[str] = mapped_column(String(40), default='القاعة الرئيسية')
    seats: Mapped[int] = mapped_column(Integer, default=4)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint('outlet_id', 'name',
                                       name='uq_pos_table'),)


class PosShift(Base):
    """وردية (§3.5): لا تُفتح جديدة قبل إقفال السابقة؛ Z-Report أرشيف مغلق."""
    __tablename__ = 'pos_shifts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    outlet_id: Mapped[str] = mapped_column(ForeignKey('pos_outlets.id'),
                                           index=True)
    opened_by: Mapped[str] = mapped_column(String(36))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    opening_float: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    status: Mapped[str] = mapped_column(String(8), default='OPEN', index=True)
    closed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    actual_cash: Mapped[Decimal | None] = mapped_column(Numeric(19, 4),
                                                        nullable=True)
    expected_cash: Mapped[Decimal | None] = mapped_column(Numeric(19, 4),
                                                          nullable=True)
    cash_variance: Mapped[Decimal | None] = mapped_column(Numeric(19, 4),
                                                          nullable=True)
    variance_entry_id: Mapped[str | None] = mapped_column(String(36),
                                                          nullable=True)
    zreport: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class PosOrder(Base):
    """طلب (§3): مسودة بلا أثر → FIRED مرسل للتحضير → CLOSED مُسدَّد بفاتورة."""
    __tablename__ = 'pos_orders'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    outlet_id: Mapped[str] = mapped_column(ForeignKey('pos_outlets.id'),
                                           index=True)
    shift_id: Mapped[str] = mapped_column(ForeignKey('pos_shifts.id'))
    table_id: Mapped[str | None] = mapped_column(ForeignKey('pos_tables.id'),
                                                 nullable=True)
    type: Mapped[str] = mapped_column(String(14), default='DINE_IN')
    status: Mapped[str] = mapped_column(String(10), default='DRAFT',
                                        index=True)
    room_reservation_id: Mapped[str | None] = mapped_column(
        ForeignKey('reservations.id'), nullable=True)
    note: Mapped[str] = mapped_column(String(200), default='')
    cancel_reason: Mapped[str | None] = mapped_column(String(200),
                                                      nullable=True)
    opened_by: Mapped[str] = mapped_column(String(36))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)


class PosOrderLine(Base):
    """بند طلب — السعر والاسم Snapshot لحظة الإضافة (مبدأ الثبات التاريخي)."""
    __tablename__ = 'pos_order_lines'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey('pos_orders.id'),
                                          index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('pos_items.id'))
    item_name: Mapped[str] = mapped_column(String(160))
    station: Mapped[str] = mapped_column(String(12), default='KITCHEN')
    qty: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    modifiers: Mapped[list] = mapped_column(JSONType, default=list)
    notes: Mapped[str] = mapped_column(String(200), default='')
    line_total: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    discount: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    status: Mapped[str] = mapped_column(String(8), default='NORMAL')
    void_reason: Mapped[str | None] = mapped_column(String(200),
                                                    nullable=True)
    void_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class PosInvoice(Base):
    """فاتورة POS — غير قابلة للتعديل بعد الإقفال إطلاقاً.
    المرتجع: فاتورة منفصلة type=RETURN بقيد عكسي كامل (§3.4).
    client_uuid: مفتاح idempotency ولّده العميل — أساس متانة الشبكة (قبول #4)."""
    __tablename__ = 'pos_invoices'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    outlet_id: Mapped[str] = mapped_column(ForeignKey('pos_outlets.id'),
                                           index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey('pos_orders.id'))
    shift_id: Mapped[str] = mapped_column(ForeignKey('pos_shifts.id'),
                                          index=True)
    invoice_no: Mapped[str] = mapped_column(String(24))
    client_uuid: Mapped[str] = mapped_column(String(40))
    type: Mapped[str] = mapped_column(String(8), default='SALE')
    return_of_id: Mapped[str | None] = mapped_column(String(36),
                                                     nullable=True)
    return_reason: Mapped[str | None] = mapped_column(String(200),
                                                      nullable=True)
    business_date: Mapped[date] = mapped_column(Date, index=True)
    gross_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    net_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    cost_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    sale_entry_id: Mapped[str | None] = mapped_column(String(36),
                                                      nullable=True)
    cogs_entry_id: Mapped[str | None] = mapped_column(String(36),
                                                      nullable=True)
    lines_snapshot: Mapped[list] = mapped_column(JSONType, default=list)
    issued_by: Mapped[str] = mapped_column(String(36))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    printed_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint('tenant_id', 'outlet_id', 'invoice_no',
                         name='uq_pos_invoice_no'),
        UniqueConstraint('tenant_id', 'client_uuid',
                         name='uq_pos_invoice_client'),
        Index('ix_pos_inv_shift_date', 'tenant_id', 'shift_id',
              'business_date'))


class PosPayment(Base):
    """سند دفع متفرق (Split §2) — المجموع يجب أن يساوي صافي الفاتورة."""
    __tablename__ = 'pos_payments'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey('pos_invoices.id'),
                                            index=True)
    method: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    folio_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    room_no: Mapped[str | None] = mapped_column(String(10), nullable=True)
    corporate_id: Mapped[str | None] = mapped_column(String(36),
                                                     nullable=True)
    house_approved_by: Mapped[str | None] = mapped_column(String(36),
                                                          nullable=True)
    house_reason: Mapped[str | None] = mapped_column(String(200),
                                                     nullable=True)


# ════════════════════════════════════════════════════════════════════
# وحدة المخزون والمشتريات — ملف 05 (INVENTORY_SPEC) كقانون ملزم
# القواعد الحاكمة:
# - متوسط مرجح متحرك لكل (صنف/مستودع) — ثابت القيمة: qty×avg = قيمة دفترية
#   تساوي رصيد حساب المخزون في الأستاذ يومياً (قبول §7.2)
# - كل حركة Append-Only في inv_moves (الكمية، التكلفة لحظتها، المستند،
#   المستخدم، الدفعة/الصلاحية — §3)
# - حساب المستودع المالي هو المرجع في قيود الحركة (§1: لكل مستودع حساب)
# - GRN المرحَّل غير قابل للتعديل إطلاقاً — التصحيح بعكس + جديد (§2 قاعدة)
# ════════════════════════════════════════════════════════════════════

class InvCategory(Base):
    """تصنيف أصناف (§1): أغذية/مشروبات/مستلزمات غرف/صيانة/قرطاسية...

    valuation_method: AVG مدعوم فعلياً؛ FIFO محجوز ويُقفل بعد أول حركة
    (§4) — تفعيله الفعلي مؤجل بقرار موثق (ADR-0018)."""
    __tablename__ = 'inv_categories'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(12))
    name_ar: Mapped[str] = mapped_column(String(120))
    default_account_code: Mapped[str] = mapped_column(String(8),
                                                      default='1210')
    valuation_method: Mapped[str] = mapped_column(String(4), default='AVG')
    method_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'code',
                                       name='uq_inv_category'),)


class InvItem(Base):
    """صنف مخزون (§1): وحدة أساسية + بدائل بمعامل إلزامي، حد إعادة طلب
    وحد أمان، حساب مخزون افتراضي، تتبع دفعات/صلاحية اختياري.
    pos_item_id: جسر المرحلة 4 — صنف POS مخزوني ↔ صنف مخزون (ADR-0017)."""
    __tablename__ = 'inv_items'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(16))
    name_ar: Mapped[str] = mapped_column(String(160))
    name_en: Mapped[str] = mapped_column(String(160), default='')
    category_id: Mapped[str] = mapped_column(ForeignKey('inv_categories.id'))
    base_unit: Mapped[str] = mapped_column(String(12), default='حبة')
    alt_units: Mapped[list] = mapped_column(JSONType, default=list)
    barcode: Mapped[str] = mapped_column(String(40), default='', index=True)
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    safety_level: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    inventory_account_code: Mapped[str] = mapped_column(String(8),
                                                        default='1210')
    track_expiry: Mapped[bool] = mapped_column(Boolean, default=False)
    pos_item_id: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True,
                                                    unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint('tenant_id', 'code',
                                       name='uq_inv_item'),)


class InvWarehouse(Base):
    """مستودع (§1): رئيسي/فرعي/منفذ POS؛ له حساب مخزون مالي (المشاركة
    مسموحة) وأمين مسؤول (RBAC + عهدة)."""
    __tablename__ = 'inv_warehouses'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey('branches.id'),
                                           index=True)
    code: Mapped[str] = mapped_column(String(12))
    name_ar: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(8), default='SUB')  # MAIN|SUB|OUTLET
    inventory_account_code: Mapped[str] = mapped_column(String(8),
                                                        default='1210')
    keeper_user_id: Mapped[str | None] = mapped_column(String(36),
                                                       nullable=True)
    allow_negative: Mapped[bool] = mapped_column(Boolean, default=False)
    pos_outlet_id: Mapped[str | None] = mapped_column(String(36),
                                                      nullable=True,
                                                      unique=True)
    cost_center_code: Mapped[str] = mapped_column(String(16), default='')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'code',
                                       name='uq_inv_warehouse'),)


class InvStock(Base):
    """رصيد (صنف/مستودع): الكمية + المتوسط المرجح المتحرك — يُحدَّثان
    ذرّياً عبر محرك الحركة فقط، والخصم المحروس يمنع السالب (قبول §7.1)."""
    __tablename__ = 'inv_stock'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    warehouse_id: Mapped[str] = mapped_column(
        ForeignKey('inv_warehouses.id'), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('inv_items.id'),
                                         index=True)
    qty_on_hand: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)

    __table_args__ = (UniqueConstraint('warehouse_id', 'item_id',
                                       name='uq_inv_stock'),)


class InvMove(Base):
    """سجل حركة إلحاقي (لا تعديل/حذف): الكمية الموقعة، التكلفة لحظتها،
    المستند، المستخدم، الدفعة/الصلاحية (§3 حرفياً)."""
    __tablename__ = 'inv_moves'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    warehouse_id: Mapped[str] = mapped_column(String(36), index=True)
    item_id: Mapped[str] = mapped_column(String(36), index=True)
    business_date: Mapped[date] = mapped_column(Date, index=True)
    qty_delta: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    value_delta: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    reason: Mapped[str] = mapped_column(String(16), index=True)
    # OPENING|PURCHASE|PURCHASE_REV|PURCHASE_RETURN|ISSUE_OUT|ISSUE_IN|
    # TRANSFER_OUT|TRANSFER_IN|WASTE|COUNT_SHORT|COUNT_OVER|
    # SALE_POS|POS_RETURN|ADJUST
    ref_type: Mapped[str] = mapped_column(String(12), default='')
    ref_id: Mapped[str] = mapped_column(String(36), default='', index=True)
    batch_no: Mapped[str] = mapped_column(String(40), default='')
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actor_id: Mapped[str] = mapped_column(String(36), default='')
    entry_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index('ix_inv_moves_wh_item', 'tenant_id',
                            'warehouse_id', 'item_id'),)


class InvSupplier(Base):
    """مورد (§1): شروط سداد، عملة، تقييم أداء — ذمته على 2101 بمطابقة
    الطرف SUPPLIER."""
    __tablename__ = 'inv_suppliers'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(160))
    contact_person: Mapped[str] = mapped_column(String(80), default='')
    phone: Mapped[str] = mapped_column(String(30), default='')
    address: Mapped[str] = mapped_column(String(200), default='')
    terms_days: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default='BASE')
    notes: Mapped[str] = mapped_column(String(300), default='')
    rating_commitment: Mapped[int] = mapped_column(Integer, default=3)
    rating_quality: Mapped[int] = mapped_column(Integer, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'code',
                                       name='uq_inv_supplier'),)


class InvSupplierPrice(Base):
    """سعر تعاقدي مؤرخ (§1): من تاريخ/إلى تاريخ — يقترح على PO تلقائياً."""
    __tablename__ = 'inv_supplier_prices'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    supplier_id: Mapped[str] = mapped_column(
        ForeignKey('inv_suppliers.id'), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('inv_items.id'),
                                         index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (UniqueConstraint('supplier_id', 'item_id',
                                       'valid_from', name='uq_inv_supprice'),)


class InvPurchaseRequest(Base):
    """طلب شراء داخلي اختياري (§2.1): من قسم → اعتماد حسب سقف."""
    __tablename__ = 'inv_prs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    pr_no: Mapped[str] = mapped_column(String(24))
    department: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(12), default='DRAFT',
                                        index=True)
    # DRAFT|SUBMITTED|APPROVED|REJECTED|CONVERTED
    notes: Mapped[str] = mapped_column(String(300), default='')
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(300),
                                                      nullable=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'pr_no',
                                       name='uq_inv_pr'),)


class InvPRLine(Base):
    __tablename__ = 'inv_pr_lines'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    pr_id: Mapped[str] = mapped_column(ForeignKey('inv_prs.id'), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('inv_items.id'))
    qty: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    note: Mapped[str] = mapped_column(String(200), default='')


class InvPurchaseOrder(Base):
    """أمر شراء (§2.2): الاعتماد على سلم القيمة (ملف 14 §2):
    ≤ حد الأمين L0 ذاتي | L1 مدير القسم | L2 مالية — لا اعتماد ذاتي."""
    __tablename__ = 'inv_purchase_orders'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    po_no: Mapped[str] = mapped_column(String(24))
    supplier_id: Mapped[str] = mapped_column(ForeignKey('inv_suppliers.id'),
                                             index=True)
    pr_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    terms: Mapped[str] = mapped_column(String(200), default='')
    status: Mapped[str] = mapped_column(String(16), default='DRAFT',
                                        index=True)
    # DRAFT|PENDING_L1|PENDING_L2|APPROVED|REJECTED|PART_RECEIVED|RECEIVED|CANCELLED
    approve_level_required: Mapped[int] = mapped_column(Integer, default=0)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved1_by: Mapped[str | None] = mapped_column(String(36),
                                                     nullable=True)
    approved1_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    approved2_by: Mapped[str | None] = mapped_column(String(36),
                                                     nullable=True)
    approved2_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(300),
                                                      nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint('tenant_id', 'po_no',
                                       name='uq_inv_po'),)


class InvPOLine(Base):
    """بند أمر شراء: الكمية بوحدة الشراء + المعامل إلزامي (§1 أدوات) —
    base_qty = qty × factor هي مرجع الاستلام."""
    __tablename__ = 'inv_po_lines'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    po_id: Mapped[str] = mapped_column(
        ForeignKey('inv_purchase_orders.id'), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('inv_items.id'))
    uom: Mapped[str] = mapped_column(String(12), default='حبة')
    factor: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=1)
    qty: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    base_qty: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(19, 4))  # للأساسية
    line_total: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    received_qty: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)


class InvGRN(Base):
    """سند استلام بضاعة (§2.3): بعد POSTED يصبح غير قابل للتعديل إطلاقاً
    من كل المسارات (قبول §7.4) — التصحيح بعكس + سند جديد فقط."""
    __tablename__ = 'inv_grns'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    grn_no: Mapped[str] = mapped_column(String(24))
    po_id: Mapped[str | None] = mapped_column(String(36), nullable=True,
                                              index=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey('inv_suppliers.id'),
                                             index=True)
    warehouse_id: Mapped[str] = mapped_column(
        ForeignKey('inv_warehouses.id'), index=True)
    purchase_type: Mapped[str] = mapped_column(String(6), default='CASH')
    supplier_invoice_no: Mapped[str] = mapped_column(String(40), default='')
    payment_account_code: Mapped[str] = mapped_column(String(8),
                                                      default='1101')
    status: Mapped[str] = mapped_column(String(10), default='DRAFT',
                                        index=True)  # DRAFT|POSTED|REVERSED
    subtotal: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    entry_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reversal_entry_id: Mapped[str | None] = mapped_column(String(36),
                                                          nullable=True)
    note: Mapped[str] = mapped_column(String(300), default='')
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    posted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'grn_no',
                                       name='uq_inv_grn'),)


class InvGRNLine(Base):
    """سطر استلام: مقبول = مستلم − مرفوض؛ فروقات الكمية بسقف٪ على PO (§2.3)."""
    __tablename__ = 'inv_grn_lines'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    grn_id: Mapped[str] = mapped_column(ForeignKey('inv_grns.id'),
                                        index=True)
    po_line_id: Mapped[str | None] = mapped_column(String(36),
                                                   nullable=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('inv_items.id'))
    qty_ordered: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    qty_received: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    qty_rejected: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    reject_reason: Mapped[str | None] = mapped_column(String(200),
                                                      nullable=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    line_total: Mapped[Decimal] = mapped_column(Numeric(19, 4))  # مقبول×سعر
    batch_no: Mapped[str] = mapped_column(String(40), default='')
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class InvSupplierInvoice(Base):
    """فاتورة مورد + مطابقة ثلاثية (§2.4): PO ↔ GRN ↔ Invoice؛ أي فرق
    سعر/كمية خارج التسامح → VARIANCE_HOLD تلقائياً (قبول §7.3)."""
    __tablename__ = 'inv_supplier_invoices'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    sinv_no: Mapped[str] = mapped_column(String(24))
    supplier_invoice_no: Mapped[str] = mapped_column(String(40))
    supplier_id: Mapped[str] = mapped_column(ForeignKey('inv_suppliers.id'),
                                             index=True)
    po_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    grn_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    invoice_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(14), default='DRAFT',
                                        index=True)
    # DRAFT|MATCHED|VARIANCE_HOLD|APPROVED|PAID|CANCELLED
    subtotal: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    match_report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    variance_entry_id: Mapped[str | None] = mapped_column(String(36),
                                                          nullable=True)
    variance_approved_by: Mapped[str | None] = mapped_column(String(36),
                                                             nullable=True)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'sinv_no',
                                       name='uq_inv_sinv'),
                      UniqueConstraint('tenant_id', 'supplier_id',
                                       'supplier_invoice_no',
                                       name='uq_inv_sinv_ext'),)


class InvSILine(Base):
    __tablename__ = 'inv_si_lines'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    sinv_id: Mapped[str] = mapped_column(
        ForeignKey('inv_supplier_invoices.id'), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('inv_items.id'))
    qty: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    line_total: Mapped[Decimal] = mapped_column(Numeric(19, 4))


class InvSupplierPayment(Base):
    """سداد مورد (§2.5 / حدث #16): Dr 2101 طرف | Cr نقد/بنك، وخصم مكتسب
    يُقيد دائناً 4901 دائماً. التخصيص على فواتير محددة + فائض ذمة."""
    __tablename__ = 'inv_supplier_payments'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    pay_no: Mapped[str] = mapped_column(String(24))
    supplier_id: Mapped[str] = mapped_column(ForeignKey('inv_suppliers.id'),
                                             index=True)
    payment_date: Mapped[date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(8), default='CASH')
    account_code: Mapped[str] = mapped_column(String(8), default='1101')
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    discount: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    allocations: Mapped[list] = mapped_column(JSONType, default=list)
    entry_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint('tenant_id', 'pay_no',
                                       name='uq_inv_pay'),)


class InvSupplierReturn(Base):
    """مرتجع للمورد (§2.6 / حدث #17) بمستند مستقل: Dr 2101 أو 1101 |
    Cr حساب المستودع — يخفض الرصيد بالمتوسط المتحرك لحظتها."""
    __tablename__ = 'inv_supplier_returns'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    srt_no: Mapped[str] = mapped_column(String(24))
    supplier_id: Mapped[str] = mapped_column(ForeignKey('inv_suppliers.id'),
                                             index=True)
    warehouse_id: Mapped[str] = mapped_column(
        ForeignKey('inv_warehouses.id'), index=True)
    grn_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    refund_to: Mapped[str] = mapped_column(String(10), default='CREDIT_AP')
    status: Mapped[str] = mapped_column(String(10), default='DRAFT',
                                        index=True)  # DRAFT|POSTED
    total: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    entry_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reason: Mapped[str] = mapped_column(String(300), default='')
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'srt_no',
                                       name='uq_inv_srt'),)


class InvSRTLine(Base):
    __tablename__ = 'inv_srt_lines'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    srt_id: Mapped[str] = mapped_column(
        ForeignKey('inv_supplier_returns.id'), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('inv_items.id'))
    qty: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    line_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)


class InvIssue(Base):
    """صرف مواد لقسم (§3 / حدث #18): طلب ← اعتماد ← صرف؛ تحويل بين
    مستودعات بلا أثر دخل (القيد فقط إن اختلف حسابا المستودعين)."""
    __tablename__ = 'inv_issues'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    iss_no: Mapped[str] = mapped_column(String(24))
    from_warehouse_id: Mapped[str] = mapped_column(
        ForeignKey('inv_warehouses.id'), index=True)
    to_warehouse_id: Mapped[str] = mapped_column(
        ForeignKey('inv_warehouses.id'))
    department: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(12), default='REQUESTED',
                                        index=True)
    # REQUESTED|APPROVED|REJECTED|ISSUED
    reason: Mapped[str] = mapped_column(String(300), default='')
    entry_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    issued_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'iss_no',
                                       name='uq_inv_issue'),)


class InvIssueLine(Base):
    __tablename__ = 'inv_issue_lines'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    issue_id: Mapped[str] = mapped_column(ForeignKey('inv_issues.id'),
                                          index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('inv_items.id'))
    qty: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(19, 4),
                                                      nullable=True)
    line_value: Mapped[Decimal | None] = mapped_column(Numeric(19, 4),
                                                       nullable=True)


class InvTransfer(Base):
    """تحويل بين مستودعات بمسوغ (§3): «على الطريق» للاستلام اللاحق
    (requires_receive) — الخصم عند الشحن والإضافة عند الاستلام."""
    __tablename__ = 'inv_transfers'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    trf_no: Mapped[str] = mapped_column(String(24))
    from_warehouse_id: Mapped[str] = mapped_column(
        ForeignKey('inv_warehouses.id'), index=True)
    to_warehouse_id: Mapped[str] = mapped_column(
        ForeignKey('inv_warehouses.id'))
    requires_receive: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(12), default='DRAFT',
                                        index=True)
    # DRAFT|IN_TRANSIT|RECEIVED|CANCELLED
    reason: Mapped[str] = mapped_column(String(300))
    entry_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dispatched_by: Mapped[str | None] = mapped_column(String(36),
                                                      nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    received_by: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'trf_no',
                                       name='uq_inv_trf'),)


class InvTransferLine(Base):
    __tablename__ = 'inv_transfer_lines'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    transfer_id: Mapped[str] = mapped_column(
        ForeignKey('inv_transfers.id'), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('inv_items.id'))
    qty: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(19, 4),
                                                      nullable=True)


class InvWaste(Base):
    """هالك/تالف (§3 / حدث #19): مستند + صورة + اعتماد + سبب؛ إحصائية
    شهرية من حركات WASTE."""
    __tablename__ = 'inv_waste'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    wst_no: Mapped[str] = mapped_column(String(24))
    warehouse_id: Mapped[str] = mapped_column(
        ForeignKey('inv_warehouses.id'), index=True)
    status: Mapped[str] = mapped_column(String(10), default='DRAFT',
                                        index=True)  # DRAFT|PENDING|POSTED|REJECTED
    reason: Mapped[str] = mapped_column(String(300))
    photo_ref: Mapped[str] = mapped_column(String(200), default='')
    total_value: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    entry_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(300),
                                                      nullable=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'wst_no',
                                       name='uq_inv_wst'),)


class InvWasteLine(Base):
    __tablename__ = 'inv_waste_lines'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    waste_id: Mapped[str] = mapped_column(ForeignKey('inv_waste.id'),
                                          index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('inv_items.id'))
    qty: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    line_value: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    line_reason: Mapped[str] = mapped_column(String(200), default='')


class InvCount(Base):
    """جرد دوري (§4): تجميد الحركة على النطاق ← عدّ ← فروقات ← اعتماد
    مزدوج (ملف 14: أمين+مالية ثم مدير عام) ← تسويات #19/#20 بالهللة
    (قبول §7.5). الجرد الشامل إلزامي قبل الإقفال السنوي."""
    __tablename__ = 'inv_counts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    cnt_no: Mapped[str] = mapped_column(String(24))
    warehouse_id: Mapped[str] = mapped_column(
        ForeignKey('inv_warehouses.id'), index=True)
    category_id: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True)
    status: Mapped[str] = mapped_column(String(12), default='FREEZE',
                                        index=True)
    # FREEZE|COUNTED|PENDING_L1|PENDING_L2|POSTED|CANCELLED
    short_value: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    over_value: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    short_entry_id: Mapped[str | None] = mapped_column(String(36),
                                                       nullable=True)
    over_entry_id: Mapped[str | None] = mapped_column(String(36),
                                                      nullable=True)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    counted_by: Mapped[str | None] = mapped_column(String(36),
                                                   nullable=True)
    counted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    approved1_by: Mapped[str | None] = mapped_column(String(36),
                                                     nullable=True)
    approved1_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    approved2_by: Mapped[str | None] = mapped_column(String(36),
                                                     nullable=True)
    approved2_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint('tenant_id', 'cnt_no',
                                       name='uq_inv_cnt'),)


class InvCountLine(Base):
    __tablename__ = 'inv_count_lines'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    count_id: Mapped[str] = mapped_column(ForeignKey('inv_counts.id'),
                                          index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('inv_items.id'))
    system_qty: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    counted_qty: Mapped[Decimal | None] = mapped_column(Numeric(19, 4),
                                                        nullable=True)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    variance_qty: Mapped[Decimal | None] = mapped_column(Numeric(19, 4),
                                                         nullable=True)
    variance_value: Mapped[Decimal | None] = mapped_column(Numeric(19, 4),
                                                           nullable=True)


class InvPolicy(Base):
    """سياسة الوحدة القابلة للضبط (ملف 14 §2 «قابلة للضبط»):
    سلم اعتمادات الشراء، تسامح المطابقة والاستلام، نوافذ التنبيه."""
    __tablename__ = 'inv_policy'
    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    po_l0_limit: Mapped[Decimal] = mapped_column(Numeric(19, 4),
                                                 default=5000)
    po_l1_limit: Mapped[Decimal] = mapped_column(Numeric(19, 4),
                                                 default=50000)
    price_tolerance_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4),
                                                         default=0)
    qty_tolerance_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4),
                                                       default=5)
    expiry_windows: Mapped[list] = mapped_column(JSONType,
                                                 default=lambda: [30, 15, 7])
    stagnant_days: Mapped[int] = mapped_column(Integer, default=90)
    consumption_days: Mapped[int] = mapped_column(Integer, default=30)
    updated_by: Mapped[str | None] = mapped_column(String(36),
                                                   nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


# ════════════════════════════════════════════════════════════════════
# الموارد البشرية والرواتب — ملف 06 + مخطط 11 §(و) + أحداث #21..#23 (ملف 02)
# ════════════════════════════════════════════════════════════════════
import uuid as _uuid


def _hr_uuid() -> str:
    return str(_uuid.uuid4())


def _hr_now():
    from datetime import timezone
    return datetime.now(timezone.utc)


class HrDepartment(Base):
    """قسم تنظيمي مرتبط بمركز تكلفة وحساب رواتب (ملف 06 §1)."""
    __tablename__ = 'hr_departments'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name_ar: Mapped[str] = mapped_column(String(100))
    cost_center_code: Mapped[str] = mapped_column(String(20), default='CC-ADMIN')
    payroll_account_code: Mapped[str] = mapped_column(String(10),
                                                      default='6310')
    is_confidential: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint('tenant_id', 'code',
                                       name='uq_hrdept_tenant_code'),)


class HrPosition(Base):
    """وظيفة داخل قسم مع درجة في السُّلم (ملف 06 §1)."""
    __tablename__ = 'hr_positions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    department_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(100))
    grade: Mapped[str] = mapped_column(String(10), default='G1')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class HrEmployee(Base):
    """ملف موظف: شخصي حساس مشفر ساكناً + عقد وحالة دورة حياة (§1)."""
    __tablename__ = 'hr_employees'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    branch_id: Mapped[str] = mapped_column(String(36))
    emp_no: Mapped[str] = mapped_column(String(20))
    full_name: Mapped[str] = mapped_column(String(150))
    national_id_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str] = mapped_column(String(30), default='')
    department_id: Mapped[str] = mapped_column(String(36), index=True)
    position_id: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True)
    shift_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    hire_date: Mapped[date] = mapped_column(Date)
    contract_type: Mapped[str] = mapped_column(String(10), default='PERM')
    # PERM دائم | TEMP مؤقت | PIECE بالقطعة
    base_salary: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    allowances: Mapped[list] = mapped_column(JSONType, default=list)
    # [{code, name, amount} | {code, name, pct_base}]
    bank_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default='ACTIVE')
    # ACTIVE نشط | SUSPENDED موقوف | TERMINATED منتهي
    termination_date: Mapped[date | None] = mapped_column(Date,
                                                          nullable=True)
    termination_reason: Mapped[str] = mapped_column(String(300), default='')
    created_by: Mapped[str] = mapped_column(String(36), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=_hr_now)
    __table_args__ = (UniqueConstraint('tenant_id', 'emp_no',
                                       name='uq_hremp_tenant_no'),)


class HrEmployeeChange(Base):
    """نقل/ترقية/تعديل أجر بمستند واعتماد (§1 — لا اعتماد ذاتي)."""
    __tablename__ = 'hr_employee_changes'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    employee_id: Mapped[str] = mapped_column(String(36), index=True)
    change_type: Mapped[str] = mapped_column(String(10))
    # TRANSFER نقل | PROMOTE ترقية | SALARY تعديل أجر
    before: Mapped[dict] = mapped_column(JSONType, default=dict)
    after: Mapped[dict] = mapped_column(JSONType, default=dict)
    doc_ref: Mapped[str] = mapped_column(String(120))
    effective_from: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default='PENDING')
    approved_by: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str] = mapped_column(String(300), default='')
    created_by: Mapped[str] = mapped_column(String(36), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=_hr_now)


class HrShift(Base):
    """وردية تعريفية؛ overnight يعني تعبر منتصف الليل (§2)."""
    __tablename__ = 'hr_shifts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(60))
    from_time: Mapped[str] = mapped_column(String(5))
    to_time: Mapped[str] = mapped_column(String(5))
    overnight: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class HrRoster(Base):
    """إسناد وردية ليوم محدد؛ صف واحد لكل (موظف، يوم)."""
    __tablename__ = 'hr_rosters'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    employee_id: Mapped[str] = mapped_column(String(36), index=True)
    roster_date: Mapped[date] = mapped_column(Date)
    shift_id: Mapped[str] = mapped_column(String(36))
    __table_args__ = (UniqueConstraint('employee_id', 'roster_date',
                                       name='uq_hrroster_emp_date'),)


class HrAttendance(Base):
    """رصد يومي: يدوي معتمد من المشرف؛ الإضافي لا يُحتسب إلا بعد الاعتماد."""
    __tablename__ = 'hr_attendance'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    employee_id: Mapped[str] = mapped_column(String(36), index=True)
    att_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default='PRESENT')
    # PRESENT حضور | ABSENT غياب | LEAVE إجازة
    in_time: Mapped[str] = mapped_column(String(5), default='')
    out_time: Mapped[str] = mapped_column(String(5), default='')
    late_min: Mapped[int] = mapped_column(Integer, default=0)
    early_min: Mapped[int] = mapped_column(Integer, default=0)
    overtime_hours: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=0)
    approved_by: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    entered_by: Mapped[str] = mapped_column(String(36), default='')
    __table_args__ = (UniqueConstraint('employee_id', 'att_date',
                                       name='uq_hratt_emp_date'),)


class HrLeaveType(Base):
    __tablename__ = 'hr_leave_types'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(80))
    paid: Mapped[bool] = mapped_column(Boolean, default=True)
    accrual_per_month: Mapped[Decimal] = mapped_column(Numeric(7, 2),
                                                       default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint('tenant_id', 'code',
                                       name='uq_hrlt_tenant_code'),)


class HrLeaveBalance(Base):
    """رصيد إجازة سنوي؛ accrued_months يمنع تكرار الاستحقاق الشهري (§2)."""
    __tablename__ = 'hr_leave_balances'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    employee_id: Mapped[str] = mapped_column(String(36), index=True)
    leave_type_id: Mapped[str] = mapped_column(String(36), index=True)
    year: Mapped[int] = mapped_column(Integer)
    entitled: Mapped[Decimal] = mapped_column(Numeric(9, 2), default=0)
    used: Mapped[Decimal] = mapped_column(Numeric(9, 2), default=0)
    accrued_months: Mapped[list] = mapped_column(JSONType, default=list)
    __table_args__ = (UniqueConstraint('employee_id', 'leave_type_id',
                                       'year', name='uq_hrlb_emp_type_year'),)


class HrLeaveRequest(Base):
    __tablename__ = 'hr_leave_requests'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    employee_id: Mapped[str] = mapped_column(String(36), index=True)
    leave_type_id: Mapped[str] = mapped_column(String(36))
    from_date: Mapped[date] = mapped_column(Date)
    to_date: Mapped[date] = mapped_column(Date)
    days: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    reason: Mapped[str] = mapped_column(String(300), default='')
    status: Mapped[str] = mapped_column(String(10), default='PENDING')
    approved_by: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str] = mapped_column(String(300), default='')
    created_by: Mapped[str] = mapped_column(String(36), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=_hr_now)


class HrAdvance(Base):
    """سلفة: طلب بسقف ← اعتماد ← صرف #23 ← استقطاع قسط شهري تلقائي (§3)."""
    __tablename__ = 'hr_advances'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    employee_id: Mapped[str] = mapped_column(String(36), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    installments: Mapped[int] = mapped_column(Integer, default=1)
    installment_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4),
                                                        default=0)
    remaining: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    request_date: Mapped[date] = mapped_column(Date)
    first_deduct_month: Mapped[str] = mapped_column(String(7), default='')
    reason: Mapped[str] = mapped_column(String(300), default='')
    status: Mapped[str] = mapped_column(String(10), default='REQUESTED')
    # REQUESTED | APPROVED | PAID | SETTLED | REJECTED | CANCELLED
    approved_by: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    paid_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                     nullable=True)
    paid_entry_id: Mapped[str | None] = mapped_column(String(36),
                                                      nullable=True)
    paid_account_code: Mapped[str] = mapped_column(String(10),
                                                   default='1101')
    reject_reason: Mapped[str] = mapped_column(String(300), default='')
    created_by: Mapped[str] = mapped_column(String(36), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=_hr_now)


class HrPayItem(Base):
    """بند راتب قابل للتكوين (§4.1): FIXED مبلغ | PCT_BASE نسبة من الأساسي."""
    __tablename__ = 'hr_pay_items'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(80))
    item_type: Mapped[str] = mapped_column(String(10))
    # EARNING استحقاق | DEDUCTION استقطاع
    calc: Mapped[str] = mapped_column(String(10), default='FIXED')
    pct_base: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=0)
    credit_account_code: Mapped[str] = mapped_column(String(10),
                                                     default='2220')
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint('tenant_id', 'code',
                                       name='uq_hrpi_tenant_code'),)


class HrPenalty(Base):
    """جزاء تأديبي بمستند واعتماد؛ يخصم في شهر apply_month (§2)."""
    __tablename__ = 'hr_penalties'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    employee_id: Mapped[str] = mapped_column(String(36), index=True)
    pen_date: Mapped[date] = mapped_column(Date)
    apply_month: Mapped[str] = mapped_column(String(7))
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    reason: Mapped[str] = mapped_column(String(300))
    doc_ref: Mapped[str] = mapped_column(String(120), default='')
    approved_by: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    deducted_run_id: Mapped[str | None] = mapped_column(String(36),
                                                        nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=_hr_now)


class HrPayrollRun(Base):
    """مسير شهري: لا قيد قبل إعداد HR + اعتماد مالي (§4.2) — واحد NORMAL
    لكل شهر؛ التصحيح بمسير تسوية SUPPLEMENTAL مربوط بالأصل (§4.3)."""
    __tablename__ = 'hr_payroll_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    kind: Mapped[str] = mapped_column(String(12), default='NORMAL')
    # NORMAL | SUPPLEMENTAL | FINAL
    parent_run_id: Mapped[str | None] = mapped_column(String(36),
                                                      nullable=True)
    supp_seq: Mapped[int] = mapped_column(Integer, default=0)
    final_employee_id: Mapped[str | None] = mapped_column(String(36),
                                                          nullable=True)
    status: Mapped[str] = mapped_column(String(10), default='DRAFT')
    # DRAFT|REVIEWED|APPROVED|POSTED|PAID|CANCELLED
    employee_count: Mapped[int] = mapped_column(Integer, default=0)
    gross_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    unearned_total: Mapped[Decimal] = mapped_column(Numeric(19, 4),
                                                    default=0)
    withholdings_total: Mapped[Decimal] = mapped_column(Numeric(19, 4),
                                                        default=0)
    advances_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    net_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    dept_totals: Mapped[dict] = mapped_column(JSONType, default=dict)
    manual_lines: Mapped[dict] = mapped_column(JSONType, default=dict)
    prepared_by: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True)
    prepared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36),
                                                    nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    posted_entry_id: Mapped[str | None] = mapped_column(String(36),
                                                        nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    paid_seq: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(36), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=_hr_now)
    __table_args__ = (UniqueConstraint('tenant_id', 'month', 'kind',
                                       'supp_seq', name='uq_hrpr_month_kind'),)


class HrPayslip(Base):
    """قسيمة: لقطة كاملة للبنود والمدخلات لحظة الاحتساب (§4.2-2) —
    غير قابلة للتعديل بعد اعتماد مسيرها (قبول-4/§5)."""
    __tablename__ = 'hr_payslips'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    employee_id: Mapped[str] = mapped_column(String(36), index=True)
    department_id: Mapped[str] = mapped_column(String(36))
    gross: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    unearned: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    withholdings: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    advances: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    penalties: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    net: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    items_snapshot: Mapped[list] = mapped_column(JSONType, default=list)
    inputs_snapshot: Mapped[dict] = mapped_column(JSONType, default=dict)
    paid_entry_id: Mapped[str | None] = mapped_column(String(36),
                                                      nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint('run_id', 'employee_id',
                                       name='uq_hrps_run_emp'),)


class HrEosProvision(Base):
    """مخصص نهاية الخدمة الشهري الاختياري (§4.3): Dr مصروف | Cr مخصص."""
    __tablename__ = 'hr_eos_provisions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    employee_id: Mapped[str] = mapped_column(String(36), index=True)
    month: Mapped[str] = mapped_column(String(7))
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    posted_entry_id: Mapped[str | None] = mapped_column(String(36),
                                                        nullable=True)
    __table_args__ = (UniqueConstraint('tenant_id', 'employee_id', 'month',
                                       name='uq_hreos_emp_month'),)


class HrPolicy(Base):
    """سياسة الرواتب القابلة للتكوين لكل مستأجر (§4.1 — بصلاحية مالية)."""
    __tablename__ = 'hr_policy'
    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    day_count_mode: Mapped[str] = mapped_column(String(10),
                                                default='FIXED30')
    # FIXED30 قسمة على 30 | CALENDAR أيام الشهر الفعلية
    advance_max_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4),
                                                     default=50)
    workday_hours: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=8)
    ot_multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 4),
                                                   default=Decimal('1.5'))
    late_deduct_daily: Mapped[Decimal] = mapped_column(Numeric(19, 4),
                                                       default=0)
    penalty_credit_code: Mapped[str] = mapped_column(String(10),
                                                     default='2220')
    # 2220 مستحقة للجهات | 4901 تُعاد إيراداً (§2 — قابل للتكوين)
    eos_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    eos_month_rate: Mapped[Decimal] = mapped_column(
        Numeric(9, 6), default=Decimal('0.083333'))
    eos_credit_account_code: Mapped[str] = mapped_column(String(10),
                                                         default='2320')
    updated_by: Mapped[str | None] = mapped_column(String(36),
                                                   nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


# ════════════════════════════════════════════════════════════════════
# (ز) الأصول الثابتة — ملف 11 + حدث #24 (ملف 02)
# ════════════════════════════════════════════════════════════════════
class FaAsset(Base):
    """أصل ثابت: سجل الإهلاك — الشراء/الإعدام بقيود يدوية موثقة (ADR)."""
    __tablename__ = 'fa_assets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(60), default='')
    purchase_date: Mapped[date] = mapped_column(Date)
    cost: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    salvage: Mapped[Decimal] = mapped_column(Numeric(19, 4),
                                             default=Decimal('0'))
    useful_life_months: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(10), default='STRAIGHT')
    asset_account_id: Mapped[str] = mapped_column(ForeignKey('accounts.id'))
    accum_account_id: Mapped[str] = mapped_column(ForeignKey('accounts.id'))
    expense_account_id: Mapped[str] = mapped_column(ForeignKey('accounts.id'))
    depreciated_total: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), default=Decimal('0'))
    last_run_month: Mapped[str | None] = mapped_column(String(7),
                                                       nullable=True)
    status: Mapped[str] = mapped_column(String(12), default='ACTIVE')
    disposed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    disposal_reason: Mapped[str] = mapped_column(String(300), default='')
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=_hr_now)
    __table_args__ = (UniqueConstraint('tenant_id', 'code', name='uq_fa_code'),)


class FaDepreciationRun(Base):
    """تشغيلة إهلاك شهرية واحدة لكل شهر — لقطة سطور صندوقة."""
    __tablename__ = 'fa_depreciation_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=_hr_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    month: Mapped[str] = mapped_column(String(7))
    lines: Mapped[list] = mapped_column(JSONType, default=list)
    total: Mapped[Decimal] = mapped_column(Numeric(19, 4),
                                           default=Decimal('0'))
    asset_count: Mapped[int] = mapped_column(Integer, default=0)
    posted_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey('journal_entries.id'), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=_hr_now)
    __table_args__ = (UniqueConstraint('tenant_id', 'month',
                                       name='uq_fa_run_month'),)
