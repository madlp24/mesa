"""The report as a file to keep or forward: Excel and PDF (US54)."""
from __future__ import annotations

import io

from django.utils.formats import date_format
from django.utils.translation import gettext as _
from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from pages.templatetags.mesa import change, cop, pct, signed

from .engine import COST_RISE, MARGIN_DROP, PRICE_DROP, Report


def _reasons(alert) -> str:
    names = {COST_RISE: _("cost up"), PRICE_DROP: _("price down"), MARGIN_DROP: _("margin down")}
    return ", ".join(str(names[r]) for r in alert.reasons)


def _jump_kind(jump) -> str:
    return {"cost": _("POS cost"), "price": _("Selling price"), "supplier": _("Supplier price")}[jump.kind]


def _day(value) -> str:
    return date_format(value, "j M Y") if value else ""


def title(report: Report) -> str:
    return _("Alerts from %(start)s to %(end)s") % {
        "start": _day(report.current.start), "end": _day(report.current.end),
    }


def _rows(report: Report):
    """The three tables every format prints, as (heading, header, rows)."""
    products = [
        (
            a.name,
            _reasons(a),
            f"{cop(a.before.unit_cost)} > {cop(a.now.unit_cost)} ({change(a.cost_change)})",
            f"{cop(a.before.unit_price)} > {cop(a.now.unit_price)} ({change(a.price_change)})",
            f"{pct(a.before.margin_pct)} > {pct(a.now.margin_pct)} ({signed(a.margin_change)})",
            cop(a.monthly_loss),
            "; ".join(
                f"{m.name} {cop(m.before)} > {cop(m.after)} {m.supplier} {m.invoice}".strip()
                for m in a.causes
            ) or _("POS cost"),
        )
        for a in report.products
    ]
    jumps = [
        (j.name, str(_jump_kind(j)), _day(j.date), cop(j.before), cop(j.after), change(j.change),
         f"{j.supplier} {j.invoice}".strip())
        for j in report.jumps
    ]
    uncosted = [(stats.name, cop(stats.revenue)) for _pid, stats in report.uncosted]
    return [
        (_("Products that lost profitability"),
         (_("Product"), _("Why"), _("Cost per portion"), _("Price per portion"), _("Margin"),
          _("Lost a month"), _("Cause")), products),
        (_("Abrupt changes"),
         (_("Item"), _("What"), _("Day"), _("Before"), _("After"), _("Change"), _("Supplier and invoice")),
         jumps),
        (_("Sold without a cost"), (_("Product"), _("Sales")), uncosted),
    ]


def report_workbook(report: Report) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = str(_("Alerts"))[:31]
    sheet.append([title(report)])
    sheet["A1"].font = Font(bold=True, size=13)
    for heading, header, rows in _rows(report):
        sheet.append([])
        sheet.append([str(heading)])
        sheet.cell(row=sheet.max_row, column=1).font = Font(bold=True)
        sheet.append([str(h) for h in header])
        for cell in sheet[sheet.max_row]:
            cell.font = Font(bold=True)
        for row in rows or [(str(_("Nothing to report.")),)]:
            sheet.append(list(row))
    for column in "ABCDEFG":
        sheet.column_dimensions[column].width = 28
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def report_pdf(report: Report, restaurant_name: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=14 * mm,
                            rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=title(report))
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=8, leading=10)
    story = [
        Paragraph(restaurant_name, styles["Title"]),
        Paragraph(title(report), styles["Heading2"]),
        Paragraph(_("Lost a month, all products: %(amount)s") % {"amount": cop(report.monthly_loss)},
                  styles["BodyText"]),
    ]
    for heading, header, rows in _rows(report):
        story += [Spacer(1, 6 * mm), Paragraph(str(heading), styles["Heading3"])]
        if not rows:
            story.append(Paragraph(_("Nothing to report."), styles["BodyText"]))
            continue
        data = [[Paragraph(f"<b>{h}</b>", small) for h in header]]
        data += [[Paragraph(str(cell), small) for cell in row] for row in rows]
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
            ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)
    doc.build(story)
    return buffer.getvalue()
