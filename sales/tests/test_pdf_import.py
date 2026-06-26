from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas

from catalog.models import Category, Product
from sales.models import Sale, SaleItem

PERIOD_LINE = (
    "PRODUCTOS VENDIDOS DEL 01/04/2025 06:00:00 AM AL 01/05/2025 06:00:00 AM"
)
# A faithful slice of the real "Productos Vendidos" report: a period header,
# GRUPO sections, product rows (CLAVE DESC then 8 numeric columns), a GRUPO
# subtotal that must be ignored, and a malformed row that must be skipped.
REPORT_LINES = [
    "TRES CUATRO CINCO STEAKHOUSE",
    PERIOD_LINE,
    "GRUPO:ACOMPAÑAMIENTOS",
    "03028 AREPA DE CHOCLO $31,481.48 34.00 $1,070,370.00 $9,302.44 "
    "$316,283.12 $754,086.87 $31,481.48 $1,070,370.37",
    "03021 ARROZ FRITO $18,518.51 14.00 $259,259.00 $3,964.32 "
    "$55,500.51 $203,758.48 $18,518.51 $259,259.25",
    "GRUPO: ACOMPAÑAMIENTOS 48.000 $1,329,629.00 $371,783.63 $957,845.36",
    "GRUPO:BEBIDAS CALIENTES",
    "14001 AMERICANO $7,262.73 64.00 $464,815.00 $906.43 "
    "$58,011.80 $406,803.19 $7,407.40 $474,074.07",
    "99999 ROW WITHOUT ENOUGH COLUMNS $10.00",
]


def _write_report_pdf(path):
    pdf = canvas.Canvas(str(path), pagesize=landscape(letter))
    pdf.setFont("Helvetica", 8)
    y = 560
    for line in REPORT_LINES:
        pdf.drawString(30, y, line)
        y -= 14
    pdf.save()


@pytest.mark.django_db
def test_import_pdf_creates_catalog_sales_and_skips_bad_rows(tmp_path, restaurant):
    path = tmp_path / "daily.pdf"
    _write_report_pdf(path)
    out = StringIO()

    call_command(
        "import_sales", "--file", str(path), "--restaurant", restaurant.slug, stdout=out
    )

    assert Sale.objects.count() == 3
    assert SaleItem.objects.count() == 3

    # Categories and products are auto-created from the report's catalog hints.
    assert set(Category.objects.values_list("name", flat=True)) == {
        "ACOMPAÑAMIENTOS",
        "BEBIDAS CALIENTES",
    }
    arepa = Product.objects.get(restaurant=restaurant, sku="03028")
    assert arepa.name == "AREPA DE CHOCLO"
    assert arepa.category.name == "ACOMPAÑAMIENTOS"
    assert arepa.cost_price == Decimal("9302.44")
    assert arepa.sale_price == Decimal("31481.48")

    sale = Sale.objects.get(restaurant=restaurant, external_id="2025-04-01:03028")
    assert sale.occurred_at.date() == date(2025, 4, 1)
    assert sale.total == Decimal("1070370.00")
    assert sale.items.get().quantity == 34

    summary = out.getvalue()
    assert "3 sales imported" in summary
    assert "3 items" in summary
    assert "1 rows skipped" in summary


@pytest.mark.django_db
def test_reimporting_same_pdf_is_idempotent(tmp_path, restaurant):
    path = tmp_path / "daily.pdf"
    _write_report_pdf(path)

    call_command(
        "import_sales", "--file", str(path), "--restaurant", restaurant.slug,
        stdout=StringIO(),
    )
    out = StringIO()
    call_command(
        "import_sales", "--file", str(path), "--restaurant", restaurant.slug, stdout=out
    )

    assert Sale.objects.count() == 3
    assert "0 sales imported" in out.getvalue()
    assert "3 skipped as duplicate" in out.getvalue()
