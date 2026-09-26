"""Tests for updating the master workbook from the web (US36)."""
import io
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from catalog.models import Category, Product
from sales.models import Sale, SaleItem

URL = "analytics:workbook_update"


def _workbook_bytes(sheet_title="Productos vendidos"):
    """The owner's two-row-header matrix, as bytes ready to upload."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.cell(row=2, column=4, value=2025)  # Marzo 2025 lives in column D
    ws.cell(row=3, column=1, value="Grupo")
    ws.cell(row=3, column=2, value="Clave")
    ws.cell(row=3, column=3, value="Producto")
    ws.cell(row=3, column=4, value="Marzo")
    ws.cell(row=4, column=1, value="ENTRADAS")
    ws.cell(row=4, column=2, value=1001)
    ws.cell(row=4, column=3, value="Arepa de Choclo")
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _upload(name="Analisis.xlsx", data=None):
    return SimpleUploadedFile(
        name,
        data if data is not None else _workbook_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@pytest.fixture
def sold(restaurant):
    """One product sold in March 2025, matching the workbook's existing row."""
    category = Category.objects.create(restaurant=restaurant, name="ENTRADAS")
    product = Product.objects.create(
        restaurant=restaurant, name="AREPA DE CHOCLO", sku="03028",
        category=category, cost_price=Decimal("1"), sale_price=Decimal("5"),
    )
    sale = Sale.objects.create(
        restaurant=restaurant, external_id="2025-03-05:03028",
        occurred_at=datetime(2025, 3, 5, 12, tzinfo=timezone.utc), total=Decimal("5"),
    )
    SaleItem.objects.create(
        sale=sale, product=product, quantity=68,
        unit_price=Decimal("5"), unit_cost=Decimal("1"),
    )
    return product


@pytest.mark.django_db
def test_requires_authentication(client):
    response = client.get(reverse(URL))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_page_renders_the_form(logged_client):
    response = logged_client.get(reverse(URL))
    assert response.status_code == 200
    assert b'type="file"' in response.content


@pytest.mark.django_db
def test_fills_the_month_and_returns_the_workbook(logged_client, sold):
    response = logged_client.post(
        reverse(URL), {"workbook": _upload(), "year": 2025, "month": 3}
    )

    assert response.status_code == 200
    assert "attachment" in response["Content-Disposition"]
    ws = load_workbook(io.BytesIO(b"".join(response.streaming_content)))[
        "Productos vendidos"
    ]
    # The month landed on the existing row, matched by name.
    assert ws.cell(row=4, column=4).value == 68
    assert ws.cell(row=4, column=2).value == 1001  # historical code untouched


@pytest.mark.django_db
def test_rejects_a_file_that_is_not_xlsx(logged_client):
    response = logged_client.post(
        reverse(URL),
        {"workbook": SimpleUploadedFile("notas.txt", b"hola"), "year": 2025, "month": 3},
    )

    assert response.status_code == 200  # back to the form, no download
    assert "not an .xlsx" in response.content.decode()


@pytest.mark.django_db
def test_workbook_without_the_sheet_fails_readably(logged_client, sold):
    response = logged_client.post(
        reverse(URL),
        {
            "workbook": _upload(data=_workbook_bytes(sheet_title="Otra hoja")),
            "year": 2025,
            "month": 3,
        },
    )

    assert response.status_code == 200
    assert "Productos vendidos" in response.content.decode()
    assert "attachment" not in response.get("Content-Disposition", "")
