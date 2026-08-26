"""واجهات المزامنة (ملف 09):
- طرف الموقع: حالة/دفع فوري/تقشير/تعارض/تصدير USB/اقتران/سحب ترخيص+نبض (§6)
- طرف المستقبِل: receive/counts/register/reseed (مفعّلة بوضع السحابة §1)
"""
import json
import urllib.request

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from .. import synck as SK
from ..config import get_settings
from ..db import get_db
from ..deps import Principal, require_perm
from ..posting import PostingError
from ..security import utcnow

router = APIRouter(prefix='/api/sync', tags=['sync'])


def _deny(code: str, msg: str, status: int = 400):
    raise HTTPException(status, {'error': {'code': code,
                                           'message_ar': msg}})


# ═══ طرف الموقع (هايبرد محلي) ═══
@router.get('/status')
def sync_status(db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('sync.view'))):
    site = SK.ensure_site(db, pr.tenant_id)
    db.commit()
    pending = db.execute(select(func.count(m.SyncEventOut.id)).where(
        m.SyncEventOut.state == 'PENDING')).scalar() or 0
    sent = db.execute(select(func.count(m.SyncEventOut.id)).where(
        m.SyncEventOut.state == 'SENT')).scalar() or 0
    acked = db.execute(select(func.count(m.SyncEventOut.id)).where(
        m.SyncEventOut.state == 'ACKED')).scalar() or 0
    conflicts = db.execute(select(func.count(m.SyncConflict.id)).where(
        m.SyncConflict.resolution.is_(None))).scalar() or 0
    s = get_settings()
    return {'site_id': site.site_id, 'cloud_url': site.cloud_url,
            'paired': bool(site.cloud_url and site.site_token),
            'receiver_mode': s.sync_receiver_enabled,
            'cycle_seconds': site.cycle_seconds, 'lean_mode': site.lean_mode,
            'pending': pending, 'sent_unacked': sent, 'acked': acked,
            'last_ack_seq': site.last_ack_seq, 'gaps': site.last_gaps,
            'last_push_at': str(site.last_push_at or ''),
            'last_success_at': str(site.last_success_at or ''),
            'last_error': site.last_error,
            'last_heartbeat_at': str(site.last_heartbeat_at or ''),
            'open_conflicts': conflicts,
            'latency_note': 'حدث مالي يصل P95 ≤ 90ث: دورة 60ث + دفعة فورية '
                            'للأولوية القصوى (09 §3/§7-4)'}


@router.post('/pair')
def sync_pair(body: dict = Body(...), db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('sync.manage'))):
    """الاقتران الأولي: يرسل حزمة التأسيس (مستأجر/دليل/فترات/ماسترات
    بمعرفاتها ذاتها) للمستلم ويخزّن رمز الموقع المستلم (§6)."""
    cloud_url = str(body.get('cloud_url', '')).strip().rstrip('/')
    register_key = str(body.get('register_key', '')).strip()
    if not cloud_url:
        _deny('SYNC.NO_URL', 'رابط السحابة مطلوب للاقتران')
    site = SK.ensure_site(db, pr.tenant_id)
    bundle = SK.pairing_bundle(db, pr.tenant_id, site)
    try:
        req = urllib.request.Request(
            cloud_url + '/api/sync/register',
            data=json.dumps(bundle, default=str).encode('utf-8'),
            headers={'Content-Type': 'application/json',
                     'X-Register-Key': register_key}, method='POST')
        with urllib.request.urlopen(req, timeout=30) as r:
            reply = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        _deny('SYNC.PAIR_FAILED', f'تعذر الاقتران: {e}')
    site.cloud_url = cloud_url
    site.site_token = reply['site_token']
    db.commit()
    return {'paired': True, 'site_id': site.site_id,
            'cloud_ack': reply.get('ack_seq', 0)}


