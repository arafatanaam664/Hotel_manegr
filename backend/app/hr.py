"""خدمة الموارد البشرية والرواتب — ملف 06 (قانون ملزم).

قواعد معمارية ثابتة:
- كل أثر مالي يولد هنا يمر عبر نواة المحرك create_and_post_journal فقط
  (أحداث #21 استحقاق، #22 صرف، #23 منح سلفة — ملف 02 §8) بنوع AUTO_PAYROLL.
- مصروف الرواتب في #21 = المستحق الفعلي (الغياب/التأخير/بدون أجر يخفض
  المصروف نفسه)، والصافي إلى 2310، والاستقطاعات النظامية إلى 2220،
  وأقساط السلف إلى 1130، والجزاءات إيراداً 4901 إن ضبطت السياسة كذلك.
- لا قيد قبل اعتمادين: إعداد HR ثم اعتماد مالي (لا اعتماد ذاتي — ملف 14).
- مسير معتمد/مرحَّل غير قابل للتعديل إطلاقاً؛ التصحيح بمسير تسوية (§4.3).
- خصوصية صفية (§6): الراتب مقنّع دون صلاحية hr.salary.view، وأقسام
  السرية تتطلب hr.salary.confidential، ومشاهدة القسائم حدث مدقق.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
import calendar
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m
from .audit import audit
from .posting import D, PostingError, create_and_post_journal
from .security import decrypt_pii, encrypt_pii


def _now() -> datetime:
    return datetime.now(timezone.utc)


def err(code: str, msg: str):
    raise PostingError(code, msg)


def q4(v: Decimal) -> Decimal:
    return Decimal(v).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)


def q2(v: Decimal) -> Decimal:
    return Decimal(v).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


_MONTH_RE = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')


def _check_month(month: str) -> str:
    if not _MONTH_RE.match(month or ''):
        err('HR.BAD_MONTH', 'صيغة الشهر يجب أن تكون YYYY-MM')
    return month


def _month_bounds(month: str) -> tuple[date, date, int]:
    y, mo = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(y, mo)[1]
    return date(y, mo, 1), date(y, mo, last), last


def _next_month(month: str) -> str:
    y, mo = int(month[:4]), int(month[5:7])
    mo += 1
    if mo == 13:
        mo, y = 1, y + 1
    return f'{y:04d}-{mo:02d}'


# ────────────────────────────────────────────────────────────────────
# السياسة (§4.1 — تُضبط بصلاحية مالية عليا)
# ────────────────────────────────────────────────────────────────────
def get_policy(db: Session, tenant_id: str) -> m.HrPolicy:
    p = db.get(m.HrPolicy, tenant_id)
    if not p:
        p = m.HrPolicy(tenant_id=tenant_id)
        db.add(p)
        db.flush()
    return p


def update_policy(db: Session, *, tenant_id: str, actor_id: str,
                  changes: dict) -> m.HrPolicy:
    p = get_policy(db, tenant_id)
    before = {'day_count_mode': p.day_count_mode,
              'advance_max_pct': str(p.advance_max_pct),
              'workday_hours': str(p.workday_hours),
              'ot_multiplier': str(p.ot_multiplier),
              'late_deduct_daily': str(p.late_deduct_daily),
              'penalty_credit_code': p.penalty_credit_code,
              'eos_enabled': p.eos_enabled,
              'eos_month_rate': str(p.eos_month_rate),
              'eos_credit_account_code': p.eos_credit_account_code}
    if changes.get('day_count_mode') is not None:
        if changes['day_count_mode'] not in ('FIXED30', 'CALENDAR'):
            err('HR.BAD_POLICY', 'نمط العد اليومي يجب FIXED30 أو CALENDAR')
        p.day_count_mode = changes['day_count_mode']
    if changes.get('penalty_credit_code') is not None:
        if changes['penalty_credit_code'] not in ('2220', '4901'):
            err('HR.BAD_POLICY', 'وجه الجزاءات يجب 2220 أو 4901')
        p.penalty_credit_code = changes['penalty_credit_code']
    if changes.get('eos_credit_account_code') is not None:
        p.eos_credit_account_code = changes['eos_credit_account_code']
    if changes.get('eos_enabled') is not None:
        p.eos_enabled = bool(changes['eos_enabled'])
    for k in ('advance_max_pct', 'workday_hours', 'ot_multiplier',
              'late_deduct_daily', 'eos_month_rate'):
        if changes.get(k) is not None:
            v = D(changes[k])
            if v <= 0:
                err('HR.BAD_POLICY', f'قيمة السياسة {k} يجب أن تكون موجبة')
            if k == 'advance_max_pct' and v > 100:
                err('HR.BAD_POLICY', 'سقف السلفة لا يتجاوز 100% من الراتب')
            setattr(p, k, v)
    p.updated_by = actor_id
    p.updated_at = _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='policy.update', entity='hr_policy',
          entity_id=tenant_id, before=before,
          after={'day_count_mode': p.day_count_mode,
                 'advance_max_pct': str(p.advance_max_pct),
                 'workday_hours': str(p.workday_hours),
                 'ot_multiplier': str(p.ot_multiplier),
                 'late_deduct_daily': str(p.late_deduct_daily),
                 'penalty_credit_code': p.penalty_credit_code,
                 'eos_enabled': p.eos_enabled,
                 'eos_month_rate': str(p.eos_month_rate),
                 'eos_credit_account_code': p.eos_credit_account_code})
    return p


def _divisor(pol: m.HrPolicy, month_days: int) -> Decimal:
    return Decimal(30) if pol.day_count_mode == 'FIXED30' else Decimal(month_days)


def _account_exists(db: Session, tenant_id: str, code: str) -> bool:
    return db.execute(select(m.Account.id).where(
        m.Account.tenant_id == tenant_id, m.Account.code == code,
        m.Account.is_postable.is_(True))).first() is not None


# ────────────────────────────────────────────────────────────────────
# §1 الهيكل التنظيمي
# ────────────────────────────────────────────────────────────────────
def create_department(db: Session, *, tenant_id: str, actor_id: str,
                      code: str, name_ar: str, cost_center_code: str,
                      payroll_account_code: str, is_confidential: bool = False
                      ) -> m.HrDepartment:
    code = code.strip().upper()
    if not _account_exists(db, tenant_id, payroll_account_code):
        err('HR.BAD_ACCOUNT', 'حساب الرواتب غير موجود أو غير قابل للترحيل')
    if db.execute(select(m.HrDepartment.id).where(
            m.HrDepartment.tenant_id == tenant_id,
            m.HrDepartment.code == code)).first():
        err('HR.DUP_DEPARTMENT', f'رمز القسم {code} مستخدم')
    d = m.HrDepartment(tenant_id=tenant_id, code=code, name_ar=name_ar,
                       cost_center_code=cost_center_code,
                       payroll_account_code=payroll_account_code,
                       is_confidential=is_confidential)
    db.add(d)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='department.create', entity='hr_department',
          entity_id=d.id, after={'code': code, 'name_ar': name_ar,
                                 'payroll_account_code': payroll_account_code})
    return d


def update_department(db: Session, *, tenant_id: str, actor_id: str,
                      dept_id: str, **fields) -> m.HrDepartment:
    d = db.get(m.HrDepartment, dept_id)
    if not d or d.tenant_id != tenant_id:
        err('HR.DEPT_NOT_FOUND', 'القسم غير موجود')
    before = {'name_ar': d.name_ar,
              'payroll_account_code': d.payroll_account_code,
              'cost_center_code': d.cost_center_code,
              'is_confidential': d.is_confidential,
              'is_active': d.is_active}
    if fields.get('payroll_account_code'):
        if not _account_exists(db, tenant_id, fields['payroll_account_code']):
            err('HR.BAD_ACCOUNT', 'حساب الرواتب غير موجود أو غير قابل للترحيل')
        d.payroll_account_code = fields['payroll_account_code']
    if fields.get('name_ar'):
        d.name_ar = fields['name_ar']
    if fields.get('cost_center_code'):
        d.cost_center_code = fields['cost_center_code']
    if fields.get('is_confidential') is not None:
        d.is_confidential = bool(fields['is_confidential'])
    if fields.get('is_active') is not None:
        d.is_active = bool(fields['is_active'])
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='department.update', entity='hr_department',
          entity_id=d.id, before=before,
          after={'name_ar': d.name_ar,
                 'payroll_account_code': d.payroll_account_code,
                 'is_confidential': d.is_confidential,
                 'is_active': d.is_active})
    return d


def list_departments(db: Session, tenant_id: str) -> list[m.HrDepartment]:
    return list(db.execute(select(m.HrDepartment).where(
        m.HrDepartment.tenant_id == tenant_id).order_by(m.HrDepartment.code)
    ).scalars())


def create_position(db: Session, *, tenant_id: str, actor_id: str,
                    department_id: str, title: str, grade: str
                    ) -> m.HrPosition:
    d = db.get(m.HrDepartment, department_id)
    if not d or d.tenant_id != tenant_id:
        err('HR.DEPT_NOT_FOUND', 'القسم غير موجود')
    p = m.HrPosition(tenant_id=tenant_id, department_id=department_id,
                     title=title, grade=grade)
    db.add(p)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='position.create', entity='hr_position',
          entity_id=p.id, after={'title': title, 'grade': grade,
                                 'department': d.code})
    return p


def update_position(db: Session, *, tenant_id: str, actor_id: str,
                    position_id: str, **fields) -> m.HrPosition:
    p = db.get(m.HrPosition, position_id)
    if not p or p.tenant_id != tenant_id:
        err('HR.POSITION_NOT_FOUND', 'الوظيفة غير موجودة')
    if fields.get('title'):
        p.title = fields['title']
    if fields.get('grade'):
        p.grade = fields['grade']
    if fields.get('is_active') is not None:
        p.is_active = bool(fields['is_active'])
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='position.update', entity='hr_position',
          entity_id=p.id, after={'title': p.title, 'grade': p.grade,
                                 'is_active': p.is_active})
    return p


def list_positions(db: Session, tenant_id: str,
                   department_id: str = '') -> list[m.HrPosition]:
    q = select(m.HrPosition).where(m.HrPosition.tenant_id == tenant_id)
    if department_id:
        q = q.where(m.HrPosition.department_id == department_id)
    return list(db.execute(q.order_by(m.HrPosition.grade, m.HrPosition.title)
                           ).scalars())


# ────────────────────────────────────────────────────────────────────
# §1 ملفات الموظفين + الخصوصية الصفية (§6)
# ────────────────────────────────────────────────────────────────────
_MASKED = -1  # قيمة حارسة للحقول المالية المقنَّعة


def dept_by_id(db: Session, tenant_id: str, dept_id: str) -> m.HrDepartment:
    d = db.get(m.HrDepartment, dept_id)
    if not d or d.tenant_id != tenant_id:
        err('HR.DEPT_NOT_FOUND', 'القسم غير موجود')
    return d


def employee_to_dict(emp: m.HrEmployee, dept: m.HrDepartment | None,
                     *, see_salary: bool, see_confidential: bool) -> dict:
    """الخصوصية الصفية (§6): الراتب يُقنَّع دون hr.salary.view،
    ورواتب الأقسام السرية تُقنَّع دون hr.salary.confidential."""
    confidential = bool(dept and dept.is_confidential)
    show_money = see_salary and (see_confidential or not confidential)
    try:
        nat = decrypt_pii(emp.national_id_enc) if emp.national_id_enc else None
    except Exception:
        nat = None
    return {
        'id': emp.id, 'emp_no': emp.emp_no, 'full_name': emp.full_name,
        'national_id': nat,
        'phone': emp.phone,
        'branch_id': emp.branch_id,
        'department_id': emp.department_id,
        'department': dept.name_ar if dept else '',
        'department_code': dept.code if dept else '',
        'department_confidential': confidential,
        'position_id': emp.position_id, 'shift_id': emp.shift_id,
        'hire_date': emp.hire_date.isoformat(),
        'contract_type': emp.contract_type,
        'base_salary': str(emp.base_salary) if show_money else None,
        'allowances': (emp.allowances or []) if show_money else [],
        'salary_masked': not show_money,
        'status': emp.status,
        'termination_date': (emp.termination_date.isoformat()
                             if emp.termination_date else None),
        'termination_reason': emp.termination_reason,
    }


def create_employee(db: Session, *, tenant_id: str, actor_id: str,
                    branch_id: str, emp_no: str, full_name: str,
                    department_id: str, hire_date: date, base_salary,
                    contract_type: str = 'PERM',
                    position_id: str | None = None,
                    shift_id: str | None = None,
                    national_id: str | None = None, phone: str = '',
                    allowances: list | None = None,
                    bank_account: str | None = None) -> m.HrEmployee:
    emp_no = emp_no.strip().upper()
    if db.execute(select(m.HrEmployee.id).where(
            m.HrEmployee.tenant_id == tenant_id,
            m.HrEmployee.emp_no == emp_no)).first():
        err('HR.DUP_EMP_NO', f'الرقم الوظيفي {emp_no} مستخدم')
    dept_by_id(db, tenant_id, department_id)
    if contract_type not in ('PERM', 'TEMP', 'PIECE'):
        err('HR.BAD_CONTRACT', 'نوع العقد يجب PERM أو TEMP أو PIECE')
    if D(base_salary) <= 0 and contract_type != 'PIECE':
        err('HR.BAD_SALARY', 'الأجر الأساسي يجب أن يكون موجباً')
    allw = _validate_allowances(allowances or [])
    e = m.HrEmployee(tenant_id=tenant_id, branch_id=branch_id, emp_no=emp_no,
                     full_name=full_name.strip(), department_id=department_id,
                     position_id=position_id, shift_id=shift_id,
                     hire_date=hire_date, contract_type=contract_type,
                     base_salary=D(base_salary), allowances=allw,
                     national_id_enc=(encrypt_pii(national_id)
                                      if national_id else None),
                     bank_enc=(encrypt_pii(bank_account)
                               if bank_account else None),
                     phone=phone, created_by=actor_id)
    db.add(e)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='employee.create', entity='hr_employee',
          entity_id=e.id,
          after={'emp_no': emp_no, 'full_name': e.full_name,
                 'department_id': department_id})
    return e


def _validate_allowances(rows: list) -> list:
    out = []
    for r in rows:
        code = (r.get('code') or '').strip().upper()
        if not code:
            err('HR.BAD_ALLOWANCE', 'كل بدل يحتاج رمزاً')
        if r.get('amount') is not None:
            if D(r['amount']) < 0:
                err('HR.BAD_ALLOWANCE', 'مبلغ البدل سالب')
            out.append({'code': code, 'name': r.get('name', code),
                        'amount': str(q4(D(r['amount'])))})
        elif r.get('pct_base') is not None:
            if D(r['pct_base']) <= 0 or D(r['pct_base']) > 200:
                err('HR.BAD_ALLOWANCE', 'نسبة البدل خارج المدى')
            out.append({'code': code, 'name': r.get('name', code),
                        'pct_base': str(D(r['pct_base']))})
        else:
            err('HR.BAD_ALLOWANCE', 'البدل يحتاج مبلغاً أو نسبة من الأساسي')
    return out


def list_employees(db: Session, tenant_id: str,
                   status: str = '', department_id: str = '',
                   q: str = '') -> list[m.HrEmployee]:
    st = select(m.HrEmployee).where(m.HrEmployee.tenant_id == tenant_id)
    if status:
        st = st.where(m.HrEmployee.status == status)
    if department_id:
        st = st.where(m.HrEmployee.department_id == department_id)
    if q:
        st = st.where(m.HrEmployee.full_name.ilike(f'%{q}%'))
    return list(db.execute(st.order_by(m.HrEmployee.emp_no)).scalars())


def get_employee(db: Session, tenant_id: str, emp_id: str) -> m.HrEmployee:
    e = db.get(m.HrEmployee, emp_id)
    if not e or e.tenant_id != tenant_id:
        err('HR.EMP_NOT_FOUND', 'الموظف غير موجود')
    return e


def suspend_employee(db: Session, *, tenant_id: str, actor_id: str,
                     emp_id: str, reason: str) -> m.HrEmployee:
    e = get_employee(db, tenant_id, emp_id)
    if e.status == 'TERMINATED':
        err('HR.EMP_TERMINATED', 'لا يمكن إيقاف موظف منتهي الخدمة')
    before = e.status
    e.status = 'SUSPENDED' if e.status == 'ACTIVE' else 'ACTIVE'
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='employee.suspend.toggle', entity='hr_employee',
          entity_id=e.id, before={'status': before},
          after={'status': e.status, 'reason': reason})
    return e


def terminate_employee(db: Session, *, tenant_id: str, actor_id: str,
                       emp_id: str, termination_date: date,
                       reason: str) -> m.HrEmployee:
    """إنهاء خدمة (§1): حالة نهائية غير قابلة للعكس إدارياً،
    والتسوية المالية عبر مسير FINAL حصرياً (قبول-3)."""
    e = get_employee(db, tenant_id, emp_id)
    if e.status == 'TERMINATED':
        err('HR.EMP_TERMINATED', 'الموظف منتهي الخدمة أصلاً')
    if termination_date < e.hire_date:
        err('HR.BAD_DATE', 'تاريخ الإنهاء قبل تاريخ التعيين')
    e.status = 'TERMINATED'
    e.termination_date = termination_date
    e.termination_reason = reason
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='employee.terminate', entity='hr_employee',
          entity_id=e.id, before={'status': 'ACTIVE'},
          after={'status': 'TERMINATED',
                 'termination_date': termination_date.isoformat(),
                 'reason': reason})
    return e


def create_change(db: Session, *, tenant_id: str, actor_id: str,
                  emp_id: str, change_type: str, after: dict,
                  doc_ref: str, effective_from: date) -> m.HrEmployeeChange:
    """نقل/ترقية/تعديل أجر بمستند — لا اعتماد ذاتي (§1 + ملف 14)."""
    e = get_employee(db, tenant_id, emp_id)
    if e.status == 'TERMINATED':
        err('HR.EMP_TERMINATED', 'لا تغيير لموظف منتهي')
    if change_type not in ('TRANSFER', 'PROMOTE', 'SALARY'):
        err('HR.BAD_CHANGE_TYPE', 'نوع التغيير غير معروف')
    before: dict = {}
    if change_type == 'TRANSFER':
        dept_by_id(db, tenant_id, after.get('department_id', ''))
        before = {'department_id': e.department_id}
    elif change_type == 'PROMOTE':
        if after.get('position_id'):
            p = db.get(m.HrPosition, after['position_id'])
            if not p or p.tenant_id != tenant_id:
                err('HR.POSITION_NOT_FOUND', 'الوظيفة غير موجودة')
        before = {'position_id': e.position_id}
    else:
        if D(after.get('base_salary', 0)) <= 0:
            err('HR.BAD_SALARY', 'الأجر الجديد يجب أن يكون موجباً')
        if 'allowances' in after:
            _validate_allowances(after['allowances'])
        before = {'base_salary': str(e.base_salary),
                  'allowances': e.allowances or []}
    c = m.HrEmployeeChange(tenant_id=tenant_id, employee_id=emp_id,
                           change_type=change_type, before=before,
                           after=after, doc_ref=doc_ref,
                           effective_from=effective_from, created_by=actor_id)
    db.add(c)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='employee.change.create',
          entity='hr_employee_change', entity_id=c.id,
          after={'change_type': change_type, 'doc_ref': doc_ref})
    return c


def approve_change(db: Session, *, tenant_id: str, actor_id: str,
                   change_id: str) -> m.HrEmployeeChange:
    c = db.get(m.HrEmployeeChange, change_id)
    if not c or c.tenant_id != tenant_id or c.status != 'PENDING':
        err('HR.CHANGE_STATE', 'التغيير غير موجود أو ليس بانتظار اعتماد')
    if c.created_by == actor_id:
        err('HR.SELF_APPROVAL', 'لا يمكن اعتماد مستند أنشأته بنفسك')
    e = get_employee(db, tenant_id, c.employee_id)
    if e.status == 'TERMINATED':
        err('HR.EMP_TERMINATED', 'الموظف أنهيت خدمته أثناء الانتظار')
    if c.change_type == 'TRANSFER':
        e.department_id = c.after['department_id']
    elif c.change_type == 'PROMOTE':
        e.position_id = c.after.get('position_id')
    else:
        e.base_salary = D(c.after['base_salary'])
        if 'allowances' in c.after:
            e.allowances = _validate_allowances(c.after['allowances'])
    c.status = 'APPROVED'
    c.approved_by = actor_id
    c.approved_at = _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='employee.change.approve',
          entity='hr_employee_change', entity_id=c.id,
          before=c.before, after=c.after)
    return c


def reject_change(db: Session, *, tenant_id: str, actor_id: str,
                  change_id: str, reason: str) -> m.HrEmployeeChange:
    c = db.get(m.HrEmployeeChange, change_id)
    if not c or c.tenant_id != tenant_id or c.status != 'PENDING':
        err('HR.CHANGE_STATE', 'التغيير غير موجود أو ليس بانتظار اعتماد')
    c.status = 'REJECTED'
    c.reject_reason = reason
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='employee.change.reject',
          entity='hr_employee_change', entity_id=c.id,
          after={'reason': reason})
    return c


def list_changes(db: Session, tenant_id: str,
                 employee_id: str = '') -> list[m.HrEmployeeChange]:
    q = select(m.HrEmployeeChange).where(
        m.HrEmployeeChange.tenant_id == tenant_id)
    if employee_id:
        q = q.where(m.HrEmployeeChange.employee_id == employee_id)
    return list(db.execute(q.order_by(
        m.HrEmployeeChange.created_at.desc())).scalars())


# ────────────────────────────────────────────────────────────────────
# §2 الورديات والجداول والحضور
# ────────────────────────────────────────────────────────────────────
def create_shift(db: Session, *, tenant_id: str, actor_id: str, name: str,
                 from_time: str, to_time: str, overnight: bool) -> m.HrShift:
    s = m.HrShift(tenant_id=tenant_id, name=name, from_time=from_time,
                  to_time=to_time, overnight=overnight)
    db.add(s)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='shift.create', entity='hr_shift',
          entity_id=s.id, after={'name': name, 'from': from_time,
                                 'to': to_time})
    return s


def list_shifts(db: Session, tenant_id: str) -> list[m.HrShift]:
    return list(db.execute(select(m.HrShift).where(
        m.HrShift.tenant_id == tenant_id, m.HrShift.is_active.is_(True))
    ).scalars())


def set_roster(db: Session, *, tenant_id: str, actor_id: str, rows: list
               ) -> int:
    """إسناد جماعي: [{employee_id, date, shift_id}] — upsert ذرّي."""
    n = 0
    for r in rows:
        emp = get_employee(db, tenant_id, r['employee_id'])
        shift = db.get(m.HrShift, r['shift_id'])
        if not shift or shift.tenant_id != tenant_id or not shift.is_active:
            err('HR.SHIFT_NOT_FOUND', 'وردية غير موجودة')
        existing = db.execute(select(m.HrRoster).where(
            m.HrRoster.tenant_id == tenant_id,
            m.HrRoster.employee_id == emp.id,
            m.HrRoster.roster_date == r['date'])).scalar_one_or_none()
        if existing:
            existing.shift_id = shift.id
        else:
            db.add(m.HrRoster(tenant_id=tenant_id, employee_id=emp.id,
                              roster_date=r['date'], shift_id=shift.id))
        n += 1
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='roster.set', entity='hr_roster',
          entity_id='', after={'rows': n})
    return n


def list_roster(db: Session, tenant_id: str, month: str) -> list[m.HrRoster]:
    _check_month(month)
    d1, d2, _ = _month_bounds(month)
    return list(db.execute(select(m.HrRoster).where(
        m.HrRoster.tenant_id == tenant_id,
        m.HrRoster.roster_date.between(d1, d2)).order_by(
            m.HrRoster.roster_date)).scalars())


def upsert_attendance(db: Session, *, tenant_id: str, actor_id: str,
                      rows: list) -> int:
    """رصد جماعي يومي: صف واحد لكل (موظف، يوم)؛ يُعاد إدخاله قبل الاعتماد."""
    n = 0
    for r in rows:
        emp = get_employee(db, tenant_id, r['employee_id'])
        att_date = r['date']
        status = r.get('status', 'PRESENT')
        if status not in ('PRESENT', 'ABSENT', 'LEAVE'):
            err('HR.BAD_ATT_STATUS', 'حالة الحضور غير صحيحة')
        existing = db.execute(select(m.HrAttendance).where(
            m.HrAttendance.tenant_id == tenant_id,
            m.HrAttendance.employee_id == emp.id,
            m.HrAttendance.att_date == att_date)).scalar_one_or_none()
        if existing:
            if existing.approved_by:
                err('HR.ATT_APPROVED',
                    f'حضور {emp.emp_no} يوم {att_date} معتمد — '
                    'الغِ الاعتماد أولاً بسلطة المشرف أو صحح بصف جديد')
            row = existing
        else:
            row = m.HrAttendance(tenant_id=tenant_id, employee_id=emp.id,
                                 att_date=att_date, entered_by=actor_id)
            db.add(row)
        row.status = status
        row.in_time = r.get('in_time', '')
        row.out_time = r.get('out_time', '')
        row.late_min = int(r.get('late_min', 0) or 0)
        row.early_min = int(r.get('early_min', 0) or 0)
        row.overtime_hours = D(r.get('overtime_hours', 0) or 0)
        if row.late_min < 0 or row.early_min < 0 or row.overtime_hours < 0:
            err('HR.BAD_ATT_VALUE', 'دقائق/ساعات سالبة مرفوضة')
        n += 1
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='attendance.upsert', entity='hr_attendance',
          entity_id='', after={'rows': n})
    return n


def approve_attendance(db: Session, *, tenant_id: str, actor_id: str,
                       ids: list[str]) -> int:
    """اعتماد مشرف (§2) — الإضافي لا يدخل الرواتب إلا بعد هذه الخطوة."""
    n = 0
    for aid in ids:
        row = db.get(m.HrAttendance, aid)
        if not row or row.tenant_id != tenant_id:
            err('HR.ATT_NOT_FOUND', 'سجل حضور غير موجود')
        if row.entered_by == actor_id:
            err('HR.SELF_APPROVAL', 'لا يمكن اعتماد حضور أدخلته بنفسك')
        if not row.approved_by:
            row.approved_by = actor_id
            row.approved_at = _now()
            n += 1
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='attendance.approve', entity='hr_attendance',
          entity_id='', after={'rows': n})
    return n


def unapprove_attendance(db: Session, *, tenant_id: str, actor_id: str,
                         ids: list[str]) -> int:
    n = 0
    for aid in ids:
        row = db.get(m.HrAttendance, aid)
        if not row or row.tenant_id != tenant_id:
            err('HR.ATT_NOT_FOUND', 'سجل حضور غير موجود')
        if row.approved_by:
            month = f'{row.att_date.year:04d}-{row.att_date.month:02d}'
            locked = db.execute(select(m.HrPayrollRun.id).where(
                m.HrPayrollRun.tenant_id == tenant_id,
                m.HrPayrollRun.month == month,
                m.HrPayrollRun.status.in_(['POSTED', 'PAID']))).first()
            if locked:
                err('HR.MONTH_LOCKED',
                    'شهر الحضور مرحل رواتبه — التصحيح بمسير تسوية فقط')
            row.approved_by = None
            row.approved_at = None
            n += 1
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='attendance.unapprove', entity='hr_attendance',
          entity_id='', after={'rows': n})
    return n


def list_attendance(db: Session, tenant_id: str, month: str,
                    employee_id: str = '') -> list[m.HrAttendance]:
    _check_month(month)
    d1, d2, _ = _month_bounds(month)
    q = select(m.HrAttendance).where(
        m.HrAttendance.tenant_id == tenant_id,
        m.HrAttendance.att_date.between(d1, d2))
    if employee_id:
        q = q.where(m.HrAttendance.employee_id == employee_id)
    return list(db.execute(q.order_by(m.HrAttendance.att_date)).scalars())


# ────────────────────────────────────────────────────────────────────
# §2 الإجازات: أنواع، أرصدة، طلبات
# ────────────────────────────────────────────────────────────────────
def create_leave_type(db: Session, *, tenant_id: str, actor_id: str,
                      code: str, name: str, paid: bool,
                      accrual_per_month) -> m.HrLeaveType:
    code = code.strip().upper()
    if db.execute(select(m.HrLeaveType.id).where(
            m.HrLeaveType.tenant_id == tenant_id,
            m.HrLeaveType.code == code)).first():
        err('HR.DUP_LEAVE_TYPE', f'رمز النوع {code} مستخدم')
    lt = m.HrLeaveType(tenant_id=tenant_id, code=code, name=name, paid=paid,
                       accrual_per_month=D(accrual_per_month))
    db.add(lt)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='leave_type.create', entity='hr_leave_type',
          entity_id=lt.id, after={'code': code, 'paid': paid,
                                  'accrual': str(accrual_per_month)})
    return lt


def list_leave_types(db: Session, tenant_id: str) -> list[m.HrLeaveType]:
    return list(db.execute(select(m.HrLeaveType).where(
        m.HrLeaveType.tenant_id == tenant_id,
        m.HrLeaveType.is_active.is_(True))).scalars())


def _bal(db: Session, tenant_id: str, emp_id: str, lt_id: str,
         year: int) -> m.HrLeaveBalance:
    row = db.execute(select(m.HrLeaveBalance).where(
        m.HrLeaveBalance.tenant_id == tenant_id,
        m.HrLeaveBalance.employee_id == emp_id,
        m.HrLeaveBalance.leave_type_id == lt_id,
        m.HrLeaveBalance.year == year)).scalar_one_or_none()
    if not row:
        row = m.HrLeaveBalance(tenant_id=tenant_id, employee_id=emp_id,
                               leave_type_id=lt_id, year=year)
        db.add(row)
        db.flush()
    return row


def accrue_leave(db: Session, *, tenant_id: str, actor_id: str,
                 month: str) -> dict:
    """استحقاق شهري (§2): يضيف accrual_per_month لكل موظف نشط/موقوف —
    ذي قوة تكرارية عبر accrued_months (إعادة النداء آمنة)."""
    month = _check_month(month)
    year = int(month[:4])
    added = 0
    types = list_leave_types(db, tenant_id)
    emps = list_employees(db, tenant_id)
    for lt in types:
        if D(lt.accrual_per_month) <= 0:
            continue
        for e in emps:
            if e.status == 'TERMINATED':
                continue
            b = _bal(db, tenant_id, e.id, lt.id, year)
            months = list(b.accrued_months or [])
            if month in months:
                continue
            b.entitled = D(b.entitled) + D(lt.accrual_per_month)
            months.append(month)
            b.accrued_months = months
            added += 1
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='leave.accrue', entity='hr_leave_balance',
          entity_id='', after={'month': month, 'rows': added})
    return {'month': month, 'accrued_rows': added}


def create_leave_request(db: Session, *, tenant_id: str, actor_id: str,
                         employee_id: str, leave_type_id: str,
                         from_date: date, to_date: date, days,
                         reason: str) -> m.HrLeaveRequest:
    e = get_employee(db, tenant_id, employee_id)
    if e.status == 'TERMINATED':
        err('HR.EMP_TERMINATED', 'لا إجازة لموظف منتهي')
    lt = db.get(m.HrLeaveType, leave_type_id)
    if not lt or lt.tenant_id != tenant_id or not lt.is_active:
        err('HR.LEAVE_TYPE_NOT_FOUND', 'نوع الإجازة غير موجود')
    if to_date < from_date:
        err('HR.BAD_DATE_RANGE', 'نهاية الإجازة قبل بدايتها')
    if from_date.month != to_date.month or from_date.year != to_date.year:
        err('HR.CROSS_MONTH',
            'v1: الطلبات ضمن شهر واحد — قسّمها على طلبين عند عبور الشهور')
    days = D(days)
    if days <= 0:
        err('HR.BAD_DAYS', 'أيام الإجازة يجب أن تكون موجبة')
    if lt.paid:
        # يمنع تجاوز الرصيد (§2: يخصم من الرصيد آلياً)
        for year in {from_date.year}:
            b = _bal(db, tenant_id, e.id, lt.id, year)
            available = D(b.entitled) - D(b.used)
            # الطلبات المعلقة تحجز رصيداً حتى لا تتجاوز الموافقات المتزامنة
            pending = db.execute(select(func.coalesce(
                func.sum(m.HrLeaveRequest.days), 0)).where(
                m.HrLeaveRequest.tenant_id == tenant_id,
                m.HrLeaveRequest.employee_id == e.id,
                m.HrLeaveRequest.leave_type_id == lt.id,
                m.HrLeaveRequest.status == 'PENDING',
                m.HrLeaveRequest.from_date >= date(year, 1, 1),
                m.HrLeaveRequest.from_date <= date(year, 12, 31))).scalar_one()
            if available - D(pending) < days:
                err('HR.LEAVE_INSUFFICIENT',
                    f'الرصيد المتاح {available - D(pending)} يوم '
                    f'أقل من المطلوب {days} لنوع {lt.code}')
    r = m.HrLeaveRequest(tenant_id=tenant_id, employee_id=e.id,
                         leave_type_id=lt.id, from_date=from_date,
                         to_date=to_date, days=days, reason=reason,
                         created_by=actor_id)
    db.add(r)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='leave.create', entity='hr_leave_request',
          entity_id=r.id, after={'days': str(days), 'type': lt.code,
                                 'paid': lt.paid})
    return r


def approve_leave(db: Session, *, tenant_id: str, actor_id: str,
                  request_id: str) -> m.HrLeaveRequest:
    """اعتماد ← خصم الرصيد آلياً (§2) — لا اعتماد ذاتي، ولا رصيد سالب."""
    r = db.get(m.HrLeaveRequest, request_id)
    if not r or r.tenant_id != tenant_id or r.status != 'PENDING':
        err('HR.LEAVE_STATE', 'طلب الإجازة غير موجود أو ليس معلقاً')
    if r.created_by == actor_id:
        err('HR.SELF_APPROVAL', 'لا يمكن اعتماد طلب أنشأته بنفسك')
    lt = db.get(m.HrLeaveType, r.leave_type_id)
    if lt.paid:
        b = _bal(db, tenant_id, r.employee_id, lt.id, r.from_date.year)
        available = D(b.entitled) - D(b.used)
        if available < D(r.days):
            err('HR.LEAVE_INSUFFICIENT',
                'الرصيد لم يعد يكفي منذ تقديم الطلب')
        b.used = D(b.used) + D(r.days)
    r.status = 'APPROVED'
    r.approved_by = actor_id
    r.approved_at = _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='leave.approve', entity='hr_leave_request',
          entity_id=r.id,
          after={'days': str(r.days), 'balance_used_after':
                 str(b.used) if lt.paid else 'غير مدفوعة'})
    return r


def reject_leave(db: Session, *, tenant_id: str, actor_id: str,
                 request_id: str, reason: str) -> m.HrLeaveRequest:
    r = db.get(m.HrLeaveRequest, request_id)
    if not r or r.tenant_id != tenant_id or r.status != 'PENDING':
        err('HR.LEAVE_STATE', 'طلب الإجازة غير موجود أو ليس معلقاً')
    r.status = 'REJECTED'
    r.reject_reason = reason
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='leave.reject', entity='hr_leave_request',
          entity_id=r.id, after={'reason': reason})
    return r


def list_leave_requests(db: Session, tenant_id: str, status: str = '',
                        employee_id: str = '') -> list[m.HrLeaveRequest]:
    q = select(m.HrLeaveRequest).where(
        m.HrLeaveRequest.tenant_id == tenant_id)
    if status:
        q = q.where(m.HrLeaveRequest.status == status)
    if employee_id:
        q = q.where(m.HrLeaveRequest.employee_id == employee_id)
    return list(db.execute(q.order_by(
        m.HrLeaveRequest.created_at.desc())).scalars())


def list_leave_balances(db: Session, tenant_id: str,
                        year: int) -> list[m.HrLeaveBalance]:
    return list(db.execute(select(m.HrLeaveBalance).where(
        m.HrLeaveBalance.tenant_id == tenant_id,
        m.HrLeaveBalance.year == year)).scalars())


# ────────────────────────────────────────────────────────────────────
# §3 السلف والشرطات
# ────────────────────────────────────────────────────────────────────
def create_advance(db: Session, *, tenant_id: str, actor_id: str,
                   employee_id: str, amount, installments: int,
                   first_deduct_month: str, reason: str) -> m.HrAdvance:
    """طلب سلفة بسقف ≤ advance_max_pct% من الراتب (§3 — مثلاً 50%)."""
    e = get_employee(db, tenant_id, employee_id)
    if e.status == 'TERMINATED':
        err('HR.EMP_TERMINATED', 'لا سلفة لموظف منتهي')
    pol = get_policy(db, tenant_id)
    amount = q4(D(amount))
    cap = q4(D(e.base_salary) * D(pol.advance_max_pct) / Decimal(100))
    if amount <= 0 or amount > cap:
        err('HR.ADV_CAP', f'السلفة يجب أن تكون موجبة ولا تتجاوز '
                          f'{cap} (سقف {pol.advance_max_pct}% من الأساسي)')
    if installments < 1 or installments > 36:
        err('HR.BAD_INSTALLMENTS', 'عدد الأقساط خارج المدى (1..36)')
    first_deduct_month = _check_month(first_deduct_month)
    inst = q2(amount / Decimal(installments))
    # آخر قسط يمتص كسر التقريب: مجموع الأقساط = المبلغ حرفياً
    a = m.HrAdvance(tenant_id=tenant_id, employee_id=e.id, amount=amount,
                    installments=installments, installment_amount=inst,
                    request_date=date.today(),
                    first_deduct_month=first_deduct_month, reason=reason,
                    created_by=actor_id)
    db.add(a)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='advance.create', entity='hr_advance',
          entity_id=a.id, after={'amount': str(amount), 'cap': str(cap),
                                 'installments': installments})
    return a


def approve_advance(db: Session, *, tenant_id: str, actor_id: str,
                    advance_id: str) -> m.HrAdvance:
    a = db.get(m.HrAdvance, advance_id)
    if not a or a.tenant_id != tenant_id or a.status != 'REQUESTED':
        err('HR.ADV_STATE', 'السلفة غير موجودة أو ليست بطلب')
    if a.created_by == actor_id:
        err('HR.SELF_APPROVAL', 'لا يمكن اعتماد سل��ة قدّمتها بنفسك')
    a.status = 'APPROVED'
    a.approved_by = actor_id
    a.approved_at = _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='advance.approve', entity='hr_advance',
          entity_id=a.id)
    return a


def reject_advance(db: Session, *, tenant_id: str, actor_id: str,
                   advance_id: str, reason: str) -> m.HrAdvance:
    a = db.get(m.HrAdvance, advance_id)
    if not a or a.tenant_id != tenant_id or a.status != 'REQUESTED':
        err('HR.ADV_STATE', 'السلفة غير موجودة أو ليست بطلب')
    a.status = 'REJECTED'
    a.reject_reason = reason
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='advance.reject', entity='hr_advance',
          entity_id=a.id, after={'reason': reason})
    return a


def disburse_advance(db: Session, *, tenant_id: str, actor_id: str,
                     branch_id: str, advance_id: str,
                     account_code: str = '1101') -> m.HrAdvance:
    """الصرف الفعلي — حدث #23: Dr 1130 (بطرف الموظف) | Cr نقدية (ملف 02)."""
    a = db.get(m.HrAdvance, advance_id)
    if not a or a.tenant_id != tenant_id or a.status != 'APPROVED':
        err('HR.ADV_STATE', 'السلفة غير موجودة أو ليست معتمدة للصرف')
    if not _account_exists(db, tenant_id, account_code):
        err('HR.BAD_ACCOUNT', 'حساب الصرف غير صالح')
    emp = get_employee(db, tenant_id, a.employee_id)
    ent = create_and_post_journal(
        db, tenant_id=tenant_id, branch_id=branch_id,
        journal_type='AUTO_PAYROLL', entry_date=date.today(),
        narration=f'صرف سلفة للموظف {emp.emp_no} — {emp.full_name}',
        raw_lines=[
            {'account': '1130', 'debit': D(a.amount), 'credit': Decimal('0'),
             'party_type': 'EMPLOYEE', 'party_id': emp.id,
             'description': 'منح سلفة موظف'},
            {'account': account_code, 'debit': Decimal('0'),
             'credit': D(a.amount), 'description': 'صرف نقدي سلفة'}],
        actor_id=actor_id, source_type='HR_ADVANCE', source_id=a.id,
        event_key=f'hr:advance:pay:{a.id}')
    a.status = 'PAID'
    a.remaining = D(a.amount)
    a.paid_by = actor_id
    a.paid_at = _now()
    a.paid_entry_id = ent.id
    a.paid_account_code = account_code
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='advance.disburse', entity='hr_advance',
          entity_id=a.id, after={'entry_id': ent.id,
                                 'amount': str(a.amount)})
    return a


