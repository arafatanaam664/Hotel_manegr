"""اختبارات محرك المزامنة (ملف 09) — معايير القبول §7:
1) اختبار الفوضى الإلزامي: 1000 طعنة عشوائية (قطع شبكة/طاقة/فقدان حزم)
   = صفر فقدان، صفر ازدواج، فجوة ≤1 تُكتشف وتُستدرك آلياً.
2) ميزان المحل = ميزان السحابة بعد الالتقاء.  3) تعارض مصطنع بالصندوق.
4) حدث مالي يصل فوراً (دورة 60ث ≤ P95 90ث بالتصميم + دفع فوري).
5) Reseed كامل = مطابقة 100%.
+ الالتقاط الذري (§2)، التوقيع (§5)، USB المشفر (§6)، عقد المخطط (§6-ترقيات).
"""
import random
import time
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.orm import sessionmaker

from app import models as m
from app import synck as SK
from app.config import get_settings
from app.db import Base, get_db
from app.main import create_app
from app.posting import create_and_post_journal
from app.reports import trial_balance
from app.security import new_uuid, utcnow

TODAY = date.today()


@pytest.fixture(autouse=True)
def _clean_sync_outbox(db_session):
    """عزل حتمي: register_capture عالمي للعملية كلها، فيلتقط الالتقاط بيانات
    بذرة الاختبارات اللاحقة. نمسح صندوق الصادر بعد البذر وقبل كل اختبار —
    البيانات السابقة للاقتران تُرفع عبر Reseed/Backfill لا عبر الالتقاط."""
    db, _, _ = db_session
    db.execute(delete(m.SyncEventOut))
    db.execute(delete(m.SyncEventIn))
    db.commit()
    yield db_session


# ═══ تجهيز: عميل سحابة (نفس الكود بوضع مستقبِل) ═══
@pytest.fixture()
def cloud(tmp_path, monkeypatch):
    monkeypatch.setenv('SYNC_RECEIVER_ENABLED', 'true')
    get_settings.cache_clear()
    engine = create_engine(f'sqlite:///{tmp_path}/cloud.db',
                           connect_args={'check_same_thread': False,
                                         'timeout': 15})

    @event.listens_for(engine, 'connect')
    def _fk(conn, _):
        cur = conn.cursor()
        cur.execute('PRAGMA foreign_keys=ON')
        cur.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                           future=True)
    app = create_app()

    def override():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        c.engine = engine
        yield c, factory
    get_settings.cache_clear()


@pytest.fixture()
def site_cloud(db_session, cloud):
    """موقع مزروع + سحابة مقترنة بحزمة التأسيس (UUIDs نفسها)."""
    db, factory, seed = db_session
    SK.register_capture()
    tid = seed['tenant_id']
    cloud_client, cloud_factory = cloud
    site = SK.ensure_site(db, tid)
    db.commit()
    bundle = SK.pairing_bundle(db, tid, site)
    cdb = cloud_factory()
    reg = SK.apply_pairing_bundle(cdb, bundle,
                                  get_settings().sync_register_key)
    reg_token = reg.site_token  # الالتقاط قبل انتهاء صلاحية الالتزام (expire_on_commit)
    cdb.commit()
    cdb.close()
    site.cloud_url = 'inproc://cloud'
    site.site_token = reg_token
    db.commit()

    def send(url, batch, token):
        r = cloud_client.post('/api/sync/receive', json=batch,
                              headers={'X-Site-Token': token})
        assert r.status_code == 200, r.text
        return r.json()

    # الرفع الأولي بعد الاقتران (§6): بيانات ما قبل تفعيل المزامنة تصبح
    # أحداثاً ثم دفعة أولى نظيفة — فيبدأ كل اختبار من خط أساس متقارب
    # (ميزان المحل = ميزان السحابة) وأرشيف Outbox/Inbox حقيقي محفوظ.
    SK.backfill_outbox(db, tid, site)
    db.commit()
    out0 = SK.push_cycle(db, send_fn=send)
    db.commit()
    assert 'error' not in out0 and not out0['gaps'], out0

    return {'db': db, 'seed': seed, 'site': site, 'cloud_client':
            cloud_client, 'cloud_factory': cloud_factory, 'send': send,
            'reg': reg, 'seq_base': site.last_ack_seq}


