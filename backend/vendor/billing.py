"""الاشتراكات والتحصيل (ملف 08 §3): خطط أسعار، فواتير بتذكير 30/14/7،
تحصيل يدوي موثق ← توليد ترخيص مجدد آلياً ← تحديث الملف مرة واحدة،
ولوحة إيراد Decimal دقيقة بلا انحراف (قبول §8-2)."""
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import licensing_svc as LS
from . import models as m
from .audit import vaudit
from .clock import vnow
from .security import vdeny

Q4 = Decimal('0.0001')


def _q(x: Decimal) -> Decimal:
    return x.quantize(Q4, rounding=ROUND_HALF_UP)


def price_quote(plan: m.Plan, *, modules: list, users: int, branches: int,
                discount_pct: Decimal) -> dict:
    """تسعير Decimal صِرف: أساس + وحدات + إضافات، بخصم ضمن سقف الاعتماد."""
    if Decimal(discount_pct) > plan.discount_max_pct:
        vdeny('BILL.DISCOUNT_OVER_CEILING',
              f'الخصم {discount_pct}% يتجاوز سقف اعتماد الخطة '
              f'({plan.discount_max_pct}%)', 400)
    subtotal = Decimal(plan.base_price)
    for mod in modules:
        subtotal += Decimal(str(plan.module_prices.get(mod, 0)))
    subtotal += max(0, users - plan.included_users) * \
        Decimal(plan.extra_user_price)
    subtotal += max(0, branches - plan.included_branches) * \
        Decimal(plan.extra_branch_price)
    disc = _q(subtotal * Decimal(discount_pct) / Decimal(100))
    total = _q(subtotal - disc)
    periods = Decimal(12) if plan.billing_period == 'YEARLY' else Decimal(1)
    return {'subtotal': _q(subtotal), 'discount_pct': Decimal(discount_pct),
            'discount_amount': disc, 'total': total,
            'monthly_value': _q(total / periods),
            'billing_period': plan.billing_period}


def next_invoice_number(db: Session) -> str:
    year = date.today().year
    n = int(db.execute(select(func.count(m.SubscriptionInvoice.id))).scalar()
            or 0) + 1
    return f'INV-{year}-{n:04d}'


def create_invoice(db: Session, client: m.Client, plan: m.Plan, *,
                   period_from: date, period_to: date,
                   discount_pct: Decimal | str | int = 0,
                   kind: str = 'RENEWAL', notes: str = '',
                   actor: m.VendorUser, users: int = 10,
                   ip: str | None = None) -> m.SubscriptionInvoice:
    quote = price_quote(plan, modules=client.modules, users=users,
                        branches=max(1, client.branches_count),
                        discount_pct=Decimal(str(discount_pct)))
    inv = m.SubscriptionInvoice(
        number=next_invoice_number(db), client_id=client.id, plan_id=plan.id,
        period_from=period_from, period_to=period_to,
        subtotal=quote['subtotal'], discount_pct=quote['discount_pct'],
        discount_amount=quote['discount_amount'], total=quote['total'],
        status='ISSUED', kind=kind, notes=notes, issued_by=actor.id)
    db.add(inv)
    db.flush()
    vaudit(db, actor_id=actor.id, module='billing', action='INVOICE_ISSUE',
           entity='vendor_invoices', entity_id=inv.id,
           after={'number': inv.number, 'client': client.code,
                  'total': str(inv.total), 'kind': kind}, ip=ip)
    return inv


def invoice_paid_total(db: Session, invoice_id: str) -> Decimal:
    return Decimal(str(db.execute(
        select(func.coalesce(func.sum(m.Collection.amount), 0)).where(
            m.Collection.invoice_id == invoice_id)).scalar() or 0))


def register_collection(db: Session, inv: m.SubscriptionInvoice, *,
                        amount: Decimal | str, method: str, reference: str,
                        notes: str, actor: m.VendorUser,
                        ip: str | None = None) -> dict:
    """يدوي موثق (نقد/تحويل)؛ اكتمال السداد ← ترخيص مجدد آلي + تحديث ملف
    العميل مرة واحدة (§3) — قبول §8-1."""
    if inv.status == 'PAID':
        vdeny('BILL.ALREADY_PAID', 'الفاتورة مسددة مسبقاً', 400)
    if not reference.strip():
        vdeny('BILL.NO_REFERENCE',
              'مرجع التحصيل إلزامي (رقم الحوالة/الإيصال) — تحصيل موثق', 400)
    amount = _q(Decimal(str(amount)))
    if amount <= 0:
        vdeny('BILL.BAD_AMOUNT', 'مبلغ التحصيل يجب أن يكون موجباً', 400)
    col = m.Collection(invoice_id=inv.id, amount=amount, method=method,
                       reference=reference, collected_by=actor.id, notes=notes)
    db.add(col)
    db.flush()
    vaudit(db, actor_id=actor.id, module='billing', action='COLLECTION_ADD',
           entity='vendor_collections', entity_id=col.id,
           after={'invoice': inv.number, 'amount': str(amount),
                  'method': method, 'reference': reference}, ip=ip)

    paid = invoice_paid_total(db, inv.id)
    out = {'collection_id': col.id, 'paid_total': str(paid),
           'invoice_total': str(inv.total), 'fully_paid': paid >= inv.total,
           'license': None}
    if paid >= inv.total:
        client = db.get(m.Client, inv.client_id)
        inv.status = 'PAID'
        inv.paid_at = vnow()
        db.flush()
        # تجديد ترخيص آلي ضمن مدة الفاتورة + ضربة ملف واحدة (§3)
        rec = LS.renew_after_collection(db, client, inv, actor_id=actor.id,
                                        ip=ip)
        client.expiry_date = inv.period_to
        client.monthly_value = _q(
            inv.total / (Decimal(12) if _period_yearly(inv) else Decimal(1)))
        _reminders(client)
        if client.status in ('GRACE', 'READ_ONLY', 'TRIAL'):
            set_client_status(db, client, 'ACTIVE',
                              reason=f'تجديد آلي عقب سداد {inv.number}',
                              actor_id=actor.id, ip=ip)
        db.flush()
        out['license'] = {'license_id': rec.license_id,
                          'serial': rec.serial, 'status': rec.status,
                          'expires': str(rec.expires_at)}
    return out


