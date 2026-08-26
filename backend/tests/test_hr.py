# اختبارات الموارد البشرية والرواتب — ملف 06 §7 (معايير القبول الأربعة)
# قبول-1 حسبة يدوية موقعة تطابق المحرك بالهللة | قبول-2 توازن #21 وتوزيعه
# على الأقسام والصافي = 2310 | قبول-3 استحالة تجاوز سلفة/راتب منتهي |
# قبول-4 استحالة تعديل مسير معتمد والتسوية سطراً جديداً.
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import hr as H
from app import models as m
from app.audit import verify_chain
from app.posting import D, PostingError
from app.security import decrypt_pii, hash_password, new_uuid, utcnow

Y = date.today().year
M1 = f'{Y}-03'      # شهر الاختبار الذهبي (قبل شهر السلفة البذرية)
M2 = f'{Y}-04'
M3 = f'{Y}-05'
D_ = D


# ═══ أدوات مساعدة ═══
def _dept(db, tid, code, name, acct='6110', conf=False, cc='CC-ROOMS'):
    return H.create_department(db, tenant_id=tid, actor_id='t-admin',
                               code=code, name_ar=name, cost_center_code=cc,
                               payroll_account_code=acct, is_confidential=conf)


def _pos(db, tid, dept, title='موظف اختبار', grade='G2'):
    return H.create_position(db, tenant_id=tid, actor_id='t-admin',
                             department_id=dept.id, title=title, grade=grade)


def _emp(db, tid, bid, no, dept, base='3000', allowances=None,
         hire=date(Y - 1, 1, 1), **kw):
    return H.create_employee(
        db, tenant_id=tid, actor_id='t-admin', branch_id=bid, emp_no=no,
        full_name=f'موظف {no}', department_id=dept.id, hire_date=hire,
        base_salary=base, allowances=allowances or [],
        national_id=kw.pop('national_id', None), **kw)


def _rec_dept(db, tid):
    return db.execute(select(m.HrDepartment).where(
        m.HrDepartment.tenant_id == tid, m.HrDepartment.code == 'REC')
    ).scalar_one()


def _adm_dept(db, tid):
    return db.execute(select(m.HrDepartment).where(
        m.HrDepartment.tenant_id == tid, m.HrDepartment.code == 'ADM')
    ).scalar_one()


def _lt(db, tid, code):
    return db.execute(select(m.HrLeaveType).where(
        m.HrLeaveType.tenant_id == tid, m.HrLeaveType.code == code)
    ).scalar_one()


def _mk_role_user(db, tid, role_code, username, password='Pass!12345'):
    role = db.execute(select(m.Role).where(
        m.Role.tenant_id == tid, m.Role.code == role_code)).scalar_one()
    u = m.User(id=new_uuid(), tenant_id=tid, username=username,
               full_name=username, password_hash=hash_password(password),
               created_at=utcnow())
    db.add(u)
    db.flush()
    db.add(m.UserRole(user_id=u.id, role_id=role.id))
    db.commit()
    return u