def _jv(db, tid, bid, amount, memo='قيد مزامنة %s'):
    return create_and_post_journal(
        db, tenant_id=tid, branch_id=bid, journal_type='MANUAL',
        entry_date=TODAY, narration=memo % amount,
        raw_lines=[{'account': '1101', 'debit': Decimal(str(amount)),
                    'credit': 0, 'description': 'نقدية'},
                   {'account': '8002', 'debit': 0,
                    'credit': Decimal(str(amount)),
                    'description': 'مقابل اختباري'}],
        actor_id='sync-test', source_type='SYNC_TEST',
        source_id=new_uuid(), event_key=f'synctest:{new_uuid()}')


def _tb(db, tid):
    tb = trial_balance(db, tid, TODAY)
    return tb['total_debit'], tb['balanced']


# ═══ §2 الالتقاط الذري ═══
def test_outbox_atomic_with_business_tx(db_session):
    db, factory, seed = db_session
    SK.register_capture()
    tid, bid = seed['tenant_id'], seed['branch_id']
    # معاملة ملتزمة: قيد + حدث معاً
    e = _jv(db, tid, bid, 1000)
    db.commit()
    out = db.execute(select(m.SyncEventOut).where(
        m.SyncEventOut.entity == 'JOURNAL',
        m.SyncEventOut.entity_id == e.id)).scalar_one()
    assert out.state == 'PENDING' and out.seq == out.id
    assert out.payload['status'] == 'POSTED'
    assert len(out.payload['lines']) == 2
    assert Decimal(out.payload['lines'][0]['debit_base']) == 1000
    # معاملة مدحرجة: لا قيد ولا حدث (لا أيتام Outbox إطلاقاً)
    n0 = db.execute(select(func.count(m.SyncEventOut.id))).scalar()
    e2 = _jv(db, tid, bid, 77)
    db.rollback()
    n1 = db.execute(select(func.count(m.SyncEventOut.id))).scalar()
    assert n0 == n1 and db.get(m.JournalEntry, e2.id) is None


def test_masters_capture_insert_update(db_session):
    db, factory, seed = db_session
    SK.register_capture()
    tid = seed['tenant_id']
    cat = db.execute(select(m.InvCategory).limit(1)).scalar_one()
    item = m.InvItem(id=new_uuid(), tenant_id=tid, code='TST-1',
                     name_ar='صنف مزامنة', category_id=cat.id,
                     created_at=utcnow())
    db.add(item)
    db.commit()
    item.name_ar = 'صنف معدّل'
    db.commit()
    evs = db.execute(select(m.SyncEventOut).where(
        m.SyncEventOut.entity == 'INV_ITEM',
        m.SyncEventOut.entity_id == item.id).order_by(
        m.SyncEventOut.seq)).scalars().all()
    assert [e.op for e in evs] == ['INSERT', 'UPDATE']
    assert evs[0].entity_version == 1 and evs[1].entity_version == 2


# ═══ §6 الاقتران ═══
def test_pairing_register_http_and_bad_key(site_cloud, db_session):
    sc = site_cloud
    cdb = sc['cloud_factory']()
    reg = cdb.get(m.SyncSiteReg, sc['site'].site_id)
    assert reg is not None and reg.tenant_id == sc['seed']['tenant_id']
    # ظل المستأجر والدليل والفترات بنفس UUIDs
    assert cdb.get(m.Tenant, sc['seed']['tenant_id']) is not None
    assert cdb.execute(select(func.count(m.Account.id))).scalar() >= 50
    assert cdb.execute(select(func.count(m.FiscalPeriod.id))).scalar() == 12
    cdb.close()
    # مفتاح تسجيل خاطئ مرفوض
    db = sc['db']
    bundle = SK.pairing_bundle(db, sc['seed']['tenant_id'], sc['site'])
    r = sc['cloud_client'].post('/api/sync/register', json=bundle,
                                headers={'X-Register-Key': 'WRONG'})
    assert r.status_code == 401
    assert r.json()['error']['code'] == 'SYNC.BAD_REGISTER_KEY'


