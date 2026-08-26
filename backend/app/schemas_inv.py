"""مخططات إدخال وحدة المخزون والمشتريات (Pydantic v2) — لا نقطة نهاية
بدون Schema إلزامي (قاعدة البناء من ملف 15)."""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class CategoryIn(BaseModel):
    code: str = Field(min_length=1, max_length=12)
    name_ar: str = Field(min_length=2, max_length=120)
    default_account_code: str = Field(default='1210', max_length=8)


class AltUnitIn(BaseModel):
    unit: str = Field(min_length=1, max_length=12)
    factor: Decimal = Field(gt=0)


class ItemIn(BaseModel):
    code: str = Field(min_length=1, max_length=16)
    name_ar: str = Field(min_length=2, max_length=160)
    name_en: str = Field(default='', max_length=160)
    category_id: str
    base_unit: str = Field(default='حبة', max_length=12)
    alt_units: list[AltUnitIn] = []
    barcode: str = Field(default='', max_length=40)
    reorder_level: Decimal = Field(default=0, ge=0)
    safety_level: Decimal = Field(default=0, ge=0)
    inventory_account_code: str | None = None
    track_expiry: bool = False


class ItemPatch(BaseModel):
    name_ar: str | None = Field(default=None, min_length=2, max_length=160)
    name_en: str | None = None
    barcode: str | None = None
    reorder_level: Decimal | None = Field(default=None, ge=0)
    safety_level: Decimal | None = Field(default=None, ge=0)
    track_expiry: bool | None = None
    is_active: bool | None = None


class WarehouseIn(BaseModel):
    code: str = Field(min_length=1, max_length=12)
    name_ar: str = Field(min_length=2, max_length=120)
    kind: str = Field(default='SUB', pattern='^(MAIN|SUB|OUTLET)$')
    inventory_account_code: str = Field(default='1210', max_length=8)
    keeper_user_id: str | None = None
    allow_negative: bool = False
    cost_center_code: str = Field(default='', max_length=16)


class WarehousePatch(BaseModel):
    name_ar: str | None = None
    keeper_user_id: str | None = None
    allow_negative: bool | None = None
    is_active: bool | None = None
    cost_center_code: str | None = None


class SupplierIn(BaseModel):
    code: str = Field(min_length=1, max_length=12)
    name: str = Field(min_length=2, max_length=160)
    contact_person: str = Field(default='', max_length=80)
    phone: str = Field(default='', max_length=30)
    address: str = Field(default='', max_length=200)
    terms_days: int = Field(default=0, ge=0)
    currency: str = Field(default='BASE', max_length=3)
    notes: str = Field(default='', max_length=300)


class SupplierPatch(BaseModel):
    name: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    address: str | None = None
    terms_days: int | None = Field(default=None, ge=0)
    currency: str | None = None
    notes: str | None = None
    rating_commitment: int | None = Field(default=None, ge=1, le=5)
    rating_quality: int | None = Field(default=None, ge=1, le=5)
    is_active: bool | None = None


class SupplierPriceIn(BaseModel):
    item_id: str
    price: Decimal = Field(gt=0)
    valid_from: date
    valid_to: date | None = None


class PRLineIn(BaseModel):
    item_id: str
    qty: Decimal = Field(gt=0)
    note: str = Field(default='', max_length=200)


class PRIn(BaseModel):
    department: str = Field(min_length=2, max_length=80)
    notes: str = Field(default='', max_length=300)
    lines: list[PRLineIn] = Field(min_length=1)


class POLineIn(BaseModel):
    item_id: str
    qty: Decimal = Field(gt=0)
    uom: str | None = None
    factor: Decimal | None = None
    unit_price: Decimal | None = Field(default=None, gt=0)


class POIn(BaseModel):
    supplier_id: str
    expected_date: date | None = None
    terms: str = Field(default='', max_length=200)
    pr_id: str | None = None
    tax_amount: Decimal = Field(default=0, ge=0)
    lines: list[POLineIn] = Field(min_length=1)


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class GRNLineIn(BaseModel):
    item_id: str
    qty_received: Decimal = Field(ge=0)
    qty_rejected: Decimal = Field(default=0, ge=0)
    reject_reason: str = Field(default='', max_length=200)
    unit_price: Decimal | None = Field(default=None, gt=0)
    batch_no: str = Field(default='', max_length=40)
    expiry_date: date | None = None


