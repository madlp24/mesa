"""Render a quote as the PDF the client receives.

This document is the one thing in the app that leaves the building, so it
carries prices and never cost, profit or margin: those exist for the person
sending the quote, not the person receiving it.
"""
from decimal import Decimal
from io import BytesIO

from django.utils.formats import date_format
from django.utils.translation import gettext as _
from django.utils.translation import pgettext
from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as pdfcanvas

from .models import Course, PricingMode

PAGE_W, PAGE_H = letter
MARGIN = 54
CONTENT_W = PAGE_W - MARGIN * 2

INK = Color(0.110, 0.102, 0.086)
MUTED = Color(0.420, 0.400, 0.360)
ACCENT = Color(0.549, 0.137, 0.094)
LINE = Color(0.780, 0.760, 0.720)
BAND = Color(0.925, 0.915, 0.895)
NOTE_BG = Color(0.965, 0.955, 0.940)
WHITE = Color(1, 1, 1)

REG, BOLD = "Helvetica", "Helvetica-Bold"

COL_QTY = MARGIN + CONTENT_W - 250
COL_UNIT = MARGIN + CONTENT_W - 130
COL_TOTAL = MARGIN + CONTENT_W


def _money(value) -> str:
    """Colombian formatting: thousands with dots, no decimals."""
    return f"{Decimal(value or 0):,.0f}".replace(",", ".")


def _wrap(text, font, size, width):
    words, lines, current = str(text or "").split(), [], ""
    for word in words:
        probe = f"{current} {word}".strip()
        if stringWidth(probe, font, size) <= width or not current:
            current = probe
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