def list_advances(db: Session, tenant_id: str, employee_id: str = '',
                  status: str = '') -> list[m.HrAdvance]:
    q = select(m.HrAdvance).where(m.HrAdvance.tenant_id == tenant_id)
    if employee_id:
        q = q.where(m.HrAdvance.employee_id == employee_id)
    if status:
        q = q.where(m.HrAdvance.status == status)
    return list(db.execute(q.order_by(m.HrAdvance.created_at.desc()))
                .scalars())


# ────────────────────────────────────────────────────────────────────
# §2 الجزاءات التأديبية (مستند + اعتماد — وجهتها حسب السياسة)
# ────────────────────────────────────────────────────────────────────
def create_penalty(db: Session, *, tenant_id: str, actor_id: str,
                   employee_id: str, pen_date: date, apply_month: str,
                   amount, reason: str, doc_ref: str) -> m.HrPenalty:
    e = get_employee(db, tenant_id, employee_id)
    if e.status == 'TERMINATED':
        err('HR.EMP_TERMINATED', 'لا جزاء لموظف منتهي')
    apply_month = _check_month(apply_month)
    if D(amount) <= 0:
        err('HR.BAD_AMOUNT', 'مبلغ الجزاء يجب أن يكون موجباً')
    p = m.HrPenalty(tenant_id=tenant_id, employee_id=e.id, pen_date=pen_date,
                    apply_month=apply_month, amount=q4(D(amount)),
                    reason=reason, doc_ref=doc_ref, created_by=actor_id)
    db.add(p)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='penalty.create', entity='hr_penalty',
          entity_id=p.id, after={'amount': str(amount),
                                 'apply_month': apply_month})
    return p