def _login(client, username, password='Pass!12345'):
    r = client.post('/api/auth/login',
                    json={'username': username, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': f'Bearer {r.json()["access_token"]}'}


def _att(db, tid, emp, day, actor_in, actor_ap, month=M1, status='PRESENT',
         ot=0, late=0):
    y, mo = int(month[:4]), int(month[5:7])
    ids = []
    n = H.upsert_attendance(db, tenant_id=tid, actor_id=actor_in,
                            rows=[{'employee_id': emp.id,
                                   'date': date(y, mo, day), 'status': status,
                                   'late_min': late, 'overtime_hours': ot}])
    assert n == 1
    row = db.execute(select(m.HrAttendance).where(
        m.HrAttendance.tenant_id == tid,
        m.HrAttendance.employee_id == emp.id,
        m.HrAttendance.att_date == date(y, mo, day))).scalar_one()
    ids.append(row.id)
    H.approve_attendance(db, tenant_id=tid, actor_id=actor_ap, ids=ids)
    return row


def _acct_of(db, tid, code):
    return db.execute(select(m.Account).where(
        m.Account.tenant_id == tid, m.Account.code == code)).scalar_one()


def _entry_lines(db, entry_id):
    return db.execute(select(m.JournalLine).where(
        m.JournalLine.entry_id == entry_id)
        .order_by(m.JournalLine.line_no)).scalars().all()


def _advance_paid(db, tid, bid, emp, amount, inst, month, c_actor='t-hr',
                  a_actor='t-hr2', p_actor='t-fin'):
    a = H.create_advance(db, tenant_id=tid, actor_id=c_actor,
                         employee_id=emp.id, amount=amount,
                         installments=inst, first_deduct_month=month,
                         reason='اختبار')
    a = H.approve_advance(db, tenant_id=tid, actor_id=a_actor,
                          advance_id=a.id)
    a = H.disburse_advance(db, tenant_id=tid, actor_id=p_actor,
                           branch_id=bid, advance_id=a.id)
    return a


def _posted_normal_run(db, tid, bid, month, creator='t-hr',
                       approver='t-fin', **kw):
    r = H.create_run(db, tenant_id=tid, actor_id=creator, month=month, **kw)
    r = H.prepare_run(db, tenant_id=tid, actor_id=creator, run_id=r.id)
    r = H.approve_run(db, tenant_id=tid, actor_id=approver, run_id=r.id)
    r = H.post_run(db, tenant_id=tid, actor_id=approver, branch_id=bid,
                   run_id=r.id)
    return r


# ════════════════════════════════════════════════════════════════════
# §1 الهيكل والموظفون والخصوصية
# ════════════════════════════════════════════════════════════════════
def test_department_and_data_guards(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    d = _dept(db, tid, 'TST', 'قسم اختبار', '6310')
    assert d.payroll_account_code == '6310'
    with pytest.raises(PostingError) as e1:
        _dept(db, tid, 'TST', 'مكرر')
    assert e1.value.code == 'HR.DUP_DEPARTMENT'
    with pytest.raises(PostingError) as e2:
        _dept(db, tid, 'TST2', 'حساب غائب', '9999')
    assert e2.value.code == 'HR.BAD_ACCOUNT'
    p = _pos(db, tid, d)
    assert p.grade == 'G2'


def test_employee_crud_encrypted_id_unique_no(db_session):
    """§1+§6: هوية مشفرة ساكناً، رقم وظيفي فريد، عقد موجب."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _rec_dept(db, tid)
    e = _emp(db, tid, bid, 'T-100', d, national_id='999000111')
    db.commit()
    row = db.execute(select(m.HrEmployee).where(
        m.HrEmployee.id == e.id)).scalar_one()
    assert row.national_id_enc != '999000111'
    assert decrypt_pii(row.national_id_enc) == '999000111'
    with pytest.raises(PostingError) as e1:
        _emp(db, tid, bid, 'T-100', d)
    assert e1.value.code == 'HR.DUP_EMP_NO'
    with pytest.raises(PostingError) as e2:
        _emp(db, tid, bid, 'T-101', d, base='0')
    assert e2.value.code == 'HR.BAD_SALARY'


def test_row_privacy_masking_and_confidential_dept(db_session):
    """§6: الراتب مقنع بلا salary.view؛ الأقسام السرية تحتاج تفويضاً أعلى."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    adm = _adm_dept(db, tid)  # مزروع is_confidential=True
    rec = _rec_dept(db, tid)
    e_adm = db.execute(select(m.HrEmployee).where(
        m.HrEmployee.tenant_id == tid,
        m.HrEmployee.department_id == adm.id)).scalars().first()
    e_rec = db.execute(select(m.HrEmployee).where(
        m.HrEmployee.tenant_id == tid,
        m.HrEmployee.department_id == rec.id)).scalars().first()
    # بلا صلاحية رواتب: الكل مقنع
    d1 = H.employee_to_dict(e_rec, rec, see_salary=False,
                            see_confidential=False)
    assert d1['base_salary'] is None and d1['salary_masked'] is True
    # راتب عادي يظهر مع salary.view
    d2 = H.employee_to_dict(e_rec, rec, see_salary=True,
                            see_confidential=False)
    assert D(d2['base_salary']) > 0
    # قسم سري يبقى مقنعاً حتى مع salary.view — يحتاج confidential
    d3 = H.employee_to_dict(e_adm, adm, see_salary=True,
                            see_confidential=False)
    assert d3['base_salary'] is None
    d4 = H.employee_to_dict(e_adm, adm, see_salary=True,
                            see_confidential=True)
    assert D(d4['base_salary']) > 0


def test_employee_changes_dual_approval(db_session):
    """§1: نقل/ترقية/أجر بمستند واعتماد غير ذاتي؛ الإنهاء يغلق التغيير."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _dept(db, tid, 'TST-C', 'قسم تغييرات')
    e = _emp(db, tid, bid, 'T-110', d, base='2000')
    c = H.create_change(db, tenant_id=tid, actor_id='t-hr', emp_id=e.id,
                        change_type='SALARY',
                        after={'base_salary': '2500'},
                        doc_ref='قرار رقم 12', effective_from=date(Y, 6, 1))
    with pytest.raises(PostingError) as e1:
        H.approve_change(db, tenant_id=tid, actor_id='t-hr', change_id=c.id)
    assert e1.value.code == 'HR.SELF_APPROVAL'
    c = H.approve_change(db, tenant_id=tid, actor_id='t-gm', change_id=c.id)
    db.refresh(e)
    assert D(e.base_salary) == D(2500)
    # رفض تغيير آخر
    c2 = H.create_change(db, tenant_id=tid, actor_id='t-hr', emp_id=e.id,
                         change_type='TRANSFER',
                         after={'department_id': _rec_dept(db, tid).id},
                         doc_ref='قرار 13', effective_from=date(Y, 7, 1))
    c2 = H.reject_change(db, tenant_id=tid, actor_id='t-gm',
                         change_id=c2.id, reason='غير مناسب')
    db.refresh(e)
    assert e.department_id == d.id
    # إنهاء ثم منع تغيير جديد
    H.terminate_employee(db, tenant_id=tid, actor_id='t-hr', emp_id=e.id,
                         termination_date=date(Y, 8, 1), reason='استقالة مثال')
    with pytest.raises(PostingError):
        H.create_change(db, tenant_id=tid, actor_id='t-hr', emp_id=e.id,
                        change_type='SALARY', after={'base_salary': '1'},
                        doc_ref='x9', effective_from=date(Y, 9, 1))


# ════════════════════════════════════════════════════════════════════
# §2 الحضور والورديات والإجازات والجزاءات
# ════════════════════════════════════════════════════════════════════
def test_roster_attendance_and_supervisor_approval(db_session):
    """§2: إسناد وردية upsert؛ اعتماد الحضور غير ذاتي؛ المعتمد محمي."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _rec_dept(db, tid)
    e = _emp(db, tid, bid, 'T-120', d)
    morning = db.execute(select(m.HrShift).where(
        m.HrShift.tenant_id == tid, m.HrShift.name == 'الصباحية')
    ).scalar_one()
    evening = db.execute(select(m.HrShift).where(
        m.HrShift.tenant_id == tid, m.HrShift.name == 'المسائية')
    ).scalar_one()
    day = date(Y, 3, 5)
    H.set_roster(db, tenant_id=tid, actor_id='t-hr', rows=[
        {'employee_id': e.id, 'date': day, 'shift_id': morning.id}])
    H.set_roster(db, tenant_id=tid, actor_id='t-hr', rows=[
        {'employee_id': e.id, 'date': day, 'shift_id': evening.id}])
    rows = H.list_roster(db, tid, M1)
    mine = [r for r in rows if r.employee_id == e.id]
    assert len(mine) == 1 and mine[0].shift_id == evening.id
    # حضور بإدخال A واعتماد B
    H.upsert_attendance(db, tenant_id=tid, actor_id='t-in', rows=[
        {'employee_id': e.id, 'date': day, 'status': 'PRESENT',
         'in_time': '07:05', 'out_time': '15:00', 'late_min': 5}])
    row = db.execute(select(m.HrAttendance).where(
        m.HrAttendance.employee_id == e.id,
        m.HrAttendance.att_date == day)).scalar_one()
    with pytest.raises(PostingError) as e1:
        H.approve_attendance(db, tenant_id=tid, actor_id='t-in',
                             ids=[row.id])
    assert e1.value.code == 'HR.SELF_APPROVAL'
    H.approve_attendance(db, tenant_id=tid, actor_id='t-sup', ids=[row.id])
    db.refresh(row)
    assert row.approved_by == 't-sup'
    # المعتمد لا يعاد إدخاله
    with pytest.raises(PostingError) as e2:
        H.upsert_attendance(db, tenant_id=tid, actor_id='t-in', rows=[
            {'employee_id': e.id, 'date': day, 'status': 'ABSENT'}])
    assert e2.value.code == 'HR.ATT_APPROVED'
    # upsert يوم آخر لنفس الموظف لا يكرر صفاً
    day2 = date(Y, 3, 6)
    H.upsert_attendance(db, tenant_id=tid, actor_id='t-in', rows=[
        {'employee_id': e.id, 'date': day2, 'status': 'PRESENT'}])
    H.upsert_attendance(db, tenant_id=tid, actor_id='t-in', rows=[
        {'employee_id': e.id, 'date': day2, 'status': 'ABSENT'}])
    n = db.execute(select(func.count()).select_from(m.HrAttendance).where(
        m.HrAttendance.employee_id == e.id,
        m.HrAttendance.att_date == day2)).scalar_one()
    assert n == 1


def test_leave_accrual_idempotent_and_balance_rules(db_session):
    """§2: استحقاق شهري (إعادة آمنة)، حجز المعلقات، اعتماد يخصم الرصيد."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _rec_dept(db, tid)
    e = _emp(db, tid, bid, 'T-130', d)
    r1 = H.accrue_leave(db, tenant_id=tid, actor_id='t-hr', month=f'{Y}-01')
    assert r1['accrued_rows'] > 0
    r2 = H.accrue_leave(db, tenant_id=tid, actor_id='t-hr', month=f'{Y}-01')
    assert r2['accrued_rows'] == 0  # إعادة آمنة
    ann = _lt(db, tid, 'ANN')
    upl = _lt(db, tid, 'UPL')
    bal = db.execute(select(m.HrLeaveBalance).where(
        m.HrLeaveBalance.employee_id == e.id,
        m.HrLeaveBalance.leave_type_id == ann.id,
        m.HrLeaveBalance.year == Y)).scalar_one()
    assert D(bal.entitled) == D('2.5')
    # طلب أكبر من الرصيد المعلّق-الحجز ممنوع
    req1 = H.create_leave_request(db, tenant_id=tid, actor_id='t-hr',
                                  employee_id=e.id, leave_type_id=ann.id,
                                  from_date=date(Y, 3, 10),
                                  to_date=date(Y, 3, 11), days=2,
                                  reason='عائلية')
    with pytest.raises(PostingError) as e1:
        H.create_leave_request(db, tenant_id=tid, actor_id='t-hr',
                               employee_id=e.id, leave_type_id=ann.id,
                               from_date=date(Y, 3, 20), to_date=date(Y, 3, 21),
                               days=2, reason='ثانية')
    assert e1.value.code == 'HR.LEAVE_INSUFFICIENT'
    # اعتماد يخصم الرصيد آلياً + لا اعتماد ذاتي
    with pytest.raises(PostingError):
        H.approve_leave(db, tenant_id=tid, actor_id='t-hr', request_id=req1.id)
    req1 = H.approve_leave(db, tenant_id=tid, actor_id='t-sup',
                           request_id=req1.id)
    db.refresh(bal)
    assert D(bal.used) == D(2)
    # بدون أجر: بلا رصيد تمر، وترفض عبر الشهور
    upl_req = H.create_leave_request(db, tenant_id=tid, actor_id='t-hr',
                                     employee_id=e.id, leave_type_id=upl.id,
                                     from_date=date(Y, 3, 25),
                                     to_date=date(Y, 3, 26), days=1,
                                     reason='ظرف')
    assert upl_req.status == 'PENDING'
    with pytest.raises(PostingError) as e2:
        H.create_leave_request(db, tenant_id=tid, actor_id='t-hr',
                               employee_id=e.id, leave_type_id=upl.id,
                               from_date=date(Y, 3, 30), to_date=date(Y, 4, 2),
                               days=3, reason='عبور')
    assert e2.value.code == 'HR.CROSS_MONTH'


def test_penalty_requires_approval_and_doc(db_session):
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _rec_dept(db, tid)
    e = _emp(db, tid, bid, 'T-140', d)
    p = H.create_penalty(db, tenant_id=tid, actor_id='t-hr',
                         employee_id=e.id, pen_date=date(Y, 3, 9),
                         apply_month=M1, amount='100', reason='تأخر متكرر',
                         doc_ref='مخالفة-7')
    with pytest.raises(PostingError):
        H.approve_penalty(db, tenant_id=tid, actor_id='t-hr', penalty_id=p.id)
    p = H.approve_penalty(db, tenant_id=tid, actor_id='t-sup',
                          penalty_id=p.id)
    assert p.approved_by == 't-sup'
    with pytest.raises(PostingError) as e1:
        H.approve_penalty(db, tenant_id=tid, actor_id='t-sup',
                          penalty_id=p.id)
    assert e1.value.code == 'HR.PEN_STATE'


# ════════════════════════════════════════════════════════════════════
# §3 السلف
# ════════════════════════════════════════════════════════════════════
def test_advance_ladder_cap_and_entry_23(db_session):
    """§3+14: سقف 50%، اعتماد غير ذاتي، صرف #23 Dr1130 بطرف الموظف."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _rec_dept(db, tid)
    e = _emp(db, tid, bid, 'T-150', d, base='2000')
    with pytest.raises(PostingError) as e1:
        H.create_advance(db, tenant_id=tid, actor_id='t-hr',
                         employee_id=e.id, amount='1001', installments=2,
                         first_deduct_month=M1, reason='أكبر من السقف')
    assert e1.value.code == 'HR.ADV_CAP'
    a = H.create_advance(db, tenant_id=tid, actor_id='t-hr',
                         employee_id=e.id, amount='600', installments=3,
                         first_deduct_month=M1, reason='مصروف')
    assert a.installment_amount == D('200.00')
    with pytest.raises(PostingError) as e2:
        H.disburse_advance(db, tenant_id=tid, actor_id='t-fin',
                           branch_id=bid, advance_id=a.id)
    assert e2.value.code == 'HR.ADV_STATE'
    with pytest.raises(PostingError) as e3:
        H.approve_advance(db, tenant_id=tid, actor_id='t-hr', advance_id=a.id)
    assert e3.value.code == 'HR.SELF_APPROVAL'
    a = H.approve_advance(db, tenant_id=tid, actor_id='t-hr2', advance_id=a.id)
    a = H.disburse_advance(db, tenant_id=tid, actor_id='t-fin',
                           branch_id=bid, advance_id=a.id)
    assert a.status == 'PAID' and D(a.remaining) == D('600')
    lines = _entry_lines(db, a.paid_entry_id)
    assert len(lines) == 2
    dr = [l for l in lines if D(l.debit_base) == D('600')][0]
    assert _acct_of(db, tid, '1130').id == dr.account_id
    assert dr.party_type == 'EMPLOYEE' and dr.party_id == e.id


# ════════════════════════════════════════════════════════════════════
# §4 المحرك — قبول-1: حسبة يدوية موقعة بالهللة
# ════════════════════════════════════════════════════════════════════
def test_golden_payroll_hand_computed(db_session):
    """06/قبول-1: عينة موقعة: أساسي 3000 + بدل 300 + 10% أساسي + 3س إضافي
    (×1.5) - غيابان - تأخير 15 - يوم بدون أجر - جزاء 100 - قسط سلفة 200 -
    استقطاع 6% ⇒ الإجمالي 3656.25 والصافي 2861.25 حرفياً."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _dept(db, tid, 'TST-G', 'قسم الذهبي', '6110')
    e = _emp(db, tid, bid, 'T-700', d, base='3000', allowances=[
        {'code': 'HOU', 'name': 'سكن', 'amount': '300'},
        {'code': 'PERF', 'name': 'حافز نسبي', 'pct_base': '10'}])
    pol = H.get_policy(db, tid)
    H.update_policy(db, tenant_id=tid, actor_id='t-admin',
                    changes={'late_deduct_daily': '15'})
    # حضور معتمد: غيابان + تأخير + 3 ساعات إضافية
    _att(db, tid, e, 5, 't-in', 't-sup', status='ABSENT')
    _att(db, tid, e, 6, 't-in', 't-sup', status='ABSENT')
    _att(db, tid, e, 7, 't-in', 't-sup', late=25)
    _att(db, tid, e, 8, 't-in', 't-sup', ot=3)
    # صف غير معتمد بساعات إضافية — يجب ألا يُحتسب (§4.2-1)
    H.upsert_attendance(db, tenant_id=tid, actor_id='t-in', rows=[
        {'employee_id': e.id, 'date': date(Y, 3, 9), 'status': 'PRESENT',
         'overtime_hours': 10}])
    # إجازة بدون أجر معتمدة يوم
    upl = _lt(db, tid, 'UPL')
    r = H.create_leave_request(db, tenant_id=tid, actor_id='t-hr',
                               employee_id=e.id, leave_type_id=upl.id,
                               from_date=date(Y, 3, 12),
                               to_date=date(Y, 3, 12), days=1, reason='ظرف')
    H.approve_leave(db, tenant_id=tid, actor_id='t-sup', request_id=r.id)
    # جزاء معتمد 100
    p = H.create_penalty(db, tenant_id=tid, actor_id='t-hr',
                         employee_id=e.id, pen_date=date(Y, 3, 15),
                         apply_month=M1, amount='100', reason='مخالفة',
                         doc_ref='J-2')
    H.approve_penalty(db, tenant_id=tid, actor_id='t-sup', penalty_id=p.id)
    # سلفة 600 × 3 أقساط → 200
    _advance_paid(db, tid, bid, e, '600', 3, M1)
    # استقطاع نظامي 6%
    H.create_pay_item(db, tenant_id=tid, actor_id='t-fin', code='WTHX',
                      name='تأمينات مثال', item_type='DEDUCTION',
                      calc='PCT_BASE', pct_base='6',
                      credit_account_code='2220')
    run = H.create_run(db, tenant_id=tid, actor_id='t-hr', month=M1)
    slip = db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == run.id, m.HrPayslip.employee_id == e.id
    )).scalar_one()
    # ── الحسبة اليدوية الموقعة ──
    exp_items = {'BASIC': D('3000'), 'HOU': D('300'), 'PERF': D('300'),
                 'OT': D('56.25'), 'ABS': D('200'), 'LATE': D('15'),
                 'UPL': D('100'), 'PEN': D('100'), 'WTHX': D('180'),
                 'ADV': D('200')}
    seen = {}
    for it in slip.items_snapshot:
        seen.setdefault(it['code'], D('0'))
        seen[it['code']] += D(it['amount'])
    for k, v in exp_items.items():
        assert seen.get(k) == v, f'{k}: متوقع {v} وُجد {seen.get(k)}'
    assert D(slip.gross) == D('3656.25')
    assert D(slip.net) == D('2861.25')
    assert slip.inputs_snapshot['attendance']['unapproved_ignored'] == 1
    assert D(slip.inputs_snapshot['attendance']['ot_hours']) == D('3')


def test_calendar_day_count_proration(db_session):
    """§4.1: نمط CALENDAR — معين يوم 16 من شهر 31 يوماً ⇒ 16/31 للكل."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    H.update_policy(db, tenant_id=tid, actor_id='t-admin',
                    changes={'day_count_mode': 'CALENDAR'})
    d = _dept(db, tid, 'TST-K', 'قسم تقويمي', '6110')
    e = _emp(db, tid, bid, 'T-701', d, base='3100',
             allowances=[{'code': 'HOU', 'name': 'سكن', 'amount': '155'}],
             hire=date(Y, 3, 16))
    run = H.create_run(db, tenant_id=tid, actor_id='t-hr', month=M1)
    slip = db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == run.id,
        m.HrPayslip.employee_id == e.id)).scalar_one()
    it = {x['code']: D(x['amount']) for x in slip.items_snapshot}
    assert it['BASIC'] == D('1600')      # 3100×16/31
    assert it['HOU'] == D('80')          # 155×(16/31)
    assert D(slip.net) == D('1680')


