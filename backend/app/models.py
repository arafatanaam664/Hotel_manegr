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
