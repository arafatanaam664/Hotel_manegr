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
    must_change_password: bool = False

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


# ═══════════ ملف 02 §10 — القوائم المالية + الأصول (المرحلة 7) ═══════════
class MoneyRow(BaseModel):
    code: str
    name: str
    amount: Decimal


class UsaliDeptOut(BaseModel):
    key: str
    name: str
    revenues: list[MoneyRow]
    expenses: list[MoneyRow]
    revenue_total: Decimal
    expense_total: Decimal
    dept_income: Decimal


class IncomeStatementOut(BaseModel):
    from_: date = Field(alias='from')
    to: date
    method: str
    departments: list[UsaliDeptOut]
    departments_income: Decimal
    other_revenue: list[MoneyRow]
    other_revenue_total: Decimal
    undistributed: list[MoneyRow]
    undistributed_total: Decimal
    gop: Decimal
    non_operating: list[MoneyRow]
    non_operating_total: Decimal
    net_income: Decimal

    model_config = {'populate_by_name': True}


class BalanceSheetOut(BaseModel):
    as_of: date
    current_assets: list[MoneyRow]
    fixed_assets: list[MoneyRow]
    system_accounts: list[MoneyRow]
    total_assets: Decimal
    liabilities: list[MoneyRow]
    total_liabilities: Decimal
    equity: list[MoneyRow]
    current_year_earnings: Decimal
    total_equity: Decimal
    balanced: bool
    diff: Decimal


class CashFlowOut(BaseModel):
    from_: date = Field(alias='from')
    to: date
    method: str
    net_income: Decimal
    depreciation_addback: Decimal
    delta_receivables: Decimal
    delta_inventory: Decimal
    delta_operating_liabilities: Decimal
    operating: Decimal
    delta_fixed_assets_gross: Decimal
    investing: Decimal
    delta_loans: Decimal
    delta_owner_current: Decimal
    delta_capital: Decimal
    financing: Decimal
    equity_and_system_transfers: Decimal
    net_change: Decimal
    cash_delta_actual: Decimal
    reconciliation_diff: Decimal
    identity_holds: bool

    model_config = {'populate_by_name': True}


class AgingRowOut(BaseModel):
    party: str
    party_name: str
    party_type: str
    buckets: dict[str, Decimal]
    total: Decimal


class AgingOut(BaseModel):
    account: str
    account_name: str
    as_of: date
    method: str
    rows: list[AgingRowOut]
    totals: dict[str, Decimal]
    grand_total: Decimal
    gl_balance: Decimal
    matches_gl: bool


class FaAssetIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    category: str = Field(default='', max_length=60)
    purchase_date: date
    cost: Decimal = Field(gt=0)
    salvage: Decimal = Field(default=Decimal('0'), ge=0)
    useful_life_months: int = Field(ge=1, le=600)
    method: str = Field(default='STRAIGHT',
                        pattern='^(STRAIGHT|DECLINING)$')
    asset_account_code: str = Field(default='1510', max_length=10)
    accum_account_code: str = Field(default='1590', max_length=10)
    expense_account_code: str = Field(default='7101', max_length=10)


class FaDisposeIn(BaseModel):
    disposed_at: date
    reason: str = Field(min_length=3, max_length=300)


class FaRunIn(BaseModel):
    month: str = Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')


# ─── الترخيص (ملف 07) ───────────────────────────────────
class LicenseInstallIn(BaseModel):
    """ملف ترخيص JSON موقَّع بتوقيع Ed25519 كما تسلّمه العميل من الشركة."""
    payload: dict


class LicenseFingerprintOut(BaseModel):
    bound: bool
    match_components: int
    passing: bool
    hash: str


class LicenseLimitsOut(BaseModel):
    max_users: int
    used_users: int
    max_branches: int
    used_branches: int


class LicenseStatusOut(BaseModel):
    state: str
    status_reason: str
    package: str
    legal_name: str
    license_id: str
    support_level: str
    issued_at: str | None = None
    valid_until: str | None = None
    grace_until: str | None = None
    days_to_expire: int | None = None
    in_grace: bool
    trial: bool
    trial_started: str | None = None
    modules_enabled: list[str]
    modules_disabled: list[str]
    features_flags: dict
    limits: LicenseLimitsOut
    fingerprint: LicenseFingerprintOut
    clock_anchor_date: str | None = None
    last_check: str | None = None
    revocation_serial: int
    site_id: str


# ─── التهيئة التجارية والتشغيلية ─────────────────────────
class ProductConfigIn(BaseModel):
    deployment_mode: str = Field(default='LOCAL', pattern='^(LOCAL|CLOUD|HYBRID)$')
    property_type: str = Field(default='HOTEL', pattern='^(HOTEL|INN|SERVICED_APARTMENTS|RESORT|OTHER)$')
    modules_enabled: list[str] = Field(default_factory=lambda: ['ACCOUNTING'])
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    multi_branch: bool = False
    complete: bool = False


class ProductConfigOut(BaseModel):
    tenant_id: str
    deployment_mode: str
    property_type: str
    setup_state: str
    modules_enabled: list[str]
    feature_flags: dict[str, bool]
    configured_by: str | None = None
    completed_at: str | None = None
    version: int
    updated_at: str | None = None


class ProductCatalogOut(BaseModel):
    modules: dict[str, dict]
    features: dict[str, str]
    dependencies: dict[str, list[str]]
    deployment_modes: list[str]
    property_types: list[str]


# ─── النسخ الاحتياطي ─────────────────────────────────────
class BackupOut(BaseModel):
    id: str
    file_name: str
    storage_kind: str
    size_bytes: int
    sha256: str
    status: str
    created_at: str
    verified: bool | None = None