def approve_penalty(db: Session, *, tenant_id: str, actor_id: str,
                    penalty_id: str) -> m.HrPenalty:
    p = db.get(m.HrPenalty, penalty_id)
    if not p or p.tenant_id != tenant_id:
        err('HR.PEN_NOT_FOUND', 'الجزاء غير موجود')
    if p.approved_by:
        err('HR.PEN_STATE', 'الجزاء معتمد مسبقاً')
    if p.created_by == actor_id:
        err('HR.SELF_APPROVAL', 'لا يمكن اعتماد جزاء أنشأته بنفسك')
    p.approved_by = actor_id
    p.approved_at = _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='penalty.approve', entity='hr_penalty',
          entity_id=p.id)
    return p


def list_penalties(db: Session, tenant_id: str, month: str = '',
                   employee_id: str = '') -> list[m.HrPenalty]:
    q = select(m.HrPenalty).where(m.HrPenalty.tenant_id == tenant_id)
    if month:
        q = q.where(m.HrPenalty.apply_month == month)
    if employee_id:
        q = q.where(m.HrPenalty.employee_id == employee_id)
    return list(db.execute(q.order_by(m.HrPenalty.pen_date)).scalars())


# ────────────────────────────────────────────────────────────────────
# §4.1 بنود الراتب القابلة للتكوين
# ────────────────────────────────────────────────────────────────────
SYSTEM_ITEMS = ('BASIC', 'OT', 'ABS', 'LATE', 'UPL', 'PEN', 'ADV', 'EOS')


