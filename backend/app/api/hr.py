"""نقاط وحدة الموارد البشرية والرواتب — ملف 06 + ملف 12:
هيكل/موظفون/دورة حياة، ورديات/جداول/حضور، إجازات، جزاءات، سلف،
بنود رواتب، معالج مسير (مسودة←إعداد←اعتماد←ترحيل #21←صرف #22)،
مخصص EOS، تقارير. كل أثر مالي عبر app/hr.py → المحرك فقط."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import hr as H
from .. import models as m
from ..db import get_db
from ..deps import Principal, require_perm
from ..posting import D
from ..schemas_hr import (AccrueIn, AdvanceIn, AttendanceApproveIn,
                          AttendanceIn, CancelIn, ChangeIn, DepartmentIn,
                          DepartmentPatch, DisburseIn, EmployeeIn,
                          EosAccrueIn, HrPolicyIn, LeaveRequestIn,
                          LeaveTypeIn, PayIn, PayItemIn, PenaltyIn,
                          PositionIn, PositionPatch, RecalcIn, RejectIn,
                          RosterIn, RunCreateIn, ShiftIn, SuspendIn,
                          TerminateIn)

router = APIRouter(prefix='/api/hr', tags=['hr'])


def _forbidden():
    raise HTTPException(403, {'error': {'code': 'HR.PRIVACY',
                                        'message_ar':
                                        'خصوصية رواتب: يتطلب تفويضاً أعلى'}})


def _bid(db: Session, pr: Principal) -> str:
    if pr.branch_ids:
        return pr.branch_ids[0]
    b = db.query(m.Branch).filter(m.Branch.tenant_id == pr.tenant_id).first()
    if not b:
        raise HTTPException(400, {'error': {'code': 'ORG.UNKNOWN_BRANCH',
                                            'message_ar': 'لا يوجد فرع'}})
    return b.id


def _staff_dicts(db: Session, pr: Principal, emps) -> list[dict]:
    see_base = pr.has('hr.salary.view')
    see_conf = pr.has('hr.salary.confidential') or pr.has('*')
    dept_cache: dict[str, m.HrDepartment | None] = {}
    out = []
    for e in emps:
        if e.department_id not in dept_cache:
            dept_cache[e.department_id] = db.get(m.HrDepartment,
                                                 e.department_id)
        out.append(H.employee_to_dict(e, dept_cache[e.department_id],
                                      see_salary=see_base,
                                      see_confidential=see_conf))
    return out


def _policy_dict(p: m.HrPolicy) -> dict:
    return {'day_count_mode': p.day_count_mode,
            'advance_max_pct': str(p.advance_max_pct),
            'workday_hours': str(p.workday_hours),
            'ot_multiplier': str(p.ot_multiplier),
            'late_deduct_daily': str(p.late_deduct_daily),
            'penalty_credit_code': p.penalty_credit_code,
            'eos_enabled': p.eos_enabled,
            'eos_month_rate': str(p.eos_month_rate),
            'eos_credit_account_code': p.eos_credit_account_code,
            'updated_by': p.updated_by,
            'updated_at': p.updated_at.isoformat() if p.updated_at else None}


def _run_dict(r: m.HrPayrollRun) -> dict:
    return {'id': r.id, 'month': r.month, 'kind': r.kind,
            'supp_seq': r.supp_seq, 'parent_run_id': r.parent_run_id,
            'final_employee_id': r.final_employee_id, 'status': r.status,
            'employee_count': r.employee_count,
            'gross_total': str(r.gross_total),
            'unearned_total': str(r.unearned_total),
            'withholdings_total': str(r.withholdings_total),
            'advances_total': str(r.advances_total),
            'net_total': str(r.net_total),
            'prepared_by': r.prepared_by,
            'approved_by': r.approved_by,
            'posted_entry_id': r.posted_entry_id,
            'paid_seq': r.paid_seq, 'created_by': r.created_by,
            'created_at': r.created_at.isoformat() if r.created_at else None}


def _slip_dict(s: m.HrPayslip, see_money: bool) -> dict:
    return {'id': s.id, 'run_id': s.run_id, 'employee_id': s.employee_id,
            'department_id': s.department_id,
            'gross': str(s.gross) if see_money else None,
            'unearned': str(s.unearned) if see_money else None,
            'withholdings': str(s.withholdings) if see_money else None,
            'advances': str(s.advances) if see_money else None,
            'penalties': str(s.penalties) if see_money else None,
            'net': str(s.net) if see_money else None,
            'items_snapshot': s.items_snapshot if see_money else [],
            'inputs_snapshot': s.inputs_snapshot if see_money else {},
            'paid_entry_id': s.paid_entry_id,
            'paid_at': s.paid_at.isoformat() if s.paid_at else None,
            'salary_masked': not see_money}


def _confidential_ok(db: Session, pr: Principal, department_id: str) -> bool:
    d = db.get(m.HrDepartment, department_id)
    if d and d.is_confidential and not (pr.has('hr.salary.confidential')
                                        or pr.has('*')):
        return False
    return True


# ═══════════════ الهيكل التنظيمي ═══════════════
@router.get('/departments')
def get_departments(db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('hr.view'))):
    return [{'id': d.id, 'code': d.code, 'name_ar': d.name_ar,
             'cost_center_code': d.cost_center_code,
             'payroll_account_code': d.payroll_account_code,
             'is_confidential': d.is_confidential, 'is_active': d.is_active}
            for d in H.list_departments(db, pr.tenant_id)]


@router.post('/departments', status_code=201)
def create_department(body: DepartmentIn, db: Session = Depends(get_db),
                      pr: Principal = Depends(
                          require_perm('hr.employees.manage'))):
    d = H.create_department(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                            code=body.code, name_ar=body.name_ar,
                            cost_center_code=body.cost_center_code,
                            payroll_account_code=body.payroll_account_code,
                            is_confidential=body.is_confidential)
    db.commit()
    return {'id': d.id, 'code': d.code}


@router.patch('/departments/{dept_id}')
def patch_department(dept_id: str, body: DepartmentPatch,
                     db: Session = Depends(get_db),
                     pr: Principal = Depends(
                         require_perm('hr.employees.manage'))):
    d = H.update_department(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                            dept_id=dept_id,
                            **body.model_dump(exclude_unset=True))
    db.commit()
    return {'id': d.id, 'updated': True}


@router.get('/positions')
def get_positions(department_id: str = '', db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('hr.view'))):
    return [{'id': p.id, 'department_id': p.department_id, 'title': p.title,
             'grade': p.grade, 'is_active': p.is_active}
            for p in H.list_positions(db, pr.tenant_id, department_id)]


@router.post('/positions', status_code=201)
def create_position(body: PositionIn, db: Session = Depends(get_db),
                    pr: Principal = Depends(
                        require_perm('hr.employees.manage'))):
    p = H.create_position(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                          department_id=body.department_id, title=body.title,
                          grade=body.grade)
    db.commit()
    return {'id': p.id}


@router.patch('/positions/{pid}')
def patch_position(pid: str, body: PositionPatch,
                   db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('hr.employees.manage'))):
    p = H.update_position(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                          position_id=pid,
                          **body.model_dump(exclude_unset=True))
    db.commit()
    return {'id': p.id, 'updated': True}


# ═══════════════ الموظفون ودورة الحياة ═══════════════
@router.get('/employees')
def get_employees(status: str = '', department_id: str = '', q: str = '',
                  db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('hr.view'))):
    emps = H.list_employees(db, pr.tenant_id, status=status,
                            department_id=department_id, q=q)
    return _staff_dicts(db, pr, emps)


@router.post('/employees', status_code=201)
def create_employee(body: EmployeeIn, db: Session = Depends(get_db),
                    pr: Principal = Depends(
                        require_perm('hr.employees.manage'))):
    e = H.create_employee(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                          branch_id=_bid(db, pr), emp_no=body.emp_no,
                          full_name=body.full_name,
                          department_id=body.department_id,
                          hire_date=body.hire_date,
                          base_salary=body.base_salary,
                          contract_type=body.contract_type,
                          position_id=body.position_id,
                          shift_id=body.shift_id,
                          national_id=body.national_id, phone=body.phone,
                          allowances=body.allowances,
                          bank_account=body.bank_account)
    db.commit()
    return {'id': e.id, 'emp_no': e.emp_no}


@router.get('/employees/{emp_id}')
def get_employee(emp_id: str, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('hr.view'))):
    e = H.get_employee(db, pr.tenant_id, emp_id)
    return _staff_dicts(db, pr, [e])[0]


@router.post('/employees/{emp_id}/suspend')
def suspend_employee(emp_id: str, body: SuspendIn,
                     db: Session = Depends(get_db),
                     pr: Principal = Depends(
                         require_perm('hr.employees.manage'))):
    e = H.suspend_employee(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                           emp_id=emp_id, reason=body.reason)
    db.commit()
    return {'id': e.id, 'status': e.status}


@router.post('/employees/{emp_id}/terminate')
def terminate_employee(emp_id: str, body: TerminateIn,
                       db: Session = Depends(get_db),
                       pr: Principal = Depends(
                           require_perm('hr.employees.manage'))):
    e = H.terminate_employee(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                             emp_id=emp_id,
                             termination_date=body.termination_date,
                             reason=body.reason)
    db.commit()
    return {'id': e.id, 'status': e.status,
            'termination_date': e.termination_date.isoformat()}


@router.get('/changes')
def get_changes(employee_id: str = '', db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('hr.view'))):
    rows = H.list_changes(db, pr.tenant_id, employee_id)
    return [{'id': c.id, 'employee_id': c.employee_id,
             'change_type': c.change_type, 'before': c.before,
             'after': c.after, 'doc_ref': c.doc_ref,
             'effective_from': c.effective_from.isoformat(),
             'status': c.status, 'approved_by': c.approved_by,
             'reject_reason': c.reject_reason, 'created_by': c.created_by}
            for c in rows]


@router.post('/changes', status_code=201)
def create_change(body: ChangeIn, db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('hr.changes.manage'))):
    c = H.create_change(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                        emp_id=body.employee_id,
                        change_type=body.change_type, after=body.after,
                        doc_ref=body.doc_ref,
                        effective_from=body.effective_from)
    db.commit()
    return {'id': c.id}


@router.post('/changes/{cid}/approve')
def approve_change(cid: str, db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('hr.changes.approve'))):
    c = H.approve_change(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                         change_id=cid)
    db.commit()
    return {'id': c.id, 'status': c.status, 'applied': True}


@router.post('/changes/{cid}/reject')
def reject_change(cid: str, body: RejectIn, db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('hr.changes.approve'))):
    c = H.reject_change(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                        change_id=cid, reason=body.reason)
    db.commit()
    return {'id': c.id, 'status': c.status}


# ═══════════════ الورديات والجداول والحضور ═══════════════
@router.get('/shifts')
def get_shifts(db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('hr.view'))):
    return [{'id': s.id, 'name': s.name, 'from_time': s.from_time,
             'to_time': s.to_time, 'overnight': s.overnight}
            for s in H.list_shifts(db, pr.tenant_id)]


@router.post('/shifts', status_code=201)
def create_shift(body: ShiftIn, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('hr.roster.manage'))):
    s = H.create_shift(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                       name=body.name, from_time=body.from_time,
                       to_time=body.to_time, overnight=body.overnight)
    db.commit()
    return {'id': s.id}


@router.get('/roster')
def get_roster(month: str, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('hr.view'))):
    emps = {e.id: e for e in H.list_employees(db, pr.tenant_id)}
    shifts = {s.id: s for s in H.list_shifts(db, pr.tenant_id)}
    return [{'id': r.id, 'employee_id': r.employee_id,
             'emp_no': emps.get(r.employee_id).emp_no
             if emps.get(r.employee_id) else '?',
             'employee': emps.get(r.employee_id).full_name
             if emps.get(r.employee_id) else '?',
             'date': r.roster_date.isoformat(), 'shift_id': r.shift_id,
             'shift': shifts.get(r.shift_id).name
             if shifts.get(r.shift_id) else '?'}
            for r in H.list_roster(db, pr.tenant_id, month)]


@router.post('/roster')
def set_roster(body: RosterIn, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('hr.roster.manage'))):
    n = H.set_roster(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                     rows=[r.model_dump() for r in body.rows])
    db.commit()
    return {'rows': n}


@router.get('/attendance')
def get_attendance(month: str, employee_id: str = '',
                   db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('hr.view'))):
    emps = {e.id: e for e in H.list_employees(db, pr.tenant_id)}
    return [{'id': a.id, 'employee_id': a.employee_id,
             'emp_no': emps.get(a.employee_id).emp_no
             if emps.get(a.employee_id) else '?',
             'date': a.att_date.isoformat(), 'status': a.status,
             'in_time': a.in_time, 'out_time': a.out_time,
             'late_min': a.late_min, 'early_min': a.early_min,
             'overtime_hours': str(a.overtime_hours),
             'approved_by': a.approved_by,
             'entered_by': a.entered_by}
            for a in H.list_attendance(db, pr.tenant_id, month, employee_id)]


@router.post('/attendance')
def upsert_attendance(body: AttendanceIn, db: Session = Depends(get_db),
                      pr: Principal = Depends(
                          require_perm('hr.attendance.manage'))):
    n = H.upsert_attendance(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                            rows=[r.model_dump() for r in body.rows])
    db.commit()
    return {'rows': n}


@router.post('/attendance/approve')
def approve_attendance(body: AttendanceApproveIn,
                       db: Session = Depends(get_db),
                       pr: Principal = Depends(
                           require_perm('hr.attendance.approve'))):
    n = H.approve_attendance(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                             ids=body.ids)
    db.commit()
    return {'approved': n}


@router.post('/attendance/unapprove')
def unapprove_attendance(body: AttendanceApproveIn,
                         db: Session = Depends(get_db),
                         pr: Principal = Depends(
                             require_perm('hr.attendance.approve'))):
    n = H.unapprove_attendance(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                               ids=body.ids)
    db.commit()
    return {'unapproved': n}


# ═══════════════ الإجازات ═══════════════
@router.get('/leave-types')
def get_leave_types(db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('hr.view'))):
    return [{'id': lt.id, 'code': lt.code, 'name': lt.name, 'paid': lt.paid,
             'accrual_per_month': str(lt.accrual_per_month)}
            for lt in H.list_leave_types(db, pr.tenant_id)]


@router.post('/leave-types', status_code=201)
def create_leave_type(body: LeaveTypeIn, db: Session = Depends(get_db),
                      pr: Principal = Depends(require_perm('hr.leave.manage'))):
    lt = H.create_leave_type(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                             code=body.code, name=body.name, paid=body.paid,
                             accrual_per_month=body.accrual_per_month)
    db.commit()
    return {'id': lt.id, 'code': lt.code}


@router.post('/leave/accrue')
def accrue_leave(body: AccrueIn, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('hr.leave.manage'))):
    res = H.accrue_leave(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                         month=body.month)
    db.commit()
    return res


@router.get('/leave/balances')
def leave_balances(year: int = Query(default=0),
                   db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('hr.view'))):
    year = year or date.today().year
    emps = {e.id: e for e in H.list_employees(db, pr.tenant_id)}
    types = {lt.id: lt for lt in H.list_leave_types(db, pr.tenant_id)}
    return [{'employee_id': b.employee_id,
             'emp_no': emps.get(b.employee_id).emp_no
             if emps.get(b.employee_id) else '?',
             'employee': emps.get(b.employee_id).full_name
             if emps.get(b.employee_id) else '?',
             'leave_type': types.get(b.leave_type_id).code
             if types.get(b.leave_type_id) else '?',
             'year': b.year, 'entitled': str(b.entitled), 'used': str(b.used),
             'remaining': str(D(b.entitled) - D(b.used))}
            for b in H.list_leave_balances(db, pr.tenant_id, year)]


@router.get('/leave/requests')
def leave_requests(status: str = '', employee_id: str = '',
                   db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('hr.view'))):
    emps = {e.id: e for e in H.list_employees(db, pr.tenant_id)}
    types = {lt.id: lt for lt in H.list_leave_types(db, pr.tenant_id)}
    return [{'id': r.id, 'employee_id': r.employee_id,
             'emp_no': emps.get(r.employee_id).emp_no
             if emps.get(r.employee_id) else '?',
             'employee': emps.get(r.employee_id).full_name
             if emps.get(r.employee_id) else '?',
             'leave_type': types.get(r.leave_type_id).code
             if types.get(r.leave_type_id) else '?',
             'paid': types.get(r.leave_type_id).paid
             if types.get(r.leave_type_id) else True,
             'from_date': r.from_date.isoformat(),
             'to_date': r.to_date.isoformat(), 'days': str(r.days),
             'reason': r.reason, 'status': r.status,
             'approved_by': r.approved_by,
             'reject_reason': r.reject_reason, 'created_by': r.created_by}
            for r in H.list_leave_requests(db, pr.tenant_id, status=status,
                                           employee_id=employee_id)]


@router.post('/leave/requests', status_code=201)
def create_leave_request(body: LeaveRequestIn, db: Session = Depends(get_db),
                         pr: Principal = Depends(
                             require_perm('hr.leave.manage'))):
    r = H.create_leave_request(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                               employee_id=body.employee_id,
                               leave_type_id=body.leave_type_id,
                               from_date=body.from_date, to_date=body.to_date,
                               days=body.days, reason=body.reason)
    db.commit()
    return {'id': r.id}


@router.post('/leave/requests/{rid}/approve')
def approve_leave(rid: str, db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('hr.leave.approve'))):
    r = H.approve_leave(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                        request_id=rid)
    db.commit()
    return {'id': r.id, 'status': r.status}


@router.post('/leave/requests/{rid}/reject')
def reject_leave(rid: str, body: RejectIn, db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('hr.leave.approve'))):
    r = H.reject_leave(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                       request_id=rid, reason=body.reason)
    db.commit()
    return {'id': r.id, 'status': r.status}


# ═══════════════ الجزاءات ═══════════════
@router.get('/penalties')
def get_penalties(month: str = '', employee_id: str = '',
                  db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('hr.view'))):
    emps = {e.id: e for e in H.list_employees(db, pr.tenant_id)}
    return [{'id': p.id, 'employee_id': p.employee_id,
             'emp_no': emps.get(p.employee_id).emp_no
             if emps.get(p.employee_id) else '?',
             'pen_date': p.pen_date.isoformat(), 'apply_month': p.apply_month,
             'amount': str(p.amount), 'reason': p.reason,
             'doc_ref': p.doc_ref, 'approved_by': p.approved_by,
             'deducted_run_id': p.deducted_run_id,
             'created_by': p.created_by}
            for p in H.list_penalties(db, pr.tenant_id, month=month,
                                      employee_id=employee_id)]


@router.post('/penalties', status_code=201)
def create_penalty(body: PenaltyIn, db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('hr.penalty.manage'))):
    p = H.create_penalty(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                         employee_id=body.employee_id, pen_date=body.pen_date,
                         apply_month=body.apply_month, amount=body.amount,
                         reason=body.reason, doc_ref=body.doc_ref)
    db.commit()
    return {'id': p.id}


@router.post('/penalties/{pid}/approve')
def approve_penalty(pid: str, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('hr.penalty.approve'))):
    p = H.approve_penalty(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                          penalty_id=pid)
    db.commit()
    return {'id': p.id, 'approved': True}


# ═══════════════ السلف ═══════════════
def _adv_dict(a: m.HrAdvance, emps: dict) -> dict:
    e = emps.get(a.employee_id)
    return {'id': a.id, 'employee_id': a.employee_id,
            'emp_no': e.emp_no if e else '?',
            'employee': e.full_name if e else '?',
            'amount': str(a.amount), 'installments': a.installments,
            'installment_amount': str(a.installment_amount),
            'remaining': str(a.remaining),
            'request_date': a.request_date.isoformat(),
            'first_deduct_month': a.first_deduct_month,
            'reason': a.reason, 'status': a.status,
            'approved_by': a.approved_by, 'paid_by': a.paid_by,
            'paid_entry_id': a.paid_entry_id,
            'paid_account_code': a.paid_account_code,
            'created_by': a.created_by}


@router.get('/advances')
def get_advances(employee_id: str = '', status: str = '',
                 db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('hr.view'))):
    emps = {e.id: e for e in H.list_employees(db, pr.tenant_id)}
    return [_adv_dict(a, emps)
            for a in H.list_advances(db, pr.tenant_id,
                                     employee_id=employee_id, status=status)]


@router.post('/advances', status_code=201)
def create_advance(body: AdvanceIn, db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('hr.advance.request'))):
    a = H.create_advance(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                         employee_id=body.employee_id, amount=body.amount,
                         installments=body.installments,
                         first_deduct_month=body.first_deduct_month,
                         reason=body.reason)
    db.commit()
    return {'id': a.id, 'installment_amount': str(a.installment_amount)}


@router.post('/advances/{aid}/approve')
def approve_advance(aid: str, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('hr.advance.approve'))):
    a = H.approve_advance(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                          advance_id=aid)
    db.commit()
    return {'id': a.id, 'status': a.status}


@router.post('/advances/{aid}/reject')
def reject_advance(aid: str, body: RejectIn, db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('hr.advance.approve'))):
    a = H.reject_advance(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                         advance_id=aid, reason=body.reason)
    db.commit()
    return {'id': a.id, 'status': a.status}


@router.post('/advances/{aid}/disburse')
def disburse_advance(aid: str, body: DisburseIn, db: Session = Depends(get_db),
                     pr: Principal = Depends(require_perm('hr.pay'))):
    a = H.disburse_advance(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                           branch_id=_bid(db, pr), advance_id=aid,
                           account_code=body.account_code)
    db.commit()
    return {'id': a.id, 'status': a.status, 'entry_id': a.paid_entry_id,
            'remaining': str(a.remaining)}


# ═══════════════ بنود الرواتب ═══════════════
@router.get('/pay-items')
def get_pay_items(db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('hr.view'))):
    return [{'id': it.id, 'code': it.code, 'name': it.name,
             'item_type': it.item_type, 'calc': it.calc,
             'pct_base': str(it.pct_base),
             'credit_account_code': it.credit_account_code,
             'is_system': it.is_system, 'is_active': it.is_active}
            for it in H.list_pay_items(db, pr.tenant_id)]


@router.post('/pay-items', status_code=201)
def create_pay_item(body: PayItemIn, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('hr.policy.manage'))):
    it = H.create_pay_item(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                           code=body.code, name=body.name,
                           item_type=body.item_type, calc=body.calc,
                           pct_base=body.pct_base,
                           credit_account_code=body.credit_account_code)
    db.commit()
    return {'id': it.id, 'code': it.code}


@router.post('/pay-items/{item_id}/toggle')
def toggle_pay_item(item_id: str, body: dict, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('hr.policy.manage'))):
    it = H.set_pay_item_active(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                               item_id=item_id,
                               is_active=bool(body.get('is_active')))
    db.commit()
    return {'id': it.id, 'is_active': it.is_active}


# ═══════════════ معالج المسير ═══════════════
@router.get('/payroll/runs')
def get_runs(month: str = '', kind: str = '', db: Session = Depends(get_db),
             pr: Principal = Depends(require_perm('hr.view'))):
    return [_run_dict(r) for r in H.list_runs(db, pr.tenant_id, month=month,
                                              kind=kind)]


@router.post('/payroll/runs', status_code=201)
def create_run(body: RunCreateIn, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('hr.payroll.prepare'))):
    manual = {eid: [ln.model_dump() for ln in lns]
              for eid, lns in body.manual_lines.items()}
    r = H.create_run(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                     month=body.month, kind=body.kind,
                     parent_run_id=body.parent_run_id,
                     employee_id=body.employee_id,
                     eos_amount=body.eos_amount, manual_lines=manual)
    db.commit()
    return _run_dict(r)


@router.get('/payroll/runs/{run_id}')
def get_run(run_id: str, db: Session = Depends(get_db),
            pr: Principal = Depends(require_perm('hr.view'))):
    r = H._get_run(db, pr.tenant_id, run_id)
    return _run_dict(r)


@router.get('/payroll/runs/{run_id}/payslips')
def get_run_payslips(run_id: str, db: Session = Depends(get_db),
                     pr: Principal = Depends(require_perm('hr.salary.view'))):
    r = H._get_run(db, pr.tenant_id, run_id)
    slips = []
    for s in H.run_payslips(db, pr.tenant_id, r.id):
        if not _confidential_ok(db, pr, s.department_id):
            _forbidden()
        slips.append(_slip_dict(s, True))
    return slips


@router.post('/payroll/runs/{run_id}/recalc')
def recalc_run(run_id: str, body: RecalcIn, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('hr.payroll.prepare'))):
    r = H.recalc_run(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                     run_id=run_id, eos_amount=body.eos_amount)
    db.commit()
    return _run_dict(r)


@router.post('/payroll/runs/{run_id}/prepare')
def prepare_run(run_id: str, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('hr.payroll.prepare'))):
    r = H.prepare_run(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                      run_id=run_id)
    db.commit()
    return _run_dict(r)


@router.post('/payroll/runs/{run_id}/approve')
def approve_run(run_id: str, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('hr.payroll.approve'))):
    r = H.approve_run(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                      run_id=run_id)
    db.commit()
    return _run_dict(r)


@router.post('/payroll/runs/{run_id}/post')
def post_run(run_id: str, db: Session = Depends(get_db),
             pr: Principal = Depends(require_perm('hr.payroll.approve'))):
    r = H.post_run(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                   branch_id=_bid(db, pr), run_id=run_id)
    db.commit()
    return _run_dict(r)


@router.post('/payroll/runs/{run_id}/pay')
def pay_run(run_id: str, body: PayIn, db: Session = Depends(get_db),
            pr: Principal = Depends(require_perm('hr.pay'))):
    r = H.pay_run(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                  branch_id=_bid(db, pr), run_id=run_id,
                  account_code=body.account_code,
                  payslip_ids=body.payslip_ids,
                  receipt_note=body.receipt_note)
    db.commit()
    return _run_dict(r)


@router.post('/payroll/runs/{run_id}/cancel')
def cancel_run(run_id: str, body: CancelIn, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('hr.payroll.prepare'))):
    r = H.cancel_run(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                     run_id=run_id, reason=body.reason)
    db.commit()
    return _run_dict(r)


@router.get('/payslips/{slip_id}')
def get_payslip(slip_id: str, db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('hr.salary.view'))):
    s = H.get_payslip(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                      payslip_id=slip_id)
    if not _confidential_ok(db, pr, s.department_id):
        _forbidden()
    db.commit()  # توثيق حدث المشاهدة (§6)
    return _slip_dict(s, True)


@router.get('/payroll/statement/{employee_id}')
def employee_statement(employee_id: str, db: Session = Depends(get_db),
                       pr: Principal = Depends(require_perm('hr.salary.view'))):
    e = H.get_employee(db, pr.tenant_id, employee_id)
    if not _confidential_ok(db, pr, e.department_id):
        _forbidden()
    rows = []
    for slip, run in H.employee_statement(db, pr.tenant_id, employee_id):
        rows.append({'month': run.month, 'kind': run.kind,
                     'supp_seq': run.supp_seq, 'run_status': run.status,
                     'payslip_id': slip.id, 'gross': str(slip.gross),
                     'net': str(slip.net),
                     'paid': slip.paid_entry_id is not None,
                     'items_snapshot': slip.items_snapshot})
    return {'employee_id': employee_id, 'rows': rows}


@router.post('/payroll/eos-accrue')
def eos_accrue(body: EosAccrueIn, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('hr.payroll.approve'))):
    res = H.eos_accrue_month(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                             branch_id=_bid(db, pr), month=body.month)
    db.commit()
    return res


# ═══════════════ التقارير ═══════════════
@router.get('/reports/register')
def report_register(month: str, db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('hr.reports'))):
    res = H.payroll_register(db, pr.tenant_id, month)
    if not pr.has('hr.salary.view') and not pr.has('*'):
        res['rows'] = []  # التفصيل لكل موظف يتطلب صلاحية الرواتب
    return res


@router.get('/reports/compare')
def report_compare(months: int = Query(default=6, ge=2, le=24),
                   db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('hr.reports'))):
    return H.month_compare(db, pr.tenant_id, months)


@router.get('/reports/advances')
def report_advances(db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('hr.reports'))):
    return H.advances_report(db, pr.tenant_id)


@router.get('/reports/leave-balances')
def report_leave(year: int = Query(default=0),
                 db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('hr.reports'))):
    return H.leave_balances_report(db, pr.tenant_id,
                                   year or date.today().year)


@router.get('/reports/turnover')
def report_turnover(year: int = Query(default=0),
                    db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('hr.reports'))):
    return H.turnover_report(db, pr.tenant_id, year or date.today().year)


@router.get('/reports/cost-vs-revenue')
def report_cost_revenue(month: str, db: Session = Depends(get_db),
                        pr: Principal = Depends(require_perm('hr.reports'))):
    return H.cost_vs_revenue(db, pr.tenant_id, month)


# ═══════════════ السياسة ═══════════════
@router.get('/settings/policy')
def get_policy(db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('hr.view'))):
    db.commit()
    return _policy_dict(H.get_policy(db, pr.tenant_id))


@router.put('/settings/policy')
def put_policy(body: HrPolicyIn, db: Session = Depends(get_db),
               pr: Principal = Depends(require_perm('hr.policy.manage'))):
    p = H.update_policy(db, tenant_id=pr.tenant_id, actor_id=pr.id,
                        changes=body.model_dump(exclude_none=True))
    db.commit()
    return _policy_dict(p)
