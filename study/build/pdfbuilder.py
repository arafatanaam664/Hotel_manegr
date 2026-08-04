# -*- coding: utf-8 -*-
"""
منشئ الملف الرئيسي PDF — نظام أثير لإدارة الفنادق
يبني وثيقة عربية RTL احترافية: غلاف، فهرس، أغلفة أقسام، جداول، عناصر بصرية.
"""
import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, Table, TableStyle, PageBreak,
                                NextPageTemplate, Flowable, KeepTogether)
from reportlab.platypus.tableofcontents import TableOfContents

FONT_DIR = '/home/user/assets/fonts'
pdfmetrics.registerFont(TTFont('Amiri', f'{FONT_DIR}/Amiri-Regular.ttf'))
pdfmetrics.registerFont(TTFont('Amiri-Bold', f'{FONT_DIR}/Amiri-Bold.ttf'))
pdfmetrics.registerFont(TTFont('Kufi', f'{FONT_DIR}/NotoKufiArabic.ttf'))

# ─── الهوية البصرية ────────────────────────────────────────────────
NAVY   = colors.HexColor('#12314E')
NAVY2  = colors.HexColor('#1D4E79')
GOLD   = colors.HexColor('#C9A227')
TEAL   = colors.HexColor('#128771')
INK    = colors.HexColor('#1F2933')
GRAY   = colors.HexColor('#5B6470')
LIGHT  = colors.HexColor('#F4F6F8')
LINE   = colors.HexColor('#D7DEE5')
RED    = colors.HexColor('#B03A2E')

def R(t):
    """تحويل نص عربي للعرض RTL مع اللاتينية والأرقام."""
    if t is None:
        return ''
    return get_display(arabic_reshaper.reshape(str(t)))

def vrow_mark(n):
    return R('') + f' .{n}'

# ─── الأنماط ───────────────────────────────────────────────────────
def st(name, **kw):
    base = dict(fontName='Amiri', fontSize=11.5, leading=17.5,
                alignment=TA_RIGHT, textColor=INK, spaceAfter=4)
    base.update(kw)
    return ParagraphStyle(name, **base)

S = {
 'body'   : st('body'),
 'bodyg'  : st('bodyg', textColor=GRAY, fontSize=10.5, leading=15.5),
 'h1'     : st('h1', fontName='Kufi', fontSize=17, leading=24, textColor=NAVY,
               spaceBefore=10, spaceAfter=6),
 'h2'     : st('h2', fontName='Kufi', fontSize=13.5, leading=19, textColor=TEAL,
               spaceBefore=8, spaceAfter=4),
 'h3'     : st('h3', fontName='Kufi', fontSize=11.5, leading=17, textColor=NAVY2,
               spaceBefore=6, spaceAfter=3),
 'bullet' : st('bullet', rightIndent=10, spaceAfter=3),
 'cell'   : st('cell', fontSize=10, leading=14, alignment=TA_CENTER),
 'cellr'  : st('cellr', fontSize=10, leading=14, alignment=TA_RIGHT),
 'cellh'  : st('cellh', fontName='Kufi', fontSize=10.5, leading=14,
               alignment=TA_CENTER, textColor=colors.white),
 'mini'   : st('mini', fontSize=9.5, leading=13, textColor=GRAY),
}

class P(Paragraph):
    """Paragraph عربي جاهز (يحوّل تلقائياً)."""
    def __init__(self, text, style='body'):
        super().__init__(R(text), S[style] if isinstance(style, str) else style)

def bullets(items, numbered=False):
    out = []
    for i, it in enumerate(items, 1):
        mark = f' .{i}' if numbered else ' •'
        out.append(Paragraph(R(it) + mark, S['bullet']))
    return out

MAX_TBL_W_MM = 170