def create_pay_item(db: Session, *, tenant_id: str, actor_id: str,
                    code: str, name: str, item_type: str, calc: str,
                    pct_base=0, credit_account_code: str = '2220'
                    ) -> m.HrPayItem:
    code = code.strip().upper()
    if item_type not in ('EARNING', 'DEDUCTION'):
        err('HR.BAD_ITEM_TYPE', 'نوع البند EARNING أو DEDUCTION')
    if calc not in ('FIXED', 'PCT_BASE'):
        err('HR.BAD_CALC', 'طريقة الحساب FIXED أو PCT_BASE')
    if calc == 'PCT_BASE' and (D(pct_base) <= 0 or D(pct_base) > 100):
        err('HR.BAD_CALC', 'نسبة البند خارج المدى')
    if db.execute(select(m.HrPayItem.id).where(
            m.HrPayItem.tenant_id == tenant_id,
            m.HrPayItem.code == code)).first():
        err('HR.DUP_ITEM', f'رمز البند {code} مستخدم')
    it = m.HrPayItem(tenant_id=tenant_id, code=code, name=name,
                     item_type=item_type, calc=calc, pct_base=D(pct_base),
                     credit_account_code=credit_account_code)
    db.add(it)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='pay_item.create', entity='hr_pay_item',
          entity_id=it.id, after={'code': code, 'type': item_type,
                                  'calc': calc, 'pct': str(pct_base)})
    return it


