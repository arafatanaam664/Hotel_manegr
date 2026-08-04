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
    room_no: str = Field(min_length=1, max_length=10)
    floor: int = Field(default=1, ge=0, le=50)
    room_type_code: str
    features: list[str] = []
