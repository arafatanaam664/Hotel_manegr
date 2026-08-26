"""مخططات إدخال نقاط البيع — تحقق صارم عند الحدود (12 §4)."""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

OrderType = Literal['DINE_IN', 'TAKEAWAY', 'ROOM_SERVICE']
PayMethod = Literal['CASH', 'CARD', 'EWALLET', 'ROOM', 'CORPORATE', 'HOUSE']
ItemType = Literal['STOCK', 'SERVICE', 'COMPOSITE']


class OutletIn(BaseModel):
    code: str = Field(min_length=2, max_length=12)
    name_ar: str = Field(min_length=2, max_length=120)
    name_en: str = Field(default='', max_length=120)
    cash_account_code: str = Field(default='1102', max_length=8)
    default_revenue_account_code: str = Field(default='4201', max_length=8)
    house_expense_account_code: str = Field(default='6610', max_length=8)
    allow_negative_stock: bool = False
    cash_variance_tolerance: Decimal = Field(default=Decimal('10'), ge=0)
    cost_center_code: str = Field(default='', max_length=16)


class CategoryIn(BaseModel):
    code: str = Field(min_length=2, max_length=12)
    name_ar: str = Field(min_length=2, max_length=120)
    name_en: str = Field(default='', max_length=120)
    color: str = Field(default='#0e7490', max_length=9)
    station: str = Field(default='KITCHEN', max_length=12)
    sort_order: int = 1


class ItemIn(BaseModel):
    code: str = Field(min_length=2, max_length=16)
    name_ar: str = Field(min_length=2, max_length=160)
    name_en: str = Field(default='', max_length=160)
    barcode: str = Field(default='', max_length=40)
    category_id: str
    price: Decimal = Field(ge=0)
    tax_included: bool = True
    revenue_account_code: str = Field(default='4201', max_length=8)
    item_type: ItemType = 'SERVICE'
    cost: Decimal = Field(default=Decimal('0'), ge=0)


class ItemPatch(BaseModel):
    name_ar: str | None = Field(default=None, max_length=160)
    name_en: str | None = Field(default=None, max_length=160)
    barcode: str | None = Field(default=None, max_length=40)
    price: Decimal | None = Field(default=None, ge=0)
    cost: Decimal | None = Field(default=None, ge=0)
    revenue_account_code: str | None = Field(default=None, max_length=8)
    is_active: bool | None = None


class ModifierIn(BaseModel):
    name_ar: str = Field(min_length=2, max_length=120)
    name_en: str = Field(default='', max_length=120)
    price: Decimal = Field(default=Decimal('0'), ge=0)


class RecipeLineIn(BaseModel):
    component_item_id: str
    qty: Decimal = Field(gt=0)


class RecipeSetIn(BaseModel):
    """وصفة صنف مركب كاملة — تُستبدل دفعة واحدة (قبول #3 حرفية الكميات)."""
    lines: list[RecipeLineIn] = Field(min_length=1)


class StockLoadIn(BaseModel):
    item_id: str
    qty: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)


class TableIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    zone: str = Field(default='القاعة الرئيسية', max_length=40)
    seats: int = Field(default=4, ge=1, le=40)


class OrderIn(BaseModel):
    outlet_id: str
    type: OrderType = 'DINE_IN'
    table_id: str | None = None
    note: str = Field(default='', max_length=200)


class LineIn(BaseModel):
    item_id: str
    qty: Decimal = Field(gt=0)
    modifiers: list[dict] = Field(default_factory=list)
    notes: str = Field(default='', max_length=200)
    discount: Decimal = Field(default=Decimal('0'), ge=0)


class LinePatch(BaseModel):
    qty: Decimal | None = Field(default=None, gt=0)
    discount: Decimal | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=200)


class VoidIn(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


class PaymentIn(BaseModel):
    method: PayMethod
    amount: Decimal = Field(gt=0)
    folio_id: str | None = None
    corporate_id: str | None = None
    reason: str | None = Field(default=None, max_length=200)
    approver_pin: str | None = Field(default=None, max_length=8)


class SettleIn(BaseModel):
    client_uuid: str = Field(min_length=8, max_length=40)
    payments: list[PaymentIn] = Field(min_length=1)
    invoice_discount: Decimal = Field(default=Decimal('0'), ge=0)
    discount_reason: str = Field(default='', max_length=200)
    approver_pin: str = Field(default='', max_length=8)


class ReturnIn(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


class ShiftOpenIn(BaseModel):
    outlet_id: str
    opening_float: Decimal = Field(default=Decimal('0'), ge=0)


class ShiftCloseIn(BaseModel):
    actual_cash: Decimal = Field(ge=0)


class PinSetIn(BaseModel):
    current_password: str = Field(min_length=6)
    pin: str = Field(pattern=r'^\d{4,8}$')