def set_pay_item_active(db: Session, *, tenant_id: str, actor_id: str,
                        item_id: str, is_active: bool) -> m.HrPayItem:
    it = db.get(m.HrPayItem, item_id)
    if not it or it.tenant_id != tenant_id:
        err('HR.ITEM_NOT_FOUND', 'البند غير موجود')
    if it.is_system and not is_active:
        err('HR.SYSTEM_ITEM', 'بنود النظام (أساسي/إضافي/غياب/سلف) لا تُعطَّل')
    it.is_active = is_active
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='pay_item.toggle', entity='hr_pay_item',
          entity_id=it.id, after={'active': is_active})
    return it


def list_pay_items(db: Session, tenant_id: str) -> list[m.HrPayItem]:
    return list(db.execute(select(m.HrPayItem).where(
        m.HrPayItem.tenant_id == tenant_id).order_by(m.HrPayItem.code)
    ).scalars())


# ────────────────────────────────────────────────────────────────────
# §4 محرك الرواتب
# ────────────────────────────────────────────────────────────────────
def _active_employees_for_normal(db: Session, tenant_id: str, month: str
                                 ) -> list[m.HrEmployee]:
    """قبول-3: المنتهي والموقوف خارج المسير الشهري حرفياً."""
    d1, d2, _ = _month_bounds(month)
    emps = list_employees(db, tenant_id, status='ACTIVE')
    # من عُيِّن بعد نهاية الشهر لا يدخل مسيره
    return [e for e in emps if e.hire_date <= d2]


def _payslip_lines(db: Session, tenant_id: str, emp: m.HrEmployee,
                   month: str, pol: m.HrPolicy, *, kind: str,
                   manual: list | None = None,
                   eos_amount=None, term_date: date | None = None
                   ) -> tuple[list[dict], dict]:
    """احتساب بنود قسيمة واحدة بلقطة مدخلات كاملة (§4.2-2 Snapshot).
    يعيد (items_snapshot, inputs_snapshot) — كل قيمة D(19,4) بالهِلَّة.
    بُنية سطر اللقطة: code/name/type(EARNING|DEDUCTION)/amount/bucket/note
    bucket: GROSS|UNEARNED|STAT:<acct>|PEN|ADV:<advance_id>|EOS"""
    d1, d2, mdays = _month_bounds(month)
    div = _divisor(pol, mdays)
    base = D(emp.base_salary)
    day_rate = base / div
    items: list[dict] = []
    inputs: dict = {'month_days': mdays, 'divisor': str(div),
                    'base_salary': str(base), 'day_rate': str(q4(day_rate))}

    if kind == 'SUPPLEMENTAL':
        # تسويات يدوية فقط (§4.3) — لا إعادة احتساب حضور ولا سلف
        if not manual:
            err('HR.NO_SUPP_LINES', 'مسير التسوية بدون سطور')
        gross = Decimal('0')
        ded_total = Decimal('0')
        for ln in manual:
            amt = q4(D(ln['amount']))
            if amt <= 0:
                err('HR.BAD_AMOUNT', 'سطر تسوية بمبلغ غير موجب')
            t = ln.get('type', 'EARNING')
            if t not in ('EARNING', 'DEDUCTION'):
                err('HR.BAD_ITEM_TYPE', 'نوع سطر التسوية غير صحيح')
            bucket = ('GROSS' if t == 'EARNING'
                      else f"STAT:{ln.get('credit', '2310')}")
            items.append({'code': ln.get('code', 'ADJ'),
                          'name': ln.get('name', 'تسوية'), 'type': t,
                          'amount': str(amt), 'bucket': bucket,
                          'note': ln.get('note', '')})
            if t == 'EARNING':
                gross += amt
            else:
                ded_total += amt
        inputs['manual_lines'] = len(manual)
        return items, inputs

    # ─── أساسي + تناسب تعيين/إنهاء (§4.1 يوم احتساب 30 أو تقويمي) ───
    work_from = max(d1, emp.hire_date)
    work_to = d2 if kind != 'FINAL' else min(d2, term_date or d2)
    if work_from > work_to:
        err('HR.NO_WORK_DAYS', 'لا أيام عمل للموظف داخل الشهر')
    cal_worked = Decimal((work_to - work_from).days + 1)
    if pol.day_count_mode == 'FIXED30':
        worked = Decimal(30) if (work_from <= d1 and work_to >= d2) \
            else min(Decimal(30), cal_worked)
        base_due = q4(base * worked / Decimal(30))
    else:
        worked = cal_worked
        base_due = q4(base * worked / div)
    inputs['hire_date'] = emp.hire_date.isoformat()
    inputs['worked_days'] = str(worked)
    inputs['calendar_days'] = str(cal_worked)
    items.append({'code': 'BASIC', 'name': 'الراتب الأساسي',
                  'type': 'EARNING', 'amount': str(base_due),
                  'bucket': 'GROSS',
                  'note': f'{worked}/{div} يوم'})

    ratio = Decimal('1') if worked >= div else (worked / div)
    # بدلات ثابتة بنسبة أيام العمل؛ النسبية من base_due (متناسبة أصلاً)
    for alw in (emp.allowances or []):
        if alw.get('amount') is not None:
            amt = q4(D(alw['amount']) * ratio)
        else:
            amt = q4(base_due * D(alw['pct_base']) / Decimal(100))
        if amt > 0:
            items.append({'code': alw['code'], 'name': alw.get('name', alw['code']),
                          'type': 'EARNING', 'amount': str(amt),
                          'bucket': 'GROSS',
                          'note': 'بدل ثابت' if alw.get('amount')
                                  is not None else f"{alw['pct_base']}% أساسي"})

    # ─── ملخصات الحضور المعتمدة فقط (§4.2-1) ───
    att = list_attendance(db, tenant_id, month, employee_id=emp.id)
    appr = [a for a in att if a.approved_by]
    unappr = len(att) - len(appr)
    absent_rows = [a for a in appr if a.status == 'ABSENT']
    late_rows = [a for a in appr if a.late_min > 0]
    ot_hours = sum((D(a.overtime_hours) for a in appr), Decimal('0'))
    inputs['attendance'] = {'rows': len(att), 'approved': len(appr),
                            'unapproved_ignored': unappr,
                            'absent_days': len(absent_rows),
                            'late_days': len(late_rows),
                            'late_min_sum': sum(a.late_min for a in appr),
                            'ot_hours': str(ot_hours)}
    if ot_hours > 0:
        ot_rate = base / div / D(pol.workday_hours)
        ot_amt = q4(ot_hours * ot_rate * D(pol.ot_multiplier))
        items.append({'code': 'OT', 'name': 'ساعات إضافية معتمدة',
                      'type': 'EARNING', 'amount': str(ot_amt),
                      'bucket': 'GROSS',
                      'note': f'{ot_hours}س × {q4(ot_rate)} × {pol.ot_multiplier}'})
    if absent_rows:
        amt = q4(Decimal(len(absent_rows)) * day_rate)
        items.append({'code': 'ABS', 'name': 'خصم غياب', 'type': 'DEDUCTION',
                      'amount': str(amt), 'bucket': 'UNEARNED',
                      'note': f'{len(absent_rows)} يوم غياب معتمد'})
    if late_rows and D(pol.late_deduct_daily) > 0:
        amt = q4(Decimal(len(late_rows)) * D(pol.late_deduct_daily))
        items.append({'code': 'LATE', 'name': 'خصم تأخير', 'type': 'DEDUCTION',
                      'amount': str(amt), 'bucket': 'UNEARNED',
                      'note': f'{len(late_rows)} أيام تأخير'})

    # ─── إجازات بدون أجر معتمدة داخل الشهر (§2 تخصم من المستحق) ───
    leave = db.execute(select(m.HrLeaveRequest).where(
        m.HrLeaveRequest.tenant_id == tenant_id,
        m.HrLeaveRequest.employee_id == emp.id,
        m.HrLeaveRequest.status == 'APPROVED')).scalars()
    upl_days = Decimal('0')
    for r in leave:
        lt = db.get(m.HrLeaveType, r.leave_type_id)
        if lt.paid:
            continue
        if f'{r.from_date.year:04d}-{r.from_date.month:02d}' == month:
            upl_days += D(r.days)
    inputs['unpaid_leave_days'] = str(upl_days)
    if upl_days > 0:
        amt = q4(upl_days * day_rate)
        items.append({'code': 'UPL', 'name': 'إجازة بدون أجر',
                      'type': 'DEDUCTION', 'amount': str(amt),
                      'bucket': 'UNEARNED', 'note': f'{upl_days} يوم'})

    # ─── جزاءات الشهر المعتمدة غير المخصومة (§2) ───
    pens = db.execute(select(m.HrPenalty).where(
        m.HrPenalty.tenant_id == tenant_id,
        m.HrPenalty.employee_id == emp.id,
        m.HrPenalty.apply_month == month,
        m.HrPenalty.approved_by.isnot(None),
        m.HrPenalty.deducted_run_id.is_(None))).scalars()
    pen_ids = []
    for p in pens:
        pen_ids.append(p.id)
        items.append({'code': 'PEN', 'name': f'جزاء: {p.reason[:40]}',
                      'type': 'DEDUCTION', 'amount': str(D(p.amount)),
                      'bucket': 'PEN', 'note': p.doc_ref})
    inputs['penalty_ids'] = pen_ids

    # ─── استقطاعات/استحقاقات نظامية قابلة للتكوين (§4.1) ───
    # v1: النسبية فقط — الثابتة تُدار كبدلات عقد وتسويات مسير تكميلي
    stat_rows = []
    for it in list_pay_items(db, tenant_id):
        if not it.is_active or it.is_system or it.code in SYSTEM_ITEMS:
            continue
        if it.calc != 'PCT_BASE':
            err('HR.BAD_ITEM_DEF',
                'v1 يدعم البنود النسبية من الأساسي فقط — الثابتة كبدلات عقد')
        amt = q4(base_due * D(it.pct_base) / Decimal(100))
        if amt <= 0:
            continue
        if it.item_type == 'EARNING':
            items.append({'code': it.code, 'name': it.name,
                          'type': 'EARNING', 'amount': str(amt),
                          'bucket': 'GROSS', 'note': f'{it.pct_base}% أساسي'})
        else:
            items.append({'code': it.code, 'name': it.name,
                          'type': 'DEDUCTION', 'amount': str(amt),
                          'bucket': f'STAT:{it.credit_account_code}',
                          'note': 'استقطاع نظامي'})
            stat_rows.append({'item': it.code, 'amount': str(amt)})
    inputs['statutory_items'] = stat_rows

    # ─── أقساط السلف الآلية (§3 — قبول-3: لا تجاوز للرصيد أبداً) ───
    adv_ids = []
    advs = db.execute(select(m.HrAdvance).where(
        m.HrAdvance.tenant_id == tenant_id,
        m.HrAdvance.employee_id == emp.id,
        m.HrAdvance.status == 'PAID',
        m.HrAdvance.first_deduct_month <= month,
        m.HrAdvance.remaining > 0).order_by(m.HrAdvance.request_date)
    ).scalars()
    for a in advs:
        deduct = min(D(a.installment_amount), D(a.remaining))
        if kind == 'FINAL':
            deduct = D(a.remaining)  # تصفية كاملة عند الإنهاء
        if deduct <= 0:
            continue
        adv_ids.append({'advance_id': a.id, 'amount': str(deduct)})
        items.append({'code': 'ADV', 'name': 'قسط سلفة',
                      'type': 'DEDUCTION', 'amount': str(deduct),
                      'bucket': f'ADV:{a.id}',
                      'note': f'متبقٍ بعده {q4(D(a.remaining) - deduct)}'})
    inputs['advance_deductions'] = adv_ids

    # ─── تعويض نهاية الخدمة في المسير النهائي (§4.3) ───
    if kind == 'FINAL' and eos_amount is not None and D(eos_amount) > 0:
        items.append({'code': 'EOS', 'name': 'تعويض نهاية الخدمة',
                      'type': 'EARNING', 'amount': str(q4(D(eos_amount))),
                      'bucket': 'GROSS', 'note': 'حسب سياسة العميل'})
        inputs['eos_amount'] = str(q4(D(eos_amount)))
    return items, inputs