def test_statutory_inactive_item_ignored(db_session):
    """§4.1: الاستقطاع النظامي معطَّل افتراضياً — WTH البذري لا يخصم."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _dept(db, tid, 'TST-W', 'قسم استقطاع', '6110')
    e = _emp(db, tid, bid, 'T-702', d, base='2000')
    run = H.create_run(db, tenant_id=tid, actor_id='t-hr', month=M1)
    slip = db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == run.id,
        m.HrPayslip.employee_id == e.id)).scalar_one()
    codes = {x['code'] for x in slip.items_snapshot}
    assert 'WTH' not in codes
    assert D(slip.gross) == D('2000') == D(slip.net)


# ════════════════════════════════════════════════════════════════════
# §4 الترحيل — قبول-2: توازن #21 وتوزيع الأقسام والصافي = 2310
# ════════════════════════════════════════════════════════════════════
def test_entry21_balanced_distributed_net_eq_2310(db_session):
    """06/قبول-2: قيد متوازن؛ كتل مدينة لحسابات الأقسام تطابق لقطات
    القسائم قسمياً؛ دائن 2310 = مجموع الصافي؛ 1130 بطرف الموظف؛ 2220
    للاستقطاعات؛ الجزاءات على 4901 إن ضبطت السياسة."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    H.update_policy(db, tenant_id=tid, actor_id='t-admin',
                    changes={'penalty_credit_code': '4901'})
    d1 = _dept(db, tid, 'TST-D1', 'قسم أول', '6110')
    d2 = _dept(db, tid, 'TST-D2', 'قسم ثانٍ', '6310')
    e1 = _emp(db, tid, bid, 'T-710', d1, base='1500',
              allowances=[{'code': 'HOU', 'name': 'سكن', 'amount': '100'}])
    e2 = _emp(db, tid, bid, 'T-711', d2, base='2000')
    _advance_paid(db, tid, bid, e2, '300', 1, M1)  # 300 قسط واحد
    p = H.create_penalty(db, tenant_id=tid, actor_id='t-hr',
                         employee_id=e1.id, pen_date=date(Y, 3, 3),
                         apply_month=M1, amount='50', reason='مخالفة أ',
                         doc_ref='x')
    H.approve_penalty(db, tenant_id=tid, actor_id='t-sup', penalty_id=p.id)
    run = _posted_normal_run(db, tid, bid, M1)
    assert run.status == 'POSTED'
    slips = db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == run.id)).scalars().all()
    net_sum = sum(D(s.net) for s in slips)
    assert D(run.net_total) == net_sum
    # إعادة بناء التوزيع المتوقع قسمياً من لقطات القسائم (مصدر الحقيقة)
    dept_acct = {d1.id: '6110', d2.id: '6310'}
    all_depts = {d.id: d.payroll_account_code
                 for d in H.list_departments(db, tid)}
    expect_exp: dict[str, Decimal] = {}
    for s in slips:
        acct = all_depts[s.department_id]
        earned = sum(D(i['amount']) for i in s.items_snapshot
                     if i['type'] == 'EARNING')
        unearned = sum(D(i['amount']) for i in s.items_snapshot
                       if i['bucket'] == 'UNEARNED')
        expect_exp[acct] = expect_exp.get(acct, D('0')) + earned - unearned
    lines = _entry_lines(db, run.posted_entry_id)
    drs: dict[str, Decimal] = {}
    crs: dict[str, Decimal] = {}
    for l in lines:
        acct = db.get(m.Account, l.account_id)
        if D(l.debit_base) > 0:
            drs[acct.code] = drs.get(acct.code, D('0')) + D(l.debit_base)
        else:
            crs[acct.code] = crs.get(acct.code, D('0')) + D(l.credit_base)
    for acct, v in expect_exp.items():
        assert drs.get(acct, D('0')) == v, f'توزيع {acct}: {v} ≠ {drs.get(acct)}'
    assert crs['2310'] == net_sum               # الصافي = 2310 حرفياً
    assert crs.get('1130', D('0')) == D('300')  # قسط السلفة
    assert crs.get('4901', D('0')) == D('50')   # جزاءات ← 4901 حسب السياسة
    assert sum(drs.values()) == sum(crs.values())
    db.commit()