@router.post('/push-now')
def sync_push_now(db: Session = Depends(get_db),
                  pr: Principal = Depends(require_perm('sync.manage'))):
    """زر رفع فوري (§6) — دورة دفع واحدة خارج الجدولة."""
    out = SK.push_cycle(db)
    db.commit()
    return out


@router.post('/backfill')
def sync_backfill(db: Session = Depends(get_db),
                  body: dict = Body(default={}),
                  pr: Principal = Depends(require_perm('sync.manage'))):
    """الرفع الأولي للبيانات السابقة لتفعيل المزامنة (§6): قيود مرحَّلة
    وماسترات بلا أحداث تصبح أحداث Outbox قابلة للدفع — آمن التكرار."""
    out = SK.backfill_outbox(db, pr.tenant_id)
    from ..audit import audit
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='sync', action='SYNC_BACKFILL', entity='sync_outbox',
          after=out)
    db.commit()
    if body.get('push'):
        pushed = SK.push_cycle(db)
        db.commit()
        out['push'] = pushed
    return out


@router.post('/lean/{mode}')
def sync_lean(mode: str, db: Session = Depends(get_db),
              pr: Principal = Depends(require_perm('sync.manage'))):
    site = SK.ensure_site(db, pr.tenant_id)
    site.lean_mode = mode == 'on'
    db.commit()
    return {'lean_mode': site.lean_mode}


@router.get('/conflicts')
def sync_conflicts(db: Session = Depends(get_db),
                   pr: Principal = Depends(require_perm('sync.view'))):
    rows = db.execute(select(m.SyncConflict).where(
        m.SyncConflict.resolution.is_(None))
        .order_by(m.SyncConflict.detected_at.desc()).limit(100)
        ).scalars().all()
    return [{'id': c.id, 'entity': c.entity, 'entity_id': c.entity_id,
             'reason': c.reason, 'local_val': c.local_val,
             'remote_val': c.remote_val,
             'detected_at': c.detected_at.isoformat()} for c in rows]


@router.post('/conflicts/{cid}/resolve')
def sync_resolve(cid: int, body: dict = Body(...),
                 db: Session = Depends(get_db),
                 pr: Principal = Depends(require_perm('sync.manage'))):
    """قرار بشري موثق §4: محلي | سحابي — يُطبَّق ويُؤرشف باسم الحاكم."""
    c = db.get(m.SyncConflict, cid)
    if c is None or c.resolution:
        _deny('SYNC.CONFLICT_GONE', 'التعارض غير موجود أو محسوم', 404)
    choice = str(body.get('choice', '')).upper()
    if choice not in ('LOCAL', 'REMOTE'):
        _deny('SYNC.BAD_CHOICE', 'اختر LOCAL (القيمة هنا) أو REMOTE (الواردة)')
    winner = c.local_val if choice == 'LOCAL' else c.remote_val
    spec = SK.SYNC_REGISTRY.get(c.entity)
    obj = db.get(spec['cls'], c.entity_id) if spec else None
    if obj is not None and choice == 'REMOTE':
        for f in spec['fields']:
            if f in winner:
                setattr(obj, f, SK._coerce(spec['cls'], f, winner[f]))
    c.resolution = choice
    c.resolved_by = pr.id
    c.resolved_at = utcnow()
    from ..audit import audit
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='sync', action='SYNC_CONFLICT_RESOLVE',
          entity=c.entity, entity_id=c.entity_id,
          after={'choice': choice, 'reason': c.reason})
    db.commit()
    return {'resolved': True, 'applied': choice}


@router.get('/export-usb')
def sync_export_usb(password: str = Query(min_length=6),
                    db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('sync.manage'))):
    """قناة بديلة للفنادق شديدة العزلة (§6): ملف مشفر موقَّع بالأحداث المعلقة."""
    if len(password) < 6:
        _deny('SYNC.WEAK_PASSWORD', 'كلمة المرور 6 أحرف فأكثر')
    site = SK.ensure_site(db, pr.tenant_id)
    packet = SK.export_usb(db, site, password, pr.tenant_id)
    db.commit()
    return packet