def _period_yearly(inv: m.SubscriptionInvoice) -> bool:
    return (inv.period_to - inv.period_from).days > 200


def _reminders(client: m.Client) -> None:
    if client.expiry_date:
        client.remind_at = [str(client.expiry_date - timedelta(days=d))
                            for d in (30, 14, 7)]


def set_client_status(db: Session, client: m.Client, to: str, *,
                      reason: str, actor_id: str, ip: str | None = None
                      ) -> m.ClientStatusHistory:
    """قبول §8-5: كل تغيير حالة له سبب + مستخدم + طابع — السبب إلزامي."""
    if not reason.strip():
        vdeny('CRM.NO_REASON', 'سبب تغيير الحالة إلزامي — بلا ثغرة واحدة',
              400)
    if to not in m.CLIENT_STATES:
        vdeny('CRM.BAD_STATE', f'حالة غير معروفة: {to}', 400)
    h = m.ClientStatusHistory(client_id=client.id, from_status=client.status,
                              to_status=to, reason=reason.strip(),
                              changed_by=actor_id)
    db.add(h)
    client.status = to
    db.flush()
    vaudit(db, actor_id=actor_id, module='crm', action='CLIENT_STATUS',
           entity='vendor_clients', entity_id=client.id,
           before={'status': h.from_status},
           after={'status': to, 'reason': reason}, ip=ip)
    return h


def create_client(db: Session, *, actor: m.VendorUser, data: dict,
                  ip: str | None = None) -> m.Client:
    n = int(db.execute(select(func.count(m.Client.id))).scalar() or 0) + 1
    c = m.Client(code=data.get('code') or f'CLI-{n:03d}',
                 legal_name=data['legal_name'],
                 trade_name=data.get('trade_name', ''),
                 contacts=data.get('contacts', {}),
                 hotel_name=data.get('hotel_name', ''),
                 rooms_count=int(data.get('rooms_count', 0)),
                 branches_count=int(data.get('branches_count', 1)),
                 sales_channel=data.get('sales_channel', 'DIRECT'),
                 contract_ref=data.get('contract_ref', ''),
                 package=data.get('package', 'LOCAL'),
                 modules=data.get('modules', ['ACCOUNTING']),
                 plan_code=data.get('plan_code', ''),
                 billing_period=data.get('billing_period', 'YEARLY'),
                 tenant_id=data.get('tenant_id', ''),
                 activation_date=data.get('activation_date'),
                 expiry_date=data.get('expiry_date'),
                 grace_days=int(data.get('grace_days', 30)),
                 status=data.get('status', 'TRIAL'),
                 edge_token=__import__('secrets').token_urlsafe(24),
                 notes=data.get('notes', ''))
    _reminders(c)
    db.add(c)
    db.flush()
    hist = m.ClientStatusHistory(client_id=c.id, from_status='',
                                 to_status=c.status,
                                 reason=data.get('open_reason',
                                                 'فتح ملف عميل جديد'),
                                 changed_by=actor.id)
    db.add(hist)
    vaudit(db, actor_id=actor.id, module='crm', action='CLIENT_CREATE',
           entity='vendor_clients', entity_id=c.id,
           after={'code': c.code, 'legal_name': c.legal_name,
                  'package': c.package, 'status': c.status}, ip=ip)
    db.flush()
    return c