def test_ladder_double_approval_and_no_entry_before(db_session):
    """§4.2-3 + ملف 14: لا قيد قبل إعداد HR ثم اعتماد مالي مختلف."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _dept(db, tid, 'TST-L', 'قسم سلم', '6110')
    _emp(db, tid, bid, 'T-720', d, base='1000')
    r = H.create_run(db, tenant_id=tid, actor_id='t-hr', month=M1)
    with pytest.raises(PostingError):
        H.approve_run(db, tenant_id=tid, actor_id='t-fin', run_id=r.id)
    with pytest.raises(PostingError):
        H.post_run(db, tenant_id=tid, actor_id='t-fin', branch_id=bid,
                   run_id=r.id)
    r = H.prepare_run(db, tenant_id=tid, actor_id='t-hr', run_id=r.id)
    with pytest.raises(PostingError) as e1:
        H.approve_run(db, tenant_id=tid, actor_id='t-hr', run_id=r.id)
    assert e1.value.code == 'HR.SELF_APPROVAL'
    n_entries = db.execute(select(func.count()).select_from(
        m.JournalEntry).where(m.JournalEntry.source_type == 'HR_PAYROLL_RUN')
    ).scalar_one()
    assert n_entries == 0  # لا قيد قبل الاعتمادين
    r = H.approve_run(db, tenant_id=tid, actor_id='t-fin', run_id=r.id)
    r = H.post_run(db, tenant_id=tid, actor_id='t-fin', branch_id=bid,
                   run_id=r.id)
    assert r.posted_entry_id
    with pytest.raises(PostingError):
        H.post_run(db, tenant_id=tid, actor_id='t-fin', branch_id=bid,
                   run_id=r.id)
    with pytest.raises(PostingError) as e2:
        H.cancel_run(db, tenant_id=tid, actor_id='t-hr', run_id=r.id,
                     reason='محاولة')
    assert e2.value.code == 'HR.RUN_IMMUTABLE'


def test_one_normal_run_per_month_then_supplemental(db_session):
    """§4.3 + 06/قبول-4: مسير واحد؛ التسوية سطراً جديداً بجوار الأصل
    الذي لا يُمَس (قيده وقيمه ثابتة)."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _dept(db, tid, 'TST-S', 'قسم تسوية', '6110')
    e = _emp(db, tid, bid, 'T-730', d, base='1200')
    r1 = _posted_normal_run(db, tid, bid, M1)
    entry_before = r1.posted_entry_id
    net_before = D(r1.net_total)
    with pytest.raises(PostingError) as e1:
        H.create_run(db, tenant_id=tid, actor_id='t-hr', month=M1)
    assert e1.value.code == 'HR.RUN_EXISTS'
    supp_lines = {e.id: [{'code': 'BONUS', 'name': 'مكافأة تسوية إهمال',
                          'type': 'EARNING', 'amount': '500'}]}
    r2 = H.create_run(db, tenant_id=tid, actor_id='t-hr', month=M1,
                      kind='SUPPLEMENTAL', parent_run_id=r1.id,
                      manual_lines=supp_lines)
    r2 = H.prepare_run(db, tenant_id=tid, actor_id='t-hr', run_id=r2.id)
    r2 = H.approve_run(db, tenant_id=tid, actor_id='t-fin', run_id=r2.id)
    r2 = H.post_run(db, tenant_id=tid, actor_id='t-fin', branch_id=bid,
                    run_id=r2.id)
    stmt = H.employee_statement(db, tid, e.id)
    kinds = [(run.kind, str(slip.net)) for slip, run in stmt
             if run.month == M1]
    assert ('NORMAL', '1200.0000') in kinds
    assert ('SUPPLEMENTAL', '500.0000') in kinds  # سطر جديد في كشف الموظف
    db.refresh(r1)
    assert r1.posted_entry_id == entry_before    # الأصل لم يُمس
    assert D(r1.net_total) == net_before         # ولا قيمه تبدّلت


