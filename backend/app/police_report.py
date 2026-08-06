"""مولّد «المعلومية اليومية» للبحث الجنائي (0.14.0 — طلب المالك).

يولّد ملف Excel مطابقاً في التصميم للقالب المعتمد (نموذج فندق دبي السياحي
المؤكد من المالك): ورقة RTL بلا شبكة، Times New Roman، ترويسة رسمية
(وزارة السياحة/المكتب/الفندق/العنوان/المديرية)، صفّا رؤوس مدمجان لـ14
عموداً، دمج خلايا كل مجموعة (نزيل رئيسي + مرافقيه)، تنسيق تاريخ عربي،
وطباعة A4 عرضية جاهزة.

قاعدة الأمان (ملف 10): أرقام الهوية تبقى مشفرة في الحمولة المؤرشفة، ولا
تُفك إلا لحظة بناء الملف نفسه — والتنزيل كله موثق باسم فاعله.
"""
from __future__ import annotations

import hashlib
import io
import json
from datetime import date, datetime, time, timezone

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from sqlalchemy import select

from . import models as m
from .security import decrypt_pii

WEEKDAYS_AR = ['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة',
               'السبت', 'الأحد']

AR_DATE_FMT = '[$-10C0000]d\\ mmmm\\ yyyy;@'  # «24 يونيو 2024» كما في القالب

_COL_WIDTHS = {'A': 4.0, 'B': 10.7, 'C': 27.1, 'D': 14.6, 'E': 14.7,
               'F': 11.4, 'G': 14.3, 'H': 11.3, 'I': 22.2, 'J': 12.7,
               'K': 21.8, 'L': 12.0, 'M': 6.9, 'N': 29.4, 'O': 27.3}

_MED = Side(style='medium')
_THIN = Side(style='thin')
B_MED = Border(left=_MED, right=_MED, top=_MED, bottom=_MED)
B_HEAD = Border(left=_MED, right=_MED, top=_MED, bottom=_THIN)

_CENTER = Alignment(horizontal='center', vertical='center')
_CENTER_W = Alignment(horizontal='center', vertical='center', wrap_text=True)
_LEFT_W = Alignment(horizontal='left', vertical='center', wrap_text=True)


def _f(sz: int) -> Font:
    return Font(name='Times New Roman', size=sz, bold=True)


def _safe_pii(token: str) -> str:
    """يفك رقم الهوية لحظة التوليد فقط؛ لا نخزّنه صريحاً في أي أرشيف."""
    if not token:
        return ''
    try:
        return decrypt_pii(token)
    except Exception:
        return ''


