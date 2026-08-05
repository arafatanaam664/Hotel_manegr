"""الدعم الفني (ملف 08 §5): تذاكر بأولويات وSLA محسوب، سير عمل كامل،
تصعيد L1←L2←هندسة، إشعار مناوب آلي لـP1 خلال 60 ثانية (قبول §8-3)،
وسبب جذري إلزامي لإغلاق الأعطال."""
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m
from .audit import vaudit
from .clock import vnow
from .config import get_vendor_settings
from .security import vdeny

CATEGORIES = ['BUG', 'QUESTION', 'FEATURE', 'TRAINING']
PRIORITIES = ['P1', 'P2', 'P3', 'P4']
FLOW = {  # سير العمل §5: جديدة ← مسندة ← قيد المعالجة ← بانتظار العميل ← محلولة ← مغلقة
    'NEW': ['ASSIGNED', 'CLOSED'],
    'ASSIGNED': ['IN_PROGRESS', 'WAITING_CLIENT', 'RESOLVED'],
    'IN_PROGRESS': ['WAITING_CLIENT', 'RESOLVED'],
    'WAITING_CLIENT': ['IN_PROGRESS', 'RESOLVED'],
    'RESOLVED': ['CLOSED', 'IN_PROGRESS'],
    'CLOSED': [],
}


def _sla_hours(priority: str) -> int:
    s = get_vendor_settings()
    return {'P1': s.sla_hours_p1, 'P2': s.sla_hours_p2,
            'P3': s.sla_hours_p3, 'P4': s.sla_hours_p4}[priority]


def create_ticket(db: Session, client: m.Client, *, actor_id: str,
                  title: str, category: str, priority: str, module: str,
                  channel: str, description: str = '',
                  attachments: list | None = None,
                  ip: str | None = None) -> m.Ticket:
    if category not in CATEGORIES:
        vdeny('TKT.BAD_CATEGORY', f'تصنيف غير معروف: {category}', 400)
    if priority not in PRIORITIES:
        vdeny('TKT.BAD_PRIORITY', f'أولوية غير معروفة: {priority}', 400)
    year = date.today().year
    n = int(db.execute(select(func.count(m.Ticket.id))).scalar() or 0) + 1
    t = m.Ticket(number=f'TKT-{year}-{n:05d}', client_id=client.id,
                 title=title.strip(), description=description,
                 category=category, priority=priority, module=module,
                 channel=channel, status='NEW',
                 sla_due=vnow() + timedelta(hours=_sla_hours(priority)),
                 created_by=actor_id,
                 attachments=attachments or [])
    db.add(t)
    db.flush()
    db.add(m.TicketEvent(ticket_id=t.id, action='CREATE',
                         note=f'{category}/{priority} عبر {channel}',
                         actor_id=actor_id))
    vaudit(db, actor_id=actor_id, module='tickets', action='TICKET_CREATE',
           entity='vendor_tickets', entity_id=t.id,
           after={'number': t.number, 'client': client.code,
                  'priority': priority, 'sla_due': t.sla_due.isoformat()},
           ip=ip)
    # قبول §8-3: P1 حرجة (النظام متوقف) = إشعار مدير المناوبة فوراً
    if priority == 'P1':
        duty = db.execute(select(m.VendorUser).where(
            m.VendorUser.is_active.is_(True),
            (m.VendorUser.duty_manager.is_(True)) |
            (m.VendorUser.role == 'DIRECTOR'))).scalars().all()
        for u in duty:
            db.add(m.Notification(
                user_id=u.id, role=u.role, kind='P1_DUTY_ALERT',
                payload={'ticket': t.number, 'client': client.code,
                         'title': t.title,
                         'alert_at': vnow().isoformat()}))  # delivered_at=vnow
        db.flush()
    return t


def transition(db: Session, ticket: m.Ticket, to: str, *,
               actor: m.VendorUser, note: str = '', root_cause: str = '',
               kb_article: str = '', ip: str | None = None) -> None:
    allowed = FLOW.get(ticket.status, [])
    if to not in allowed:
        vdeny('TKT.BAD_TRANSITION',
              f'انتقال غير مسموح: {ticket.status} → {to}. '
              f'المسموح: {allowed or ["لا شيء — مغلقة"]}', 400)
    if to == 'CLOSED' and ticket.category == 'BUG' and \
            not (root_cause or ticket.root_cause):
        vdeny('TKT.ROOT_CAUSE_REQUIRED',
              'إغلاق عطل يتطلب تصنيف سبب جذري إلزامياً (§5)', 400)
    before = ticket.status
    ticket.status = to
    if root_cause:
        ticket.root_cause = root_cause
    if kb_article:
        ticket.kb_article = kb_article
    if to == 'CLOSED':
        ticket.closed_at = vnow()
    db.flush()
    db.add(m.TicketEvent(ticket_id=ticket.id, action=f'{before}_TO_{to}',
                         note=note, actor_id=actor.id))
    vaudit(db, actor_id=actor.id, module='tickets', action='TICKET_FLOW',
           entity='vendor_tickets', entity_id=ticket.id,
           before={'status': before}, after={'status': to, 'note': note},
           ip=ip)


def assign(db: Session, ticket: m.Ticket, assignee: m.VendorUser, *,
           actor: m.VendorUser, ip: str | None = None) -> None:
    if assignee.role not in ('SUPPORT_L1', 'SUPPORT_L2', 'DIRECTOR'):
        vdeny('TKT.BAD_ASSIGNEE', 'الإسناد لفريق الدعم فقط', 400)
    ticket.assignee_id = assignee.id
    if ticket.status == 'NEW':
        ticket.status = 'ASSIGNED'
    db.flush()
    db.add(m.TicketEvent(ticket_id=ticket.id, action='ASSIGN',
                         note=f'إسناد إلى {assignee.full_name}',
                         actor_id=actor.id))
    vaudit(db, actor_id=actor.id, module='tickets', action='TICKET_ASSIGN',
           entity='vendor_tickets', entity_id=ticket.id,
           after={'assignee': assignee.username}, ip=ip)


def escalate(db: Session, ticket: m.Ticket, *, actor: m.VendorUser,
             note: str = '', ip: str | None = None) -> str:
    """تصعيد §5: L1 ← L2 ← هندسة المنتج."""
    chain = {'SUPPORT_L1': 'SUPPORT_L2', 'SUPPORT_L2': 'ENGINEERING',
             'ENGINEERING': 'ENGINEERING'}
    current = 'ENGINEERING' if any(
        e.action == 'ESCALATE_ENGINEERING' for e in db.execute(
            select(m.TicketEvent).where(
                m.TicketEvent.ticket_id == ticket.id)).scalars().all()
    ) else None
    if current is None:
        lvl2 = any(e.action == 'ESCALATE_L2' for e in db.execute(
            select(m.TicketEvent).where(
                m.TicketEvent.ticket_id == ticket.id)).scalars().all())
        current = 'SUPPORT_L2' if lvl2 else 'SUPPORT_L1'
    target = chain[current]
    db.add(m.TicketEvent(ticket_id=ticket.id,
                         action=f'ESCALATE_{"L2" if target == "SUPPORT_L2" else target}',
                         note=note or f'تصعيد {current} ← {target}',
                         actor_id=actor.id))
    db.flush()
    vaudit(db, actor_id=actor.id, module='tickets', action='TICKET_ESCALATE',
           entity='vendor_tickets', entity_id=ticket.id,
           after={'from': current, 'to': target}, ip=ip)
    return target