def test_cancel_frees_month_and_recalc_only_draft(db_session):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    d = _dept(db, tid, 'TST-RC', 'قسم إعادة', '6110')
    _emp(db, tid, seed['branch_id'], 'T-731', d, base='900')
    r = H.create_run(db, tenant_id=tid, actor_id='t-hr', month=M1)
    r = H.prepare_run(db, tenant_id=tid, actor_id='t-hr', run_id=r.id)
    with pytest.raises(PostingError):
        H.recalc_run(db, tenant_id=tid, actor_id='t-hr', run_id=r.id)
    r = H.cancel_run(db, tenant_id=tid, actor_id='t-hr', run_id=r.id,
                     reason='مصفوفة تغيرت')
    assert r.status == 'CANCELLED'
    r2 = H.create_run(db, tenant_id=tid, actor_id='t-hr', month=M1)
    assert r2.supp_seq == r.supp_seq + 1  # الملغي يحجز رقمته (لا ثغرة)


# ════════════════════════════════════════════════════════════════════
# قبول-3: سلفة لا تتجاوز رصيدها + استحالة راتب لمنتهي الخدمة
# ════════════════════════════════════════════════════════════════════
def test_advance_never_overdeducted_then_settled(db_session):
    """06/قبول-3: آخر قسط يقتصر على الرصيد، ويُصفّر ويُغلق — استحالة سالب."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _dept(db, tid, 'TST-A', 'قسم سلف', '6110')
    e = _emp(db, tid, bid, 'T-740', d, base='1000')
    a = _advance_paid(db, tid, bid, e, '400', 2, M1)  # قسطان 200
    r1 = _posted_normal_run(db, tid, bid, M1)
    db.refresh(a)
    assert D(a.remaining) == D('200')
    r2 = _posted_normal_run(db, tid, bid, M2)
    db.refresh(a)
    assert D(a.remaining) == D('0') and a.status == 'SETTLED'
    r3 = H.create_run(db, tenant_id=tid, actor_id='t-hr', month=M3)
    _posted = r3
    slip_e = db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == _posted.id,
        m.HrPayslip.employee_id == e.id)).scalar_one()
    assert not [i for i in slip_e.items_snapshot
                if i['bucket'].startswith('ADV:')]
    db.refresh(a)
    assert D(a.remaining) == D('0')


def test_terminated_excluded_and_final_run_prorated(db_session):
    """06/قبول-3: المنهي خارج الشهري؛ FINAL بنسبة 15 يوماً + EOS + تصفية سلفة."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _dept(db, tid, 'TST-T', 'قسم إنهاء', '6110')
    e = _emp(db, tid, bid, 'T-750', d, base='3100',
             allowances=[{'code': 'HOU', 'name': 'سكن', 'amount': '100'}])
    a = _advance_paid(db, tid, bid, e, '400', 4, M1)  # متبقٍ 400
    H.terminate_employee(db, tenant_id=tid, actor_id='t-hr', emp_id=e.id,
                         termination_date=date(Y, 3, 15), reason='إنهاء مثال')
    # المنهي خارج المسير الشهري استحالةً
    run_n = H.create_run(db, tenant_id=tid, actor_id='t-hr', month=M1)
    ids = [s.employee_id for s in db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == run_n.id)).scalars()]
    assert e.id not in ids
    # FINAL: أساسي 3100×15/30=1550 + بدل 100×0.5=50 + EOS 800 - سلفة كاملة 400
    rf = H.create_run(db, tenant_id=tid, actor_id='t-hr', month=M1,
                      kind='FINAL', employee_id=e.id, eos_amount='800')
    rf = H.prepare_run(db, tenant_id=tid, actor_id='t-hr', run_id=rf.id)
    rf = H.approve_run(db, tenant_id=tid, actor_id='t-fin', run_id=rf.id)
    rf = H.post_run(db, tenant_id=tid, actor_id='t-fin', branch_id=bid,
                    run_id=rf.id)
    slip = db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == rf.id, m.HrPayslip.employee_id == e.id
    )).scalar_one()
    it = {x['code']: D(x['amount']) for x in slip.items_snapshot}
    assert it['BASIC'] == D('1550') and it['HOU'] == D('50')
    assert it['EOS'] == D('800') and it['ADV'] == D('400')
    assert D(slip.net) == D('2000')
    db.refresh(a)
    assert D(a.remaining) == D('0') and a.status == 'SETTLED'
    # ولا يتكرر FINAL نشط لنفس الموظف/الشهر
    with pytest.raises(PostingError):
        H.create_run(db, tenant_id=tid, actor_id='t-hr', month=M1,
                     kind='FINAL', employee_id=e.id, eos_amount='1')


