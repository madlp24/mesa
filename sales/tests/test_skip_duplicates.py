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
]


def _write_workbook(path, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADER)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


@pytest.fixture
def product(restaurant):
    category = Category.objects.create(restaurant=restaurant, name="Mains")
    return Product.objects.create(
        restaurant=restaurant,
        name="Burger",
        sku="BUR-01",
        category=category,
        cost_price=Decimal("4.00"),
        sale_price=Decimal("10.00"),
    )


@pytest.fixture
def workbook(tmp_path, product):
    path = tmp_path / "sales.xlsx"
    _write_workbook(
        path,
        [
            ["S1", "2026-01-10 12:00", "BUR-01", 3, "10.00", "4.00"],
            ["S2", "2026-01-11 12:00", "BUR-01", 2, "10.00", "4.00"],
        ],
    )
    return path


@pytest.mark.django_db
def test_first_import_reports_new_sales(restaurant, workbook):
    out = StringIO()

    call_command(
        "import_sales", "--file", str(workbook), "--restaurant", restaurant.slug,
        stdout=out,
    )

    assert Sale.objects.count() == 2
    assert "2 new sales, 0 skipped as duplicate" in out.getvalue()


@pytest.mark.django_db
def test_reimporting_same_file_is_a_no_op(restaurant, workbook):
    call_command(
        "import_sales", "--file", str(workbook), "--restaurant", restaurant.slug,
        stdout=StringIO(),
    )
    sale_ids = set(Sale.objects.values_list("id", flat=True))
    item_count = SaleItem.objects.count()

    out = StringIO()
    call_command(
        "import_sales", "--file", str(workbook), "--restaurant", restaurant.slug,
        stdout=out,
    )

    # No new rows, and existing rows are untouched.
    assert Sale.objects.count() == 2
    assert set(Sale.objects.values_list("id", flat=True)) == sale_ids
    assert SaleItem.objects.count() == item_count
    assert "0 new sales, 2 skipped as duplicate" in out.getvalue()