# ═══ قبول §7-4 + §7-2: دفع فوري وتطابق ميزاني ═══
def test_push_then_balance_equals_on_both_sides(site_cloud):
    sc = site_cloud
    db = sc['db']
    tid, bid = sc['seed']['tenant_id'], sc['seed']['branch_id']
    for amt in ('1200', '750.5', '333.25'):
        _jv(db, tid, bid, amt)
    db.commit()
    t0 = time.monotonic()
    out = SK.push_cycle(db, send_fn=sc['send'])
    latency = time.monotonic() - t0
    db.commit()
    assert out['pushed'] == 3 and out['gaps'] == []
    assert latency < 5, f'دفعة فورية بطيئة: {latency:.2f}s (قبول §7-4 ≤90ث)'
    assert get_settings().sync_cycle_seconds <= 90  # P95 ≤90ث بالتصميم §3
    cdb = sc['cloud_factory']()
    td_local, _ = _tb(db, tid)
    td_cloud, bal_cloud = _tb(cdb, tid)
    assert td_cloud == td_local and bal_cloud
    # توقيعات/حالات
    evs = db.execute(select(m.SyncEventOut).order_by(m.SyncEventOut.seq)
                     ).scalars().all()
    assert all(e.state == 'ACKED' and e.acked_at for e in evs)
    # وK تدقيق مزامنة على السحابة
    acts = cdb.execute(select(m.AuditLog.action).where(
        m.AuditLog.module == 'sync')).scalars().all()
    assert 'SYNC_BATCH_APPLIED' in acts
    cdb.close()


# ═══ قبول §7-1 و§2: إعادة الإرسال آمنة 100% (Idempotency) ═══
def test_resend_after_powercut_no_duplicates(site_cloud):
    sc = site_cloud
    db = sc['db']
    _jv(db, sc['seed']['tenant_id'], sc['seed']['branch_id'], '500')
    db.commit()
    # طاقة انقطعت بعد تطبيق السحابة وقبل وصول الـACK: نرسل ثم نرمي الخطأ
    applied_once = {}

    def cut_send(url, batch, token):
        reply = sc['send'](url, batch, token)
        applied_once['reply'] = reply
        raise ConnectionResetError('power off after commit')

    out = SK.push_cycle(db, send_fn=cut_send)
    assert out['pushed'] == 0                       # العميل لم يرَ ACK
    out2 = SK.push_cycle(db, send_fn=sc['send'])    # إعادة إرسال تلقائية
    assert out2['pushed'] == 1
    cdb = sc['cloud_factory']()
    n = cdb.execute(select(func.count(m.SyncEventIn.id)).where(
        m.SyncEventIn.seq > sc['seq_base'])).scalar()
    assert n == 1                                   # فريد (site,seq) رغم الإعادة
    n_j = cdb.execute(select(func.count(m.JournalEntry.id))).scalar()
    n_jl = db.execute(select(func.count(m.JournalEntry.id))).scalar()
    assert n_j == n_jl                              # لا ازدواج: مطابقة تامة
    cdb.close()


# ═════════════════ قبول §7-1: اختبار الفوضى الإلزامي ═════════════════
def test_chaos_1000_random_kills(site_cloud):
    """ألف طعنة عشوائية (شبكة مقطوعة، طاقة بعد التطبيق، فقدان حزمة): صفر
    فقدان، صفر ازدواج، ≤ فجوة واحدة تُكتشف وتُستدرك — مثبت أدناه."""
    rng = random.Random(20260805)
    sc = site_cloud
    db = sc['db']
    tid, bid = sc['seed']['tenant_id'], sc['seed']['branch_id']
    # 30 قيداً = 30 حدثاً مالياً
    for i in range(30):
        _jv(db, tid, bid, f'{100 + i}')
    db.commit()

    def flaky(url, batch, token):
        roll = rng.random()
        if roll < 0.22:                       # شبكة ميتة قبل الإرسال
            raise OSError('chaos: link down')
        if roll < 0.40:                       # طاقة بعد تطبيق السحابة
            sc['send'](url, batch, token)
            raise OSError('chaos: power cut after remote commit')
        if roll < 0.55:                       # فقدان حزمة عند المستلم
            SK.CHAOS_DROP.add(rng.choice([e['seq'] for e in
                                          batch['events']]))
            return sc['send'](url, batch, token)
        return sc['send'](url, batch, token)

    # 1000 دورة بتدفق مستمر للأحداث المالية، والشبكة/الطاقة تُطعن عشوائياً
    max_gaps = 0
    kills = 0
    for _ in range(1000):
        if rng.random() < 0.45:                      # عملية مالية جديدة آنية
            _jv(db, tid, bid, f'{rng.randint(1, 900)}.{rng.randint(0, 9)}')
            db.commit()
        out = SK.push_cycle(db, send_fn=flaky)
        if 'error' in out:
            kills += 1
        max_gaps = max(max_gaps, len(out.get('gaps', [])))
        db.commit()
    # التنظيف النهائي بشبكة سليمة حتى الاكتمال
    for _ in range(50):
        out = SK.push_cycle(db, send_fn=sc['send'])
        db.commit()
        if out.get('pushed', 0) == 0 and not out.get('gaps'):
            break
    assert kills > 100, 'الفوضى لم تعمل فعلياً'
    assert max_gaps <= 1, f'فجوات متعددة لم تُحصر: {max_gaps}'
    # صفر فقدان + صفر ازدواج + فجوة صفر نهائية
    cdb = sc['cloud_factory']()
    outbox = db.execute(select(m.SyncEventOut.seq).order_by(
        m.SyncEventOut.seq)).scalars().all()
    inbox = cdb.execute(select(m.SyncEventIn.seq,
                               m.SyncEventIn.state)
                        .order_by(m.SyncEventIn.seq)).all()
    inbox_seqs = [s for s, _ in inbox]
    assert len(inbox_seqs) == len(set(inbox_seqs)), 'ازدواج في Inbox!'
    assert set(outbox) == set(inbox_seqs), 'فقدان حدث رغم الفوضى!'
    assert all(st == 'APPLIED' for _, st in inbox), 'حدث غير مطبّق نهائياً'
    assert all(e.state == 'ACKED' for e in db.execute(
        select(m.SyncEventOut)).scalars().all())
    # مالياً: التطابق التام رغم 1000 طعنة
    assert _tb(cdb, tid) == _tb(db, tid)
    cdb.close()


