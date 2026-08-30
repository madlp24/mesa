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
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as pdfcanvas

from .models import Course, PricingMode

PAGE_W, PAGE_H = letter
MARGIN = 54
CONTENT_W = PAGE_W - MARGIN * 2

INK = Color(0.110, 0.102, 0.086)
MUTED = Color(0.420, 0.400, 0.360)
#: The red of the house mark, sampled from the emblem itself.
ACCENT = Color(0.878, 0.063, 0.125)
ACCENT_DEEP = Color(0.678, 0.055, 0.106)
LINE = Color(0.855, 0.835, 0.815)
BAND = Color(0.973, 0.957, 0.953)
WHITE = Color(1, 1, 1)

REG, BOLD = "Helvetica", "Helvetica-Bold"
#: A serif carries the wordmark, the way the house's own stationery does.
SERIF, SERIF_BOLD = "Times-Roman", "Times-Bold"

#: How much of the emblem survives behind the text.
WATERMARK_ALPHA = 0.07
WATERMARK_SIZE = 340

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
    def __init__(self, quote, tight=1.0):
        self.quote = quote
        #: Vertical breathing room, 1.0 being the designed spacing. Lowered only
        #: when doing so saves the reader a page (see ``render_quote_pdf``).
        self.tight = tight
        self.buffer = BytesIO()
        self.c = pdfcanvas.Canvas(self.buffer, pagesize=letter)
        self.page = 1
        self.y = 0

    def gap(self, points):
        """A vertical gap, shrunk when the document is being squeezed."""
        return points * self.tight

    # -- primitives ----------------------------------------------------------

    def _font(self, bold, serif):
        if serif:
            return SERIF_BOLD if bold else SERIF
        return BOLD if bold else REG

    def text(self, s, x, y, size, bold=False, color=INK, spacing=0, serif=False):
        # Character spacing lives on the text object, not the canvas.
        obj = self.c.beginText(x, y)
        obj.setFont(self._font(bold, serif), size)
        obj.setFillColor(color)
        # Always set it, including 0: the value persists on the canvas and would
        # otherwise leak the masthead's spacing into every line below it.
        obj.setCharSpace(spacing)
        obj.textOut(str(s))
        self.c.drawText(obj)

    def text_right(self, s, x, y, size, bold=False, color=INK, spacing=0, serif=False):
        font = self._font(bold, serif)
        obj = self.c.beginText(0, y)
        obj.setFont(font, size)
        obj.setFillColor(color)
        obj.setCharSpace(spacing)
        width = stringWidth(str(s), font, size) + spacing * len(str(s))
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
    FLOOR_TOTALS = MARGIN + 44

    def room(self, needed, floor=None):
        if self.y - needed < (self.FLOOR if floor is None else floor):
            self.finish_page()
            self.start_page(first=False)

    # -- structure -----------------------------------------------------------

    def watermark(self):
        """The house emblem, faded far enough back to read straight through."""
        raw = self.quote.restaurant.logo
        if not raw:
            return
        try:
            from PIL import Image

            img = Image.open(BytesIO(bytes(raw))).convert("RGBA")
            alpha = img.split()[3].point(lambda v: int(v * WATERMARK_ALPHA))
            img.putalpha(alpha)
            side = WATERMARK_SIZE
            self.c.drawImage(
                ImageReader(img),
                (PAGE_W - side) / 2,
                (PAGE_H - side) / 2 - 30,
                width=side,
                height=side * img.height / img.width,
                mask="auto",
            )
        except Exception:
            # A logo that will not decode must never cost the client their quote.
            return

    def start_page(self, first):
        self.y = PAGE_H - MARGIN
        self.watermark()
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
        self.rule(MARGIN + 40, ACCENT, 0.7)
        self.text(self.quote.restaurant.name, MARGIN, MARGIN + 26, 8.5,
                  bold=True, color=ACCENT_DEEP, spacing=1.4, serif=True)
        self.text_right(
            _("Page %(n)s") % {"n": self.page}, MARGIN + CONTENT_W, MARGIN + 15, 7.6, color=MUTED
        )
        self.c.showPage()
        self.page += 1

    def masthead(self):
        """The house mark on the left, what the document is on the right."""
        self.band(self.y - 2, 2.5, ACCENT)
        self.y -= 30
        self.text(
            self.quote.restaurant.name.upper(), MARGIN, self.y, 17,
            bold=True, color=INK, spacing=2.6, serif=True,
        )
        self.text_right(_("Quotation"), MARGIN + CONTENT_W, self.y + 2, 21, color=ACCENT, serif=True)
        self.y -= 12
        self.text(_("EVENTS"), MARGIN, self.y, 7, color=MUTED, spacing=2.2)
        self.text_right(
            f"{_('No.')} {self.quote.number}", MARGIN + CONTENT_W, self.y, 10.5, bold=True
        )
        self.y -= 13
        self.rule(self.y, LINE, 0.7)
        self.y -= self.gap(20)

    def meta(self):
        """Value first, label under it in red -- the house's own stationery."""
        quote = self.quote
        guests = str(quote.guests) + (
            _(" x %(n)s days") % {"n": quote.days} if quote.days > 1 else ""
        )
        fields = [
            (_("Client"), quote.client_name or "-"),
            (_("Concept"), quote.concept or "-"),
            (_("Quote date"), date_format(quote.created_at, "DATE_FORMAT")),
            (
                _("Event date"),
                date_format(quote.event_date, "DATE_FORMAT") if quote.event_date else _("To be defined"),
            ),
            (_("Guests"), guests),
            (_("Payment terms"), quote.payment_terms or "-"),
        ]
        col_w, row_h = CONTENT_W / 3, self.gap(32)
        for i, (label, value) in enumerate(fields):
            x = MARGIN + (i % 3) * col_w
            top = self.y - (i // 3) * row_h
            # The rule and its label sit at a fixed depth in the cell and the
            # value stacks upward from them: a two-line value that grew
            # downward would land on the row underneath.
            base = top - 20
            wrapped = _wrap(value, BOLD, 10, col_w - 14)[:2]
            for j, line in enumerate(reversed(wrapped)):
                self.text(line, x, base + 4 + j * 10.6, 10, bold=True)
            self.c.setStrokeColor(LINE)
            self.c.setLineWidth(0.5)
            self.c.line(x, base, x + col_w - 18, base)
            self.text(label.upper(), x, base - 7, 6.4, color=ACCENT, spacing=1.0)
        # The rule and label sit at a fixed depth inside the cell, so only the
        # row pitch and the trailing gap may shrink -- take the fixed 27 out of
        # the squeeze or the note strip lands on the last row of labels.
        self.y -= row_h + 27 + self.gap(10)

    def note(self):
        """The quote's own conditions when it has them, the standing one when not."""
        note = self.quote.notes.strip() or _(
            "To confirm and hold the date, transfer the deposit agreed in the payment terms above."
        )
        lines = []
        for paragraph in note.splitlines():
            lines.extend(_wrap(paragraph, REG, 7.6, CONTENT_W - 24) if paragraph.strip() else [""])
        height = len(lines) * 9.6 + 11
        self.band(self.y - height + 6, height, BAND)
        self.band(self.y - height + 6, height, ACCENT, x=MARGIN, width=1.8)
        y = self.y - 3
        for line in lines:
            self.text(line, MARGIN + 12, y, 7.6, color=MUTED)
            y -= 9.6
        self.y -= height + self.gap(5)

    def table_head(self):
        per_guest = self.quote.pricing_mode == PricingMode.PER_GUEST
        self.text(_("DESCRIPTION"), MARGIN, self.y, 6.8, color=ACCENT, spacing=1.3)
        if self.quote.show_quantities:
            self.text_right(pgettext("column heading", "QTY"), COL_QTY, self.y, 6.8, color=ACCENT, spacing=0.6)
        if not per_guest:
            self.text_right(pgettext("column heading", "UNIT"), COL_UNIT, self.y, 6.8, color=ACCENT, spacing=0.6)
            self.text_right(pgettext("column heading", "TOTAL"), COL_TOTAL, self.y, 6.8, color=ACCENT, spacing=0.6)
        self.y -= 7
        self.rule(self.y, ACCENT, 0.9)
        self.y -= self.gap(13)

    def lines(self):
        quote = self.quote
        per_guest = quote.pricing_mode == PricingMode.PER_GUEST
        desc_w = COL_QTY - MARGIN - 66
        all_lines = quote.food_lines

        for value, label in Course.choices:
            course_lines = [line for line in all_lines if line.course == value]
            if not course_lines:
                continue

            self.room(46)
            self.band(self.y - 4, 14)
            self.text(str(label).upper(), MARGIN + 8, self.y, 7.6, bold=True,
                      color=ACCENT_DEEP, spacing=1.7)
            if not per_guest:
                subtotal = sum(line.line_total for line in course_lines)
                self.text_right(_money(subtotal), COL_TOTAL - 7, self.y, 8, bold=True, color=MUTED)
            self.y -= self.gap(19)

            for line in course_lines:
                name_lines = _wrap(line.name, BOLD, 9.5, desc_w)
                desc_lines = _wrap(line.description, REG, 7.8, desc_w) if line.description else []
                height = (
                    len(name_lines) * 11.3
                    + len(desc_lines) * 9.2
                    + self.gap(4)
                )
                self.room(height + 12)

                y = self.y
                for text in name_lines:
                    self.text(text, MARGIN, y, 9.5, bold=True)
                    y -= 11.5
                for text in desc_lines:
                    self.text(text, MARGIN, y + 1, 7.8, color=MUTED)
                    y -= 9.6

                if quote.show_quantities:
                    self.text_right(f"{line.quantity:,.0f}".replace(",", "."), COL_QTY, self.y, 9.5)
                if not per_guest:
                    self.text_right(_money(line.unit_price), COL_UNIT, self.y, 9.5)
                    self.text_right(_money(line.line_total), COL_TOTAL, self.y, 9.5, bold=True)

                self.y -= height
                self.rule(self.y + 3, Color(0.895, 0.885, 0.865), 0.4)
                self.y -= self.gap(3)
            self.y -= self.gap(4)

    def totals(self):
        """The breakdown the client asked for: what the food costs before the
        state and the staff take their share, then each of those named."""
        quote = self.quote
        per_guest = quote.pricing_mode == PricingMode.PER_GUEST

        rows = []
        if per_guest:
            rows.append((_("Price per guest"), _money(quote.price_per_guest), False))
            rows.append((_("Guests"), str(quote.guests), False))
            if quote.days > 1:
                rows.append((_("Days"), str(quote.days), False))
        for line in quote.add_on_lines:
            label = line.name
            if line.quantity != 1:
                label = f"{label}  x{line.quantity:,.0f}".replace(",", ".")
            rows.append((label, _money(line.line_total), False))
        rows.append((_("Subtotal before tax and tip"), _money(quote.taxable_base), True))
        rows.append((_("Consumption tax 8%"), _money(quote.tax_included), False))
        if quote.charges_tip:
            rows.append((_("Suggested tip 10%"), _money(quote.tip), False))

        self.room(8 + len(rows) * 15 + 4 + 34 + 8, floor=self.FLOOR_TOTALS)
        self.y -= 8

        box_x = MARGIN + CONTENT_W - 258
        for label, value, strong in rows:
            self.text(label, box_x, self.y, 8.8, color=INK if strong else MUTED)
            self.text_right(value, COL_TOTAL, self.y, 9.5, bold=strong)
            self.y -= 15

        self.y -= 4
        self.band(self.y - 22, 30, ACCENT, x=box_x, width=COL_TOTAL - box_x)
        self.text(_("TOTAL"), box_x + 12, self.y - 12, 9.5, bold=True, color=WHITE, spacing=1.8)
        self.text_right(_money(quote.total), COL_TOTAL - 12, self.y - 13, 15, bold=True, color=WHITE)
        self.y -= 34

        footer = _("Prices already include the consumption tax. The tip is voluntary.")
        self.text_right(footer, COL_TOTAL, self.y, 7.4, color=MUTED)
        self.y -= 14

    def build(self) -> bytes:
        self.start_page(first=True)
        self.lines()
        self.totals()
        self.finish_page()
        self.c.save()
        return self.buffer.getvalue()


#: Tried in order. Anything below the last value starts to read as cramped, so a
#: quote long enough to need a second page simply gets one.
FIT_STEPS = (1.0, 0.86, 0.72)


def _page_count(data: bytes) -> int:
    return data.count(b"/Type /Page\n")


def render_quote_pdf(quote) -> bytes:
    """Render the quote, squeezing the layout only if that saves a page.

    A quote that spills by a few points leaves a second sheet holding nothing
    but the totals, which reads as a mistake on a document sent to a client.
    """
    best = None
    for tight in FIT_STEPS:
        data = QuoteCanvas(quote, tight=tight).build()
        pages = _page_count(data)
        if best is None:
            best = (pages, data)
        if pages < best[0]:
            best = (pages, data)
        if pages <= 1:
            return data
    return best[1]
