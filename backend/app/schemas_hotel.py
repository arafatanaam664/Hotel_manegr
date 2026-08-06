"""مخططات وحدة الفندق (طلبات/ردود) — تحقق صارم عند الحدود."""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class GuestIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(default='', max_length=30)
    id_number: str = Field(default='', max_length=40)  # يُشفَّر ساكناً
    nationality: str = Field(default='', max_length=50)
    vip: bool = False
    notes: str = Field(default='', max_length=300)


class GuestOut(BaseModel):
    id: str
    full_name: str
    phone: str
    id_masked: str
    nationality: str
    vip: bool
    blacklist: bool


class CorporateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    contact_person: str = Field(default='', max_length=80)
    phone: str = Field(default='', max_length=30)
    credit_limit: Decimal | None = None
    discount_pct: Decimal = Field(default=Decimal('0'), ge=0, le=100)


class ReservationIn(BaseModel):
    guest_id: str
    room_type_code: str
    arrival_date: date
    departure_date: date
    corporate_id: str | None = None
    rate_plan_code: str | None = None
    room_no: str | None = None           # اختياري: تخصيص يدوي مباشر
    adults: int = Field(default=1, ge=1, le=8)
    children: int = Field(default=0, ge=0, le=6)
    source: str = Field(default='DIRECT')
    rate_override: Decimal | None = Field(default=None, gt=0)

    @field_validator('source')
    @classmethod
    def _src(cls, v: str) -> str:
        allowed = {'DIRECT', 'PHONE', 'WALKIN', 'CORPORATE', 'OTA'}
        if v.upper() not in allowed:
            raise ValueError(f'مصدر حجز غير صالح: {v}')
        return v.upper()


class ModifyReservationIn(BaseModel):
    new_arrival: date | None = None
    new_departure: date | None = None
    new_room_no: str | None = None


class DepositIn(BaseModel):
    amount: Decimal = Field(gt=0)
    method: str = Field(default='CASH')


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)
    fee: Decimal = Field(default=Decimal('0'), ge=0)
    refund: bool = True


class CheckInIn(BaseModel):
    allow_dirty: bool = False  # يتطلب صلاحية checkin.dirty_override


class WalkInIn(BaseModel):
    guest_id: str
    room_type_code: str
    departure_date: date
    corporate_id: str | None = None
    rate_plan_code: str | None = None
    room_no: str | None = None
    adults: int = Field(default=1, ge=1, le=8)
    children: int = Field(default=0, ge=0, le=6)
    allow_dirty: bool = False


class RoomMoveIn(BaseModel):
    new_room_no: str
    reason: str = Field(min_length=3, max_length=300)


class ChargeIn(BaseModel):
    extra_code: str
    qty: int = Field(default=1, ge=1, le=100)
    unit_price: Decimal | None = Field(default=None, gt=0)
    description: str = Field(default='', max_length=200)
    event_key: str | None = Field(default=None, max_length=64)


class PaymentIn(BaseModel):
    amount: Decimal = Field(gt=0)
    method: str = 'CASH'
    event_key: str | None = Field(default=None, max_length=64)

    @field_validator('method')
    @classmethod
    def _method(cls, v: str) -> str:
        if v not in ('CASH', 'CARD', 'EWALLET'):
            raise ValueError('وسيلة دفع غير صالحة')
        return v


class DiscountIn(BaseModel):
    amount: Decimal = Field(gt=0)
    reason: str = Field(min_length=3, max_length=300)
    approver_id: str | None = None


class TransferCorpIn(BaseModel):
    amount: Decimal = Field(gt=0)
    reason: str = Field(default='', max_length=200)


class CheckoutIn(BaseModel):
    late_fee: Decimal = Field(default=Decimal('0'), ge=0)
    payments: list[PaymentIn] = []
    corporate_transfer: bool = False


class HkChangeIn(BaseModel):
    new_status: str
    reason: str | None = Field(default=None, max_length=300)
    ooo_from: date | None = None
    ooo_to: date | None = None