def _totals(items: list[dict]) -> dict:
    gross = sum((D(i['amount']) for i in items if i['type'] == 'EARNING'),
                Decimal('0'))
    unearned = sum((D(i['amount']) for i in items
                    if i['bucket'] == 'UNEARNED'), Decimal('0'))
    adv = sum((D(i['amount']) for i in items
               if i['bucket'].startswith('ADV:')), Decimal('0'))
    pen = sum((D(i['amount']) for i in items if i['bucket'] == 'PEN'),
              Decimal('0'))
    stat = sum((D(i['amount']) for i in items
                if i['bucket'].startswith('STAT:')), Decimal('0'))
    net = gross - unearned - adv - pen - stat
    return {'gross': gross, 'unearned': unearned, 'advances': adv,
            'penalties': pen, 'withholdings': stat, 'net': net}


def _replace_payslips(db: Session, tenant_id: str, run: m.HrPayrollRun,
                      rows: list[tuple[m.HrEmployee, list[dict], dict]]):
    for old in db.execute(select(m.HrPayslip).where(
            m.HrPayslip.run_id == run.id)).scalars():
        db.delete(old)
    db.flush()
    tg = tu = tw = ta = Decimal('0')
    for emp, items, inputs in rows:
        t = _totals(items)
        if t['net'] < 0:
            err('HR.NEGATIVE_NET',
                f'صافي {emp.emp_no} سالب ({t["net"]}) — راجع الجزاءات/السلف')
        db.add(m.HrPayslip(tenant_id=tenant_id, run_id=run.id,
                           employee_id=emp.id,
                           department_id=emp.department_id,
                           gross=t['gross'], unearned=t['unearned'],
                           withholdings=t['withholdings'],
                           advances=t['advances'], penalties=t['penalties'],
                           net=t['net'], items_snapshot=items,
                           inputs_snapshot=inputs))
        tg += t['gross']; tu += t['unearned']
        tw += t['withholdings'] + t['penalties']; ta += t['advances']
    run.employee_count = len(rows)
    run.gross_total = tg
    run.unearned_total = tu
    run.withholdings_total = tw
    run.advances_total = ta
    run.net_total = tg - tu - tw - ta
    db.flush()


def create_run(db: Session, *, tenant_id: str, actor_id: str, month: str,
               kind: str = 'NORMAL', parent_run_id: str | None = None,
               employee_id: str | None = None, eos_amount=None,
               manual_lines: dict | None = None) -> m.HrPayrollRun:
    """§4.2 معالج موجه — الخطوة 2: مسودة بلقطة كاملة؛ لا قيد إطلاقاً هنا.
    §4.3: لا مسيرين NORMAL نشطين لنفس الشهر؛ التسوية مرتبطة بأصل مرحَّل."""
    month = _check_month(month)
    if kind not in ('NORMAL', 'SUPPLEMENTAL', 'FINAL'):
        err('HR.BAD_KIND', 'نوع المسير غير صحيح')
    active = db.execute(select(m.HrPayrollRun).where(
        m.HrPayrollRun.tenant_id == tenant_id,
        m.HrPayrollRun.month == month,
        m.HrPayrollRun.kind == kind,
        m.HrPayrollRun.status != 'CANCELLED')).scalars()
    if kind == 'NORMAL' and list(active):
        err('HR.RUN_EXISTS',
            f'يوجد مسير نشط لشهر {month} أصلاً — التصحيح بمسير تسوية')
    if kind == 'FINAL' and any(r.final_employee_id == employee_id
                               for r in active):
        err('HR.RUN_EXISTS', 'يوجد مسير نهائي نشط لهذا الموظف/الشهر')
    if kind == 'SUPPLEMENTAL':
        parent = db.get(m.HrPayrollRun, parent_run_id or '')
        if (not parent or parent.tenant_id != tenant_id
                or parent.month != month
                or parent.status not in ('POSTED', 'PAID')):
            err('HR.SUPP_NEEDS_PARENT',
                'التسوية تتطلب مسير أصل مرحَّلاً لنفس الشهر')
        if not (manual_lines or {}):
            err('HR.NO_SUPP_LINES', 'مسير التسوية بدون سطور')
    max_seq = db.execute(select(func.coalesce(func.max(
        m.HrPayrollRun.supp_seq), 0)).where(
        m.HrPayrollRun.tenant_id == tenant_id,
        m.HrPayrollRun.month == month,
        m.HrPayrollRun.kind == kind)).scalar_one()
    run = m.HrPayrollRun(tenant_id=tenant_id, month=month, kind=kind,
                         parent_run_id=parent_run_id,
                         final_employee_id=employee_id,
                         supp_seq=max_seq + 1, created_by=actor_id,
                         manual_lines=manual_lines or {})
    db.add(run)
    db.flush()
    pol = get_policy(db, tenant_id)
    rows: list[tuple[m.HrEmployee, list[dict], dict]] = []
    if kind == 'NORMAL':
        targets = _active_employees_for_normal(db, tenant_id, month)
    elif kind == 'FINAL':
        e = get_employee(db, tenant_id, employee_id or '')
        if e.status != 'TERMINATED' or not e.termination_date:
            err('HR.NEEDS_TERMINATION', 'المسير النهائي لموظف منتهٍ فقط')
        targets = [e]
    else:
        targets = [get_employee(db, tenant_id, eid)
                   for eid in (manual_lines or {}).keys()]
    for emp in targets:
        manual = (manual_lines or {}).get(emp.id)
        items, inputs = _payslip_lines(db, tenant_id, emp, month, pol,
                                       kind=kind, manual=manual,
                                       eos_amount=eos_amount,
                                       term_date=emp.termination_date)
        rows.append((emp, items, inputs))
    _replace_payslips(db, tenant_id, run, rows)
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='payroll.run.create', entity='hr_payroll_run',
          entity_id=run.id,
          after={'month': month, 'kind': kind, 'employees': run.employee_count,
                 'gross': str(run.gross_total), 'net': str(run.net_total)})
    return run


def recalc_run(db: Session, *, tenant_id: str, actor_id: str,
               run_id: str, eos_amount=None) -> m.HrPayrollRun:
    """إعادة الاحتساب مسموحة في المسودة فقط (§4.2-2 تُعاد من المدخلات)."""
    r = _get_run(db, tenant_id, run_id)
    if r.status != 'DRAFT':
        err('HR.RUN_LOCKED_AFTER_REVIEW',
            'أُعدّ المسير — إعادة الاحتساب تتطلب العودة لمسودة (لا تراجع)')
    pol = get_policy(db, tenant_id)
    rows: list[tuple[m.HrEmployee, list[dict], dict]] = []
    if r.kind == 'NORMAL':
        targets = _active_employees_for_normal(db, tenant_id, r.month)
    elif r.kind == 'FINAL':
        targets = [get_employee(db, tenant_id, r.final_employee_id or '')]
    else:
        targets = [get_employee(db, tenant_id, eid)
                   for eid in (r.manual_lines or {}).keys()]
    for emp in targets:
        manual = (r.manual_lines or {}).get(emp.id)
        items, inputs = _payslip_lines(db, tenant_id, emp, r.month, pol,
                                       kind=r.kind, manual=manual,
                                       eos_amount=eos_amount,
                                       term_date=emp.termination_date)
        rows.append((emp, items, inputs))
    _replace_payslips(db, tenant_id, r, rows)
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='payroll.run.recalc', entity='hr_payroll_run',
          entity_id=r.id,
          after={'employees': r.employee_count, 'gross': str(r.gross_total),
                 'net': str(r.net_total)})
    return r


def _get_run(db: Session, tenant_id: str, run_id: str) -> m.HrPayrollRun:
    r = db.get(m.HrPayrollRun, run_id)
    if not r or r.tenant_id != tenant_id:
        err('HR.RUN_NOT_FOUND', 'المسير غير موجود')
    return r