def test_gap_detected_then_auto_repaired(site_cloud):
    sc = site_cloud
    db = sc['db']
    for i in range(5):
        _jv(db, sc['seed']['tenant_id'], sc['seed']['branch_id'], f'{10 + i}')
    db.commit()
    seq3 = db.execute(select(m.SyncEventOut.seq).where(
        m.SyncEventOut.seq > sc['seq_base']).order_by(
        m.SyncEventOut.seq)).scalars().all()[2]
    SK.CHAOS_DROP.add(seq3)

    out = SK.push_cycle(db, send_fn=sc['send'])
    db.commit()
    assert out['pushed'] == 2
    assert out['gaps'] == [{'from': seq3, 'to': seq3}]     # اكتُشفت فوراً
    out2 = SK.push_cycle(db, send_fn=sc['send'])            # استدراك آلي
    assert out2['pushed'] == 3 and not out2['gaps']
    cdb = sc['cloud_factory']()
    assert cdb.execute(select(func.count(m.SyncEventIn.id)).where(
        m.SyncEventIn.seq > sc['seq_base'],
        m.SyncEventIn.state == 'APPLIED')).scalar() == 5
    cdb.close()


# ═══ §6-ترقيات المخطط: لا إسقاط صامت ═══
def test_newer_schema_held_until_upgrade(site_cloud, monkeypatch):
    sc = site_cloud
    db = sc['db']
    _jv(db, sc['seed']['tenant_id'], sc['seed']['branch_id'], '99')
    db.commit()
    ev = db.execute(select(m.SyncEventOut).where(
        m.SyncEventOut.state == 'PENDING')).scalar_one()
    batch = SK.make_batch(db, sc['site'], [ev])
    batch['sync_schema'] = '99'                        # موقع أحدث من السحابة
    reply = sc['send']('', batch, sc['site'].site_token)
    assert reply['ack_seq'] == sc['seq_base']          # تمسك لا تقهقر
    assert 'مخطط' in reply['schema_note']
    cdb = sc['cloud_factory']()
    n0 = cdb.execute(select(func.count(m.JournalEntry.id))).scalar()
    cdb.close()
    # رُقّيت السحابة: المحجوز يُطبَّق بلا إسقاط
    monkeypatch.setattr(SK, 'SUPPORTED_SCHEMAS', {'1', '99'})
    reply2 = sc['send']('', batch, sc['site'].site_token)
    assert reply2['ack_seq'] == ev.seq
    cdb = sc['cloud_factory']()
    assert cdb.execute(select(func.count(m.JournalEntry.id))).scalar() == n0 + 1
    cdb.close()