@router.post('/import-usb')
def sync_import_usb(body: dict = Body(...), db: Session = Depends(get_db),
                    pr: Principal = Depends(require_perm('sync.manage'))):
    """استيراد ملف USB مشفر على الطرف المقابل."""
    packet = body.get('packet') or {}
    password = str(body.get('password', ''))
    try:
        out = SK.import_usb(db, packet, password)
    except ValueError as e:
        code = str(e)
        _deny(code, 'ملف USB مرفوض: تالف/كلمة مرور خاطئة/موقع غير مقترن')
    db.commit()
    return out


@router.post('/pull-licenses')
def sync_pull_licenses(db: Session = Depends(get_db),
                       pr: Principal = Depends(require_perm('sync.manage'))):
    """سحب اتجاه سحابة→محلي من لوحة الشركة (§1): أحدث ترخيص + إلغاءات."""
    from .. import licensing as lic
    s = get_settings()
    if not (s.vendor_edge_url and s.vendor_edge_token and
            s.vendor_client_code):
        _deny('SYNC.NO_VENDOR', 'اضبط vendor_edge_url/token/client_code أولاً')
    got = {}

    def _get(path):
        req = urllib.request.Request(
            s.vendor_edge_url.rstrip('/') + path,
            headers={'X-Edge-Token': s.vendor_edge_token})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode('utf-8'))

    payload = _get(f'/edge/license/latest?client_code={s.vendor_client_code}')
    try:
        out = lic.install_license(db, pr.tenant_id, payload, actor_id=pr.id)
        got['license'] = {'installed': out['installed'],
                          'state': out['status']['state']}
    except lic.LicError as e:
        got['license'] = {'installed': False, 'error': e.code}
    try:
        rev = _get(f'/edge/revocations/latest?client_code='
                   f'{s.vendor_client_code}')
        if rev.get('revocation_serial'):
            out2 = lic.import_revocations(db, pr.tenant_id, rev,
                                          actor_id=pr.id)
            got['revocations'] = {'imported': out2['imported'],
                                  'serial': out2['revocation_serial']}
    except lic.LicError as e:
        got['revocations'] = {'imported': False, 'error': e.code}
    db.commit()
    return got


@router.post('/heartbeat-now')
def sync_heartbeat_now(db: Session = Depends(get_db),
                       pr: Principal = Depends(require_perm('sync.manage'))):
    """نبضة صحة فورية للوحة الشركة (أولوية: تراخيص+نبض §3)."""
    from .. import licensing as lic
    s = get_settings()
    if not (s.vendor_edge_url and s.vendor_edge_token and
            s.vendor_client_code):
        _deny('SYNC.NO_VENDOR', 'اضبط بيانات لوحة الشركة أولاً')
    pending = db.execute(select(func.count(m.SyncEventOut.id)).where(
        m.SyncEventOut.state != 'ACKED')).scalar() or 0
    import shutil
    disk = shutil.disk_usage('/').free / (1024 ** 3)
    st = lic.evaluate(db, pr.tenant_id)
    body = {'client_code': s.vendor_client_code,
            'site_id': st['site_id'], 'product_version': s.version,
            'outbox_lag': pending, 'backup_ok': True,
            'disk_free_gb': f'{disk:.1f}',
            'fingerprint_hash': st['fingerprint']['hash'],
            'payload': {'license_state': st['state']}}
    try:
        req = urllib.request.Request(
            s.vendor_edge_url.rstrip('/') + '/edge/heartbeat',
            data=json.dumps(body).encode('utf-8'),
            headers={'Content-Type': 'application/json',
                     'X-Edge-Token': s.vendor_edge_token}, method='POST')
        with urllib.request.urlopen(req, timeout=20) as r:
            reply = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        _deny('SYNC.HEARTBEAT_FAILED', f'تعذر إرسال النبض: {e}')
    site = SK.ensure_site(db, pr.tenant_id)
    site.last_heartbeat_at = utcnow()
    db.commit()
    return reply


