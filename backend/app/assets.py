"""خدمة الأصول الثابتة والإهلاك — ملف 11 (ز) + حدث #24 (ملف 02 §8).

قواعد ثابتة:
- قيد الإهلاك الشهري #24: مدين حساب مصروف الأصل (افتراضي 7101) /
  دائن مجمع الإهلاك (افتراضي 1590) — عبر المحرك فقط وبنوع AUTO_DEPRECIATION.
- تشغيلة واحدة لكل شهر (قيد فريد + مفتاح Outbox) وبأثر رجعي ممنوع:
  كل أصل يحفظ last_run_month فلا يُحمَّل الشهر نفسه مرتين أبداً.
- الإهلاك يبدأ من الشهر التالي لتاريخ الشراء، ويتوقف عند الخردة (salvage)
  أرضيةً مطلقة، وعند الإعدام (DISPOSED) — ADR-0029.
- إزالة الأصل من الدفاتر عند الإعدام/البيع قيد يدوي موثق (لا حدث معرفاً
  في ملف 02 §8 حتى v1 — ADR-0030).
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m
from .audit import audit
from .posting import D, PostingError, create_and_post_journal, get_account


def _now() -> datetime:
    return datetime.now(timezone.utc)


def err(code: str, msg: str):
    raise PostingError(code, msg)


def q4(v: Decimal) -> Decimal:
    return Decimal(v).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)


MONTH_RE = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')


def _check_month(month: str) -> str:
    if not MONTH_RE.match(month or ''):
        err('FA.BAD_MONTH', 'صيغة الشهر يجب أن تكون YYYY-MM')
    return month


def _month_end(month: str) -> date:
    y, mo = int(month[:4]), int(month[5:7])
    return date(y, mo, calendar.monthrange(y, mo)[1])


def next_fa_code(db: Session, tenant_id: str) -> str:
    last = db.execute(
        select(m.FaAsset.code).where(m.FaAsset.tenant_id == tenant_id)
        .order_by(m.FaAsset.code.desc())).scalars().first()
    n = int(last.split('-')[1]) + 1 if last else 1
    return f'FA-{n:03d}'


# ────────────────────────────────────────────────────────────────────
# التسجيل
# ────────────────────────────────────────────────────────────────────
def create_asset(db: Session, *, tenant_id: str, actor_id: str, name: str,
                 category: str, purchase_date: date, cost: Decimal,
                 salvage: Decimal, useful_life_months: int, method: str,
                 asset_account_code: str, accum_account_code: str,
                 expense_account_code: str) -> m.FaAsset:
    cost, salvage = D(cost), D(salvage)
    if cost <= 0:
        err('FA.BAD_COST', 'تكلفة الأصل يجب أن تكون موجبة')
    if salvage < 0 or salvage >= cost:
        err('FA.BAD_SALVAGE', 'الخردة يجب أن تكون صفراً أو أكثر وأقل من التكلفة')
    if useful_life_months < 1 or useful_life_months > 600:
        err('FA.BAD_LIFE', 'العمر الإنتاجي بالأشهر بين 1 و600')
    if method not in ('STRAIGHT', 'DECLINING'):
        err('FA.BAD_METHOD', 'الطريقة STRAIGHT أو DECLINING')
    aa = get_account(db, tenant_id, asset_account_code)
    xa = get_account(db, tenant_id, accum_account_code)
    ea = get_account(db, tenant_id, expense_account_code)
    for acc, label, typ in ((aa, 'حساب الأصل', 'ASSET'),
                            (xa, 'مجمع الإهلاك', 'ASSET'),
                            (ea, 'مصروف الإهلاك', 'EXPENSE')):
        if not acc.is_postable:
            err('FA.PARENT_ACCOUNT', f'{label} أب — الترحيل على الأوراق فقط')
        if acc.type != typ:
            err('FA.BAD_ACCOUNT_TYPE',
                f'{label} يجب أن يكون من نوع {typ} لا {acc.type}')

    a = m.FaAsset(tenant_id=tenant_id, code=next_fa_code(db, tenant_id),
                  name=name.strip(), category=(category or '').strip(),
                  purchase_date=purchase_date, cost=cost, salvage=salvage,
                  useful_life_months=useful_life_months, method=method,
                  asset_account_id=aa.id, accum_account_id=xa.id,
                  expense_account_id=ea.id, created_by=actor_id)
    db.add(a)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='fa', action='asset.create', entity='fa_assets',
          entity_id=a.id,
          after={'code': a.code, 'name': a.name, 'cost': str(cost),
                 'life_months': useful_life_months, 'method': method},
          business_date=purchase_date)
    return a


def list_assets(db: Session, tenant_id: str) -> list[m.FaAsset]:
    return db.execute(
        select(m.FaAsset).where(m.FaAsset.tenant_id == tenant_id)
        .order_by(m.FaAsset.code)).scalars().all()


def get_asset(db: Session, tenant_id: str, asset_id: str) -> m.FaAsset:
    a = db.get(m.FaAsset, asset_id)
    if a is None or a.tenant_id != tenant_id:
        err('GENERAL.NOT_FOUND', 'الأصل غير موجود')
    return a


def dispose_asset(db: Session, *, tenant_id: str, actor_id: str,
                  asset_id: str, disposed_at: date, reason: str) -> m.FaAsset:
    a = get_asset(db, tenant_id, asset_id)
    if a.status == 'DISPOSED':
        err('FA.ALREADY_DISPOSED', 'الأصل مُعدَم مسبقاً')
    if disposed_at < a.purchase_date:
        err('FA.BAD_DISPOSE_DATE', 'تاريخ الإعدام قبل تاريخ الشراء')
    a.status = 'DISPOSED'
    a.disposed_at = disposed_at
    a.disposal_reason = reason.strip()
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='fa', action='asset.dispose', entity='fa_assets',
          entity_id=a.id,
          after={'disposed_at': str(disposed_at), 'reason': reason,
                 'nbv': str(D(a.cost) - D(a.depreciated_total))},
          business_date=disposed_at)
    return a


# ────────────────────────────────────────────────────────────────────
# الاحتساب
# ────────────────────────────────────────────────────────────────────
def _nbv(a: m.FaAsset) -> Decimal:
    return D(a.cost) - D(a.depreciated_total)


def _months_between(purchase: date, month: str) -> int:
    """أشهر الإهلاك المتراكمة واجبة الاحتساب حتى «month» شاملاً
    (البدء من الشهر التالي للشراء — ADR-0029)."""
    y, mo = int(month[:4]), int(month[5:7])
    return (y - purchase.year) * 12 + (mo - purchase.month)


def charge_for(a: m.FaAsset, month: str) -> Decimal:
    """قسط الشهر لأصل واحد بالهللة — دالة نقية تُستخدم أيضاً للجدولة."""
    nbv = _nbv(a)
    room = q4(nbv - D(a.salvage))
    if room <= 0:
        return Decimal('0')
    if a.method == 'STRAIGHT':
        base = q4((D(a.cost) - D(a.salvage)) / a.useful_life_months)
        if nbv - base < D(a.salvage):
            base = room  # القسط الأخير يهبط للخردة بالضبط
        return q4(base)
    # متناقص مضاعف شهرياً مع أرضية الخردة (ADR-0029)
    ch = q4(nbv * Decimal('2') / a.useful_life_months)
    if ch <= 0:
        return Decimal('0')
    if nbv - ch < D(a.salvage):
        ch = room
    return q4(ch)


def asset_schedule(a: m.FaAsset, from_month: str) -> list[dict]:
    """جدولة استشرافية 12 شهراً (لا تكتب شيئاً)."""
    out = []
    cost, dep = D(a.cost), D(a.depreciated_total)
    y, mo = int(from_month[:4]), int(from_month[5:7])
    for _ in range(12):
        month = f'{y:04d}-{mo:02d}'
        if a.status != 'ACTIVE' or _months_between(a.purchase_date, month) < 1:
            ch = Decimal('0')
        else:
            nbv = cost - dep
            room = q4(nbv - D(a.salvage))
            if room <= 0:
                ch = Decimal('0')
            elif a.method == 'STRAIGHT':
                base = q4((cost - D(a.salvage)) / a.useful_life_months)
                ch = q4(base if nbv - base >= D(a.salvage) else room)
            else:
                ch = q4(nbv * Decimal('2') / a.useful_life_months)
                if nbv - ch < D(a.salvage):
                    ch = room
        dep += ch
        out.append({'month': month, 'charge': str(q4(ch)),
                    'acc_dep': str(q4(dep)), 'nbv': str(q4(cost - dep))})
        mo += 1
        if mo > 12:
            mo, y = 1, y + 1
    return out


# ────────────────────────────────────────────────────────────────────
# تشغيلة الشهر (#24)
# ────────────────────────────────────────────────────────────────────
def run_depreciation(db: Session, *, tenant_id: str, actor_id: str,
                     branch_id: str, month: str) -> m.FaDepreciationRun:
    month = _check_month(month)
    dup = db.execute(
        select(m.FaDepreciationRun).where(
            m.FaDepreciationRun.tenant_id == tenant_id,
            m.FaDepreciationRun.month == month)).scalar_one_or_none()
    if dup is not None:
        err('FA.RUN_EXISTS', f'تشغيلة إهلاك {month} موجودة — الشهر يُشغَّل مرة واحدة')

    rows: list[tuple[m.FaAsset, Decimal]] = []
    for a in list_assets(db, tenant_id):
        if a.status != 'ACTIVE':
            continue
        if _months_between(a.purchase_date, month) < 1:
            continue  # الإهلاك من الشهر التالي للشراء
        if a.last_run_month and a.last_run_month >= month:
            continue  # محمي من أي إعادة (إضافةً لقيد الشهر الفريد)
        ch = charge_for(a, month)
        if ch > 0:
            rows.append((a, ch))
    if not rows:
        err('FA.NOTHING_TO_DEPRECIATE',
            f'لا أصول مستحقة الإهلاك في {month}')

    # قيد #24 مجمعاً حسب زوج (مصروف، مجمّع) — افتراضياً 7101/1590
    acc_ids = {a.expense_account_id for a, _ in rows} | \
              {a.accum_account_id for a, _ in rows}
    accs = {i: db.get(m.Account, i) for i in acc_ids}
    by_pair: dict[tuple[str, str], Decimal] = {}
    raw = []
    lines_snap = []
    total = Decimal('0')
    for a, ch in rows:
        key = (a.expense_account_id, a.accum_account_id)
        by_pair[key] = by_pair.get(key, Decimal('0')) + ch
        total += ch
        lines_snap.append({
            'asset_id': a.id, 'code': a.code, 'name': a.name,
            'method': a.method, 'cost': str(a.cost),
            'nbv_before': str(q4(_nbv(a))), 'charge': str(ch),
            'nbv_after': str(q4(_nbv(a) - ch))})
    for (ea_id, xa_id), amt in sorted(by_pair.items()):
        ea, xa = accs[ea_id], accs[xa_id]
        raw.append({'account': ea.code, 'debit': q4(amt), 'credit': Decimal('0'),
                    'description': f'إهلاك {month} — {ea.name_ar}'})
        raw.append({'account': xa.code, 'debit': Decimal('0'), 'credit': q4(amt),
                    'description': f'مجمع إهلاك {month}'})

    ent = create_and_post_journal(
        db, tenant_id=tenant_id, branch_id=branch_id,
        journal_type='AUTO_DEPRECIATION', entry_date=_month_end(month),
        narration=f'إهلاك الأصول الثابتة لشهر {month}',
        raw_lines=raw, actor_id=actor_id,
        source_type='FA_DEPRECIATION', source_id=month,
        event_key=f'fa:dep:{tenant_id}:{month}')
    for a, ch in rows:
        a.depreciated_total = q4(D(a.depreciated_total) + ch)
        a.last_run_month = month
    run = m.FaDepreciationRun(tenant_id=tenant_id, month=month,
                              lines=lines_snap, total=q4(total),
                              asset_count=len(rows), posted_entry_id=ent.id,
                              created_by=actor_id)
    db.add(run)
    db.flush()
    audit(db, tenant_id=tenant_id, actor_id=actor_id, actor_type='user',
          module='fa', action='depreciation.run', entity='fa_depreciation_runs',
          entity_id=run.id,
          after={'month': month, 'total': str(q4(total)), 'assets': len(rows),
                 'entry_id': ent.id},
          business_date=_month_end(month))
    return run


def list_runs(db: Session, tenant_id: str) -> list[m.FaDepreciationRun]:
    return db.execute(
        select(m.FaDepreciationRun).where(
            m.FaDepreciationRun.tenant_id == tenant_id)
        .order_by(m.FaDepreciationRun.month.desc())).scalars().all()


# ────────────────────────────────────────────────────────────────────
# سجل الأصول + مطابقة الأستاذ
# ────────────────────────────────────────────────────────────────────
def _gl_balance(db: Session, tenant_id: str, account_id: str,
                as_of: date) -> Decimal:
    """رصيد حساب عند تاريخ — مدرك لمرساة الافتتاحية (ADR-0031)."""
    from . import reports as R
    sums = R.account_sums(db, tenant_id, as_of)
    td, tc = sums.get(account_id, (Decimal('0'), Decimal('0')))
    return D(td) - D(tc)


def register_report(db: Session, tenant_id: str) -> dict:
    """السجل مقابل الأستاذ: NBV السجل = (حسابات الأصول المستخدمة − مجمعاتها)."""
    rows = []
    tot_cost = tot_dep = Decimal('0')
    used_assets: set[str] = set()
    used_accs: set[str] = set()
    for a in list_assets(db, tenant_id):
        nbv = _nbv(a)
        rows.append({'id': a.id, 'code': a.code, 'name': a.name,
                     'category': a.category, 'method': a.method,
                     'purchase_date': a.purchase_date.isoformat(),
                     'cost': str(a.cost), 'salvage': str(a.salvage),
                     'life_months': a.useful_life_months,
                     'depreciated_total': str(a.depreciated_total),
                     'nbv': str(q4(nbv)), 'status': a.status,
                     'last_run_month': a.last_run_month,
                     'disposed_at': (a.disposed_at.isoformat()
                                     if a.disposed_at else None)})
        if a.status == 'ACTIVE':
            tot_cost += D(a.cost)
            tot_dep += D(a.depreciated_total)
            used_assets.add(a.asset_account_id)
            used_accs.add(a.accum_account_id)
    # قيم GL لحسابات الأصول/المجمعات المستخدمة فقط (إزالة المُعدم يدوياً
    # تتم بقيد موثق فيظل متطابقاً ما دامت العملية مكتملة)
    gl_cost = sum((_gl_balance(db, tenant_id, i, date.today())
                   for i in used_assets), Decimal('0'))
    gl_accum = Decimal('0')
    for i in used_accs:
        gl_accum += -_gl_balance(db, tenant_id, i, date.today())
    reg_nbv = q4(tot_cost - tot_dep)
    gl_nbv = q4(gl_cost - gl_accum)
    return {'rows': rows,
            'totals': {'cost': str(q4(tot_cost)),
                       'depreciated': str(q4(tot_dep)),
                       'nbv': str(reg_nbv)},
            'gl': {'asset_accounts_cost': str(q4(gl_cost)),
                   'accum_depreciation': str(q4(gl_accum)),
                   'nbv': str(gl_nbv)},
            'matches_gl': reg_nbv == gl_nbv,
            'note': ('المطابقة تقارن صافي السجل بصافي الحسابات المستخدمة — '
                     'شراء الأصل نفسه قيد يدوي موثق (ADR-0030)')}