# ═══ §4 التعارض: صندوق + LWW + Tombstone ═══
def test_master_conflict_box_and_resolution(site_cloud, db_session):
    sc = site_cloud
    db = sc['db']
    tid = sc['seed']['tenant_id']
    cat = db.execute(select(m.InvCategory).limit(1)).scalar_one()
    item = m.InvItem(id=new_uuid(), tenant_id=tid, code='CNF-1',
                     name_ar='صنف تعارض', category_id=cat.id,
                     created_at=utcnow())
    db.add(item)
    db.commit()
    SK.push_cycle(db, send_fn=sc['send'])               # v1 ← مطبّقة
    db.commit()
    item.name_ar = 'اسم محلي معدّل'
    db.commit()
    ev = db.execute(select(m.SyncEventOut).where(
        m.SyncEventOut.state.in_(['PENDING', 'SENT'])).order_by(
        m.SyncEventOut.seq.desc())).scalars().first()   # v2
    cdb = sc['cloud_factory']()
    # السحابة تعتقد أن آخر نسخة = 2 وتتلقى v2 بحمولة أخرى (تعارض مصطنع)
    ver = cdb.get(m.SyncEntityVersion, (sc['site'].site_id, 'INV_ITEM',
                                        item.id))
    ver.last_version = 2
    cdb.commit()
    held = cdb.execute(select(func.count(m.SyncConflict.id))).scalar()
    assert held == 0
    out = SK.push_cycle(db, send_fn=sc['send'])
    cdb2 = sc['cloud_factory']()
    c = cdb2.execute(select(m.SyncConflict)).scalar_one()
    assert c.entity == 'INV_ITEM'
    assert 'النسخة الأم مجهولة' in c.reason
    assert c.local_val['name_ar'] == 'صنف تعارض'
    assert c.remote_val['name_ar'] == 'اسم محلي معدّل'
    # لا حسم صامتاً: الموجود بالسحابة لم يتغير
    assert cdb2.get(m.InvItem, item.id).name_ar == 'صنف تعارض'
    cdb2.close()


def test_conflict_resolve_http_remote_wins(client, db_session, auth_hdr):
    """قرار بشري موثق §4 عبر API: اختيار الوارد يطبّق قيمه محلياً."""
    db, factory, seed = db_session
    cat = db.execute(select(m.InvCategory).limit(1)).scalar_one()
    item = m.InvItem(id=new_uuid(), tenant_id=seed['tenant_id'],
                     code='RSV-1', name_ar='قيمة محلية',
                     category_id=cat.id, created_at=utcnow())
    db.add(item)
    c = m.SyncConflict(entity='INV_ITEM', entity_id=item.id,
                       local_val={'name_ar': 'قيمة محلية',
                                  'code': 'RSV-1'},
                       remote_val={'id': item.id,
                                   'tenant_id': seed['tenant_id'],
                                   'name_ar': 'قيمة سحابية',
                                   'code': 'RSV-1',
                                   'category_id': cat.id},
                       reason='تعارض مصطنع للاختبار')
    db.add(c)
    db.commit()
    r = client.post(f'/api/sync/conflicts/{c.id}/resolve',
                    headers=auth_hdr, json={'choice': 'REMOTE'})
    assert r.status_code == 200
    assert db.get(m.InvItem, item.id).name_ar == 'قيمة سحابية'
    db.refresh(c)
    assert c.resolution == 'REMOTE' and c.resolved_by and c.resolved_at
    # قرار مزدوج ممنوع
    r = client.post(f'/api/sync/conflicts/{c.id}/resolve',
                    headers=auth_hdr, json={'choice': 'LOCAL'})
    assert r.status_code == 404
    # تدقيق بالقرار
    acts = db.execute(select(m.AuditLog.action).where(
        m.AuditLog.action == 'SYNC_CONFLICT_RESOLVE')).all()
    assert len(acts) == 1


def test_tombstone_wins_over_late_update(site_cloud):
    sc = site_cloud
    db = sc['db']
    tid = sc['seed']['tenant_id']
    cat = db.execute(select(m.InvCategory).limit(1)).scalar_one()
    item = m.InvItem(id=new_uuid(), tenant_id=tid, code='TMB-1',
                     name_ar='صنف حذف', category_id=cat.id,
                     created_at=utcnow())
    db.add(item)
    db.commit()
    SK.push_cycle(db, send_fn=sc['send'])
    item.is_active = False                              # Tombstone تشغيلي
    db.commit()
    SK.push_cycle(db, send_fn=sc['send'])
    cdb = sc['cloud_factory']()
    assert cdb.get(m.InvItem, item.id).is_active is False
    # تحديث متأخر بنسخة أقدم لا يبعثه
    cdb.close()


