"""Tests for the daily report footer parser (Bar/Kitchen totals, US32)."""
from decimal import Decimal

import pytest
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas

from sales.importers.pdf_daily import parse_daily_totals

PERIOD_LINE = (
    "PRODUCTOS VENDIDOS DEL 01/04/2025 06:00:00 AM AL 02/04/2025 06:00:00 AM"
)
# The footer block a daily report ends with. Note "ALIMENTOS :" with a space
# before the colon -- a real variant seen in the data (08 Marzo 2025).
FOOTER_LINES = [
    "TRES CUATRO CINCO STEAKHOUSE",
    PERIOD_LINE,
    "VENTA CANTIDAD COSTOS VENTA - COSTO",
    "5348.000 $8,298,083.00 $2,593,223.93 $5,704,859.06 $8,298,083.42",
    "BEBIDAS: $1,651,851.00 (20%) 78 $591,901.87 $1,059,949.12",
    "ALIMENTOS : $6,646,232.00 (80%) 5270 $2,001,322.05 $4,644,909.94",
    "OTROS: $0.00 (0%) 0 $0.00 $0.00",
]


def _write_pdf(path, lines):
    pdf = canvas.Canvas(str(path), pagesize=landscape(letter))
    pdf.setFont("Helvetica", 8)
    y = 560
    for line in lines:
        pdf.drawString(30, y, line)
        y -= 14
    pdf.save()


def test_parse_daily_totals_extracts_bar_and_kitchen(tmp_path):
    path = tmp_path / "day.pdf"
    _write_pdf(path, FOOTER_LINES)

    totals = parse_daily_totals(path)

    assert totals is not None
    assert totals.date == "2025-04-01"
    assert totals.venta_bar == Decimal("1651851.00")
    assert totals.costo_bar == Decimal("591901.87")
    assert totals.venta_cocina == Decimal("6646232.00")  # "ALIMENTOS :" variant parsed
    assert totals.costo_cocina == Decimal("2001322.05")


def test_parse_daily_totals_none_without_footer(tmp_path):
    path = tmp_path / "no_footer.pdf"
    _write_pdf(path, [PERIOD_LINE, "GRUPO:POSTRES", "06008 FLAN $1.00 2.00 $2.00"])

    assert parse_daily_totals(path) is None


@pytest.mark.parametrize("missing", ["BEBIDAS", "ALIMENTOS"])
def test_parse_daily_totals_none_when_a_family_missing(tmp_path, missing):
    lines = [line for line in FOOTER_LINES if not line.startswith(missing)]
    path = tmp_path / "partial.pdf"
    _write_pdf(path, lines)

    assert parse_daily_totals(path) is None