def test_suspended_excluded_from_normal_run(db_session):
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _dept(db, tid, 'TST-SP', 'قسم إيقاف', '6110')
    e = _emp(db, tid, bid, 'T-760', d, base='800')
    H.suspend_employee(db, tenant_id=tid, actor_id='t-hr', emp_id=e.id,
                       reason='إيقاف مؤقت')
    run = H.create_run(db, tenant_id=tid, actor_id='t-hr', month=M1)
    ids = [s.employee_id for s in db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == run.id)).scalars()]
    assert e.id not in ids


def test_negative_net_blocked(db_session):
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _dept(db, tid, 'TST-N', 'قسم سالب', '6110')
    e = _emp(db, tid, bid, 'T-770', d, base='100')
    p = H.create_penalty(db, tenant_id=tid, actor_id='t-hr',
                         employee_id=e.id, pen_date=date(Y, 3, 1),
                         apply_month=M1, amount='500', reason='جسيمة',
                         doc_ref='z')
    H.approve_penalty(db, tenant_id=tid, actor_id='t-sup', penalty_id=p.id)
    with pytest.raises(PostingError) as e1:
        H.create_run(db, tenant_id=tid, actor_id='t-hr', month=M1)
    assert e1.value.code == 'HR.NEGATIVE_NET'


def test_unapprove_blocked_after_post(db_session):
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _dept(db, tid, 'TST-UL', 'قسم قفل', '6110')
    e = _emp(db, tid, bid, 'T-780', d, base='900')
    row = _att(db, tid, e, 4, 't-in', 't-sup')
    _posted_normal_run(db, tid, bid, M1)
    with pytest.raises(PostingError) as e1:
        H.unapprove_attendance(db, tenant_id=tid, actor_id='t-sup',
                               ids=[row.id])
    assert e1.value.code == 'HR.MONTH_LOCKED'