class QuoteCanvas:
    def __init__(self, quote):
        self.quote = quote
        self.buffer = BytesIO()
        self.c = pdfcanvas.Canvas(self.buffer, pagesize=letter)
        self.page = 1
        self.y = 0

    # -- primitives ----------------------------------------------------------

    def text(self, s, x, y, size, bold=False, color=INK, spacing=0):
        # Character spacing lives on the text object, not the canvas.
        obj = self.c.beginText(x, y)
        obj.setFont(BOLD if bold else REG, size)
        obj.setFillColor(color)
        # Always set it, including 0: the value persists on the canvas and would
        # otherwise leak the masthead's spacing into every line below it.
        obj.setCharSpace(spacing)
        obj.textOut(str(s))
        self.c.drawText(obj)

    def text_right(self, s, x, y, size, bold=False, color=INK, spacing=0):
        obj = self.c.beginText(0, y)
        obj.setFont(BOLD if bold else REG, size)
        obj.setFillColor(color)
        obj.setCharSpace(spacing)
        width = stringWidth(str(s), BOLD if bold else REG, size) + spacing * len(str(s))
        obj.setTextOrigin(x - width, y)
        obj.textOut(str(s))
        self.c.drawText(obj)

    def rule(self, y, color=LINE, width=0.6):
        self.c.setStrokeColor(color)
        self.c.setLineWidth(width)
        self.c.line(MARGIN, y, MARGIN + CONTENT_W, y)

    def band(self, y, height, color=BAND, x=MARGIN, width=CONTENT_W):
        self.c.setFillColor(color)
        self.c.rect(x, y, width, height, stroke=0, fill=1)

    #: Table rows stop here, leaving air above the footer rule at MARGIN + 40.
    FLOOR = MARGIN + 46
    #: The totals block is the last thing on the page, so it may sit closer to
    #: the footer than a row that still has neighbours below it -- but not so
    #: close that it lands on the footer rule at MARGIN + 40.
    FLOOR_TOTALS = MARGIN + 50

    def room(self, needed, floor=None):
        if self.y - needed < (self.FLOOR if floor is None else floor):
            self.finish_page()
            self.start_page(first=False)

    # -- structure -----------------------------------------------------------

    def start_page(self, first):
        self.y = PAGE_H - MARGIN
        if first:
            self.masthead()
            self.meta()
            self.note()
        else:
            self.text(
                f"{self.quote.restaurant.name}  -  {self.quote.number}",
                MARGIN, self.y - 10, 9, bold=True, color=MUTED, spacing=1.2,
            )
            self.y -= 22
            self.rule(self.y)
            self.y -= 18
        self.table_head()

    def finish_page(self):
        self.rule(MARGIN + 40)
        self.text(self.quote.restaurant.name, MARGIN, MARGIN + 26, 8.5, bold=True, spacing=1.4)
        self.text_right(
            _("Page %(n)s") % {"n": self.page}, MARGIN + CONTENT_W, MARGIN + 15, 7.6, color=MUTED
        )
        self.c.showPage()
        self.page += 1

    def masthead(self):
        self.band(self.y - 4, 3, ACCENT)
        self.y -= 34
        name = self.quote.restaurant.name.upper()
        self.text(name, MARGIN, self.y, 20, bold=True, spacing=3.2)
        self.text_right(_("QUOTE"), MARGIN + CONTENT_W, self.y, 11, bold=True, color=ACCENT)
        self.y -= 13
        self.text(_("EVENTS"), MARGIN, self.y, 8.5, color=MUTED, spacing=2.4)
        self.text_right(self.quote.number, MARGIN + CONTENT_W, self.y, 13, bold=True)
        self.y -= 16
        self.rule(self.y, LINE, 0.8)
        self.y -= 22

    def meta(self):
        quote = self.quote
        fields = [
            (_("Client"), quote.client_name or "-"),
            (_("Concept"), quote.concept or "-"),
            (_("Quote date"), date_format(quote.created_at, "DATE_FORMAT")),
            (
                _("Event date"),
                date_format(quote.event_date, "DATE_FORMAT") if quote.event_date else _("To be defined"),
            ),
            (
                _("Guests"),
                f"{quote.guests}"
                + (_(" x %(n)s days") % {"n": quote.days} if quote.days > 1 else ""),
            ),
            (_("Payment terms"), quote.payment_terms or "-"),
        ]
        col_w, row_h = CONTENT_W / 3, 34
        for i, (label, value) in enumerate(fields):
            x = MARGIN + (i % 3) * col_w
            y = self.y - (i // 3) * row_h
            self.text(label.upper(), x, y, 6.6, color=MUTED, spacing=1.1)
            for j, line in enumerate(_wrap(value, BOLD, 10.5, col_w - 12)[:2]):
                self.text(line, x, y - 13 - j * 11, 10.5, bold=True)
        self.y -= row_h * 2 - 4

    def note(self):
        note = _(
            "To confirm and hold the date, transfer the deposit agreed in the payment terms above."
        )
        lines = _wrap(note, REG, 7.8, CONTENT_W - 20)
        height = len(lines) * 10 + 12
        self.band(self.y - height + 6, height, NOTE_BG)
        self.band(self.y - height + 6, height, ACCENT, x=MARGIN, width=2)
        y = self.y - 4
        for line in lines:
            self.text(line, MARGIN + 12, y, 7.8, color=MUTED)
            y -= 10
        self.y -= height + 8

    def table_head(self):
        per_guest = self.quote.pricing_mode == PricingMode.PER_GUEST
        # Contextual: the column heading and the grand total are different words
        # in Spanish even though both read "TOTAL" in English.
        self.text(_("DESCRIPTION"), MARGIN, self.y, 7, color=MUTED, spacing=1.2)
        self.text_right(pgettext("column heading", "QTY"), COL_QTY, self.y, 7, color=MUTED)
        if not per_guest:
            self.text_right(pgettext("column heading", "UNIT"), COL_UNIT, self.y, 7, color=MUTED)
            self.text_right(pgettext("column heading", "TOTAL"), COL_TOTAL, self.y, 7, color=MUTED)
        self.y -= 7
        self.rule(self.y, INK, 0.9)
        self.y -= 14

    def lines(self):
        quote = self.quote
        per_guest = quote.pricing_mode == PricingMode.PER_GUEST
        desc_w = COL_QTY - MARGIN - 66
        all_lines = list(quote.lines.all())

        for value, label in Course.choices:
            course_lines = [line for line in all_lines if line.course == value]
            if not course_lines:
                continue

            self.room(46)
            self.band(self.y - 4, 15)
            self.text(str(label).upper(), MARGIN + 7, self.y, 8, bold=True, spacing=1.6)
            if not per_guest:
                subtotal = sum(line.line_total for line in course_lines)
                self.text_right(_money(subtotal), COL_TOTAL - 7, self.y, 8, bold=True, color=MUTED)
            self.y -= 19

            for line in course_lines:
                name_lines = _wrap(line.name, BOLD, 9.5, desc_w)
                desc_lines = _wrap(line.description, REG, 7.8, desc_w) if line.description else []
                height = len(name_lines) * 11.5 + len(desc_lines) * 9.3 + 5
                self.room(height + 12)

                y = self.y
                for text in name_lines:
                    self.text(text, MARGIN, y, 9.5, bold=True)
                    y -= 11.5
                for text in desc_lines:
                    self.text(text, MARGIN, y + 1, 7.8, color=MUTED)
                    y -= 9.6

                self.text_right(f"{line.quantity:,.0f}".replace(",", "."), COL_QTY, self.y, 9.5)
                if not per_guest:
                    self.text_right(_money(line.unit_price), COL_UNIT, self.y, 9.5)
                    self.text_right(_money(line.line_total), COL_TOTAL, self.y, 9.5, bold=True)

                self.y -= height
                self.rule(self.y + 3, Color(0.895, 0.885, 0.865), 0.4)
                self.y -= 3
            self.y -= 4

    def totals(self):
        quote = self.quote
        per_guest = quote.pricing_mode == PricingMode.PER_GUEST
        rows = []
        if per_guest:
            rows.append((_("Price per guest"), _money(quote.price_per_guest)))
            rows.append((_("Guests"), str(quote.guests)))
            if quote.days > 1:
                rows.append((_("Days"), str(quote.days)))
        else:
            rows.append((_("Subtotal (tax included)"), _money(quote.subtotal)))
        rows.append((_("of which tax, already included"), _money(quote.tax_included)))
        if quote.charges_tip:
            rows.append((_("Suggested tip"), _money(quote.tip)))

        # Distance from here down to the last ink: 6 lead, the rows, a 2pt gap,
        # then the total box and the footnote below it. Measured rather than
        # padded — spending a whole page on three lines of totals is a bad trade.
        self.room(6 + len(rows) * 15 + 2 + 34 + 8, floor=self.FLOOR_TOTALS)
        self.y -= 6
        box_x = MARGIN + CONTENT_W - 250
        for label, value in rows:
            self.text(label, box_x, self.y, 9, color=MUTED)
            self.text_right(value, COL_TOTAL, self.y, 9.5)
            self.y -= 15

        self.y -= 2
        self.band(self.y - 22, 30, ACCENT, x=box_x, width=COL_TOTAL - box_x)
        self.text(_("TOTAL"), box_x + 10, self.y - 12, 9.5, bold=True, color=WHITE, spacing=1.6)
        self.text_right(_money(quote.total), COL_TOTAL - 10, self.y - 13, 15, bold=True, color=WHITE)
        self.y -= 34

        footer = _("Prices already include the consumption tax. The tip is voluntary.")
        self.text_right(footer, COL_TOTAL, self.y, 7.8, color=MUTED)
        self.y -= 14

    def build(self) -> bytes:
        self.start_page(first=True)
        self.lines()
        self.totals()
        self.finish_page()
        self.c.save()
        return self.buffer.getvalue()


def render_quote_pdf(quote) -> bytes:
    return QuoteCanvas(quote).build()