def prepare_run(db: Session, *, tenant_id: str, actor_id: str,
                run_id: str) -> m.HrPayrollRun:
    """§4.2-3 إعداد HR (التوقيع الأول)."""
    r = _get_run(db, tenant_id, run_id)
    if r.status != 'DRAFT':
        err('HR.RUN_STATE', 'الإعداد يتطلب مسودة')
    r.status = 'REVIEWED'
    r.prepared_by = actor_id
    r.prepared_at = _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='payroll.run.prepare', entity='hr_payroll_run',
          entity_id=r.id)
    return r


def approve_run(db: Session, *, tenant_id: str, actor_id: str,
                run_id: str) -> m.HrPayrollRun:
    """§4.2-3 اعتماد مالي مزدوج — لا قيد قبل الاثنين، ولا اعتماد ذاتي."""
    r = _get_run(db, tenant_id, run_id)
    if r.status != 'REVIEWED':
        err('HR.RUN_STATE', 'الاعتماد يتطلب مراجعة HR أولاً')
    if r.prepared_by == actor_id:
        err('HR.SELF_APPROVAL', 'لا يمكن اعتماد مسير أعددته بنفسك')
    r.status = 'APPROVED'
    r.approved_by = actor_id
    r.approved_at = _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='payroll.run.approve', entity='hr_payroll_run',
          entity_id=r.id)
    return r


def _build_entry_21_lines(db: Session, tenant_id: str,
                          run: m.HrPayrollRun) -> list[dict]:
    """#21 بالكتل: Dr مصروف أقسام (المستحق الفعلي) | Cr 2310/1130/2220..."""
    slips = list(db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == run.id)).scalars())
    if not slips:
        err('HR.EMPTY_RUN', 'لا يمكن ترحيل مسير فارغ')
    dept_map: dict[str, str] = {}
    for d in list_departments(db, tenant_id):
        dept_map[d.id] = d.payroll_account_code
    by_dept: dict[str, dict] = {}
    adv_lines: list[dict] = []
    bucket_credit: dict[str, Decimal] = {}
    total_net = Decimal('0')
    pol = get_policy(db, tenant_id)
    for s in slips:
        acct = dept_map.get(s.department_id)
        if not acct:
            err('HR.DEPT_MISSING', 'قسم موظف في المسير غير موجود')
        b = by_dept.setdefault(acct, {'expense': Decimal('0'), 'emps': 0})
        earned = Decimal('0')
        unearned = Decimal('0')
        for it in s.items_snapshot:
            amt = D(it['amount'])
            bk = it['bucket']
            if it['type'] == 'EARNING':
                earned += amt
            elif bk == 'UNEARNED':
                unearned += amt
            elif bk.startswith('ADV:'):
                adv_lines.append({'account': '1130', 'debit': Decimal('0'),
                                  'credit': amt, 'party_type': 'EMPLOYEE',
                                  'party_id': s.employee_id,
                                  'description': 'استقطاع قسط سلفة'})
            elif bk == 'PEN':
                bucket_credit[pol.penalty_credit_code] = \
                    bucket_credit.get(pol.penalty_credit_code, Decimal('0')) + amt
            elif bk.startswith('STAT:'):
                tgt = bk.split(':', 1)[1]
                bucket_credit[tgt] = bucket_credit.get(tgt, Decimal('0')) + amt
        b['expense'] += earned - unearned
        # صافي الموظف من لقطته — مصدر الحقيقة الوحيد
        total_net += D(s.net)
        b['emps'] += 1
    lines: list[dict] = []
    for acct in sorted(by_dept):
        v = by_dept[acct]
        lines.append({'account': acct, 'debit': q4(v['expense']),
                      'credit': Decimal('0'),
                      'description': f"استحقاق رواتب {run.month} — "
                                     f"حساب {acct} ({v['emps']} موظفين)"})
    lines.append({'account': '2310', 'debit': Decimal('0'),
                  'credit': q4(total_net),
                  'description': f'صافي رواتب شهر {run.month}'})
    lines.extend(adv_lines)
    credits_desc = {'2220': 'استقطاعات مستحقة للجهات',
                    '4901': 'جزاءات معادة إيراداً', '2310': 'صافي',
                    '2320': 'مخصص/مستحق'}
    for acct in sorted(bucket_credit):
        if bucket_credit[acct] > 0:
            lines.append({'account': acct, 'debit': Decimal('0'),
                          'credit': q4(bucket_credit[acct]),
                          'description': credits_desc.get(
                              acct, f'استقطاعات إلى {acct}')})
    # توازن حتمي بالبناء: Dr = (أجور - غير مستحق) ≡ net + سلف + استقطاعات
    deb = sum(D(x['debit']) for x in lines)
    cred = sum(D(x['credit']) for x in lines)
    if deb != cred:
        err('HR.INTERNAL_UNBALANCED',
            f'خلل تركيب داخلي بالقيد (مدين {deb} ≠ دائن {cred}) — '
            'أوقف الترحيل، راجع الفريق الهندسي')
    return lines


def post_run(db: Session, *, tenant_id: str, actor_id: str, branch_id: str,
             run_id: str) -> m.HrPayrollRun:
    """§4.2-4 الترحيل الذري عبر المحرك؛ بعده المسير أبدي غير قابل للمس."""
    r = _get_run(db, tenant_id, run_id)
    if r.status != 'APPROVED':
        err('HR.RUN_STATE', 'الترحيل يتطلب إعداد HR ثم اعتماد مالي')
    _, d2, _ = _month_bounds(r.month)
    lines = _build_entry_21_lines(db, tenant_id, r)
    ent = create_and_post_journal(
        db, tenant_id=tenant_id, branch_id=branch_id,
        journal_type='AUTO_PAYROLL', entry_date=d2,
        narration=f'استحقاق رواتب {r.month} ({r.kind}'
                  + (f' #{r.supp_seq}' if r.kind != 'NORMAL' else '') + ')',
        raw_lines=lines, actor_id=actor_id,
        source_type='HR_PAYROLL_RUN', source_id=r.id,
        event_key=f'hr:payroll:post:{r.id}')
    # ربط الجزاءات المخصومة وخصم أرصدة السلف — داخل نفس الذرّة
    slips = list(db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == r.id)).scalars())
    for s in slips:
        for pid in s.inputs_snapshot.get('penalty_ids', []):
            p = db.get(m.HrPenalty, pid)
            if p and not p.deducted_run_id:
                p.deducted_run_id = r.id
        for ad in s.inputs_snapshot.get('advance_deductions', []):
            a = db.get(m.HrAdvance, ad['advance_id'])
            if not a or a.status != 'PAID':
                continue
            amt = D(ad['amount'])
            if amt > D(a.remaining):
                err('HR.ADV_OVERDEDUCT',
                    'رصيد السلفة تغيّر منذ المسودة — أعد الاحتساب (قبول-3)')
            a.remaining = q4(D(a.remaining) - amt)
            if a.remaining <= 0:
                a.remaining = Decimal('0')
                a.status = 'SETTLED'
    r.status = 'POSTED'
    r.posted_entry_id = ent.id
    r.posted_at = _now()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='payroll.run.post', entity='hr_payroll_run',
          entity_id=r.id,
          after={'entry_id': ent.id, 'gross': str(r.gross_total),
                 'net': str(r.net_total)})
    return r


def pay_run(db: Session, *, tenant_id: str, actor_id: str, branch_id: str,
            run_id: str, account_code: str = '1101',
            payslip_ids: list[str] | None = None,
            receipt_note: str = '') -> m.HrPayrollRun:
    """§4.2-6 الصرف الفعلي #22: Dr 2310 | Cr نقد/بنك — جماعي أو فردي
    مع إثبات استلام على كل قسيمة (paid_entry_id)."""
    r = _get_run(db, tenant_id, run_id)
    if r.status not in ('POSTED', 'PAID'):
        err('HR.RUN_STATE', 'الصرف يتطلب مسيراً مرحَّلاً')
    if not _account_exists(db, tenant_id, account_code):
        err('HR.BAD_ACCOUNT', 'حساب الصرف غير صالح')
    slips = list(db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == r.id, m.HrPayslip.paid_entry_id.is_(None))
    ).scalars())
    if payslip_ids:
        ids = set(payslip_ids)
        slips = [s for s in slips if s.id in ids]
    if not slips:
        err('HR.NOTHING_TO_PAY', 'لا قسائم غير مدفوعة ضمن الاختيار')
    amount = sum((D(s.net) for s in slips), Decimal('0'))
    if amount <= 0:
        err('HR.NOTHING_TO_PAY', 'المبلغ المدفوع صفر')
    seq = r.paid_seq + 1
    ent = create_and_post_journal(
        db, tenant_id=tenant_id, branch_id=branch_id,
        journal_type='AUTO_PAYROLL', entry_date=date.today(),
        narration=f'صرف رواتب {r.month} — دفعة {seq}'
                  + (f' — {receipt_note}' if receipt_note else ''),
        raw_lines=[
            {'account': '2310', 'debit': q4(amount), 'credit': Decimal('0'),
             'description': f'إيفاء رواتب مستحقة {r.month}'},
            {'account': account_code, 'debit': Decimal('0'),
             'credit': q4(amount), 'description': 'صرف نقدي/بنكي للرواتب'}],
        actor_id=actor_id, source_type='HR_PAYROLL_PAY', source_id=r.id,
        event_key=f'hr:payroll:pay:{r.id}:{seq}')
    now = _now()
    for s in slips:
        s.paid_entry_id = ent.id
        s.paid_at = now
    r.paid_seq = seq
    db.flush()  # إلزامي قبل العد: جلسات الاختبار/الإنتاج بلا autoflush
    remaining = db.execute(select(func.count()).select_from(
        m.HrPayslip).where(m.HrPayslip.run_id == r.id,
                           m.HrPayslip.paid_entry_id.is_(None))).scalar_one()
    if remaining == 0:
        r.status = 'PAID'
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='payroll.run.pay', entity='hr_payroll_run',
          entity_id=r.id,
          after={'entry_id': ent.id, 'amount': str(amount),
                 'payslips': len(slips), 'receipt_note': receipt_note})
    return r


def cancel_run(db: Session, *, tenant_id: str, actor_id: str,
               run_id: str, reason: str) -> m.HrPayrollRun:
    """إلغاء مسودة/مراجعة فقط؛ المرحَّل أبدي (قبول-4 — التسوية بديلاً)."""
    r = _get_run(db, tenant_id, run_id)
    if r.status in ('POSTED', 'PAID'):
        err('HR.RUN_IMMUTABLE',
            'مسير مرحَّل لا يُلغى إطلاقاً — التصحيح بمسير تسوية موثق')
    if r.status == 'CANCELLED':
        err('HR.RUN_STATE', 'ملغى مسبقاً')
    r.status = 'CANCELLED'
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='payroll.run.cancel', entity='hr_payroll_run',
          entity_id=r.id, after={'reason': reason})
    return r


def list_runs(db: Session, tenant_id: str, month: str = '',
              kind: str = '') -> list[m.HrPayrollRun]:
    q = select(m.HrPayrollRun).where(m.HrPayrollRun.tenant_id == tenant_id)
    if month:
        q = q.where(m.HrPayrollRun.month == month)
    if kind:
        q = q.where(m.HrPayrollRun.kind == kind)
    return list(db.execute(q.order_by(m.HrPayrollRun.month.desc(),
                                      m.HrPayrollRun.supp_seq)).scalars())


