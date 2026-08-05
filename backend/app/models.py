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