class GRNIn(BaseModel):
    supplier_id: str
    warehouse_id: str
    purchase_type: str = Field(pattern='^(CASH|CREDIT)$')
    po_id: str | None = None
    supplier_invoice_no: str = Field(default='', max_length=40)
    payment_account_code: str = Field(default='1101', max_length=8)
    tax_amount: Decimal = Field(default=0, ge=0)
    note: str = Field(default='', max_length=300)
    business_date: date | None = None
    lines: list[GRNLineIn] = Field(min_length=1)


class SILineIn(BaseModel):
    item_id: str
    qty: Decimal = Field(gt=0)
    unit_price: Decimal = Field(gt=0)


class SupplierInvoiceIn(BaseModel):
    supplier_id: str
    supplier_invoice_no: str = Field(min_length=1, max_length=40)
    invoice_date: date
    po_id: str | None = None
    grn_id: str | None = None
    tax_amount: Decimal = Field(default=0, ge=0)
    lines: list[SILineIn] = Field(min_length=1)


class VarianceResolveIn(BaseModel):
    action: str = Field(pattern='^(EDIT|APPROVE_VARIANCE)$')
    corrected_lines: list[SILineIn] | None = None


class PaymentAllocIn(BaseModel):
    invoice_id: str
    amount: Decimal = Field(gt=0)


class PaymentIn(BaseModel):
    supplier_id: str
    amount: Decimal = Field(gt=0)
    method: str = Field(default='CASH', pattern='^(CASH|BANK|EWALLET)$')
    discount: Decimal = Field(default=0, ge=0)
    payment_date: date | None = None
    allocations: list[PaymentAllocIn] = []


class ReturnLineIn(BaseModel):
    item_id: str
    qty: Decimal = Field(gt=0)


class SupplierReturnIn(BaseModel):
    supplier_id: str
    warehouse_id: str
    grn_id: str | None = None
    refund_to: str = Field(default='CREDIT_AP', pattern='^(CREDIT_AP|CASH)$')
    reason: str = Field(min_length=3, max_length=300)
    lines: list[ReturnLineIn] = Field(min_length=1)


class IssueLineIn(BaseModel):
    item_id: str
    qty: Decimal = Field(gt=0)


class IssueIn(BaseModel):
    from_warehouse_id: str
    to_warehouse_id: str
    department: str = Field(min_length=2, max_length=80)
    reason: str = Field(default='', max_length=300)
    lines: list[IssueLineIn] = Field(min_length=1)


class TransferIn(BaseModel):
    from_warehouse_id: str
    to_warehouse_id: str
    reason: str = Field(min_length=3, max_length=300)
    requires_receive: bool = True
    lines: list[IssueLineIn] = Field(min_length=1)


class WasteLineIn(BaseModel):
    item_id: str
    qty: Decimal = Field(gt=0)
    reason: str = Field(default='', max_length=200)


class WasteIn(BaseModel):
    warehouse_id: str
    reason: str = Field(min_length=3, max_length=300)
    photo_ref: str = Field(default='', max_length=200)
    lines: list[WasteLineIn] = Field(min_length=1)


class CountIn(BaseModel):
    warehouse_id: str
    category_id: str | None = None


class CountedLineIn(BaseModel):
    item_id: str
    counted_qty: Decimal = Field(ge=0)


class CountEntryIn(BaseModel):
    counted: list[CountedLineIn] = Field(min_length=1)


class CountApproveIn(BaseModel):
    level: int = Field(ge=1, le=2)


class PolicyIn(BaseModel):
    po_l0_limit: Decimal | None = Field(default=None, ge=0)
    po_l1_limit: Decimal | None = Field(default=None, ge=0)
    price_tolerance_pct: Decimal | None = Field(default=None, ge=0, le=100)
    qty_tolerance_pct: Decimal | None = Field(default=None, ge=0, le=100)
    expiry_windows: list[int] | None = Field(default=None, min_length=3,
                                             max_length=3)
    stagnant_days: int | None = Field(default=None, ge=1, le=3650)
    consumption_days: int | None = Field(default=None, ge=1, le=365)

    @field_validator('expiry_windows')
    @classmethod
    def _windows(cls, v):
        if v is None:
            return v
        if any((w < 1 or w > 365) for w in v):
            raise ValueError('نوافذ الصلاحية أيام موجبة ≤365')
        return sorted(v, reverse=True)


class DateRangeQuery(BaseModel):
    date_from: date
    date_to: date

    @field_validator('date_to')
    @classmethod
    def _order(cls, v, info):
        if info.data.get('date_from') and v < info.data['date_from']:
            raise ValueError('date_to قبل date_from')
        return v