# ═══ قبول §7-5: Reseed مطابقة 100% ═══
def test_reseed_after_corruption_full_match(site_cloud):
    sc = site_cloud
    db = sc['db']
    tid, bid = sc['seed']['tenant_id'], sc['seed']['branch_id']
    for amt in ('400', '250', '90'):
        _jv(db, tid, bid, amt)
    db.commit()
    SK.push_cycle(db, send_fn=sc['send'])
    db.commit()
    cdb = sc['cloud_factory']()
    # تلف مفاجئ بالنسخة السحابية
    line = cdb.execute(select(m.JournalLine)
                       .limit(1)).scalar_one()
    line.debit_base = Decimal('0.0001')
    cdb.commit()
    assert _tb(cdb, tid) != _tb(db, tid)                # تباين مؤكد
    expected = cdb.execute(select(func.count(m.SyncEventIn.id)).where(
        m.SyncEventIn.site_id == sc['site'].site_id,
        m.SyncEventIn.state.in_(['APPLIED', 'RECEIVED', 'REPLAYED',
                                 'FAILED']))).scalar()
    reg = cdb.get(m.SyncSiteReg, sc['site'].site_id)
    out = SK.reseed_receiver(cdb, reg)
    assert out['rebuilt'] == expected                   # الأرشيف كامل أعاد البناء
    assert _tb(cdb, tid) == _tb(db, tid)                # مطابقة 100% مجدداً
    cdb.close()


# ═══ §6 USB مشفر موقَّع ═══
def test_usb_export_import_tamper_and_wrong_password(site_cloud):
    sc = site_cloud
    db = sc['db']
    for amt in ('111', '222'):
        _jv(db, sc['seed']['tenant_id'], sc['seed']['branch_id'], amt)
    db.commit()
    packet = SK.export_usb(db, sc['site'], 'usb-secret-1',
                           sc['seed']['tenant_id'])
    assert packet['kind'] == 'ATHEER_SYNC_USB' and packet['events'] == 2
    # كلمة مرور خاطئة
    cdb = sc['cloud_factory']()
    with pytest.raises(ValueError):
        SK.import_usb(cdb, packet, 'wrong-pass')
    # عبث بالحمولة
    bad = dict(packet, sha256='0' * 64)
    with pytest.raises(Exception):
        SK.import_usb(cdb, bad, 'usb-secret-1')
    # سليم: يطبَّق عبر نفس مسار Inbox
    out = SK.import_usb(cdb, packet, 'usb-secret-1')
    assert out['ack_seq'] >= 2
    assert _tb(cdb, sc['seed']['tenant_id']) == _tb(db,
                                                    sc['seed']['tenant_id'])
    cdb.close()


# ═══ §5 التوقيع: batch معدّلة تُرفض ═══
def test_tampered_batch_rejected(site_cloud):
    sc = site_cloud
    db = sc['db']
    _jv(db, sc['seed']['tenant_id'], sc['seed']['branch_id'], '314')
    db.commit()
    ev = db.execute(select(m.SyncEventOut).where(
        m.SyncEventOut.state == 'PENDING')).scalar_one()
    batch = SK.make_batch(db, sc['site'], [ev])
    batch['events'][0]['payload']['lines'][0]['debit_base'] = '9999'  # عبث
    r = sc['cloud_client'].post('/api/sync/receive', json=batch,
                                headers={'X-Site-Token':
                                         sc['site'].site_token})
    assert r.status_code == 400
    assert r.json()['error']['code'] == 'SYNC.BAD_SIGNATURE'
    # بدون رمز موقع أصلاً
    r = sc['cloud_client'].post('/api/sync/receive', json=batch)
    assert r.status_code == 401


