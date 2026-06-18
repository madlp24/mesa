from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from catalog.models import Category, Product
from sales.models import Sale, SaleItem

HEADER = [
    "external_id",
    "occurred_at",
    "product_sku",
    "quantity",
    "unit_price",
    "unit_cost",
]


def _write_pdf(path, rows):
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    table = Table([HEADER, *rows])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    doc.build([table])


@pytest.fixture
def product(db):
    category = Category.objects.create(name="Mains")
    return Product.objects.create(
        name="Burger",
        sku="BUR-01",
        category=category,
        cost_price=Decimal("4.00"),
        sale_price=Decimal("10.00"),
    )


@pytest.mark.django_db
def test_import_from_pdf_creates_sales_and_skips_invalid_rows(tmp_path, product):
    path = tmp_path / "daily.pdf"
    _write_pdf(
        path,
        [
            ["P1", "2026-02-01 10:00", "BUR-01", "2", "10.00", "4.00"],
            ["P2", "2026-02-01 11:30", "BUR-01", "1", "10.00", "4.00"],
            # row 4: missing external_id -> skipped
            ["", "2026-02-01 12:00", "BUR-01", "5", "10.00", "4.00"],
        ],
    )
    out = StringIO()

    call_command("import_sales", "--file", str(path), stdout=out)

    assert Sale.objects.count() == 2
    assert SaleItem.objects.count() == 2
    total_units = sum(item.quantity for item in SaleItem.objects.all())
    assert total_units == 3
    assert Sale.objects.get(external_id="P1").total == Decimal("20.00")

    summary = out.getvalue()
    assert "2 sales imported" in summary
    assert "2 items" in summary
    assert "1 rows skipped" in summary