def rtable(headers, rows, widths=None, altr_rows=True, fs=10, hdr_fs=10.5,
           align=TA_CENTER):
    """جدول RTL: الأعمدة تُعرَّف منطقياً (أول عمود يظهر يميناً).
    widths بالمليمتر؛ تُقاس تلقائياً إن تجاوزت عرض الصفحة."""
    if align in (0, 1, True, False):          # 0=center, 1=right اختصار
        align = TA_RIGHT if align in (1, True) else TA_CENTER
    stt = ParagraphStyle('ch', parent=S['cellh'], fontSize=hdr_fs)
    stc = ParagraphStyle('cc', parent=S['cell'], fontSize=fs,
                         alignment=align, leading=fs + 4)
    data = [[Paragraph(R(h), stt) for h in reversed(headers)]]
    for r in rows:
        data.append([Paragraph(R(c), stc) if not isinstance(c, Paragraph)
                     else c for c in reversed(r)])
    if widths:
        total = sum(widths)
        scale = min(1.0, MAX_TBL_W_MM / total) if total > 0 else 1.0
        widths = [w * mm * scale for w in reversed(widths)]
    t = Table(data, colWidths=widths, repeatRows=1, hAlign='CENTER',
              splitByRow=1)
    style = [
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('GRID', (0, 0), (-1, -1), 0.6, LINE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]
    if altr_rows:
        for i in range(1, len(data)):
            if i % 2 == 0:
                style.append(('BACKGROUND', (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(style))
    return t

class Callout(Flowable):
    """صندوق معلومات/تنبيه أنيق بحد أيمن ذهبي."""
    def __init__(self, text, kind='info', width=170 * mm):
        super().__init__()
        self.text, self.kind, self.widthU = text, kind, width
        self._para = None
        kind_map = {'info': (NAVY2, LIGHT), 'warn': (RED, colors.HexColor('#FBEFED')),
                    'gold': (GOLD, colors.HexColor('#FBF6E7')),
                    'teal': (TEAL, colors.HexColor('#EAF6F3'))}
        self.edge, self.bg = kind_map.get(kind, kind_map['info'])

    def wrap(self, availWidth, availHeight):
        w = min(self.widthU, availWidth)
        style = ParagraphStyle('co', parent=S['body'], fontSize=11, leading=16,
                               textColor=INK)
        self._para = Paragraph(R(self.text), style)
        pw, ph = self._para.wrap(w - 16 * mm, availHeight)
        self.width, self.height = w, ph + 8 * mm
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(self.bg)
        c.setStrokeColor(self.edge)
        c.roundRect(0, 0, self.width, self.height, 2.5 * mm, fill=1, stroke=0)
        c.setFillColor(self.edge)
        c.rect(self.width - 2.6 * mm, 0, 2.6 * mm, self.height, fill=1, stroke=0)
        self._para.drawOn(c, 6 * mm, 4 * mm)
        c.restoreState()

class SectionCover(Flowable):
    """غلاف قسم: رقم كبير + عنوان + وصف."""
    def __init__(self, num, title, subtitle=''):
        super().__init__()
        self.num, self.title, self.subtitle = num, title, subtitle

    def wrap(self, availWidth, availHeight):
        self.width, self.height = availWidth, availHeight
        return self.width, self.height

    def draw(self):
        c = self.canv
        w, h = self.width, self.height
        c.saveState()
        c.setFillColor(NAVY)
        c.rect(0, h - 120 * mm, w, 120 * mm, fill=1, stroke=0)
        c.setFillColor(GOLD)
        c.rect(0, h - 122 * mm, w, 2 * mm, fill=1, stroke=0)
        # رقم القسم (شبح سفلي)
        c.setFillColor(colors.HexColor('#2A5A87'))
        c.setFont('Kufi', 80)
        c.drawRightString(w - 24 * mm, h - 106 * mm, f'{self.num:02d}')
        # شريط جانبي
        c.setFillColor(GOLD)
        c.rect(w - 8 * mm, h - 72 * mm, 3 * mm, 44 * mm, fill=1, stroke=0)
        # عنوان
        c.setFillColor(colors.white)
        c.setFont('Kufi', 28)
        c.drawRightString(w - 15 * mm, h - 56 * mm, R(self.title))
        if self.subtitle:
            c.setFillColor(colors.HexColor('#BCCBDB'))
            c.setFont('Amiri', 13.5)
            c.drawRightString(w - 15 * mm, h - 68 * mm, R(self.subtitle))
        c.restoreState()

    def getSpaceAfter(self):
        return 8 * mm


class KPIRow(Flowable):
    """صف بطاقات أرقام رئيسية."""
    def __init__(self, items, height=26 * mm):
        super().__init__()
        # items: [(القيمة, الوصف)]
        self.items, self.h = items, height

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        return self.width, self.h

    def draw(self):
        c = self.canv
        n = len(self.items)
        gap = 4 * mm
        cw = (self.width - gap * (n - 1)) / n
        for i, (val, label) in enumerate(self.items):
            # RTL: أول بطاقة يميناً
            x = self.width - (i + 1) * cw - i * gap
            c.setFillColor(LIGHT if i % 2 == 0 else colors.HexColor('#EDF3F8'))
            c.roundRect(x, 0, cw, self.h, 2 * mm, fill=1, stroke=0)
            c.setFillColor(GOLD)
            c.rect(x, self.h - 1.6 * mm, cw, 1.6 * mm, fill=1, stroke=0)
            c.setFillColor(NAVY)
            c.setFont('Kufi', 15)
            c.drawCentredString(x + cw / 2, self.h - 11 * mm, R(val))
            c.setFillColor(GRAY)
            c.setFont('Amiri', 10)
            c.drawCentredString(x + cw / 2, self.h - 20 * mm, R(label))

class ProcessSteps(Flowable):
    """خطوات عملية كبطاقات متتابعة يمين→يسار."""
    def __init__(self, steps, height=20 * mm, color=TEAL):
        super().__init__()
        self.steps, self.h, self.color = steps, height, color

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        return self.width, self.h

    def draw(self):
        c = self.canv
        n = len(self.steps)
        gap = 5 * mm
        cw = (self.width - gap * (n - 1)) / n
        for i, sText in enumerate(self.steps):
            x = self.width - (i + 1) * cw - i * gap
            c.setFillColor(self.color if i % 2 == 0 else NAVY2)
            c.roundRect(x, 3 * mm, cw, self.h - 3 * mm, 2 * mm, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont('Amiri-Bold', 10)
            c.drawCentredString(x + cw / 2, self.h - 9 * mm, R(sText))
            if i < n - 1:
                c.setFillColor(GOLD)
                ax, ay = x - gap / 2, self.h - 8 * mm
                p = c.beginPath()
                p.moveTo(ax - 1.6 * mm, ay - 2 * mm)
                p.lineTo(ax + 1.6 * mm, ay)
                p.lineTo(ax - 1.6 * mm, ay + 2 * mm)
                p.close()
                c.drawPath(p, fill=1, stroke=0)

class BarChart(Flowable):
    """أعمدة بيانية أفقية بسيطة للتوقعات المالية."""
    def __init__(self, rows, maxv, height=None):
        super().__init__()
        # rows: [(تسمية, قيمة, عنوان قيمة)]
        self.rows, self.maxv = rows, maxv
        self.rh = 11 * mm
        self.h = height or (len(rows) * self.rh + 4 * mm)

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        return self.width, self.h

    def draw(self):
        c = self.canv
        label_w = 34 * mm
        val_w = 26 * mm
        bar_w = self.width - label_w - val_w - 6 * mm
        y = self.h - self.rh
        for i, (label, val, disp) in enumerate(self.rows):
            x0 = self.width  # من اليمين
            c.setFillColor(INK)
            c.setFont('Amiri-Bold', 10.5)
            c.drawRightString(x0, y + self.rh / 2 - 3 * mm, R(label))
            bx = x0 - label_w - bar_w
            w = max(2, bar_w * val / self.maxv)
            c.setFillColor(NAVY2 if i % 2 == 0 else TEAL)
            c.roundRect(bx + (bar_w - w), y + 1.5 * mm, w, self.rh - 4 * mm,
                        1.2 * mm, fill=1, stroke=0)
            c.setFillColor(GRAY)
            c.setFont('Amiri', 10)
            c.drawString(bx - val_w + 2 * mm, y + self.rh / 2 - 3 * mm, R(disp))
            y -= self.rh

# ─── القوالب والصفحات ────────────────────────────────────────────
DOC_TITLE = 'الدراسة التأسيسية الكاملة — نظام أثير لإدارة الفنادق'
PAGE_W, PAGE_H = A4

def on_body(canvas, doc):
    canvas.saveState()
    # ترويسة
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(1.2)
    canvas.line(18 * mm, PAGE_H - 14 * mm, PAGE_W - 18 * mm, PAGE_H - 14 * mm)
    canvas.setFont('Amiri', 9)
    canvas.setFillColor(GRAY)
    canvas.drawRightString(PAGE_W - 18 * mm, PAGE_H - 12 * mm, R(DOC_TITLE))
    canvas.drawString(18 * mm, PAGE_H - 12 * mm, 'v1.0 — 2026-08-04')
    # تذييل
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.7)
    canvas.line(18 * mm, 15 * mm, PAGE_W - 18 * mm, 15 * mm)
    canvas.setFont('Kufi', 9.5)
    canvas.setFillColor(NAVY2)
    canvas.drawCentredString(PAGE_W / 2, 9.5 * mm, f'— {doc.page} —')
    canvas.setFont('Amiri', 8.5)
    canvas.setFillColor(GRAY)
    canvas.drawRightString(PAGE_W - 18 * mm, 9.5 * mm, R('وثيقة سرية للاستخدام الداخلي'))
    canvas.drawString(18 * mm, 9.5 * mm, 'Atheer Hospitality ERP')
    canvas.restoreState()

def on_cover(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setFillColor(GOLD)
    canvas.rect(0, PAGE_H - 10 * mm, PAGE_W, 10 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor('#1D4E79'))
    canvas.circle(PAGE_W - 30 * mm, PAGE_H - 60 * mm, 55 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor('#17415F'))
    canvas.circle(28 * mm, 40 * mm, 48 * mm, fill=1, stroke=0)
    canvas.restoreState()

class RTDoc(BaseDocTemplate):
    def afterFlowable(self, fl):
        if isinstance(fl, Paragraph):
            stl = fl.style.name
            if stl in ('h1', 'h2'):
                level = 0 if stl == 'h1' else 1
                self.notify('TOCEntry', (level, fl.text, self.page))


def build(out_path, blocks):
    doc = RTDoc(out_path, pagesize=A4,
                leftMargin=18 * mm, rightMargin=18 * mm,
                topMargin=20 * mm, bottomMargin=19 * mm,
                title=DOC_TITLE, author='Atheer ERP — دراسة تأسيسية')
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  id='main')
    cover_frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width,
                        doc.height, id='cover')
    doc.addPageTemplates([
        PageTemplate(id='cover', frames=[cover_frame], onPage=on_cover),
        PageTemplate(id='body', frames=[frame], onPage=on_body),
    ])

    story = _cover_story_blocks()

    for b in blocks:
        kind = b[0]
        if kind == 'h1':
            story.append(Paragraph(R(b[1]), ParagraphStyle('h1', parent=S['h1'])))
        elif kind == 'h2':
            story.append(Paragraph(R(b[1]), ParagraphStyle('h2', parent=S['h2'])))
        elif kind == 'h3':
            story.append(Paragraph(R(b[1]), ParagraphStyle('h3', parent=S['h3'])))
        elif kind == 'p':
            story.append(P(b[1]))
        elif kind == 'pg':   # فقرة رمادية
            story.append(P(b[1], 'bodyg'))
        elif kind == 'mini':
            story.append(P(b[1], 'mini'))
        elif kind == 'bullets':
            story.extend(bullets(b[1]))
            story.append(Spacer(1, 2 * mm))
        elif kind == 'numbers':
            story.extend(bullets(b[1], numbered=True))
            story.append(Spacer(1, 2 * mm))
        elif kind == 'table':
            kw = b[3] if len(b) > 3 else {}
            story.append(Spacer(1, 1.5 * mm))
            story.append(rtable(b[1], b[2], **kw))
            story.append(Spacer(1, 2.5 * mm))
        elif kind == 'callout':
            story.append(Spacer(1, 1.5 * mm))
            story.append(Callout(b[1], *(b[2:] or ['info'])))
            story.append(Spacer(1, 2.5 * mm))
        elif kind == 'kpi':
            story.append(KPIRow(b[1]))
            story.append(Spacer(1, 3 * mm))
        elif kind == 'steps':
            story.append(ProcessSteps(b[1]))
            story.append(Spacer(1, 3 * mm))
        elif kind == 'bars':
            story.append(BarChart(b[1], b[2]))
            story.append(Spacer(1, 2 * mm))
        elif kind == 'section':
            story.append(NextPageTemplate('body'))
            story.append(PageBreak())
            story.append(SectionCover(b[1], b[2], b[3] if len(b) > 3 else ''))
        elif kind == 'pagebreak':
            story.append(PageBreak())
        elif kind == 'toc':
            story.append(NextPageTemplate('body'))
            story.append(PageBreak())
            story.extend(_toc_flowables())
        elif kind == 'spacer':
            story.append(Spacer(1, b[1] * mm))

    doc.multiBuild(story)
    print(f'PDF built: {out_path}')


def _cover_story_blocks():
    sp = lambda h: Spacer(1, h * mm)
    title_st = ParagraphStyle('cvt', fontName='Kufi', fontSize=30, leading=42,
                              textColor=colors.white, alignment=TA_RIGHT)
    sub_st = ParagraphStyle('cvs', fontName='Amiri-Bold', fontSize=16,
                            leading=24, textColor=GOLD, alignment=TA_RIGHT)
    txt_st = ParagraphStyle('cvd', fontName='Amiri', fontSize=12, leading=19,
                            textColor=colors.HexColor('#C7D3E0'),
                            alignment=TA_RIGHT)
    badge_st = ParagraphStyle('cvb', fontName='Kufi', fontSize=11,
                              textColor=colors.white, alignment=TA_RIGHT)
    return [
        sp(28),
        Paragraph(R('نظام أثير لإدارة الفنادق'), title_st),
        Paragraph(R('Atheer Hospitality ERP — Accounting-First Hotel Management'), 
                  ParagraphStyle('x', parent=txt_st, fontSize=11)),
        sp(4),
        Paragraph(R('الدراسة التأسيسية الشاملة للمنتج'), sub_st),
        sp(8),
        Paragraph(R('نظام ERP محاسبي إداري متكامل للفنادق يعمل محلياً وسحابياً '
                    'وهجيناً من قاعدة كود واحدة — مبني على محرك قيد مزدوج صارم '
                    'لا يقبل الخطأ، محمي بترخيص مشفر، ويُدار تجارياً من لوحة '
                    'تحكم مركزية للشركة.'), txt_st),
        sp(16),
        Paragraph(R('محتوى هذه الوثيقة'), 
                  ParagraphStyle('b', parent=badge_st, textColor=GOLD)),
        sp(2),
        Paragraph(R('ملخص تنفيذي • رؤية ورسالة • دراسة سوق • نموذج العمل • '
                    'معمارية النظام • الإطار المحاسبي • العمليات الفندقية • '
                    'المعمارية الهجينة • التراخيص • الأمان • المخاطر • التوسع • '
                    'التعافي من الكوارث • خارطة التنفيذ • الإسقاط المالي • الامتثال'),
                  ParagraphStyle('z', parent=txt_st, fontSize=11)),
        sp(85),
        Paragraph(R('الإصدار 1.0 • 4 أغسطس 2026 • وثيقة مرجعية معتمدة'), txt_st),
        Paragraph(R('سريّة وخاصة بفريق المشروع — لا يجوز توزيعها خارجياً'),
                  ParagraphStyle('y', parent=txt_st, textColor=GOLD)),
        NextPageTemplate('body'),
    ]


def _toc_flowables():
    head = ParagraphStyle('toch', fontName='Kufi', fontSize=20, leading=28,
                          textColor=NAVY, alignment=TA_RIGHT, spaceAfter=8)
    toc = TableOfContents()
    levels = [
        ParagraphStyle('t0', fontName='Amiri-Bold', fontSize=12.5, leading=20,
                       textColor=NAVY, alignment=TA_RIGHT, rightIndent=2),
        ParagraphStyle('t1', fontName='Amiri', fontSize=11, leading=17,
                       textColor=INK, alignment=TA_RIGHT, rightIndent=14),
    ]
    toc.levelStyles = levels
    toc.dotsMinLevel = 0
    return [Paragraph(R('فهرس المحتويات'), head), Spacer(1, 3 * mm), toc,
            PageBreak()]