def run_payslips(db: Session, tenant_id: str, run_id: str
                 ) -> list[m.HrPayslip]:
    r = _get_run(db, tenant_id, run_id)
    return list(db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == r.id).order_by(m.HrPayslip.employee_id)
    ).scalars())


def get_payslip(db: Session, *, tenant_id: str, actor_id: str,
                payslip_id: str) -> m.HrPayslip:
    """§6: كل فتح لقسيمة حدث مدقق (من رأى ماذا ومتى)."""
    p = db.get(m.HrPayslip, payslip_id)
    if not p or p.tenant_id != tenant_id:
        err('HR.PS_NOT_FOUND', 'القسيمة غير موجودة')
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='payslip.view', entity='hr_payslip',
          entity_id=p.id,
          after={'employee_id': p.employee_id, 'run_id': p.run_id})
    return p


def employee_statement(db: Session, tenant_id: str, employee_id: str
                       ) -> list[m.HrPayslip]:
    """كشف الموظف عبر الشهور — قبول-4: التسويات تظهر أسطراً جديدة."""
    e = get_employee(db, tenant_id, employee_id)
    q = select(m.HrPayslip, m.HrPayrollRun).join(
        m.HrPayrollRun, m.HrPayslip.run_id == m.HrPayrollRun.id).where(
        m.HrPayslip.tenant_id == tenant_id,
        m.HrPayslip.employee_id == e.id,
        m.HrPayrollRun.status != 'CANCELLED').order_by(
        m.HrPayrollRun.month, m.HrPayrollRun.kind)
    return list(db.execute(q).all())


def eos_accrue_month(db: Session, *, tenant_id: str, actor_id: str,
                     branch_id: str, month: str) -> dict:
    """§4.3 مخصص نهاية الخدمة الشهري (اختياري): Dr مصروف | Cr 2320."""
    month = _check_month(month)
    pol = get_policy(db, tenant_id)
    if not pol.eos_enabled:
        err('HR.EOS_DISABLED', 'مخصص نهاية الخدمة معطل في السياسة')
    _, d2, mdays = _month_bounds(month)
    dept_map = {d.id: d.payroll_account_code for d in list_departments(db, tenant_id)}
    emps = [e for e in list_employees(db, tenant_id, status='ACTIVE')
            if e.hire_date <= d2]
    by_dept: dict[str, Decimal] = {}
    rows = []
    total = Decimal('0')
    for e in emps:
        dup = db.execute(select(m.HrEosProvision.id).where(
            m.HrEosProvision.tenant_id == tenant_id,
            m.HrEosProvision.employee_id == e.id,
            m.HrEosProvision.month == month)).first()
        if dup:
            continue
        amt = q4(D(e.base_salary) * D(pol.eos_month_rate))
        if amt <= 0:
            continue
        acct = dept_map.get(e.department_id, '6310')
        by_dept[acct] = by_dept.get(acct, Decimal('0')) + amt
        rows.append((e, amt))
        total += amt
    if not rows:
        return {'month': month, 'posted': 0, 'total': '0'}
    lines = [{'account': acct, 'debit': q4(v), 'credit': Decimal('0'),
              'description': f'مخصص نهاية خدمة {month}'}
             for acct, v in sorted(by_dept.items())]
    lines.append({'account': pol.eos_credit_account_code,
                  'debit': Decimal('0'), 'credit': q4(total),
                  'description': f'مخصص نهاية الخدمة الشهري {month}'})
    ent = create_and_post_journal(
        db, tenant_id=tenant_id, branch_id=branch_id,
        journal_type='AUTO_PAYROLL', entry_date=d2,
        narration=f'مخصص نهاية خدمة شهر {month}',
        raw_lines=lines, actor_id=actor_id,
        source_type='HR_EOS_PROVISION', source_id=month,
        event_key=f'hr:eos:{month}')
    for e, amt in rows:
        db.add(m.HrEosProvision(tenant_id=tenant_id, employee_id=e.id,
                                month=month, amount=amt,
                                posted_entry_id=ent.id))
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='hr', action='payroll.eos_accrue', entity='hr_eos_provision',
          entity_id=month, after={'entry_id': ent.id, 'total': str(total),
                                  'employees': len(rows)})
    return {'month': month, 'posted': len(rows), 'total': str(q4(total)),
            'entry_id': ent.id}


# ────────────────────────────────────────────────────────────────────
# §5 التقارير
# ────────────────────────────────────────────────────────────────────
def payroll_register(db: Session, tenant_id: str, month: str) -> dict:
    """كشف الشهر بالقسم/الموظف/البند (§5)."""
    month = _check_month(month)
    runs = [r for r in list_runs(db, tenant_id, month=month)
            if r.status not in ('CANCELLED',)]
    by_dept: dict[str, dict] = {}
    by_item: dict[str, dict] = {}
    rows = []
    for r in runs:
        for s in run_payslips(db, tenant_id, r.id):
            emp = get_employee(db, tenant_id, s.employee_id)
            dept = db.get(m.HrDepartment, s.department_id)
            key = dept.code if dept else '—'
            b = by_dept.setdefault(key, {'dept': dept.name_ar if dept else '—',
                                         'employees': 0, 'gross': Decimal('0'),
                                         'deductions': Decimal('0'),
                                         'net': Decimal('0')})
            b['employees'] += 1
            b['gross'] += D(s.gross)
            b['deductions'] += (D(s.unearned) + D(s.withholdings)
                                + D(s.advances) + D(s.penalties))
            b['net'] += D(s.net)
            for it in s.items_snapshot:
                ib = by_item.setdefault(it['code'],
                                        {'name': it['name'], 'type': it['type'],
                                         'amount': Decimal('0')})
                ib['amount'] += D(it['amount'])
            rows.append({'emp_no': emp.emp_no, 'name': emp.full_name,
                         'department': key, 'kind': r.kind,
                         'gross': str(s.gross), 'net': str(s.net),
                         'run_seq': r.supp_seq,
                         'status': r.status})
    return {'month': month,
            'by_department': [{'department_code': k,
                               **{kk: (str(vv) if isinstance(vv, Decimal) else vv)
                                  for kk, vv in b.items()}}
                              for k, b in sorted(by_dept.items())],
            'by_item': [{'code': k,
                         **{kk: (str(vv) if isinstance(vv, Decimal) else vv)
                            for kk, vv in b.items()}}
                        for k, b in sorted(by_item.items())],
            'rows': rows}


def month_compare(db: Session, tenant_id: str, months: int = 6) -> list[dict]:
    """مقارنة أشهر: إجماليات المسيرات العادية المرحَّلة (§5)."""
    q = select(m.HrPayrollRun).where(
        m.HrPayrollRun.tenant_id == tenant_id,
        m.HrPayrollRun.status.in_(['POSTED', 'PAID'])).order_by(
        m.HrPayrollRun.month.desc()).limit(months * 3)
    agg: dict[str, dict] = {}
    for r in db.execute(q).scalars():
        a = agg.setdefault(r.month, {'month': r.month, 'runs': 0,
                                     'gross': Decimal('0'),
                                     'net': Decimal('0')})
        a['runs'] += 1
        a['gross'] += D(r.gross_total)
        a['net'] += D(r.net_total)
    out = [a for _, a in sorted(agg.items(), reverse=True)][:months]
    return [{k: (str(v) if isinstance(v, Decimal) else v)
             for k, v in a.items()} for a in out]


def advances_report(db: Session, tenant_id: str) -> list[dict]:
    """أرصدة سلف قائمة مع تقادم عمري بالأشهر (§5 + §3 كشف 1130)."""
    today = date.today()
    out = []
    for a in db.execute(select(m.HrAdvance).where(
            m.HrAdvance.tenant_id == tenant_id,
            m.HrAdvance.status.in_(['PAID', 'SETTLED'])).order_by(
            m.HrAdvance.request_date)).scalars():
        e = get_employee(db, tenant_id, a.employee_id)
        aging = (today.year - a.request_date.year) * 12 + (
            today.month - a.request_date.month)
        out.append({'advance_id': a.id, 'emp_no': e.emp_no,
                    'employee': e.full_name, 'amount': str(a.amount),
                    'remaining': str(a.remaining), 'status': a.status,
                    'installments': a.installments,
                    'installment_amount': str(a.installment_amount),
                    'request_date': a.request_date.isoformat(),
                    'first_deduct_month': a.first_deduct_month,
                    'aging_months': aging})
    return out


def leave_balances_report(db: Session, tenant_id: str, year: int
                          ) -> list[dict]:
    out = []
    types = {lt.id: lt for lt in list_leave_types(db, tenant_id)}
    for b in list_leave_balances(db, tenant_id, year):
        e = get_employee(db, tenant_id, b.employee_id)
        lt = types.get(b.leave_type_id)
        out.append({'emp_no': e.emp_no, 'employee': e.full_name,
                    'leave_type': lt.code if lt else '?',
                    'paid': lt.paid if lt else True,
                    'entitled': str(b.entitled), 'used': str(b.used),
                    'remaining': str(D(b.entitled) - D(b.used))})
    return out


def turnover_report(db: Session, tenant_id: str, year: int) -> list[dict]:
    """دوران الموظفين: تعيينات وإنهاءات مجمعة شهرياً (§5)."""
    emps = list_employees(db, tenant_id)
    out = []
    for mo in range(1, 13):
        hires = sum(1 for e in emps
                    if e.hire_date.year == year and e.hire_date.month == mo)
        terms = sum(1 for e in emps
                    if e.termination_date and e.termination_date.year == year
                    and e.termination_date.month == mo)
        out.append({'month': f'{year:04d}-{mo:02d}', 'hires': hires,
                    'terminations': terms})
    return out


def cost_vs_revenue(db: Session, tenant_id: str, month: str) -> dict:
    """تكلفة الموظف الكاملة مقابل إيراد الشهر (§5 مؤشر USALI استرشادي)."""
    month = _check_month(month)
    runs = [r for r in list_runs(db, tenant_id, month=month)
            if r.status in ('POSTED', 'PAID')]
    payroll = sum((D(r.gross_total) for r in runs), Decimal('0'))
    d1, d2, _ = _month_bounds(month)
    rev = db.execute(select(func.coalesce(
        func.sum(m.JournalLine.credit_base - m.JournalLine.debit_base), 0)
        ).join(m.JournalEntry, m.JournalLine.entry_id == m.JournalEntry.id
        ).join(m.Account, m.JournalLine.account_id == m.Account.id)
        .where(m.JournalEntry.tenant_id == tenant_id,
               m.JournalEntry.status == 'POSTED',
               m.JournalEntry.entry_date.between(d1, d2),
               m.Account.type == 'REVENUE')).scalar_one()
    ratio = (q4(payroll / D(rev) * Decimal(100)) if D(rev) > 0
             else None)
    return {'month': month, 'payroll_gross': str(q4(payroll)),
            'revenue': str(q4(D(rev))),
            'payroll_to_revenue_pct': (str(ratio) if ratio is not None
                                       else None)}
