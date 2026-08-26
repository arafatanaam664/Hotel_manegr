# مخططات إدخال الموارد البشرية — كل نقطة نهاية بمخطط تحقق (ملف 15)
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class DepartmentIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name_ar: str = Field(min_length=2, max_length=100)
    cost_center_code: str = Field(default='CC-ADMIN', max_length=20)
    payroll_account_code: str = Field(default='6310', max_length=10)
    is_confidential: bool = False


class DepartmentPatch(BaseModel):
    name_ar: str | None = Field(default=None, max_length=100)
    cost_center_code: str | None = Field(default=None, max_length=20)
    payroll_account_code: str | None = Field(default=None, max_length=10)
    is_confidential: bool | None = None
    is_active: bool | None = None


class PositionIn(BaseModel):
    department_id: str
    title: str = Field(min_length=2, max_length=100)
    grade: str = Field(default='G1', max_length=10)


class PositionPatch(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    grade: str | None = Field(default=None, max_length=10)
    is_active: bool | None = None


class EmployeeIn(BaseModel):
    emp_no: str = Field(min_length=2, max_length=20)
    full_name: str = Field(min_length=3, max_length=150)
    department_id: str
    hire_date: date
    base_salary: Decimal = Field(ge=0)
    contract_type: str = Field(default='PERM', pattern='^(PERM|TEMP|PIECE)$')
    position_id: str | None = None
    shift_id: str | None = None
    national_id: str | None = Field(default=None, max_length=40)
    phone: str = Field(default='', max_length=30)
    allowances: list[dict] = Field(default_factory=list)
    bank_account: str | None = Field(default=None, max_length=60)


class SuspendIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class TerminateIn(BaseModel):
    termination_date: date
    reason: str = Field(min_length=3, max_length=300)


class ChangeIn(BaseModel):
    employee_id: str
    change_type: str = Field(pattern='^(TRANSFER|PROMOTE|SALARY)$')
    after: dict
    doc_ref: str = Field(min_length=2, max_length=120)
    effective_from: date


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class ShiftIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    from_time: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    to_time: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    overnight: bool = False


class RosterRow(BaseModel):
    employee_id: str
    date: date
    shift_id: str


class RosterIn(BaseModel):
    rows: list[RosterRow] = Field(min_length=1, max_length=500)


class AttendanceRow(BaseModel):
    employee_id: str
    date: date
    status: str = Field(default='PRESENT', pattern='^(PRESENT|ABSENT|LEAVE)$')
    in_time: str = Field(default='', max_length=5)
    out_time: str = Field(default='', max_length=5)
    late_min: int = Field(default=0, ge=0, le=720)
    early_min: int = Field(default=0, ge=0, le=720)
    overtime_hours: Decimal = Field(default=Decimal('0'), ge=0, le=24)


class AttendanceIn(BaseModel):
    rows: list[AttendanceRow] = Field(min_length=1, max_length=500)


class AttendanceApproveIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)


class LeaveTypeIn(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    name: str = Field(min_length=2, max_length=80)
    paid: bool = True
    accrual_per_month: Decimal = Field(default=Decimal('0'), ge=0, le=31)


class LeaveRequestIn(BaseModel):
    employee_id: str
    leave_type_id: str
    from_date: date
    to_date: date
    days: Decimal = Field(gt=0, le=365)
    reason: str = Field(default='', max_length=300)


class AccrueIn(BaseModel):
    month: str = Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')


class AdvanceIn(BaseModel):
    employee_id: str
    amount: Decimal = Field(gt=0)
    installments: int = Field(ge=1, le=36, default=1)
    first_deduct_month: str = Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    reason: str = Field(default='', max_length=300)


class DisburseIn(BaseModel):
    account_code: str = Field(default='1101', max_length=10)


class PenaltyIn(BaseModel):
    employee_id: str
    pen_date: date
    apply_month: str = Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    amount: Decimal = Field(gt=0)
    reason: str = Field(min_length=3, max_length=300)
    doc_ref: str = Field(default='', max_length=120)


class PayItemIn(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    name: str = Field(min_length=2, max_length=80)
    item_type: str = Field(pattern='^(EARNING|DEDUCTION)$')
    calc: str = Field(default='PCT_BASE', pattern='^(FIXED|PCT_BASE)$')
    pct_base: Decimal = Field(default=Decimal('0'), ge=0, le=100)
    credit_account_code: str = Field(default='2220', max_length=10)


class SuppLineIn(BaseModel):
    code: str = Field(default='ADJ', max_length=20)
    name: str = Field(min_length=2, max_length=80)
    type: str = Field(default='EARNING', pattern='^(EARNING|DEDUCTION)$')
    amount: Decimal = Field(gt=0)
    credit: str = Field(default='2310', max_length=10)
    note: str = Field(default='', max_length=200)


class RunCreateIn(BaseModel):
    month: str = Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    kind: str = Field(default='NORMAL',
                      pattern='^(NORMAL|SUPPLEMENTAL|FINAL)$')
    parent_run_id: str | None = None
    employee_id: str | None = None
    eos_amount: Decimal | None = Field(default=None, ge=0)
    manual_lines: dict[str, list[SuppLineIn]] = Field(default_factory=dict)

    @field_validator('kind')
    @classmethod
    def _needs(cls, v: str) -> str:
        return v


class RecalcIn(BaseModel):
    eos_amount: Decimal | None = Field(default=None, ge=0)


class PayIn(BaseModel):
    account_code: str = Field(default='1101', max_length=10)
    payslip_ids: list[str] | None = None
    receipt_note: str = Field(default='', max_length=200)


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class HrPolicyIn(BaseModel):
    day_count_mode: str | None = Field(default=None,
                                       pattern='^(FIXED30|CALENDAR)$')
    advance_max_pct: Decimal | None = Field(default=None, gt=0, le=100)
    workday_hours: Decimal | None = Field(default=None, gt=0, le=24)
    ot_multiplier: Decimal | None = Field(default=None, gt=0, le=5)
    late_deduct_daily: Decimal | None = Field(default=None, ge=0)
    penalty_credit_code: str | None = Field(default=None,
                                            pattern='^(2220|4901)$')
    eos_enabled: bool | None = None
    eos_month_rate: Decimal | None = Field(default=None, gt=0, le=1)
    eos_credit_account_code: str | None = Field(default=None, max_length=10)


class EosAccrueIn(BaseModel):
    month: str = Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