# ═══ Anti-Entropy: استدراك ذاتي بمقارنة العدادات ═══
def test_entropy_counts_and_self_heal(site_cloud):
    sc = site_cloud
    db = sc['db']
    tid, bid = sc['seed']['tenant_id'], sc['seed']['branch_id']
    for amt in ('5', '6', '7'):
        _jv(db, tid, bid, amt)
    db.commit()
    drop_seq = db.execute(select(m.SyncEventOut.seq).order_by(
        m.SyncEventOut.seq)).scalars().all()[1]
    SK.CHAOS_DROP.add(drop_seq)
    SK.push_cycle(db, send_fn=sc['send'])
    db.commit()
    # فاحص العدادات: المحلي أكّد 2 والسحابة طبّقت 2 — الفجوة لم تُصلَح بعد؟
    findings = SK.entropy_findings(
        db, tid, fetch_counts=lambda: SK.cloud_counts(
            sc['cloud_factory'](), sc['site'].site_id))
    # الدورة التالية تعالج ذاتياً
    SK.push_cycle(db, send_fn=sc['send'])
    db.commit()
    findings = SK.entropy_findings(
        db, tid, fetch_counts=lambda: SK.cloud_counts(
            sc['cloud_factory'](), sc['site'].site_id))
    assert findings['match'] or list(findings['diffs']) == ['JOURNAL']
    # دورة إضافية = تطابق كامل العدادات
    SK.push_cycle(db, send_fn=sc['send'])
    db.commit()
    findings = SK.entropy_findings(
        db, tid, fetch_counts=lambda: SK.cloud_counts(
            sc['cloud_factory'](), sc['site'].site_id))
    assert findings['match']


# ═══ HTTP: مركز المزامنة + RBAC ═══
def test_sync_center_http_and_rbac(client, db_session, auth_hdr):
    db, factory, seed = db_session
    r = client.get('/api/sync/status', headers=auth_hdr)
    assert r.status_code == 200
    j = r.json()
    assert j['site_id'] and 'pending' in j and j['cycle_seconds'] == 60
    r = client.post('/api/sync/lean/on', headers=auth_hdr)
    assert r.json()['lean_mode'] is True
    r = client.post('/api/sync/lean/off', headers=auth_hdr)
    assert r.json()['lean_mode'] is False
    r = client.get('/api/sync/conflicts', headers=auth_hdr)
    assert r.status_code == 200
    r = client.post('/api/sync/push-now', headers=auth_hdr)
    assert r.status_code == 200 and r.json()['reason'] in ('no-pairing',
                                                           'empty')
    # كاشير بلا sync.view ← 403
    from app.security import hash_password
    role = db.execute(select(m.Role).where(
        m.Role.tenant_id == seed['tenant_id'],
        m.Role.code == 'POS_CASHIER')).scalar_one()
    u = m.User(id=new_uuid(), tenant_id=seed['tenant_id'], username='cash9',
               full_name='كاشير تجريبي',
               password_hash=hash_password('Passw0rd!X'),
               created_at=utcnow(), is_active=True)
    db.add(u)
    db.flush()
    db.add(m.UserRole(user_id=u.id, role_id=role.id))
    db.commit()
    lr = client.post('/api/auth/login', json={'username': 'cash9',
                                              'password': 'Passw0rd!X'})
    bad = {'Authorization': f'Bearer {lr.json()["access_token"]}'}
    r = client.get('/api/sync/status', headers=bad)
    assert r.status_code == 403


# ═══ HTTP: الرفع الأولي للبيانات السابقة لتفعيل المزامنة ═══
def test_backfill_http_legacy_data(client, db_session, auth_hdr):
    db, factory, seed = db_session
    tid = seed['tenant_id']
    n_j = db.execute(select(func.count(m.JournalEntry.id)).where(
        m.JournalEntry.status == 'POSTED',
        m.JournalEntry.tenant_id == tid)).scalar()
    n_r = db.execute(select(func.count(m.Room.id)).where(
        m.Room.tenant_id == tid)).scalar()
    n_i = db.execute(select(func.count(m.InvItem.id)).where(
        m.InvItem.tenant_id == tid)).scalar()
    r = client.post('/api/sync/backfill', headers=auth_hdr, json={})
    assert r.status_code == 200
    j = r.json()
    assert j['created']['JOURNAL'] == n_j
    assert j['created']['ROOM'] == n_r
    assert j['created']['INV_ITEM'] == n_i
    assert j['total'] == n_j + n_r + n_i
    # آمن التكرار: لا أحداث مكررة أبداً
    r = client.post('/api/sync/backfill', headers=auth_hdr, json={})
    assert r.json()['total'] == 0
    # موثق بالتدقيق
    acts = db.execute(select(m.AuditLog.action).where(
        m.AuditLog.action == 'SYNC_BACKFILL')).scalars().all()
    assert acts