# ════════════════════════════════════════════════════════════════════
# §4.2-6 الصرف + §4.3 المخصص + §5 تقارير + §6 تدقيق المشاهدة
# ════════════════════════════════════════════════════════════════════
def test_pay_run_full_and_partial_entry22(db_session):
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _dept(db, tid, 'TST-P', 'قسم صرف', '6110')
    e = _emp(db, tid, bid, 'T-790', d, base='777')
    run = _posted_normal_run(db, tid, bid, M1)
    slips = db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == run.id)).scalars().all()
    my = [s for s in slips if s.employee_id == e.id][0]
    r = H.pay_run(db, tenant_id=tid, actor_id='t-fin', branch_id=bid,
                  run_id=run.id, payslip_ids=[my.id],
                  receipt_note='استلم الموظف T-790 نقداً')
    db.refresh(my)
    assert my.paid_entry_id
    db.refresh(r)
    assert r.status == 'POSTED'  # بقية القسائم (البذرية) بعد
    r = H.pay_run(db, tenant_id=tid, actor_id='t-fin', branch_id=bid,
                  run_id=run.id)
    db.refresh(r)
    assert r.status == 'PAID'
    # #22: مجموع مديني الدفعتين = مجموع الصافي
    ent_ids = {s.paid_entry_id for s in db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == run.id)).scalars()}
    paid_total = D('0')
    for eid in ent_ids:
        for l in _entry_lines(db, eid):
            acct = db.get(m.Account, l.account_id)
            if acct.code == '2310':
                paid_total += D(l.debit_base)
    assert paid_total == sum(D(s.net) for s in db.execute(
        select(m.HrPayslip).where(m.HrPayslip.run_id == run.id)).scalars())
    with pytest.raises(PostingError) as e1:
        H.pay_run(db, tenant_id=tid, actor_id='t-fin', branch_id=bid,
                  run_id=run.id)
    assert e1.value.code == 'HR.NOTHING_TO_PAY'


def test_eos_monthly_provision_and_idempotency(db_session):
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    with pytest.raises(PostingError) as e1:
        H.eos_accrue_month(db, tenant_id=tid, actor_id='t-fin',
                           branch_id=bid, month=M1)
    assert e1.value.code == 'HR.EOS_DISABLED'
    H.update_policy(db, tenant_id=tid, actor_id='t-fin',
                    changes={'eos_enabled': True, 'eos_month_rate': '0.05'})
    res = H.eos_accrue_month(db, tenant_id=tid, actor_id='t-fin',
                             branch_id=bid, month=M1)
    assert res['posted'] >= 5  # الموظفون البذريون على الأقل
    # مبلغ EMP-001 (أساسي 1200): 1200×0.05 = 60 بالضبط (معدل قابل للضبط)
    e1row = db.execute(select(m.HrEmployee).where(
        m.HrEmployee.tenant_id == tid,
        m.HrEmployee.emp_no == 'EMP-001')).scalar_one()
    prov = db.execute(select(m.HrEosProvision).where(
        m.HrEosProvision.tenant_id == tid,
        m.HrEosProvision.employee_id == e1row.id,
        m.HrEosProvision.month == M1)).scalar_one()
    assert D(prov.amount) == D('60.0000')
    res2 = H.eos_accrue_month(db, tenant_id=tid, actor_id='t-fin',
                              branch_id=bid, month=M1)
    assert res2['posted'] == 0  # إعادة آمنة
    crl = [l for l in _entry_lines(db, res['entry_id']) if D(l.credit_base) > 0]
    assert len(crl) == 1
    assert db.get(m.Account, crl[0].account_id).code == '2320'


def test_reports_register_advances_turnover(db_session):
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _dept(db, tid, 'TST-R', 'قسم تقارير', '6110')
    e = _emp(db, tid, bid, 'T-791', d, base='500')
    run = _posted_normal_run(db, tid, bid, M1)
    reg = H.payroll_register(db, tid, M1)
    mine = [r for r in reg['rows'] if r['emp_no'] == 'T-791']
    assert mine and D(mine[0]['net']) == D('500')
    dept_row = [x for x in reg['by_department'] if x['department_code'] == 'TST-R']
    assert D(dept_row[0]['net']) == D('500')
    basic_item = [x for x in reg['by_item'] if x['code'] == 'BASIC']
    assert D(basic_item[0]['amount']) >= D('500')
    comp = H.month_compare(db, tid, 6)
    assert any(c['month'] == M1 for c in comp)
    advr = H.advances_report(db, tid)
    assert any(a['emp_no'] == 'EMP-001' and a['status'] == 'PAID'
               for a in advr)  # السلفة البذرية بتقادم
    turn = H.turnover_report(db, tid, Y)
    assert sum(t['hires'] for t in turn) >= 0
    bals = H.leave_balances_report(db, tid, Y)
    assert any(b['emp_no'] == 'EMP-001' and b['leave_type'] == 'ANN'
               and D(b['entitled']) > 0 for b in bals)
    cvr = H.cost_vs_revenue(db, tid, M1)
    assert D(cvr['payroll_gross']) > 0


