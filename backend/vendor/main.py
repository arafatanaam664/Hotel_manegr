"""تجميع لوحة الشركة (ملف 08) — تطبيق مستقل بمنفذه وقاعدته وسرّه الخاص.
الواجهات:
- /api/v1/*  : واجهات فريق الشركة (MFA إلزامي + أقل امتياز + تدقيق مستقل)
- /edge/*    : واجهة العميل المحدودة (نبض+تحقق ترخيص+تذكرة+تحديث — لا أكثر §1)
- /*         : واجهة الويب RTL المضمّنة (static/index.html)
"""
import os

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import billing as B
from . import healthmon as H
from . import licensing_svc as LS
from . import models as m
from . import schemas as S
from . import tickets as T
from .audit import vaudit
from .clock import vnow
from .config import get_vendor_settings
from .db import SessionVendor, VendorBase, engine, get_vdb
from .security import (ROLE_AR, VPrincipal, authenticate_edge, create_token,
                       decode_token, get_vprincipal, new_totp_secret,
                       require_perm, totp_ok, vdeny, verify_password)


def _client_or_404(db: Session, code: str) -> m.Client:
    c = db.execute(select(m.Client).where(m.Client.code == code)
                   ).scalar_one_or_none()
    if c is None:
        vdeny('CRM.NOT_FOUND', f'العميل غير موجود: {code}', 404)
    return c


def _ip(request: Request) -> str:
    return request.client.host if request.client else ''


