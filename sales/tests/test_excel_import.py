from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from openpyxl import Workbook

from catalog.models import Category, Product
from sales.models import Sale, SaleItem

HEADER = [
    "external_id",
    "occurred_at",
    "product_sku",
    "quantity",
    "unit_price",
    "unit_cost",
    "payment_method",
]


def _write_workbook(path, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADER)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


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
def test_import_creates_sales_and_items_and_skips_invalid_rows(tmp_path, product):
    path = tmp_path / "sales.xlsx"
    _write_workbook(
        path,
        [
            ["S1", "2026-01-10 12:00", "BUR-01", 3, "10.00", "4.00", "cash"],
            # row 3: missing external_id -> skipped
            ["", "2026-01-11 12:00", "BUR-01", 2, "10.00", "4.00", "card"],
        ],
    )
    out = StringIO()

    call_command("import_sales", "--file", str(path), stdout=out)

    assert Sale.objects.count() == 1
    assert SaleItem.objects.count() == 1
    sale = Sale.objects.get()
    assert sale.external_id == "S1"
    assert sale.total == Decimal("30.00")
    item = sale.items.get()
    assert item.quantity == 3
    assert item.unit_price == Decimal("10.00")

    summary = out.getvalue()
    assert "1 sales imported" in summary
    assert "1 items" in summary
    assert "1 rows skipped" in summary


@pytest.mark.django_db
def test_invalid_row_is_logged_with_row_number(tmp_path, product, caplog):
    path = tmp_path / "sales.xlsx"
    _write_workbook(
        path,
        [
            ["S1", "2026-01-10 12:00", "BUR-01", 3, "10.00", "4.00", "cash"],
            ["", "2026-01-11 12:00", "BUR-01", 2, "10.00", "4.00", "card"],
        ],
    )

    with caplog.at_level("WARNING"):
        call_command("import_sales", "--file", str(path), stdout=StringIO())

    assert "Row 3" in caplog.text
    assert "external_id" in caplog.text
