"""محرك المزامنة الهجينة (ملف 09 كاملاً) — اتساق نهائي متعمد، مالية لا
تقبل أرقاماً تقريبية أبداً.

البنية:
- الالتقاط (§2): Outbox داخل قاعدة البيانات **بنفس معاملة العمل** عبر
  أحداث Mapper (اتصال خام — لا حدث بلا قيد ولا قيد بلا حدث)، ولا حذف
  قبل ACK، وseq = معرف الإدراج (ترتيب كامل لكل موقع بنيوياً).
- النقل (§2): دفعات ≤500 حدث موقَّعة Ed25519 بمفتاح الموقع عبر HTTPS،
  استئناف من آخر ACK؛ Inbox خام فريد (site,seq) فإعادة الإرسال آمنة 100%.
- لا فقدان (§2): فجوات التسلسل تُعلَّم وتُستدرك آلياً بإعادة الإرسال من
  Outbox المؤرشف + فاحص Anti-Entropy (مقارنة عدادات لكل كيان).
- التعارض (§4): مالية Append-Only = لا تعارض بنيوياً؛ الماسترات LWW
  بنسخة لكل كيان، والنسخة المجهولة/المتباعدة ← صندوق تعارض بقرار بشري.
- Reseed (§6): إعادة بناء المستلم من Inbox المؤرشف كاملاً في أي وقت.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable

import contextvars

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key, load_pem_public_key)
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from . import models as m
from .audit import audit
from .security import utcnow

# قمع الالتقاط عند تطبيق أحداث واردة (لا حلقات مزامنة §1)
_capture_suppressed: contextvars.ContextVar[bool] = contextvars.ContextVar(
    'sync_capture_suppressed', default=False)

BATCH_MAX = 500                      # §2: دفعة ≤ 500 حدث
SYNC_SCHEMA = '1'                    # §6: تعايش N و N-1، بلا إسقاط صامت
SUPPORTED_SCHEMAS = {'1'}

# نوع البيانات ← مالكها (09 §1) — ماليوها أحادية الاتجاه محلي→سحابة
ENTITY_APPEND = 'APPEND'             # لا تعارض ممكناً بنيوياً (مالي)
ENTITY_MASTER = 'MASTER'             # ثنائي بحوكمة LWW (§4)


def _jlines_payload(obj: m.JournalEntry, db: Session) -> dict:
    lines = db.execute(select(m.JournalLine).where(
        m.JournalLine.entry_id == obj.id)
        .order_by(m.JournalLine.line_no)).scalars().all()
    return {
        'id': obj.id, 'tenant_id': obj.tenant_id, 'branch_id': obj.branch_id,
        'journal_type': obj.journal_type, 'entry_no': obj.entry_no,
        'entry_date': str(obj.entry_date),
        'posting_date': str(obj.posting_date or ''),
        'period_id': obj.period_id, 'currency_code': obj.currency_code,
        'status': obj.status, 'narration': obj.narration,
        'reference': obj.reference, 'source_type': obj.source_type,
        'source_id': obj.source_id, 'event_key': obj.event_key,
        'reversed_entry_id': obj.reversed_entry_id,
        'created_by': obj.created_by,
        'lines': [{'line_no': l.line_no, 'account_id': l.account_id,
                   'debit_base': str(l.debit_base),
                   'credit_base': str(l.credit_base),
                   'currency_code': l.currency_code,
                   'debit_fcy': str(l.debit_fcy),
                   'credit_fcy': str(l.credit_fcy),
                   'fx_rate': str(l.fx_rate) if l.fx_rate else None,
                   'party_type': l.party_type, 'party_id': l.party_id,
                   'cost_center_id': l.cost_center_id,
                   'description': l.description} for l in lines]}


def _jsonable(v: Any) -> Any:
    """تحويل أي قيمة لصيغة JSON آمنة — Decimal نصاً حفاظاً على الدقة (ملف 15)."""
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def _master_payload(obj, fields: list[str]) -> dict:
    out = {}
    for f in fields:
        out[f] = _jsonable(getattr(obj, f, None))
    out['id'] = obj.id
    out['tenant_id'] = obj.tenant_id
    return out


# سجل الكيانات المزامَنة: اسم ← (الصنف، النوع، باني الحمولة/الحقول)
ROOM_FIELDS = ['branch_id', 'room_no', 'floor', 'room_type_id', 'features',
               'hk_status', 'ooo_reason', 'ooo_from', 'ooo_to', 'kind',
               'parent_room_id', 'is_active']
ITEM_FIELDS = ['code', 'name_ar', 'name_en', 'category_id', 'base_unit',
               'alt_units', 'barcode', 'reorder_level', 'safety_level',
               'inventory_account_code', 'track_expiry', 'pos_item_id',
               'is_active']
SYNC_REGISTRY: dict[str, dict] = {
    'JOURNAL': {'cls': m.JournalEntry, 'kind': ENTITY_APPEND},
    'ROOM': {'cls': m.Room, 'kind': ENTITY_MASTER, 'fields': ROOM_FIELDS},
    'INV_ITEM': {'cls': m.InvItem, 'kind': ENTITY_MASTER,
                 'fields': ITEM_FIELDS},
}
_CLS_TO_ENTITY = {v['cls']: k for k, v in SYNC_REGISTRY.items()}

_registered = False


# ═══ الالتقاط (§2) — داخل معاملة العمل نفسها ═══
def register_capture() -> None:
    """يربط أحداث Mapper مرة واحدة — الاتصال الخام يبقي الحدث والقيد
    ذرّيين حتى لو رُفضت المعاملة لاحقاً (الاثنان يُدحرجان معاً)."""
    global _registered
    if _registered:
        return
    _registered = True

    def _capture(connection, entity_name, entity_id, tenant_id, op):
        if _capture_suppressed.get():
            return
        site = _site_row_by_conn(connection)
        prev = connection.execute(
            m.SyncEventOut.__table__.select().where(
                m.SyncEventOut.__table__.c.tenant_id == tenant_id,
                m.SyncEventOut.__table__.c.entity == entity_name,
                m.SyncEventOut.__table__.c.entity_id == entity_id)
            .order_by(m.SyncEventOut.__table__.c.id.desc()).limit(1)
        ).first()
        version = int(prev.entity_version) + (0 if op == 'INSERT' else 1) \
            if prev else 1
        res = connection.execute(
            m.SyncEventOut.__table__.insert().values(
                site_id=site.site_id if site else '', tenant_id=tenant_id,
                entity=entity_name, entity_id=entity_id, op=op,
                entity_version=version, payload={}, state='PENDING',
                occurred_at=utcnow()))
        seq = res.lastrowid
        connection.execute(
            m.SyncEventOut.__table__.update()
            .where(m.SyncEventOut.__table__.c.id == seq)
            .values(seq=seq))

    for cls, name in _CLS_TO_ENTITY.items():
        if name == 'JOURNAL':
            continue  # قيود: مرحَّلة فقط في رحلة المستخدم — تُلتقط عند الترحيل
        event.listen(cls, 'after_insert',
                     lambda mapper, conn, target, _n=name: _capture(
                         conn, _n, target.id, target.tenant_id, 'INSERT'))
        event.listen(cls, 'after_update',
                     lambda mapper, conn, target, _n=name: _capture(
                         conn, _n, target.id, target.tenant_id, 'UPDATE'))
        event.listen(cls, 'after_delete',
                     lambda mapper, conn, target, _n=name: _capture(
                         conn, _n, target.id, target.tenant_id, 'DELETE'))


def capture_journal_posting(db: Session, entry: m.JournalEntry) -> None:
    """التقاط مخصص للقيود المرحَّلة (مالك محلي، Append-Only §1):
    يُستدعى من محرك الترحيل في المعاملة ذاتها — لا عرض بدون قيد."""
    site = _get_site(db)
    db.flush()
    prev = db.execute(select(m.SyncEventOut).where(
        m.SyncEventOut.tenant_id == entry.tenant_id,
        m.SyncEventOut.entity == 'JOURNAL',
        m.SyncEventOut.entity_id == entry.id)
        .order_by(m.SyncEventOut.id.desc()).limit(1)).first()
    version = int(prev.entity_version or 1) if prev else 1
    row = m.SyncEventOut(
        site_id=site.site_id if site else '', tenant_id=entry.tenant_id,
        entity='JOURNAL', entity_id=entry.id, op='INSERT',
        entity_version=version,
        payload=_jlines_payload(entry, db), state='PENDING',
        occurred_at=utcnow())
    db.add(row)
    db.flush()
    row.seq = row.id
    db.flush()


def backfill_outbox(db: Session, tenant_id: str,
                    site: m.SyncSite | None = None) -> dict:
    """الرفع الأولي بعد الاقتران: كل ما وُجد قبل تفعيل المزامنة يصبح حدثاً
    (قيود مرحَّلة + ماسترات) — مرة واحدة لكل سجل، ذرّياً مع طلب المشغّل."""
    site = site or _get_site(db)
    sid = site.site_id if site else ''
    made = {'JOURNAL': 0}

    def _has(entity: str, entity_id: str) -> bool:
        return db.execute(select(m.SyncEventOut.id).where(
            m.SyncEventOut.entity == entity,
            m.SyncEventOut.entity_id == entity_id).limit(1)).first() is not None

    def _emit(entity: str, entity_id: str, payload: dict) -> None:
        row = m.SyncEventOut(site_id=sid, tenant_id=tenant_id,
                             entity=entity, entity_id=entity_id, op='INSERT',
                             entity_version=1, payload=payload,
                             state='PENDING', occurred_at=utcnow())
        db.add(row)
        db.flush()
        row.seq = row.id
        made.setdefault(entity, 0)
        made[entity] += 1

    entries = db.execute(select(m.JournalEntry).where(
        m.JournalEntry.tenant_id == tenant_id,
        m.JournalEntry.status == 'POSTED')
        .order_by(m.JournalEntry.entry_date,
                  m.JournalEntry.id)).scalars().all()
    for e in entries:
        if not _has('JOURNAL', e.id):
            _emit('JOURNAL', e.id, _jlines_payload(e, db))
    for name, spec in SYNC_REGISTRY.items():
        if name == 'JOURNAL':
            continue
        cls = spec['cls']
        objs = db.execute(select(cls).where(
            cls.tenant_id == tenant_id)).scalars().all()
        if name == 'ROOM':
            # الأجنحة المركبة (ADR-0035): الآباء قبل الأبناء — فكرة FK
            # على المستلم تفترض أسبقية الأب بنفس الدفعة.
            objs = sorted(objs, key=lambda o: 1
                          if getattr(o, 'parent_room_id', None) else 0)
        for o in objs:
            if not _has(name, o.id):
                _emit(name, o.id, {})
    db.flush()
    return {'created': made, 'total': sum(made.values())}


def _site_row_by_conn(connection) -> m.SyncSite | None:
    return connection.execute(
        m.SyncSite.__table__.select().limit(1)).first()


def _get_site(db: Session) -> m.SyncSite | None:
    return db.execute(select(m.SyncSite).limit(1)).scalar_one_or_none()


def ensure_site(db: Session, tenant_id: str | None = None) -> m.SyncSite:
    """هوية الموقع + زوج مفاتيح التوقيع (يولَّد محلياً أول مرة §5)."""
    site = _get_site(db)
    if site is None:
        k = Ed25519PrivateKey.generate()
        site = m.SyncSite(
            tenant_id=tenant_id or '',
            private_key_pem=k.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()).decode(),
            public_key_pem=k.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo).decode())
        db.add(site)
        db.flush()
    return site


# ═══ فيض الدفعة وتوقيعها ═══
def _canon(d: dict) -> bytes:
    return json.dumps(d, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), default=str).encode('utf-8')


# حقول المغلَّف المتقلبة لا تدخل بالتوقيع: التوقيع يحمي جسم الأحداث (§5)،
# ورقم المخطط وسم مصافحة يُفرض صراحة بفحص SUPPORTED_SCHEMAS لا بالتوقيع —
# وإلا تعذّرت ترقية المخطط لاحقاً (حزمة معلَّقة تُقبل بعد الترقية).
UNSIGNED_ENVELOPE_KEYS = {'signature', 'sync_schema'}


def _signed_body(batch: dict) -> bytes:
    return _canon({k: v for k, v in batch.items()
                   if k not in UNSIGNED_ENVELOPE_KEYS})


def build_payloads(db: Session, events: list[m.SyncEventOut],
                   lean: bool) -> None:
    """حمولة كسولة عند الإرسال: JOURNAL خُزّنت عند الالتقاط (صندوقية)،
    الماسترات تُقرأ من الصف الحالي (الأحدث — تجميع LWW طبيعي للتيار)."""
    for ev in events:
        if ev.entity == 'JOURNAL' or ev.payload:
            continue
        spec = SYNC_REGISTRY[ev.entity]
        obj = db.get(spec['cls'], ev.entity_id)
        if obj is None:
            ev.payload = {'deleted': True, 'id': ev.entity_id,
                          'tenant_id': ev.tenant_id}
            ev.op = 'DELETE' if ev.op != 'INSERT' else ev.op
        else:
            ev.payload = _master_payload(obj, spec['fields'])
        if lean:
            ev.payload.pop('features', None)     # وضع التقشير (§3)
            ev.payload.pop('alt_units', None)
    db.flush()


def make_batch(db: Session, site: m.SyncSite, events: list[m.SyncEventOut]
               ) -> dict:
    batch = {'sync_schema': SYNC_SCHEMA, 'site_id': site.site_id,
             'tenant_id': events[0].tenant_id if events else '',
             'from_seq': events[0].seq, 'to_seq': events[-1].seq,
             'events': [{'seq': e.seq, 'entity': e.entity,
                         'entity_id': e.entity_id, 'op': e.op,
                         'version': e.entity_version, 'payload': e.payload,
                         'occurred_at': e.occurred_at.isoformat()
                         if e.occurred_at else ''} for e in events]}
    priv = load_pem_private_key(site.private_key_pem.encode(), password=None)
    batch['signature'] = base64.b64encode(
        priv.sign(_signed_body(batch))).decode('ascii')
    return batch


def verify_batch_signature(batch: dict, public_pem: str) -> bool:
    try:
        pub = load_pem_public_key(public_pem.encode())
        pub.verify(base64.b64decode(batch['signature']),
                   _signed_body(batch))
        return True
    except Exception:
        return False


# ═══ دورة الدفع (§3) — Backoff أسّي مع Jitter، العمل المحلي لا يتأثر ═══
SendFn = Callable[[str, dict, str], dict]   # (cloud_url, batch, token) → reply


def http_send(cloud_url: str, batch: dict, token: str) -> dict:  # افتراضي §2
    import urllib.request
    req = urllib.request.Request(
        cloud_url.rstrip('/') + '/api/sync/receive',
        data=json.dumps(batch).encode('utf-8'),
        headers={'Content-Type': 'application/json',
                 'X-Site-Token': token}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as r:   # TLS بالنشر
        return json.loads(r.read().decode('utf-8'))


def push_cycle(db: Session, *, send_fn: SendFn | None = None,
               mark_sent: bool = True) -> dict:
    """دفعة واحدة ≤500: يبني، يوقّع، يرسل، ويؤكد الـACK فقط — فشل النقل
    يترك كل شيء PENDING فلا فقدان ولا ازدواج بنيوياً (قبول §7-1)."""
    site = _get_site(db)
    if site is None or not site.cloud_url:
        return {'pushed': 0, 'reason': 'no-pairing'}
    events = db.execute(select(m.SyncEventOut).where(
        m.SyncEventOut.state.in_(['PENDING', 'SENT']))
        .order_by(m.SyncEventOut.seq).limit(BATCH_MAX)).scalars().all()
    if not events:
        return {'pushed': 0, 'reason': 'empty'}
    build_payloads(db, events, site.lean_mode)
    batch = make_batch(db, site, events)
    try:
        reply = (send_fn or http_send)(site.cloud_url, batch, site.site_token)
    except Exception as e:                          # شبكة/طاقة — تراكم فقط
        site.last_error = f'{type(e).__name__}: {e}'[:400]
        site.last_push_at = utcnow()
        db.flush()
        return {'pushed': 0, 'error': site.last_error,
                'pending': len(events)}
    site.last_push_at = utcnow()
    ack_seq = int(reply.get('ack_seq', 0))
    site.last_ack_seq = max(site.last_ack_seq, ack_seq)
    site.last_gaps = reply.get('gaps', [])
    site.last_error = reply.get('schema_note', '')
    now = utcnow()
    site.last_success_at = now
    for e in events:
        if e.seq <= ack_seq:
            e.state = 'ACKED'
            e.acked_at = now
        elif mark_sent:
            e.state = 'SENT'          # سلّمت للنقل لكن لم تُطبَّق بعد §2
    db.flush()
    return {'pushed': sum(1 for e in events if e.seq <= ack_seq),
            'ack_seq': ack_seq, 'gaps': site.last_gaps,
            'held': reply.get('held', 0), 'sent': len(events)}


# ═══ الاستقبال والتطبيق (سحابة) ═══
def receive_batch(db: Session, reg: m.SyncSiteReg, batch: dict) -> dict:
    """Inbox خام فريد ← معالج مرتَّب ← ACK متصل فقط. فريد (site,seq)
    يجعل إعادة الإرسال آمنة؛ HELD_GAP/HELD_SCHEMA بلا إسقاط صامت أبداً."""
    if batch.get('sync_schema') not in SUPPORTED_SCHEMAS:
        # §6: أحداث بمخطط أحدث تُحجَر كلها حتى ترقية المستلم
        held = _store_inbox(db, reg, batch, state='HELD_SCHEMA')
        _audit_sync(db, batch['tenant_id'], 'SYNC_HELD_SCHEMA',
                    {'schema': batch.get('sync_schema'), 'held': held})
        return {'ack_seq': reg.last_ack_seq, 'held': held,
                'schema_note': f'مخطط {batch.get("sync_schema")} أحدث من '
                f'المدعوم — محجوز حتى ترقية السحابة (لا إسقاط)'}
    if not verify_batch_signature(batch, reg.public_key_pem):
        db.rollback()
        raise ValueError('SYNC.BAD_SIGNATURE')
    # مخطط مدعوم الآن: حرّر المحجوز سابقاً بسبب المخطط (§6 لا إسقاط صامت)
    db.execute(m.SyncEventIn.__table__.update().where(
        m.SyncEventIn.site_id == reg.site_id,
        m.SyncEventIn.state == 'HELD_SCHEMA').values(state='RECEIVED'))
    db.flush()
    tok = _capture_suppressed.set(True)
    try:
        _store_inbox(db, reg, batch)
        ack, gaps, held = _apply_contiguous(db, reg)
    finally:
        _capture_suppressed.reset(tok)
    reg.last_ack_seq = max(reg.last_ack_seq, ack)
    db.flush()
    _audit_sync(db, batch['tenant_id'], 'SYNC_BATCH_APPLIED',
                {'site': batch['site_id'], 'to_seq': batch['to_seq'],
                 'ack': ack, 'gaps': gaps, 'held': held})
    return {'ack_seq': reg.last_ack_seq, 'gaps': gaps, 'held': held}


def _store_inbox(db: Session, reg: m.SyncSiteReg, batch: dict,
                 state: str = 'RECEIVED') -> int:
    n = 0
    now = utcnow()
    for ev in batch.get('events', []):
        exists = db.execute(select(m.SyncEventIn).where(
            m.SyncEventIn.site_id == reg.site_id,
            m.SyncEventIn.seq == ev['seq'])).scalar_one_or_none()
        if exists:                      # إعادة إرسال — لا تكرار إطلاقاً
            if exists.state in ('LOST_SIM', 'FAILED'):
                # فقدان محاكى أو فشل تطبيق عابر: عبّئ وأعد المحاولة —
                # لا حفرة صامتة أبداً؛ الثابت عَرضي يظهر كفجوة بلا نهاية
                # مقصودة تُضبط بالمراقبة أو Reseed (§7-1/§7-5).
                exists.state = 'RECEIVED'
                exists.payload = ev.get('payload') or {}
                exists.error = None
            continue
        db.add(m.SyncEventIn(
            site_id=reg.site_id, seq=ev['seq'], tenant_id=batch['tenant_id'],
            entity=ev['entity'], entity_id=ev['entity_id'], op=ev['op'],
            entity_version=ev.get('version', 1),
            payload=ev.get('payload') or {},
            occurred_at=ev.get('occurred_at', ''),
            received_at=now, state=state))
        n += 1
    db.flush()
    return n


def _apply_contiguous(db: Session, reg: m.SyncSiteReg
                      ) -> tuple[int, list, int]:
    """يطبّق بالترتيب حتى أول فجوة؛ ما بعدها ينتظر الاستدراك (قبول §7-1:
    فجوة واحدة كحد أقصى تُكتشف وتُستدرك آلياً)."""
    gaps, held = [], 0
    ack = int(reg.last_ack_seq or 0)
    rows = db.execute(select(m.SyncEventIn).where(
        m.SyncEventIn.site_id == reg.site_id,
        m.SyncEventIn.seq > ack,
        m.SyncEventIn.state.in_(['RECEIVED', 'REPLAYED']))
        .order_by(m.SyncEventIn.seq)).scalars().all()
    expected = ack + 1
    for idx, row in enumerate(rows):
        if row.seq > expected:
            gaps.append({'from': expected, 'to': row.seq - 1})
            held += max(0, len(rows) - idx)
            break
        try:
            with db.begin_nested():          # SAVEPOINT: عزلة صف بلا كسر الجلسة
                _apply_event(db, reg, row)
            row.state = 'APPLIED'
            row.applied_at = utcnow()
        except SimulatedLost:
            row.state = 'LOST_SIM'
            row.error = 'محاكاة فقدان حزمة (قبول §7-1)'
            held += _breach_gap(rows, idx, expected, gaps)
            break
        except Exception as e:
            row.state = 'FAILED'
            row.error = f'{type(e).__name__}: {e}'[:380]
            held += _breach_gap(rows, idx, expected, gaps)
            break
        expected = row.seq + 1
        ack = row.seq
        db.flush()
    return ack, gaps, held


def _breach_gap(rows: list, idx: int, expected: int, gaps: list) -> int:
    """كسر التسلسل (فقدان/فشل) عند الصف idx: الفجوة تُبلَّغ فوراً —
    من التسلسل المنتظر حتى آخر صف موجود قبل أول صف لاحق (لا إسقاط صامت)."""
    rest = rows[idx + 1:]
    gaps.append({'from': expected,
                 'to': (rest[0].seq - 1) if rest else expected})
    return len(rest)


class SimulatedLost(Exception):
    """حقن فوضى اختبارية فقط (09 §7-1) — غير مستخدمة بالإنتاج."""


# محاكي الفوضى: seqs يُسقطها المستلم عمداً (فقدان حزمة/قرص)
CHAOS_DROP: set[int] = set()


def _apply_event(db: Session, reg: m.SyncSiteReg, row: m.SyncEventIn) -> None:
    if row.seq in CHAOS_DROP:
        CHAOS_DROP.discard(row.seq)
        raise SimulatedLost()
    if row.entity == 'JOURNAL':
        _apply_journal(db, row)
    elif row.entity == 'ROOM':
        _apply_master(db, row, spec_of='ROOM')
    elif row.entity == 'INV_ITEM':
        _apply_master(db, row, spec_of='INV_ITEM')
    else:
        raise ValueError(f'SYNC.UNKNOWN_ENTITY:{row.entity}')


def _apply_journal(db: Session, row: m.SyncEventIn) -> None:
    """مالي Append-Only — أي «تعارض ظاهر» = عيب مزامنة يحقق بالتدقيق (§4)."""
    p = row.payload
    exists = db.get(m.JournalEntry, p['id'])
    if exists:
        if exists.status == 'DRAFT' and p['status'] == 'POSTED':
            exists.status = 'POSTED'
            exists.posting_date = _dt(p.get('posting_date'))
            db.flush()
            return
        return                             # مكرر أو انتقال غير مشروع: تجاهل
    db.add(m.JournalEntry(
        id=p['id'], tenant_id=reg_tenant(row), branch_id=p['branch_id'],
        journal_type=p['journal_type'], entry_no=p['entry_no'],
        entry_date=date.fromisoformat(p['entry_date'][:10]),
        posting_date=_dt(p.get('posting_date')), period_id=p['period_id'],
        currency_code=p.get('currency_code', 'YER'), status=p['status'],
        narration=p.get('narration', ''), reference=p.get('reference'),
        source_type=p.get('source_type'), source_id=p.get('source_id'),
        event_key=p.get('event_key'), created_by=p.get('created_by', 'sync'),
        posted_by=p.get('created_by', 'sync'), created_at=utcnow(),
        posted_at=_dt(p.get('posting_date')),
        reversed_entry_id=p.get('reversed_entry_id')))
    db.flush()
    for i, l in enumerate(p.get('lines', [])):
        db.add(m.JournalLine(
            id=f"{p['id']}:L{i}", entry_id=p['id'], account_id=l['account_id'],
            tenant_id=reg_tenant(row),
            line_no=l.get('line_no', i + 1),
            debit_base=l.get('debit_base', '0'),
            credit_base=l.get('credit_base', '0'),
            currency_code=l.get('currency_code'),
            debit_fcy=l.get('debit_fcy', '0'),
            credit_fcy=l.get('credit_fcy', '0'), fx_rate=l.get('fx_rate'),
            party_type=l.get('party_type'), party_id=l.get('party_id'),
            cost_center_id=l.get('cost_center_id'),
            description=l.get('description', '')))
    db.flush()


def _apply_master(db: Session, row: m.SyncEventIn, *, spec_of: str) -> None:
    """ماسترات ثنائية §4: LWW بنسخة؛ tombstone (أحدث) يهزم التعديل؛
    النسخة المجهولة/المتباعدة ← صندوق تعارض لقرار بشري (لا حسم صامتاً)."""
    spec = SYNC_REGISTRY[spec_of]
    cls = spec['cls']
    p = row.payload
    obj = db.get(cls, row.entity_id)
    ver = db.get(m.SyncEntityVersion, (row.site_id, spec_of, row.entity_id))
    if ver is None:
        ver = m.SyncEntityVersion(site_id=row.site_id, entity=spec_of,
                                  entity_id=row.entity_id, last_version=0)
        db.add(ver)
        db.flush()
    is_tomb = row.op == 'DELETE' or p.get('deleted') or p.get('is_active') is False
    if obj is None:
        if is_tomb:
            return                         # حذف لم يصلنا أصله — لا شيء
        values = {f: _coerce(cls, f, p.get(f)) for f in spec['fields']
                  if f in p}
        if 'created_at' in cls.__table__.columns and \
                values.get('created_at') is None:
            values['created_at'] = utcnow()   # حقول نظام إلزامية لا تُزامَن
        obj = cls(id=row.entity_id, tenant_id=reg_tenant(row), **values)
        db.add(obj)
        db.flush()
        ver.last_version = row.entity_version
        ver.last_op = row.op
        ver.updated_at = utcnow()
        return
    # موجود: قارن النسخ
    if row.entity_version < ver.last_version:
        return                             # حدث قديم وصل متأخراً — تجاهل
    if row.entity_version == ver.last_version:
        # إعادة إرسال آمنة: حمولة مطابقة للواقع = مكرر صامت؛ غير ذلك تعارض
        changed = {f: p[f] for f in spec['fields']
                   if f in p and _jsonable(getattr(obj, f, None)) != p[f]}
        current_op = 'DELETE' if (not obj.is_active) else ver.last_op
        if changed or (row.op != 'DELETE' and current_op == 'DELETE'):
            _conflict(db, spec_of, row, obj,
                      'نفس النسخة بحمولة مختلفة — النسخة الأم مجهولة')
        return
    if is_tomb:
        if ver.last_op == 'DELETE':
            return
        # Tombstone أحدث يهزم التعديل (تشغيلي فقط — المالي لا يحذف §4)
        obj.is_active = False
        db.flush()
        ver.last_version = row.entity_version
        ver.last_op = 'DELETE'
        ver.updated_at = utcnow()
        return
    changed = {}
    for f in spec['fields']:
        if f in p and _jsonable(getattr(obj, f, None)) != p[f]:
            changed[f] = p[f]
    if not changed:
        ver.last_version = row.entity_version
        ver.last_op = row.op
        return
    for f, v in changed.items():
        setattr(obj, f, _coerce(cls, f, v))
    db.flush()
    ver.last_version = row.entity_version
    ver.last_op = row.op
    ver.updated_at = utcnow()


def _conflict(db: Session, entity: str, row: m.SyncEventIn, obj,
              reason: str) -> None:
    local = _master_payload(obj, SYNC_REGISTRY[entity]['fields'])
    db.add(m.SyncConflict(entity=entity, entity_id=row.entity_id,
                          local_val=local, remote_val=row.payload,
                          reason=reason))
    db.flush()


def _coerce(cls, field: str, value):
    """إعادة قيمة JSON إلى نوع عمود النموذج (Decimal نصاً ← Numeric…)."""
    if value is None:
        return None
    col = cls.__table__.columns.get(field)
    if col is None:
        return value
    try:
        py = col.type.python_type
    except NotImplementedError:
        return value
    if py is Decimal and not isinstance(value, Decimal):
        return Decimal(str(value))
    if py is datetime and isinstance(value, str):
        return datetime.fromisoformat(value)
    if py is date and isinstance(value, str):
        return date.fromisoformat(value[:10])
    return value


def reg_tenant(row: m.SyncEventIn) -> str:
    return row.tenant_id


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.replace('Z', '+00:00')
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _audit_sync(db: Session, tenant_id: str, action: str, after: dict) -> None:
    try:
        audit(db, tenant_id=tenant_id or 'sync', actor_id=None,
              actor_type='system', module='sync', action=action,
              entity='sync', after=after)
    except Exception:
        pass


# ═══ Anti-Entropy (§2) + مقارنة العدادات ═══
def cloud_counts(db: Session, site_id: str) -> dict:
    """عدادات مطبَّقة لكل كيان لموقع — يقارنها الطرف الآخر ويستدرك."""
    rows = db.execute(select(m.SyncEventIn.entity,
                             func.count(m.SyncEventIn.id))
                      .where(m.SyncEventIn.site_id == site_id,
                             m.SyncEventIn.state == 'APPLIED')
                      .group_by(m.SyncEventIn.entity)).all()
    return {e: c for e, c in rows}


def local_counts(db: Session, tenant_id: str) -> dict:
    rows = db.execute(select(m.SyncEventOut.entity,
                             func.count(m.SyncEventOut.id))
                      .where(m.SyncEventOut.tenant_id == tenant_id,
                             m.SyncEventOut.state == 'ACKED')
                      .group_by(m.SyncEventOut.entity)).all()
    return {e: c for e, c in rows}


def entropy_findings(db: Session, tenant_id: str,
                     fetch_counts: Callable[[], dict]) -> dict:
    """فاحص دوري: اختلاف عدادات = استدراك تلقائي بدفع المدى الناقص."""
    remote = fetch_counts()
    local = local_counts(db, tenant_id)
    diffs = {}
    for ent in set(local) | set(remote):
        if int(local.get(ent, 0)) != int(remote.get(ent, 0)):
            diffs[ent] = {'local_acked': int(local.get(ent, 0)),
                          'remote_applied': int(remote.get(ent, 0))}
    return {'match': not diffs, 'diffs': diffs,
            'action': 'ستُستدرك تلقائياً بدورة دفع إضافية من المؤرشف'
            if diffs else 'لا شيء'}


# ═══ Reseed (§6) — إعادة بناء كاملة من المؤرشف ═══
def reseed_receiver(db: Session, reg: m.SyncSiteReg) -> dict:
    """تلفت النسخة السحابية؟ أعد التشغيل من Outbox/Inbox المؤرشف — قبول §7-5
    (مطابقة 100% على الجداول الحرجة بعد إعادة البناء)."""
    tok = _capture_suppressed.set(True)
    try:
        tid = reg.tenant_id
        db.execute(m.JournalLine.__table__.delete().where(
            m.JournalLine.__table__.c.entry_id.in_(
                select(m.JournalEntry.id).where(
                    m.JournalEntry.tenant_id == tid))))
        db.execute(m.JournalEntry.__table__.delete().where(
            m.JournalEntry.tenant_id == tid))
        for spec in ('ROOM', 'INV_ITEM'):
            cls = SYNC_REGISTRY[spec]['cls']
            db.execute(cls.__table__.delete().where(cls.tenant_id == tid))
        db.execute(m.SyncEntityVersion.__table__.delete().where(
            m.SyncEntityVersion.site_id == reg.site_id))
        db.flush()
        reg.last_ack_seq = 0
        rows = db.execute(select(m.SyncEventIn).where(
            m.SyncEventIn.site_id == reg.site_id,
            m.SyncEventIn.state.in_(['APPLIED', 'RECEIVED', 'REPLAYED',
                                     'FAILED']))
            .order_by(m.SyncEventIn.seq)).scalars().all()
        rebuilt = 0
        for row in rows:
            try:
                with db.begin_nested():
                    _apply_event(db, reg, row)
                row.state = 'APPLIED'
                row.applied_at = utcnow()
                reg.last_ack_seq = max(reg.last_ack_seq, row.seq)
                rebuilt += 1
            except Exception as e:
                row.state = 'FAILED'
                row.error = f'reseed: {type(e).__name__}: {e}'[:350]
            db.flush()
        _audit_sync(db, tid, 'SYNC_RESEED', {'rebuilt': rebuilt})
        return {'rebuilt': rebuilt, 'ack_seq': reg.last_ack_seq}
    finally:
        _capture_suppressed.reset(tok)


# ═══ القنوات اليدوية الطارئة (§6): USB مشفر موقَّع ═══
def export_usb(db: Session, site: m.SyncSite, password: str,
               tenant_id: str) -> dict:
    """تصدير Outbox المعلّق بملف مشفر (Fernet/PBKDF2 من كلمة مرور) وموقَّع
    بمفتاح الموقع — قناة بديلة للفنادق شديدة العزلة."""
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    events = db.execute(select(m.SyncEventOut).where(
        m.SyncEventOut.state != 'ACKED').order_by(m.SyncEventOut.seq)
        ).scalars().all()
    build_payloads(db, events, lean=False)
    batch = make_batch(db, site, events) if events else {
        'site_id': site.site_id, 'tenant_id': tenant_id, 'events': [],
        'sync_schema': SYNC_SCHEMA}
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=120_000)
    key = base64.urlsafe_b64encode(kdf.derive(password.encode('utf-8')))
    f = Fernet(key)
    inner = json.dumps(batch, ensure_ascii=False, default=str).encode('utf-8')
    token = f.encrypt(inner)
    return {'kind': 'SIJILL_SYNC_USB', 'site_id': site.site_id,
            'tenant_id': tenant_id, 'salt': base64.b64encode(salt).decode(),
            'payload_enc': token.decode(), 'sha256':
            hashlib.sha256(inner).hexdigest(), 'events': len(events)}


def import_usb(db: Session, packet: dict, password: str) -> dict:
    """استيراد على الطرف المقابل — فك تشفير ثم نفس مسار Inbox/التطبيق.
    كلمة مرور خاطئة أو عبث بالحمولة = رفض ValueError موثق (§6)."""
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt = base64.b64decode(packet['salt'])
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=120_000)
    key = base64.urlsafe_b64encode(kdf.derive(password.encode('utf-8')))
    try:
        raw = Fernet(key).decrypt(packet['payload_enc'].encode())
    except InvalidToken as e:
        raise ValueError('SYNC.USB_TAMPERED_OR_WRONG_PASSWORD') from e
    batch = json.loads(raw.decode('utf-8'))
    if hashlib.sha256(json.dumps(batch, ensure_ascii=False, default=str)
                      .encode('utf-8')).hexdigest() != packet['sha256']:
        raise ValueError('SYNC.USB_TAMPERED')
    reg = db.get(m.SyncSiteReg, batch['site_id'])
    if reg is None:
        raise ValueError('SYNC.SITE_NOT_REGISTERED')
    return receive_batch(db, reg, batch)


# ═══ الاقتران (§6) — حزمة تأسيس: مستأجر/دليل/فترات بحوافظ UUID نفسها ═══
def pairing_bundle(db: Session, tenant_id: str, site: m.SyncSite) -> dict:
    tenant = db.get(m.Tenant, tenant_id)
    branch = db.execute(select(m.Branch).where(
        m.Branch.tenant_id == tenant_id).limit(1)).scalar_one()
    years = db.execute(select(m.FiscalYear).where(
        m.FiscalYear.tenant_id == tenant_id)).scalars().all()
    periods = db.execute(select(m.FiscalPeriod).join(
        m.FiscalYear, m.FiscalPeriod.fiscal_year_id == m.FiscalYear.id)
        .where(m.FiscalYear.tenant_id == tenant_id)).scalars().all()
    accounts = db.execute(select(m.Account).where(
        m.Account.tenant_id == tenant_id)).scalars().all()
    cats = db.execute(select(m.InvCategory).where(
        m.InvCategory.tenant_id == tenant_id).limit(500)).scalars().all()
    rtypes = db.execute(select(m.RoomType).limit(200)).scalars().all()
    return {
        'kind': 'SYNC_PAIRING_BUNDLE', 'site_id': site.site_id,
        'public_key_pem': site.public_key_pem,
        'tenant': {'id': tenant.id, 'legal_name': tenant.legal_name,
                   'trade_name': tenant.trade_name,
                   'base_currency': tenant.base_currency,
                   'country': tenant.country, 'timezone': tenant.timezone},
        'branch': {'id': branch.id, 'code': branch.code, 'name': branch.name},
        'years': [{'id': y.id, 'year_no': y.year_no,
                   'start_date': str(y.start_date),
                   'end_date': str(y.end_date), 'status': y.status}
                  for y in years],
        'periods': [{'id': p.id, 'fiscal_year_id': p.fiscal_year_id,
                     'period_no': p.period_no,
                     'start_date': str(p.start_date),
                     'end_date': str(p.end_date), 'status': p.status}
                    for p in periods],
        'accounts': [{'id': a.id, 'code': a.code, 'name_ar': a.name_ar,
                      'name_en': a.name_en,
                      'parent_id': a.parent_id, 'type': a.type,
                      'nature': a.nature, 'is_postable': a.is_postable,
                      'party_required': a.party_required, 'level': a.level,
                      'is_active': a.is_active, 'is_system': a.is_system}
                     for a in accounts],
        'inv_categories': [{'id': c.id, 'code': c.code, 'name_ar': c.name_ar,
                            'default_account_code': c.default_account_code,
                            'valuation_method': c.valuation_method}
                           for c in cats],
        'room_types': [{'id': r.id, 'code': r.code, 'name_ar': r.name_ar,
                        'name_en': r.name_en,
                        'capacity_adults': r.capacity_adults,
                        'capacity_children': r.capacity_children,
                        'beds': r.beds, 'amenities': r.amenities,
                        'base_rate': str(r.base_rate),
                        'display_order': r.display_order,
                        'is_active': r.is_active}
                       for r in rtypes],
    }


def apply_pairing_bundle(db: Session, bundle: dict, register_key: str
                         ) -> m.SyncSiteReg:
    """المستلم يبني ظل المستأجر بنفس UUIDs — بلا تحويل معرفات إطلاقاً."""
    t = bundle['tenant']
    if db.get(m.Tenant, t['id']) is None:
        db.add(m.Tenant(id=t['id'], legal_name=t['legal_name'],
                        trade_name=t.get('trade_name', ''),
                        base_currency=t.get('base_currency', 'YER'),
                        country=t.get('country', 'YE'),
                        timezone=t.get('timezone', 'Asia/Aden'),
                        status='CLOUD_SHADOW', created_at=utcnow()))
    db.flush()  # المستأجر أولاً: لا علاقة ORM مع الفرع (FK خام) فيُرتَّب يدوياً
    b = bundle['branch']
    if db.get(m.Branch, b['id']) is None:
        db.add(m.Branch(id=b['id'], tenant_id=t['id'], code=b['code'],
                        name=b['name']))
    db.flush()
    for y in bundle['years']:
        if db.get(m.FiscalYear, y['id']) is None:
            db.add(m.FiscalYear(id=y['id'], tenant_id=t['id'],
                                year_no=y['year_no'],
                                start_date=date.fromisoformat(y['start_date']),
                                end_date=date.fromisoformat(y['end_date']),
                                status=y['status']))
    db.flush()
    for p in bundle['periods']:
        if db.get(m.FiscalPeriod, p['id']) is None:
            db.add(m.FiscalPeriod(id=p['id'],
                                  fiscal_year_id=p['fiscal_year_id'],
                                  period_no=p['period_no'],
                                  start_date=date.fromisoformat(p['start_date']),
                                  end_date=date.fromisoformat(p['end_date']),
                                  status=p['status']))
    for a in bundle['accounts']:
        if db.get(m.Account, a['id']) is None:
            db.add(m.Account(id=a['id'], tenant_id=t['id'], code=a['code'],
                             name_ar=a['name_ar'],
                             name_en=a.get('name_en', ''),
                             parent_id=a['parent_id'], type=a['type'],
                             nature=a['nature'],
                             is_postable=a['is_postable'],
                             party_required=a['party_required'],
                             is_system=a['is_system'], level=a['level'],
                             is_active=a.get('is_active', True)))
    from .models import InvCategory, RoomType
    for c in bundle['inv_categories']:
        if db.get(InvCategory, c['id']) is None:
            db.add(InvCategory(id=c['id'], tenant_id=t['id'], code=c['code'],
                               name_ar=c['name_ar'],
                               default_account_code=c.get(
                                   'default_account_code', '1210'),
                               valuation_method=c.get('valuation_method',
                                                      'AVG')))
    for r in bundle['room_types']:
        if db.get(RoomType, r['id']) is None:
            db.add(RoomType(id=r['id'], tenant_id=t['id'], code=r['code'],
                            name_ar=r['name_ar'], name_en=r.get('name_en', ''),
                            capacity_adults=r.get('capacity_adults', 2),
                            capacity_children=r.get('capacity_children', 1),
                            beds=r.get('beds', ''),
                            amenities=r.get('amenities', []),
                            base_rate=r.get('base_rate', '0'),
                            display_order=r.get('display_order', 0),
                            is_active=r.get('is_active', True)))
    db.flush()
    reg = db.get(m.SyncSiteReg, bundle['site_id'])
    if reg is None:
        reg = m.SyncSiteReg(site_id=bundle['site_id'], tenant_id=t['id'],
                            branch_id=b['id'],
                            legal_name=t['legal_name'],
                            public_key_pem=bundle['public_key_pem'],
                            site_token=base64.urlsafe_b64encode(
                                os.urandom(24)).decode())
        db.add(reg)
    else:
        reg.public_key_pem = bundle['public_key_pem']
    db.flush()
    _audit_sync(db, t['id'], 'SYNC_PAIRING', {'site': bundle['site_id']})
    return reg


def suppress_capture(db: Session) -> None:
    """مزامنة واردة لا تُلتقط مجدداً (لا حلقات §1)."""
    db.info['sync_suppress'] = True