class RoomIn(BaseModel):
    """إنشاء غرفة — kind: STANDARD (افتراضي) | SUITE_UNIT (جناح مركب=أب)،
    وparent_room_no يربط الغرفة ابناً لجناح قائم (ADR-0035)."""
    room_no: str = Field(min_length=1, max_length=10)
    floor: int = Field(default=1, ge=0, le=50)
    room_type_code: str
    features: list[str] = []
    kind: str = Field(default='STANDARD', pattern='^(STANDARD|SUITE_UNIT)$')
    parent_room_no: str | None = None


class RoomPatch(BaseModel):
    """تعديل غرفة — parent_room_no: None لا تغيير، '' فك ربط، قيمة ربط."""
    room_no: str | None = Field(default=None, min_length=1, max_length=10)
    floor: int | None = Field(default=None, ge=0, le=50)
    room_type_code: str | None = None
    features: list[str] | None = None
    kind: str | None = Field(default=None,
                             pattern='^(STANDARD|SUITE_UNIT)$')
    parent_room_no: str | None = None
    is_active: bool | None = None
    set_parent: bool = False   # True + parent_room_no → ربط/فك-ربط مقصود


class RoomTypeIn(BaseModel):
    code: str = Field(min_length=1, max_length=16, pattern=r'^[A-Z0-9-]+$')
    name_ar: str = Field(min_length=2, max_length=80)
    name_en: str = Field(default='', max_length=80)
    capacity_adults: int = Field(default=2, ge=1, le=10)
    capacity_children: int = Field(default=1, ge=0, le=8)
    beds: str = Field(default='', max_length=60)
    amenities: list[str] = []
    base_rate: Decimal = Field(ge=0)
    display_order: int = Field(default=0, ge=0)


class RoomTypePatch(BaseModel):
    name_ar: str | None = Field(default=None, min_length=2, max_length=80)
    name_en: str | None = Field(default=None, max_length=80)
    capacity_adults: int | None = Field(default=None, ge=1, le=10)
    capacity_children: int | None = Field(default=None, ge=0, le=8)
    beds: str | None = Field(default=None, max_length=60)
    amenities: list[str] | None = None
    base_rate: Decimal | None = Field(default=None, ge=0)
    display_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class RatePlanIn(BaseModel):
    code: str = Field(min_length=1, max_length=16, pattern=r'^[A-Z0-9-]+$')
    name_ar: str = Field(min_length=2, max_length=80)
    ref_rate: Decimal | None = Field(default=None, ge=0)
    includes_breakfast: bool = False
    cancel_policy: str = Field(default='مرن', max_length=300)
    min_nights: int = Field(default=1, ge=1, le=90)
    for_corporate: bool = False
    tax_inclusive: bool = False
    meals_included: list[str] = []


class RatePlanPatch(BaseModel):
    name_ar: str | None = Field(default=None, min_length=2, max_length=80)
    ref_rate: Decimal | None = Field(default=None, ge=0)
    includes_breakfast: bool | None = None
    cancel_policy: str | None = Field(default=None, max_length=300)
    min_nights: int | None = Field(default=None, ge=1, le=90)
    for_corporate: bool | None = None
    tax_inclusive: bool | None = None
    meals_included: list[str] | None = None
    is_active: bool | None = None


class RateCalendarBulk(BaseModel):
    """تعبئة تقويم أسعار لمدى ≤ 92 يوماً (03 §1.4) — upsert بلا تكرار."""
    room_type_code: str
    rate_plan_code: str | None = None   # None/'': الافتراضي
    date_from: date
    date_to: date
    price: Decimal = Field(gt=0)
    day_type: str = Field(default='NORMAL', max_length=12)


class ExtraIn(BaseModel):
    code: str = Field(min_length=1, max_length=20, pattern=r'^[A-Z0-9_-]+$')
    name_ar: str = Field(min_length=2, max_length=80)
    price: Decimal = Field(ge=0)
    revenue_account_code: str = Field(min_length=1, max_length=10)


class ExtraPatch(BaseModel):
    name_ar: str | None = Field(default=None, min_length=2, max_length=80)
    price: Decimal | None = Field(default=None, ge=0)
    revenue_account_code: str | None = None
    is_active: bool | None = None
