"""نماذج الطلبات/الردود (Pydantic v2) — تحقق مخطط صارم على كل نقطة دخول."""
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator


# ─── الهوية ────────────────────────────────────────────
class LoginIn(BaseModel):
    username: str = Field(min_length=2, max_length=60)
    password: str = Field(min_length=6, max_length=128)
    tenant_code: str | None = None

class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = 'bearer'
    expires_in: int
    user: 'UserOut'

class RefreshIn(BaseModel):
    refresh_token: str

class UserOut(BaseModel):
    id: str
    username: str
    full_name: str
    tenant_id: str
    roles: list[str]
    perms: list[str]
    branches: list[str]

class MeOut(UserOut):
    mfa_enabled: bool


# ─── الحسابات ──────────────────────────────────────────
class AccountOut(BaseModel):
    id: str
    code: str
    name_ar: str
    name_en: str
    parent_id: str | None
    level: int
    type: str
    nature: str
    is_postable: bool
    is_active: bool
    party_required: bool
    is_system: bool
    model_config = {'from_attributes': True}


# ─── القيود ────────────────────────────────────────────
class LineIn(BaseModel):
    account_code: str
    debit: Decimal = Field(default=Decimal('0'), ge=0)
    credit: Decimal = Field(default=Decimal('0'), ge=0)
    party_type: str | None = None
    party_id: str | None = None
    cost_center_code: str | None = None
    description: str = Field(default='', max_length=300)

    @field_validator('debit', 'credit')
    @classmethod
    def _clamp(cls, v: Decimal) -> Decimal:
        return v.quantize(Decimal('0.0001'))


class ManualJournalIn(BaseModel):
    entry_date: date
    branch_code: str = 'MAIN'
    narration: str = Field(min_length=3, max_length=400)
    reference: str | None = Field(default=None, max_length=80)
    lines: list[LineIn]


class JournalLineOut(BaseModel):
    line_no: int
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    party_type: str | None
    cost_center: str | None
    description: str
    model_config = {'from_attributes': False}


class JournalOut(BaseModel):
    id: str
    journal_type: str
    entry_no: str
    entry_date: date
    status: str
    currency_code: str
    narration: str
    reference: str | None
    source_type: str | None
    event_key: str | None
    reversal_of_entry_id: str | None
    reversed_entry_id: str | None
    total_debit: Decimal
    total_credit: Decimal
    created_at: datetime
    posted_at: datetime | None
    lines: list[JournalLineOut]


class ReverseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


# ─── الفترات ───────────────────────────────────────────
class PeriodOut(BaseModel):
    id: str
    period_no: int
    start_date: date
    end_date: date
    status: str
    year_no: int
    model_config = {'from_attributes': False}


# ─── التقارير ──────────────────────────────────────────
class TBRow(BaseModel):
    account_code: str
    account_name: str
    level: int
    nature: str
    debit_sum: Decimal
    credit_sum: Decimal
    balance: Decimal                  # موجب حسب طبيعة الحساب
    balance_side: str                 # DEBIT|CREDIT|ZERO

class TrialBalanceOut(BaseModel):
    as_of: date
    total_debit: Decimal
    total_credit: Decimal
    balanced: bool
    net_balance_zero: bool
    rows: list[TBRow]

class LedgerRow(BaseModel):
    entry_no: str
    entry_date: date
    journal_type: str
    narration: str
    debit: Decimal
    credit: Decimal
    running_balance: Decimal

class LedgerOut(BaseModel):
    account_code: str
    account_name: str
    opening_balance: Decimal
    closing_balance: Decimal
    rows: list[LedgerRow]


class GenericOut(BaseModel):
    detail: str


class AuditVerifyOut(BaseModel):
    ok: bool
    checked: int
    broken_at: str | None = None
    detail: str | None = None


TokenPair.model_rebuild()