def collect_payload(db, tenant_id: str, day: date) -> dict:
    """يجمع نزلاء «من لامس الفندق ذلك اليوم» (قرار المالك):
    كل حجز وصل فعلاً (CHECKED_IN / CHECKED_OUT) يتداخل مع اليوم —
    بمن فيهم من سجّل وغادر في اليوم نفسه (الاستخدام النهاري).
    يستثني الملغي وعدم الحضور والمبدئي والمؤكد الذي لم يصل بعد."""
    st = db.execute(
        select(m.Reservation).where(
            m.Reservation.tenant_id == tenant_id,
            m.Reservation.status.in_(('CHECKED_IN', 'CHECKED_OUT')),
            m.Reservation.arrival_date <= day,
            m.Reservation.departure_date >= day,
        )).scalars().all()

    def _sort_key(r: m.Reservation):
        at = r.checked_in_at or datetime.combine(
            r.arrival_date, time(12), tzinfo=timezone.utc)
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        room = db.get(m.Room, r.room_id) if r.room_id else None
        return (at, room.room_no if room else '9999')

    rows: list[dict] = []
    warnings: list[str] = []
    serial = 0
    for gi, r in enumerate(sorted(st, key=_sort_key), start=1):
        room = db.get(m.Room, r.room_id) if r.room_id else None
        g = db.get(m.Guest, r.guest_id)
        companions = db.execute(
            select(m.ReservationCompanion).where(
                m.ReservationCompanion.reservation_id == r.id)
            .order_by(m.ReservationCompanion.sort_order,
                      m.ReservationCompanion.created_at)).scalars().all()

        if not g or not g.id_number_enc:
            warnings.append(
                f'غرفة {room.room_no if room else "؟"}: '
                f'{g.full_name if g else "؟"} بلا رقم هوية (ناقص في المعلومية)')
        if not r.purpose:
            warnings.append(
                f'غرفة {room.room_no if room else "؟"}: الغرض من القدوم فارغ')

        in_at = r.checked_in_at
        serial += 1
        rows.append({
            'kind': 'main', 'stay': gi, 'serial': serial,
            'room_no': room.room_no if room and room.room_no else '',
            'name': g.full_name if g else '—',
            'arrival': r.arrival_date.isoformat(),
            'purpose': r.purpose,
            'origin_gov': r.origin_gov,
            'origin_district': r.origin_district,
            'id_type': (g.id_type if g else ''),
            'id_enc': (g.id_number_enc if g else ''),
            'issue_place': (g.id_issue_place if g else ''),
            'issue_date': (g.id_issue_date.isoformat()
                           if g and g.id_issue_date else ''),
            'phone': (g.phone if g else ''),
            'in_time': in_at.strftime('%H:%M') if in_at else '',
            'notes': r.police_notes,
            'vehicle': r.vehicle_note,
        })
        for c in companions:
            if not c.id_number_enc:
                warnings.append(f'المرافق «{c.full_name}» بلا رقم هوية')
            serial += 1
            rows.append({
                'kind': 'companion', 'stay': gi, 'serial': serial,
                'room_no': '', 'name': c.full_name, 'arrival': '',
                'purpose': '', 'origin_gov': c.origin_gov,
                'id_type': c.id_type,
                'origin_district': c.origin_district,
                'id_enc': c.id_number_enc,
                'issue_place': c.id_issue_place,
                'issue_date': (c.id_issue_date.isoformat()
                               if c.id_issue_date else ''),
                'phone': c.phone, 'in_time': '', 'notes': '', 'vehicle': '',
            })

    t = db.get(m.Tenant, tenant_id)
    header = {
        'hotel': (t.trade_name or t.legal_name) if t else '',
        'address': t.address if t else '',
        'district': t.district if t else '',
        'office': t.office_label if t else '',
        'weekday': WEEKDAYS_AR[day.weekday()],
        'date': day.isoformat(),
    }
    return {'header': header, 'rows': rows, 'warnings': warnings,
            'stays_count': len(st), 'rows_count': len(rows)}