@router.get('/events')
def sync_events(limit: int = Query(default=50, ge=1, le=200),
                db: Session = Depends(get_db),
                pr: Principal = Depends(require_perm('sync.view'))):
    rows = db.execute(select(m.SyncEventOut)
                      .order_by(m.SyncEventOut.seq.desc()).limit(limit)
                      ).scalars().all()
    return [{'seq': r.seq, 'entity': r.entity, 'entity_id': r.entity_id,
             'op': r.op, 'version': r.entity_version, 'state': r.state,
             'occurred_at': r.occurred_at.isoformat()
             if r.occurred_at else ''} for r in rows]


# ═══ طرف المستقبِل (السحابة — تُفعَّل بالبيئة) ═══
def _receiver_guard():
    if not get_settings().sync_receiver_enabled:
        raise HTTPException(503, {'error': {'code': 'SYNC.RECEIVER_OFF',
                            'message_ar': 'هذه العقدة ليست مستقبِل مزامنة'}})


def _site_from_token(x_site_token: str | None, db: Session) -> m.SyncSiteReg:
    _receiver_guard()
    if not x_site_token:
        _deny('SYNC.NO_TOKEN', 'ترويسة X-Site-Token مطلوبة', 401)
    reg = db.execute(select(m.SyncSiteReg).where(
        m.SyncSiteReg.site_token == x_site_token)).scalar_one_or_none()
    if reg is None:
        _deny('SYNC.BAD_TOKEN', 'رمز موقع غير معروف', 401)
    return reg


@router.post('/receive')
def sync_receive(batch: dict = Body(...),
                 x_site_token: str | None = Header(default=None),
                 db: Session = Depends(get_db)):
    reg = _site_from_token(x_site_token, db)
    try:
        out = SK.receive_batch(db, reg, batch)
    except ValueError as e:
        if 'BAD_SIGNATURE' in str(e):
            _deny('SYNC.BAD_SIGNATURE', 'توقيع الدفعة غير صالح — مرفوضة', 400)
        raise
    db.commit()
    return out


@router.get('/counts')
def sync_cloud_counts(x_site_token: str | None = Header(default=None),
                      db: Session = Depends(get_db)):
    reg = _site_from_token(x_site_token, db)
    return {'counts': SK.cloud_counts(db, reg.site_id),
            'ack_seq': reg.last_ack_seq}


@router.post('/register')
def sync_register(bundle: dict = Body(...),
                  x_register_key: str | None = Header(default=None),
                  db: Session = Depends(get_db)):
    _receiver_guard()
    if x_register_key != get_settings().sync_register_key:
        _deny('SYNC.BAD_REGISTER_KEY', 'مفتاح تسجيل المواقع غير صالح', 401)
    reg = SK.apply_pairing_bundle(db, bundle, x_register_key)
    db.commit()
    return {'site_id': reg.site_id, 'site_token': reg.site_token,
            'ack_seq': reg.last_ack_seq}


@router.post('/reseed')
def sync_reseed(x_site_token: str | None = Header(default=None),
                db: Session = Depends(get_db)):
    """إعادة بناء كاملة من مؤرشف Inbox (§6/قبول §7-5)."""
    reg = _site_from_token(x_site_token, db)
    out = SK.reseed_receiver(db, reg)
    db.commit()
    return out


@router.get('/inbox')
def sync_inbox(x_site_token: str | None = Header(default=None),
               limit: int = Query(default=50, le=500),
               db: Session = Depends(get_db)):
    reg = _site_from_token(x_site_token, db)
    rows = db.execute(select(m.SyncEventIn).where(
        m.SyncEventIn.site_id == reg.site_id)
        .order_by(m.SyncEventIn.seq.desc()).limit(limit)).scalars().all()
    return [{'seq': r.seq, 'entity': r.entity, 'state': r.state,
             'error': r.error,
             'received_at': r.received_at.isoformat()} for r in rows]