def create_vendor_app() -> FastAPI:
    s = get_vendor_settings()
    app = FastAPI(title=s.app_name, version=s.version,
                  docs_url='/api/v1/docs',
                  openapi_url='/api/v1/openapi.json')
    app.add_middleware(CORSMiddleware, allow_origins=['*'],
                       allow_credentials=False, allow_methods=['*'],
                       allow_headers=['*'])

    @app.exception_handler(StarletteHTTPException)
    async def _http_err(_: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and 'error' in detail:
            return JSONResponse(status_code=exc.status_code, content=detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={'error': {'code': f'HTTP.{exc.status_code}',
                               'message_ar': str(detail)}})

    @app.exception_handler(RequestValidationError)
    async def _val_err(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        return JSONResponse(status_code=422, content={
            'error': {'code': 'VALIDATION.INVALID_INPUT',
                      'message_ar': 'مدخلات غير صالحة',
                      'detail': str(first.get('loc', '')) + ': ' +
                                str(first.get('msg', ''))}})

    # ═════════ المصادقة — MFA إلزامي (§7) ═════════
    @app.post('/api/v1/auth/login')
    def login(body: S.LoginIn, request: Request, db: Session =
              Depends(get_vdb)):
        u = db.execute(select(m.VendorUser).where(
            m.VendorUser.username == body.username)).scalar_one_or_none()
        if u is None or not verify_password(body.password, u.password_hash):
            vdeny('VND.INVALID_CREDENTIALS', 'بيانات الدخول غير صحيحة', 401)
        if not u.is_active:
            vdeny('VND.USER_INACTIVE', 'الحساب موقوف', 403)
        if not u.mfa_enabled:
            # التسجيل الإجباري الأول: سر يُعرض مرة واحدة ثم تأكيد برمز صالح
            if not u.mfa_secret:
                u.mfa_secret = new_totp_secret()
                db.flush()
            enroll = create_token(user_id=u.id, kind='mfa_enroll', minutes=10)
            vaudit(db, actor_id=u.id, module='security',
                   action='MFA_ENROLL_START', entity='vendor_users',
                   entity_id=u.id)
            db.commit()
            import pyotp
            return {'mfa_required': True, 'enrolled': False,
                    'enroll_token': enroll,
                    'totp_secret': u.mfa_secret,
                    'otpauth': pyotp.TOTP(u.mfa_secret).provisioning_uri(
                        name=u.username, issuer_name='MantiqSoft Vendor'),
                    'message_ar': 'امسح الرمز بتطبيق المصادقة ثم أدخل الرمز '
                                  'لإتمام التفعيل الإجباري (§7)'}
        if not body.totp_code or not totp_ok(u.mfa_secret, body.totp_code):
            vaudit(db, actor_id=u.id, module='security',
                   action='MFA_LOGIN_FAIL', entity='vendor_users',
                   entity_id=u.id, ip=_ip(request))
            db.commit()
            vdeny('VND.MFA_REQUIRED',
                  'أدخل رمز التحقق الثنائي الصحيح من تطبيق المصادقة', 401)
        vaudit(db, actor_id=u.id, module='security', action='LOGIN_SUCCESS',
               entity='vendor_users', entity_id=u.id, ip=_ip(request))
        db.commit()
        return {'access_token': create_token(user_id=u.id),
                'token_type': 'bearer',
                'user': {'username': u.username, 'full_name': u.full_name,
                         'role': u.role, 'role_ar': ROLE_AR.get(u.role, ''),
                         'duty_manager': u.duty_manager}}

    @app.post('/api/v1/auth/mfa/confirm')
    def mfa_confirm(body: S.MfaConfirmIn, request: Request,
                    db: Session = Depends(get_vdb)):
        try:
            payload = decode_token(body.enroll_token)
        except Exception:
            vdeny('VND.INVALID_TOKEN', 'رمز التسجيل منتهي — أعد الدخول', 401)
        if payload.get('type') != 'mfa_enroll':
            vdeny('VND.WRONG_TYPE', 'نوع الرمز غير صحيح', 401)
        u = db.get(m.VendorUser, payload.get('sub'))
        if u is None or not totp_ok(u.mfa_secret, body.totp_code):
            vdeny('VND.BAD_TOTP', 'الرمز غير صحيح — تحقق من الساعة والتطبيق',
                  400)
        u.mfa_enabled = True
        db.flush()
        vaudit(db, actor_id=u.id, module='security', action='MFA_ENROLLED',
               entity='vendor_users', entity_id=u.id, ip=_ip(request))
        db.commit()
        return {'enabled': True,
                'access_token': create_token(user_id=u.id),
                'token_type': 'bearer',
                'user': {'username': u.username, 'full_name': u.full_name,
                         'role': u.role}}

    # ═════════ CRM العملاء (§2) ═════════
    def _client_out(db: Session, c: m.Client) -> dict:
        hist = db.execute(select(m.ClientStatusHistory).where(
            m.ClientStatusHistory.client_id == c.id)
            .order_by(m.ClientStatusHistory.at.desc()).limit(50)
            ).scalars().all()
        lic_now = LS.latest_active_license(db, c)
        return {'code': c.code, 'legal_name': c.legal_name,
                'trade_name': c.trade_name, 'contacts': c.contacts,
                'hotel_name': c.hotel_name, 'rooms_count': c.rooms_count,
                'branches_count': c.branches_count,
                'sales_channel': c.sales_channel,
                'contract_ref': c.contract_ref, 'package': c.package,
                'modules': c.modules, 'plan_code': c.plan_code,
                'billing_period': c.billing_period,
                'monthly_value': str(c.monthly_value),
                'activation_date': str(c.activation_date or ''),
                'expiry_date': str(c.expiry_date or ''),
                'grace_days': c.grace_days, 'status': c.status,
                'remind_at': c.remind_at, 'notes': c.notes,
                'active_license': {'license_id': lic_now.license_id,
                                   'serial': lic_now.serial,
                                   'expires': str(lic_now.expires_at)}
                if lic_now else None,
                'history': [{'from': h.from_status, 'to': h.to_status,
                             'reason': h.reason, 'by': h.changed_by,
                             'at': h.at.isoformat()} for h in hist]}

    @app.get('/api/v1/clients')
    def list_clients(status: str | None = None,
                     db: Session = Depends(get_vdb),
                     pr: VPrincipal = Depends(require_perm('clients.view'))):
        q = select(m.Client).order_by(m.Client.code)
        if status:
            q = q.where(m.Client.status == status)
        return [_client_out(db, c) for c in db.execute(q).scalars().all()]

    @app.post('/api/v1/clients', status_code=201)
    def create_client(body: S.ClientIn, request: Request,
                      db: Session = Depends(get_vdb),
                      pr: VPrincipal = Depends(require_perm('clients.manage'))):
        c = B.create_client(db, actor=pr.user, data=body.model_dump(),
                            ip=_ip(request))
        db.commit()
        return _client_out(db, c)

    @app.get('/api/v1/clients/{code}')
    def get_client(code: str, db: Session = Depends(get_vdb),
                   pr: VPrincipal = Depends(require_perm('clients.view'))):
        return _client_out(db, _client_or_404(db, code))

    @app.post('/api/v1/clients/{code}/status')
    def set_status(code: str, body: S.ClientStatusIn, request: Request,
                   db: Session = Depends(get_vdb),
                   pr: VPrincipal = Depends(require_perm('clients.manage'))):
        c = _client_or_404(db, code)
        B.set_client_status(db, c, body.to_status, reason=body.reason,
                            actor_id=pr.id, ip=_ip(request))
        db.commit()
        return _client_out(db, c)

    # ═════════ الخطط والفوترة والتحصيل (§3) ═════════
    @app.post('/api/v1/plans', status_code=201)
    def create_plan(body: S.PlanIn, request: Request,
                    db: Session = Depends(get_vdb),
                    pr: VPrincipal = Depends(require_perm('clients.manage'))):
        if db.execute(select(m.Plan).where(m.Plan.code == body.code)).first():
            vdeny('BILL.PLAN_EXISTS', 'رمز الخطة مستخدم مسبقاً', 409)
        p = m.Plan(**body.model_dump())
        db.add(p)
        db.flush()
        vaudit(db, actor_id=pr.id, module='billing', action='PLAN_CREATE',
               entity='vendor_plans', entity_id=p.id,
               after={'code': p.code, 'base_price': str(p.base_price)},
               ip=_ip(request))
        db.commit()
        return {'id': p.id, 'code': p.code, 'name_ar': p.name_ar}

    @app.get('/api/v1/plans')
    def list_plans(db: Session = Depends(get_vdb),
                   pr: VPrincipal = Depends(require_perm('clients.view',
                                                       'revenue.view'))):
        return [{'code': p.code, 'name_ar': p.name_ar,
                 'billing_period': p.billing_period,
                 'base_price': str(p.base_price),
                 'module_prices': p.module_prices,
                 'included_users': p.included_users,
                 'included_branches': p.included_branches,
                 'extra_user_price': str(p.extra_user_price),
                 'extra_branch_price': str(p.extra_branch_price),
                 'discount_max_pct': str(p.discount_max_pct),
                 'is_active': p.is_active}
                for p in db.execute(select(m.Plan)).scalars().all()]

    @app.post('/api/v1/invoices', status_code=201)
    def create_invoice(body: S.InvoiceIn, request: Request,
                       db: Session = Depends(get_vdb),
                       pr: VPrincipal = Depends(require_perm('invoices.create',
                                                             'invoices.issue'))):
        c = _client_or_404(db, body.client_code)
        p = db.execute(select(m.Plan).where(m.Plan.code == body.plan_code)
                       ).scalar_one_or_none()
        if p is None or not p.is_active:
            vdeny('BILL.PLAN_UNKNOWN', 'خطة غير معروفة أو موقوفة', 404)
        inv = B.create_invoice(db, c, p, period_from=body.period_from,
                               period_to=body.period_to,
                               discount_pct=body.discount_pct, kind=body.kind,
                               notes=body.notes, actor=pr.user,
                               users=body.users, ip=_ip(request))
        db.commit()
        return _inv_out(db, inv)

    def _inv_out(db: Session, inv: m.SubscriptionInvoice) -> dict:
        cols = db.execute(select(m.Collection).where(
            m.Collection.invoice_id == inv.id)
            .order_by(m.Collection.at)).scalars().all()
        paid = B.invoice_paid_total(db, inv.id)
        return {'number': inv.number, 'client_id': inv.client_id,
                'client_code': db.get(m.Client, inv.client_id).code,
                'period_from': str(inv.period_from),
                'period_to': str(inv.period_to),
                'subtotal': str(inv.subtotal),
                'discount_pct': str(inv.discount_pct),
                'discount_amount': str(inv.discount_amount),
                'total': str(inv.total), 'paid': str(paid),
                'status': inv.status, 'kind': inv.kind,
                'issued_at': inv.issued_at.isoformat(),
                'collections': [{'amount': str(x.amount), 'method': x.method,
                                 'reference': x.reference,
                                 'at': x.at.isoformat()} for x in cols]}

    @app.get('/api/v1/invoices')
    def list_invoices(status: str | None = None,
                      db: Session = Depends(get_vdb),
                      pr: VPrincipal = Depends(require_perm('invoices.view',
                                                            'revenue.view'))):
        q = select(m.SubscriptionInvoice).order_by(
            m.SubscriptionInvoice.issued_at.desc())
        if status:
            q = q.where(m.SubscriptionInvoice.status == status)
        return [_inv_out(db, i) for i in db.execute(q).scalars().all()]

    @app.post('/api/v1/collections', status_code=201)
    def add_collection(body: S.CollectionIn, request: Request,
                       db: Session = Depends(get_vdb),
                       pr: VPrincipal = Depends(require_perm(
                           'collections.manage'))):
        inv = db.execute(select(m.SubscriptionInvoice).where(
            m.SubscriptionInvoice.number == body.invoice_number)
            ).scalar_one_or_none()
        if inv is None:
            vdeny('BILL.INVOICE_NOT_FOUND', 'الفاتورة غير موجودة', 404)
        out = B.register_collection(db, inv, amount=body.amount,
                                    method=body.method,
                                    reference=body.reference,
                                    notes=body.notes, actor=pr.user,
                                    ip=_ip(request))
        db.commit()
        return out

    @app.post('/api/v1/billing/run-cycle')
    def run_cycle(db: Session = Depends(get_vdb),
                  pr: VPrincipal = Depends(require_perm('invoices.issue'))):
        out = B.run_billing_cycle(db)
        db.commit()
        return out

    @app.get('/api/v1/revenue')
    def revenue(db: Session = Depends(get_vdb),
                pr: VPrincipal = Depends(require_perm('revenue.view'))):
        return B.revenue_dashboard(db)

    # ═════════ التراخيص (§4 تكامل 07) ═════════
    @app.get('/api/v1/licenses')
    def list_licenses(status: str | None = None,
                      db: Session = Depends(get_vdb),
                      pr: VPrincipal = Depends(require_perm('licenses.view',
                                                            'licenses.issue'))):
        q = select(m.LicenseRecord).order_by(
            m.LicenseRecord.issued_at.desc()).limit(200)
        if status:
            q = select(m.LicenseRecord).where(
                m.LicenseRecord.status == status).order_by(
                m.LicenseRecord.issued_at.desc()).limit(200)
        return [{'id': r.id,
                 'client': db.get(m.Client, r.client_id).code,
                 'license_id': r.license_id, 'serial': r.serial,
                 'kind': r.kind, 'status': r.status,
                 'expires': str(r.expires_at),
                 'over_plan_reason': r.over_plan_reason,
                 'issued_by': r.issued_by,
                 'issued_at': r.issued_at.isoformat(),
                 'approved_by': r.approved_by}
                for r in db.execute(q).scalars().all()]

    @app.post('/api/v1/licenses', status_code=201)
    def issue_license(body: S.LicenseIssueIn, request: Request,
                      db: Session = Depends(get_vdb),
                      pr: VPrincipal = Depends(require_perm('licenses.issue'))):
        c = _client_or_404(db, body.client_code)
        rec = LS.issue_license(db, c, actor=pr.user, kind=body.kind,
                               modules=body.modules,
                               max_users=body.max_users,
                               max_branches=body.max_branches,
                               expires=body.expires, days=body.days,
                               grace_days=body.grace_days,
                               fingerprint=body.fingerprint,
                               features=body.features,
                               support=body.support, ip=_ip(request))
        db.commit()
        return {'id': rec.id, 'license_id': rec.license_id,
                'serial': rec.serial, 'status': rec.status,
                'needs_second_approval': rec.needs_second_approval,
                'over_plan_reason': rec.over_plan_reason,
                'payload': rec.payload_signed}

    @app.post('/api/v1/licenses/{rec_id}/approve')
    def approve_license(rec_id: str, request: Request,
                        db: Session = Depends(get_vdb),
                        pr: VPrincipal = Depends(require_perm('*'))):
        rec = db.get(m.LicenseRecord, rec_id)
        if rec is None:
            vdeny('VND.NOT_FOUND', 'سجل الترخيص غير موجود', 404)
        LS.approve_license(db, rec, approver=pr.user, ip=_ip(request))
        db.commit()
        return {'id': rec.id, 'status': rec.status,
                'approved_by': pr.user.username}

    @app.get('/api/v1/licenses/{rec_id}/file')
    def license_file(rec_id: str, db: Session = Depends(get_vdb),
                     pr: VPrincipal = Depends(require_perm('licenses.view',
                                                           'licenses.issue'))):
        rec = db.get(m.LicenseRecord, rec_id)
        if rec is None:
            vdeny('VND.NOT_FOUND', 'سجل الترخيص غير موجود', 404)
        return rec.payload_signed

    @app.post('/api/v1/revocations', status_code=201)
    def publish_revocations(body: S.RevocationIn, request: Request,
                            db: Session = Depends(get_vdb),
                            pr: VPrincipal = Depends(require_perm(
                                'licenses.revoke'))):
        rec = LS.make_revocation_list(db, actor=pr.user,
                                      entries=body.entries, ip=_ip(request))
        db.commit()
        return {'revocation_serial': rec.revocation_serial,
                'payload': rec.payload}

    @app.get('/api/v1/revocations')
    def list_revocations(db: Session = Depends(get_vdb),
                         pr: VPrincipal = Depends(require_perm(
                             'licenses.view', 'licenses.revoke'))):
        rows = db.execute(select(m.RevocationListRec).order_by(
            m.RevocationListRec.revocation_serial)).scalars().all()
        return [{'revocation_serial': r.revocation_serial,
                 'entries': r.payload.get('entries', []),
                 'issued_at': r.issued_at.isoformat()} for r in rows]

    @app.get('/api/v1/fingerprint-alerts')
    def fp_alerts(db: Session = Depends(get_vdb),
                  pr: VPrincipal = Depends(require_perm('fingerprints.view'))):
        rows = db.execute(select(m.FingerprintAlert).order_by(
            m.FingerprintAlert.at.desc()).limit(100)).scalars().all()
        return [{'hash': a.fingerprint_hash[:16], 'seen_on': a.seen_on,
                 'at': a.at.isoformat(), 'resolved': a.resolved}
                for a in rows]

    # ═════════ التذاكر (§5) ═════════
    def _tkt_out(db: Session, t: m.Ticket) -> dict:
        events = db.execute(select(m.TicketEvent).where(
            m.TicketEvent.ticket_id == t.id)
            .order_by(m.TicketEvent.at)).scalars().all()
        return {'number': t.number,
                'client': db.get(m.Client, t.client_id).code,
                'title': t.title, 'category': t.category,
                'priority': t.priority, 'module': t.module,
                'channel': t.channel, 'status': t.status,
                'assignee': (db.get(m.VendorUser, t.assignee_id).username
                             if t.assignee_id else None),
                'sla_due': t.sla_due.isoformat() if t.sla_due else None,
                'sla_breached': bool(t.sla_due and vnow() > t.sla_due
                                     and t.status != 'CLOSED'),
                'root_cause': t.root_cause, 'kb_article': t.kb_article,
                'created_at': t.created_at.isoformat(),
                'closed_at': t.closed_at.isoformat() if t.closed_at else None,
                'events': [{'action': e.action, 'note': e.note,
                            'at': e.at.isoformat()} for e in events]}

    @app.get('/api/v1/tickets')
    def list_tickets(status: str | None = None, priority: str | None = None,
                     db: Session = Depends(get_vdb),
                     pr: VPrincipal = Depends(require_perm('tickets.view',
                                                           'tickets.work'))):
        q = select(m.Ticket).order_by(m.Ticket.created_at.desc()).limit(200)
        if status:
            q = q.where(m.Ticket.status == status)
        if priority:
            q = q.where(m.Ticket.priority == priority)
        return [_tkt_out(db, t) for t in db.execute(q).scalars().all()]

    @app.post('/api/v1/tickets', status_code=201)
    def create_ticket(body: S.TicketIn, request: Request,
                      db: Session = Depends(get_vdb),
                      pr: VPrincipal = Depends(require_perm('tickets.work',
                                                            'clients.manage'))):
        c = _client_or_404(db, body.client_code)
        t = T.create_ticket(db, c, actor_id=pr.id, title=body.title,
                            category=body.category, priority=body.priority,
                            module=body.module, channel=body.channel,
                            description=body.description,
                            attachments=body.attachments, ip=_ip(request))
        db.commit()
        return _tkt_out(db, t)

    @app.post('/api/v1/tickets/{number}/assign')
    def assign_ticket(number: str, body: S.AssignIn, request: Request,
                      db: Session = Depends(get_vdb),
                      pr: VPrincipal = Depends(require_perm('tickets.work'))):
        t = db.execute(select(m.Ticket).where(m.Ticket.number == number)
                       ).scalar_one_or_none()
        if t is None:
            vdeny('TKT.NOT_FOUND', 'التذكرة غير موجودة', 404)
        target = db.execute(select(m.VendorUser).where(
            m.VendorUser.username == body.username)).scalar_one_or_none()
        if target is None:
            vdeny('TKT.USER_NOT_FOUND', 'المستخدم غير موجود', 404)
        T.assign(db, t, target, actor=pr.user, ip=_ip(request))
        db.commit()
        return _tkt_out(db, t)

    @app.post('/api/v1/tickets/{number}/transition')
    def transition_ticket(number: str, body: S.TicketTransitionIn,
                          request: Request,
                          db: Session = Depends(get_vdb),
                          pr: VPrincipal = Depends(require_perm(
                              'tickets.work'))):
        t = db.execute(select(m.Ticket).where(m.Ticket.number == number)
                       ).scalar_one_or_none()
        if t is None:
            vdeny('TKT.NOT_FOUND', 'التذكرة غير موجودة', 404)
        if body.to_status == 'CLOSED' and not pr.has('tickets.close') \
                and not pr.has('*'):
            vdeny('VND.FORBIDDEN', 'إغلاق التذاكر يتطلب دعم L2 فأعلى', 403)
        T.transition(db, t, body.to_status, actor=pr.user, note=body.note,
                     root_cause=body.root_cause,
                     kb_article=body.kb_article, ip=_ip(request))
        db.commit()
        return _tkt_out(db, t)

    @app.post('/api/v1/tickets/{number}/escalate')
    def escalate_ticket(number: str, request: Request,
                        db: Session = Depends(get_vdb),
                        pr: VPrincipal = Depends(require_perm(
                            'tickets.escalate'))):
        t = db.execute(select(m.Ticket).where(m.Ticket.number == number)
                       ).scalar_one_or_none()
        if t is None:
            vdeny('TKT.NOT_FOUND', 'التذكرة غير موجودة', 404)
        target = T.escalate(db, t, actor=pr.user, ip=_ip(request))
        db.commit()
        return {'escalated_to': target}

    # ═════════ صحة الأسطول والتحديثات (§6) ═════════
    @app.get('/api/v1/health/fleet')
    def fleet(db: Session = Depends(get_vdb),
              pr: VPrincipal = Depends(require_perm('health.view'))):
        return H.fleet_health(db)

    @app.post('/api/v1/releases', status_code=201)
    def create_release(body: S.ReleaseIn, request: Request,
                       db: Session = Depends(get_vdb),
                       pr: VPrincipal = Depends(require_perm('*'))):
        r = m.Release(version=body.version, ring=body.ring,
                      notes=body.notes, released_by=pr.id)
        db.add(r)
        db.flush()
        vaudit(db, actor_id=pr.id, module='releases', action='RELEASE_PUBLISH',
               entity='vendor_releases', entity_id=r.id,
               after={'version': r.version, 'ring': r.ring}, ip=_ip(request))
        db.commit()
        return {'id': r.id, 'version': r.version, 'ring': r.ring}

    @app.get('/api/v1/releases')
    def list_releases(db: Session = Depends(get_vdb),
                      pr: VPrincipal = Depends(require_perm('releases.view',
                                                            '*'))):
        rows = db.execute(select(m.Release).order_by(
            m.Release.released_at.desc())).scalars().all()
        return [{'version': r.version, 'ring': r.ring, 'notes': r.notes,
                 'released_at': r.released_at.isoformat(),
                 'updates': db.execute(select(func.count(
                     m.ClientUpdate.id)).where(
                     m.ClientUpdate.release_id == r.id)).scalar()}
                for r in rows]

    @app.get('/api/v1/notifications')
    def my_notifications(db: Session = Depends(get_vdb),
                         pr: VPrincipal = Depends(get_vprincipal)):
        rows = db.execute(select(m.Notification).where(
            (m.Notification.user_id == pr.id) |
            ((m.Notification.user_id.is_(None)) &
             (m.Notification.role == pr.role)))
            .order_by(m.Notification.delivered_at.desc()).limit(50)
            ).scalars().all()
        return [{'kind': n.kind, 'payload': n.payload, 'state': n.state,
                 'at': n.delivered_at.isoformat()} for n in rows]

    @app.get('/api/v1/audit')
    def audit_feed(module: str | None = None,
                   db: Session = Depends(get_vdb),
                   pr: VPrincipal = Depends(require_perm('*'))):
        q = select(m.VendorAudit).order_by(m.VendorAudit.id.desc()).limit(200)
        if module:
            q = q.where(m.VendorAudit.module == module)
        return [{'id': a.id, 'actor': a.actor_id, 'module': a.module,
                 'action': a.action, 'entity': a.entity,
                 'entity_id': a.entity_id, 'at': a.at.isoformat(),
                 'row_hash': a.row_hash[:16]}
                for a in db.execute(q).scalars().all()]

    # ═════════ واجهة العميل المحدودة (§1) — نبض/ترخيص/تذكرة/تحديث ═════════
    def _edge_auth(db: Session, client_code: str, token: str | None):
        if not token:
            vdeny('EDGE.AUTH', 'ترويسة X-Edge-Token مطلوبة', 401)
        return authenticate_edge(db, client_code, token)

    @app.post('/edge/heartbeat')
    def edge_heartbeat(body: S.HeartbeatIn,
                       x_edge_token: str | None = Header(default=None),
                       db: Session = Depends(get_vdb)):
        c = _edge_auth(db, body.client_code, x_edge_token)
        hb = H.ingest_heartbeat(
            db, c, site_id=body.site_id, product_version=body.product_version,
            outbox_lag=body.outbox_lag, backup_ok=body.backup_ok,
            disk_free_gb=body.disk_free_gb,
            fingerprint_hash=body.fingerprint_hash, payload=body.payload)
        rec = LS.latest_active_license(db, c)
        rev = db.execute(select(func.max(
            m.RevocationListRec.revocation_serial))).scalar()
        db.commit()
        return {'ok': True, 'server_time': vnow().isoformat(),
                'heartbeat_id': hb.id,
                'new_license_available': bool(rec and rec.status == 'ACTIVE'),
                'latest_license_serial': rec.serial if rec else None,
                'revocation_serial': int(rev or 0)}

    @app.get('/edge/license/latest')
    def edge_latest_license(client_code: str,
                            x_edge_token: str | None = Header(default=None),
                            db: Session = Depends(get_vdb)):
        c = _edge_auth(db, client_code, x_edge_token)
        rec = LS.latest_active_license(db, c)
        if rec is None:
            vdeny('EDGE.NO_LICENSE', 'لا ترخيص نشط لهذا العميل', 404)
        return rec.payload_signed

    @app.get('/edge/revocations/latest')
    def edge_latest_revocations(client_code: str,
                                x_edge_token: str | None = Header(
                                    default=None),
                                db: Session = Depends(get_vdb)):
        _edge_auth(db, client_code, x_edge_token)
        rev = db.execute(select(m.RevocationListRec).order_by(
            m.RevocationListRec.revocation_serial.desc()).limit(1)
            ).scalar_one_or_none()
        if rev is None:
            return {'kind': 'REVOCATION_LIST', 'revocation_serial': 0,
                    'entries': []}
        return rev.payload

    @app.post('/edge/tickets', status_code=201)
    def edge_ticket(body: S.EdgeTicketIn,
                    x_edge_token: str | None = Header(default=None),
                    db: Session = Depends(get_vdb)):
        c = _edge_auth(db, body.client_code, x_edge_token)
        t = T.create_ticket(db, c, actor_id='edge-client',
                            title=body.title, category=body.category,
                            priority=body.priority, module=body.module,
                            channel='IN_APP', description=body.description)
        db.commit()
        return {'number': t.number, 'status': t.status,
                'sla_due': t.sla_due.isoformat()}

    @app.get('/edge/releases/latest')
    def edge_latest_release(client_code: str, current_version: str,
                            x_edge_token: str | None = Header(default=None),
                            db: Session = Depends(get_vdb)):
        c = _edge_auth(db, client_code, x_edge_token)
        r = db.execute(select(m.Release).order_by(
            m.Release.released_at.desc()).limit(1)).scalar_one_or_none()
        if r is None or r.version == current_version:
            return {'update_available': False}
        return {'update_available': True, 'version': r.version,
                'ring': r.ring, 'notes': r.notes}

    @app.post('/edge/releases/ack')
    def edge_release_ack(client_code: str, version: str, state: str,
                         error: str = '',
                         x_edge_token: str | None = Header(default=None),
                         db: Session = Depends(get_vdb)):
        c = _edge_auth(db, client_code, x_edge_token)
        r = db.execute(select(m.Release).where(m.Release.version == version)
                       ).scalar_one_or_none()
        if r is None:
            vdeny('EDGE.NO_RELEASE', 'إصدار غير معروف', 404)
        db.add(m.ClientUpdate(release_id=r.id, client_id=c.id,
                              state='SUCCESS' if state == 'SUCCESS'
                              else 'FAILED', error=error))
        db.commit()
        return {'ok': True}

    # ═════════ الإقلاع + الواجهة ═════════
    @app.on_event('startup')
    def _startup():
        VendorBase.metadata.create_all(engine)
        if s.seed_on_startup:
            db = SessionVendor()
            try:
                from .seed import seed_vendor
                seed_vendor(db)
            finally:
                db.close()

    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    if os.path.isdir(static_dir):
        app.mount('/', StaticFiles(directory=static_dir, html=True),
                  name='vendor-spa')
    return app


app = create_vendor_app()