def test_payslip_view_is_audited(db_session):
    """§6: فتح القسيمة حدث مدقق مستقل."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _dept(db, tid, 'TST-V', 'قسم مشاهدة', '6110')
    e = _emp(db, tid, bid, 'T-792', d, base='300')
    run = H.create_run(db, tenant_id=tid, actor_id='t-hr', month=M1)
    slip = db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == run.id,
        m.HrPayslip.employee_id == e.id)).scalar_one()
    H.get_payslip(db, tenant_id=tid, actor_id='fin-1', payslip_id=slip.id)
    db.flush()  # جلسة الاختبار بلا autoflush — صف التدقيق معلق
    row = db.execute(select(m.AuditLog).where(
        m.AuditLog.tenant_id == tid, m.AuditLog.action == 'payslip.view',
        m.AuditLog.entity_id == slip.id)).scalar_one()
    assert row.actor_user_id == 'fin-1'
    chk = verify_chain(db, tid)
    assert chk['ok'] is True


# ════════════════════════════════════════════════════════════════════
# HTTP: RBAC + خصوصية صفية + استحالة تعديل المسير من كل المسارات
# ════════════════════════════════════════════════════════════════════
def _seed_posted_run_http(db, tid, bid, admin_id):
    d = _dept(db, tid, 'TST-H', 'قسم HTTP', '6110')
    _emp(db, tid, bid, 'T-800', d, base='600')
    adm = _adm_dept(db, tid)
    run = H.create_run(db, tenant_id=tid, actor_id=admin_id, month=M1)
    run = H.prepare_run(db, tenant_id=tid, actor_id=admin_id, run_id=run.id)
    run = H.approve_run(db, tenant_id=tid, actor_id='t-fin', run_id=run.id)
    run = H.post_run(db, tenant_id=tid, actor_id='t-fin', branch_id=bid,
                     run_id=run.id)
    db.commit()
    return run


def test_http_rbac_and_immutability(db_session, client, auth_hdr):
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    run = _seed_posted_run_http(db, tid, bid, seed['admin_id'])
    cashier = _mk_role_user(db, tid, 'POS_CASHIER', 'cas-hr1')
    ch = _login(client, 'cas-hr1')
    assert client.get('/api/hr/employees', headers=ch).status_code == 403
    assert client.post('/api/hr/payroll/runs', headers=ch,
                       json={'month': M2}).status_code == 403
    # لا PUT/PATCH على المسيرات إطلاقاً (قبول-4 من مسار الواجهة)
    for method in (client.put, client.patch):
        r = method(f'/api/hr/payroll/runs/{run.id}',
                   headers=auth_hdr, json={'status': 'DRAFT'})
        assert r.status_code in (404, 405)
    assert client.delete(f'/api/hr/payroll/runs/{run.id}',
                         headers=auth_hdr).status_code in (404, 405)


def test_http_row_privacy_confidential_payslip_403(db_session, client,
                                                   auth_hdr):
    """§6: مدير HR لا يرى قسيمة قسم سري؛ المالية (مفوضة) ترى."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    run = _seed_posted_run_http(db, tid, bid, seed['admin_id'])
    adm = _adm_dept(db, tid)
    adm_slip = db.execute(select(m.HrPayslip).where(
        m.HrPayslip.run_id == run.id,
        m.HrPayslip.department_id == adm.id)).scalars().first()
    assert adm_slip is not None  # EMP-004 بذري في ADM السري
    hr_user = _mk_role_user(db, tid, 'HR_MANAGER', 'hrm-1')
    fin_user = _mk_role_user(db, tid, 'FINANCE_MANAGER', 'fin-1')
    hh = _login(client, 'hrm-1')
    fh = _login(client, 'fin-1')
    r = client.get(f'/api/hr/payslips/{adm_slip.id}', headers=hh)
    assert r.status_code == 403
    r2 = client.get(f'/api/hr/payslips/{adm_slip.id}', headers=fh)
    assert r2.status_code == 200
    assert D(r2.json()['net']) > 0
    # قائمة الموظفين لمدير HR تقنّع رواتب القسم السري فقط
    emps = client.get('/api/hr/employees', headers=hh).json()
    by_dept = {}
    for row in emps:
        by_dept.setdefault(row['department_code'], row['salary_masked'])
    assert by_dept.get('ADM') is True and by_dept.get('REC') is False
    # ممثل بدون salary.view لا يرى القسائم
    gm = _mk_role_user(db, tid, 'GM', 'gm-1')
    gh = _login(client, 'gm-1')
    assert client.get(f'/api/hr/payroll/runs/{run.id}/payslips',
                      headers=gh).status_code == 403
    # سجل التجميعة متاح للتقارير دون تفاصيل فردية
    reg = client.get(f'/api/hr/reports/register?month={M1}', headers=gh)
    assert reg.status_code == 200 and reg.json()['rows'] == []
    assert any(x['department_code'] == 'TST-H'
               for x in reg.json()['by_department'])


def test_http_e2e_wizard_full_cycle(db_session, client, auth_hdr):
    """رحلة HR ومالية عبر HTTP: مسودة ← إعداد ← اعتماد ← ترحيل ← صرف."""
    db, factory, seed = db_session
    tid, bid = seed['tenant_id'], seed['branch_id']
    d = _dept(db, tid, 'TST-E', 'قسم E2E', '6110')
    _emp(db, tid, bid, 'T-810', d, base='1000')
    db.commit()
    hr_user = _mk_role_user(db, tid, 'HR_MANAGER', 'hrm-2')
    fin_user = _mk_role_user(db, tid, 'FINANCE_MANAGER', 'fin-2')
    hh = _login(client, 'hrm-2')
    fh = _login(client, 'fin-2')
    r = client.post('/api/hr/payroll/runs', headers=hh, json={'month': M2})
    assert r.status_code == 201, r.text
    run = r.json()
    assert run['gross_total'] != '0'
    # عرض القسائم: يشمل قسماً سرياً بذرياً — يلزم تفويض مالي (§6)
    assert client.get(f"/api/hr/payroll/runs/{run['id']}/payslips",
                      headers=hh).status_code == 403
    slips = client.get(f"/api/hr/payroll/runs/{run['id']}/payslips",
                       headers=fh).json()
    assert isinstance(slips, list)
    assert any(s['net'] == '1000.0000' for s in slips)
    # منطق السلم عبر API: اعتماد المعد ممنوع، ولكن مالية آخر يقبل
    assert client.post(f"/api/hr/payroll/runs/{run['id']}/approve",
                       headers=fh).status_code == 400  # لم يُعدَّ بعد
    assert client.post(f"/api/hr/payroll/runs/{run['id']}/post",
                       headers=fh).status_code == 400
    assert client.post(f"/api/hr/payroll/runs/{run['id']}/prepare",
                       headers=hh).status_code == 200
    assert client.post(f"/api/hr/payroll/runs/{run['id']}/approve",
                       headers=fh).status_code == 200
    assert client.post(f"/api/hr/payroll/runs/{run['id']}/post",
                       headers=fh).status_code == 200
    assert client.post(f"/api/hr/payroll/runs/{run['id']}/pay",
                       headers=fh, json={}).status_code == 200
    done = client.get(f"/api/hr/payroll/runs/{run['id']}", headers=fh).json()
    assert done['status'] == 'PAID' and done['posted_entry_id']


def test_hr_seed_idempotent_and_audit_chain(db_session):
    db, factory, seed = db_session
    from app.seed import seed_hr
    tid, bid = seed['tenant_id'], seed['branch_id']
    db.commit()
    before = {t: db.execute(select(func.count()).select_from(tbl)).scalar_one()
              for t, tbl in (('dept', m.HrDepartment), ('emp', m.HrEmployee),
                             ('lt', m.HrLeaveType), ('pi', m.HrPayItem))}
    again = seed_hr(db, tid, bid)
    db.commit()
    after = {t: db.execute(select(func.count()).select_from(tbl)).scalar_one()
             for t, tbl in (('dept', m.HrDepartment), ('emp', m.HrEmployee),
                            ('lt', m.HrLeaveType), ('pi', m.HrPayItem))}
    assert before == after
    assert all(v == 0 for k, v in again.items() if k != 'balances')
    chk = verify_chain(db, tid)
    assert chk['ok'] is True and chk['checked'] > 0