def payload_sha256(payload: dict) -> str:
    """بصمة مستقرة للمحتوى (تجاهل التحذيرات — لا تدخل الملف)."""
    body = json.dumps({'header': payload['header'], 'rows': payload['rows']},
                      sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def build_xlsx(header: dict, rows: list[dict]) -> bytes:
    """يبني ملف Excel مطابقاً لتصميم القالب خلية بخلية (قابل لإعادة البناء
    من الحمولة المؤرشفة فينتج نفس المحتوى حرفياً بعد أي تعديل لاحق)."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'ورقة1'
    ws.sheet_view.rightToLeft = True
    ws.sheet_view.showGridLines = False
    for col, w in _COL_WIDTHS.items():
        ws.column_dimensions[col].width = w

    day = date.fromisoformat(header['date'])

    def put(coord, value, size=12, merge=None, border=None, align=_CENTER,
            fmt=None):
        if merge:
            ws.merge_cells(merge)
        c = ws[coord]
        c.value = value
        c.font = _f(size)
        c.alignment = align
        if fmt:
            c.number_format = fmt
        if border:
            _paint_border(merge or coord, border)

    def _paint_border(rng, border):
        if isinstance(rng, str) and ':' not in rng:
            ws[rng].border = border
            return
        for row in ws[rng]:
            for c in row:
                c.border = border

    # ── الترويسة الرسمية (صفوف 1-5) ──
    put('M2', f'فندق: {header["hotel"]}', merge='M2:O2')
    put('A3', 'وزارة الســيـاحة', merge='A3:C3')
    put('M3', f'العنوان :{header["address"]}', merge='M3:O3')
    put('A4', header['office'] or 'م / …', merge='A4:C4')
    put('M4', f'مديرية: {header["district"]}', merge='M4:O4')
    put('D5', f'معلومية النزلاء ليوم  {header["weekday"]}', size=14,
        merge='D5:F5', border=B_MED, align=_CENTER_W)
    ws['D5'].border = Border(bottom=_MED)
    put('G5', day, size=14, fmt=AR_DATE_FMT)
    for rr, h in ((2, 14.25), (3, 14.25), (4, 14.25), (5, 18.75)):
        ws.row_dimensions[rr].height = h

    # ── صفّا رؤوس الأعمدة (6-7) ──
    heads = [
        ('A6', 'A6:A7', 'م', 11), ('B6', 'B6:B7', 'رقم الغرفة', 11),
        ('C6', 'C6:C7', 'اسم النزيل رباعياً مع اللقب', 12),
        ('D6', 'D6:D7', 'تاريخ القدوم', 11),
        ('E6', 'E6:E7', 'الغرض من القدوم', 11),
        ('F6', 'F6:G6', 'الجهة القادم منها', 14),
        ('H6', 'H6:J6', 'معلومية الهوية للأجانب واليمنيين', 12),
        ('K6', 'K6:K7', 'ت الإصدار', 12), ('L6', 'L6:L7', 'رقم التلفون', 12),
        ('M6', 'M6:M7', 'وقت النزول', 12),
        ('N6', 'N6:N7', 'المرافقين ( ملاحظات )', 12),
        ('O6', 'O6:O7', 'المركبات/ملاحظة', 12),
    ]
    for coord, rng, text, size in heads:
        put(coord, text, size=size, merge=rng, border=B_HEAD,
            align=_CENTER_W)
    put('F7', 'المحافظة', merge='F7:F7', border=B_HEAD)
    put('G7', 'المديرية', merge='G7:G7', border=B_HEAD)
    put('H7', 'نوعها', border=B_HEAD)
    put('I7', 'رقمها', border=B_HEAD)
    put('J7', 'مكان الإصدار', border=B_HEAD)
    ws.row_dimensions[6].height = 18.75
    ws.row_dimensions[7].height = 15.0

    # ── صفوف البيانات: نزيل رئيسي ثم مرافقوه، مع دمج خلايا المجموعة ──
    r = 8
    i = 0
    while i < len(rows):
        row = rows[i]
        j = i
        while j + 1 < len(rows) and rows[j + 1]['stay'] == row['stay']:
            j += 1
        span = j - i + 1  # عدد صفوف المجموعة (الرئيسي + مرافقوه)
        r_end = r + span - 1

        def cell(col, rr, value, fmt=None, align=_CENTER, size=11):
            c = ws[f'{col}{rr}']
            c.value = value
            c.font = _f(size)
            c.alignment = align
            c.border = B_MED
            if fmt:
                c.number_format = fmt

        for k in range(i, j + 1):
            d = rows[k]
            rr = r + (k - i)
            cell('A', rr, d['serial'])
            cell('C', rr, d['name'], align=_CENTER_W, size=12)
            cell('E', rr, d['purpose'])
            cell('F', rr, d['origin_gov'])
            cell('G', rr, d['origin_district'])
            cell('H', rr, d['id_type'])
            cell('I', rr, _safe_pii(d['id_enc']))
            cell('J', rr, d['issue_place'])
            cell('K', rr, date.fromisoformat(d['issue_date'])
                 if d['issue_date'] else None, fmt=AR_DATE_FMT)
            cell('L', rr, d['phone'])
            ws.row_dimensions[rr].height = 15.75

        # خلايا مستوى المجموعة (تُدمج عمودياً كما في القالب):
        def group_cell(col, value, fmt=None, align=_CENTER):
            rng = f'{col}{r}:{col}{r_end}' if span > 1 else None
            if rng:
                ws.merge_cells(rng)
            cell(col, r, value, fmt=fmt, align=align)
            if span > 1:
                _paint_border(f'{col}{r}:{col}{r_end}', B_MED)

        group_cell('B', row['room_no'] or None)
        group_cell('D', date.fromisoformat(row['arrival']), fmt=AR_DATE_FMT)
        group_cell('M', row['in_time'] or None)
        group_cell('N', row['notes'] or None, align=_LEFT_W)
        group_cell('O', row['vehicle'] or None, align=_LEFT_W)

        r = r_end + 1
        i = j + 1

    last = max(r - 1, 8)
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = 9  # A4
    ws.print_area = f'$A$1:$O${last + 6}'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def rows_public(rows: list[dict]) -> list[dict]:
    """نسخة معاينة آمنة: بلا أرقام هوية صريحة (تُظهر «موجود/مفقود» فقط)."""
    out = []
    for d0 in rows:
        d = dict(d0)
        d['has_id'] = bool(d.pop('id_enc'))
        out.append(d)
    return out