def run_billing_cycle(db: Session, *, now: datetime | None = None
                      ) -> dict:
    """قواعد آلية §3: انتهاء بلا سداد ← GRACE ← إشعار + مهمة مبيعات ←
    بعدها READ_ONLY (العميل يتقيد ذاتياً عبر ملف 07 §3)."""
    today = (now or vnow()).date()
    out = {'to_grace': 0, 'to_read_only': 0, 'reminders': 0}
    clients = db.execute(select(m.Client).where(
        m.Client.status.in_(['ACTIVE', 'GRACE', 'TRIAL']))).scalars().all()
    for c in clients:
        if not c.expiry_date:
            continue
        grace_end = c.expiry_date + timedelta(days=c.grace_days)
        if c.status in ('ACTIVE', 'TRIAL') and today > c.expiry_date:
            set_client_status(db, c, 'GRACE',
                              reason='انتهاء الاشتراك بلا سداد — مهلة الترخيص',
                              actor_id='system-billing')
            db.add_all([
                m.Notification(role='SALES', kind='TASK_RENEWAL',
                               payload={'client': c.code,
                                        'expired': str(c.expiry_date)}),
                m.Notification(role='FINANCE', kind='CLIENT_OVERDUE',
                               payload={'client': c.code,
                                        'expired': str(c.expiry_date)})])
            out['to_grace'] += 1
        elif c.status == 'GRACE' and today > grace_end:
            set_client_status(db, c, 'READ_ONLY',
                              reason='انتهاء المهلة بلا سداد — قراءة فقط ذاتية',
                              actor_id='system-billing')
            db.add(m.Notification(role='LIC_OPERATOR',
                                  kind='CLIENT_READ_ONLY',
                                  payload={'client': c.code}))
            out['to_read_only'] += 1
        elif str(today) in (c.remind_at or []):
            db.add(m.Notification(role='SALES', kind='REMINDER_DUE',
                                  payload={'client': c.code,
                                           'expires': str(c.expiry_date)}))
            out['reminders'] += 1
    db.flush()
    return out


def revenue_dashboard(db: Session) -> dict:
    """لوحة الإيراد §3 — قبول §8-2: MRR = مجموع اشتراكات نشطة حسابياً بلا
    انحراف (Decimal حتى العرض)."""
    active_states = ('ACTIVE', 'GRACE')
    clients = db.execute(select(m.Client).where(
        m.Client.status.in_(active_states))).scalars().all()
    mrr = sum((Decimal(c.monthly_value) for c in clients), Decimal(0))
    arr = _q(mrr * 12)

    today = date.today()
    since180 = today - timedelta(days=180)
    expirations = db.execute(select(func.count(m.Client.id)).where(
        m.Client.expiry_date.isnot(None),
        m.Client.expiry_date >= since180,
        m.Client.expiry_date <= today)).scalar() or 0
    renewals = db.execute(select(func.count(m.SubscriptionInvoice.id)).where(
        m.SubscriptionInvoice.status == 'PAID',
        m.SubscriptionInvoice.kind == 'RENEWAL',
        m.SubscriptionInvoice.paid_at >= datetime.combine(
            since180, datetime.min.time()))).scalar() or 0
    renewal_rate = float(Decimal(renewals) / Decimal(expirations)
                         ) if expirations else None

    since90 = today - timedelta(days=90)
    terminated = db.execute(select(func.count(m.Client.id)).where(
        m.Client.status == 'TERMINATED')).scalar() or 0
    base = max(1, len(clients) + terminated)

    overdue_rows = []
    buckets = {'0-30': Decimal(0), '31-60': Decimal(0), '61-90': Decimal(0),
               '+90': Decimal(0)}
    for c in db.execute(select(m.Client).where(
            m.Client.status.in_(['GRACE', 'READ_ONLY']))).scalars().all():
        days = (today - c.expiry_date).days if c.expiry_date else 0
        b = ('0-30' if days <= 30 else '31-60' if days <= 60 else
             '61-90' if days <= 90 else '+90')
        amt = Decimal(c.monthly_value) * 12
        buckets[b] += amt
        overdue_rows.append({'code': c.code, 'legal_name': c.legal_name,
                             'status': c.status, 'days_overdue': days,
                             'bucket': b, 'annual_value': str(amt)})

    pkg: dict[str, int] = {}
    for c in db.execute(select(m.Client).where(
            m.Client.status.in_(active_states))).scalars().all():
        pkg[c.package] = pkg.get(c.package, 0) + 1

    horizon = today + timedelta(days=90)
    issued_unpaid = Decimal(str(db.execute(
        select(func.coalesce(func.sum(m.SubscriptionInvoice.total), 0)).where(
            m.SubscriptionInvoice.status == 'ISSUED')).scalar() or 0))
    expiring = [c for c in clients
                if c.expiry_date and c.expiry_date <= horizon]
    projected = sum((Decimal(c.monthly_value) * 12 if c.billing_period
                     == 'YEARLY' else Decimal(c.monthly_value)
                     for c in expiring), Decimal(0))

    return {
        'mrr': str(_q(mrr)), 'arr': str(arr),
        'active_clients': len(clients),
        'renewal_rate_180d': renewal_rate,
        'renewals_180d': renewals, 'expirations_180d': expirations,
        'churn_90d': round(terminated / base, 4),
        'overdue': {'buckets': {k: str(_q(v)) for k, v in buckets.items()},
                    'rows': overdue_rows},
        'packages': pkg,
        'expected_90d': str(_q(issued_unpaid + projected)),
        'expected_90d_detail': {'issued_unpaid': str(_q(issued_unpaid)),
                                'projected_renewals': str(_q(projected))},
        'mrr_proof': [{'code': c.code, 'monthly_value': str(c.monthly_value)}
                      for c in clients],
    }
