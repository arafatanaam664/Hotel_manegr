"""مخططات اللوحة — كل نقطة نهاية بـ Schema وRBAC وIdempotency (ملف 15)."""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str = Field(min_length=2, max_length=60)
    password: str = Field(min_length=4, max_length=128)
    totp_code: str | None = None


class MfaConfirmIn(BaseModel):
    enroll_token: str
    totp_code: str = Field(min_length=6, max_length=8)


class ClientIn(BaseModel):
    legal_name: str = Field(min_length=2, max_length=200)
    trade_name: str = ''
    contacts: dict = Field(default_factory=dict)
    hotel_name: str = ''
    rooms_count: int = Field(default=0, ge=0)
    branches_count: int = Field(default=1, ge=1)
    sales_channel: str = 'DIRECT'
    contract_ref: str = ''
    package: str = Field(default='LOCAL', pattern='^(LOCAL|CLOUD|HYBRID)$')
    modules: list[str] = Field(default_factory=lambda: ['ACCOUNTING'])
    plan_code: str = ''
    billing_period: str = Field(default='YEARLY',
                                pattern='^(MONTHLY|YEARLY)$')
    tenant_id: str = ''
    activation_date: date | None = None
    expiry_date: date | None = None
    grace_days: int = Field(default=30, ge=0, le=90)
    status: str = 'TRIAL'
    open_reason: str = 'فتح ملف عميل جديد'
    notes: str = ''


class ClientStatusIn(BaseModel):
    to_status: str
    reason: str = Field(min_length=3)   # قبول §8-5: السبب إلزامي


class PlanIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name_ar: str = Field(min_length=2, max_length=120)
    billing_period: str = Field(default='YEARLY',
                                pattern='^(MONTHLY|YEARLY)$')
    setup_fee: Decimal = Decimal('0')
    base_price: Decimal = Field(ge=0)
    module_prices: dict = Field(default_factory=dict)
    included_users: int = Field(default=5, ge=0)
    included_branches: int = Field(default=1, ge=0)
    extra_user_price: Decimal = Decimal('0')
    extra_branch_price: Decimal = Decimal('0')
    discount_max_pct: Decimal = Field(default=Decimal('15'), ge=0, le=100)


class InvoiceIn(BaseModel):
    client_code: str
    plan_code: str
    period_from: date
    period_to: date
    discount_pct: Decimal = Field(default=Decimal('0'), ge=0, le=100)
    kind: str = Field(default='RENEWAL', pattern='^(SETUP|RENEWAL)$')
    notes: str = ''
    users: int = Field(default=10, ge=1)


class CollectionIn(BaseModel):
    invoice_number: str
    amount: Decimal = Field(gt=0)
    method: str = Field(pattern='^(CASH|TRANSFER)$')
    reference: str = Field(min_length=2, max_length=120)
    notes: str = ''


class LicenseIssueIn(BaseModel):
    client_code: str
    kind: str = Field(default='ISSUE', pattern='^(ISSUE|RENEW|MODIFY|REPAIR)$')
    modules: list[str] | None = None
    max_users: int = Field(default=10, ge=1)
    max_branches: int = Field(default=1, ge=1)
    days: int = Field(default=365, ge=1, le=3700)
    expires: date | None = None
    grace_days: int | None = Field(default=None, ge=0, le=90)
    fingerprint: dict | None = None
    features: dict | None = None
    support: str = 'STANDARD'


class RevocationIn(BaseModel):
    entries: list[dict] = Field(min_length=1)


class TicketIn(BaseModel):
    client_code: str
    title: str = Field(min_length=3, max_length=200)
    category: str
    priority: str
    module: str = 'GENERAL'
    channel: str = 'IN_APP'
    description: str = ''
    attachments: list = Field(default_factory=list)


class TicketTransitionIn(BaseModel):
    to_status: str
    note: str = ''
    root_cause: str = ''
    kb_article: str = ''


class AssignIn(BaseModel):
    username: str


class HeartbeatIn(BaseModel):
    client_code: str
    site_id: str = ''
    product_version: str = ''
    outbox_lag: int = Field(default=0, ge=0)
    backup_ok: bool = True
    disk_free_gb: Decimal = Decimal('0')
    fingerprint_hash: str = ''
    payload: dict = Field(default_factory=dict)


class EdgeTicketIn(BaseModel):
    client_code: str
    title: str = Field(min_length=3, max_length=200)
    category: str = 'QUESTION'
    priority: str = Field(default='P3', pattern='^P[2-4]$')  # P1 للوحة/Director
    module: str = 'GENERAL'
    description: str = ''


class ReleaseIn(BaseModel):
    version: str = Field(min_length=3, max_length=20)
    ring: str = Field(default='CANARY', pattern='^(CANARY|GENERAL)$')
    notes: str = ''
