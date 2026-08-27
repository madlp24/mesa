"""Tests for the Excel exports (US22)."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from analytics.exports import (
    PRODUCTOS_VENDIDOS_SHEET,
    build_analysis_workbook,
    build_productos_vendidos_workbook,
)
from catalog.models import Category, Product
from sales.models import Sale, SaleItem


@pytest.fixture
def catalog(restaurant):
    food = Category.objects.create(restaurant=restaurant, name="Acompañamientos")
    drinks = Category.objects.create(restaurant=restaurant, name="Bebidas")
    arepa = Product.objects.create(
        restaurant=restaurant,
        name="Arepa de Choclo", sku="03028", category=food,
        cost_price=Decimal("3"), sale_price=Decimal("10"),
    )
    cafe = Product.objects.create(
        restaurant=restaurant,
        name="Americano", sku="14001", category=drinks,
        cost_price=Decimal("1"), sale_price=Decimal("4"),
    )
    return {"arepa": arepa, "cafe": cafe}


def _sell(product, ext, year, month, day, qty):
    sale = Sale.objects.create(
        restaurant=product.restaurant,
        external_id=ext,
        occurred_at=datetime(year, month, day, 12, tzinfo=UTC),
        total=product.sale_price * qty,
    )
    SaleItem.objects.create(
        sale=sale, product=product, quantity=qty,
        unit_price=product.sale_price, unit_cost=product.cost_price,
    )


@pytest.mark.django_db
def test_productos_vendidos_matrix(restaurant, catalog):
    _sell(catalog["arepa"], "a1", 2026, 1, 5, 10)
    _sell(catalog["arepa"], "a2", 2026, 2, 5, 4)
    _sell(catalog["cafe"], "c1", 2026, 1, 7, 20)

    ws = build_productos_vendidos_workbook(restaurant)[PRODUCTOS_VENDIDOS_SHEET]
    header = [cell.value for cell in ws[1]]
    assert header == ["Grupo", "Clave", "Producto", "Enero 2026", "Febrero 2026"]

    rows = {row[2]: row for row in ws.iter_rows(min_row=2, values_only=True)}
    # Arepa: 10 in Jan, 4 in Feb.
    assert rows["Arepa de Choclo"][3:] == (10, 4)
    # Americano: 20 in Jan, 0 in Feb (zero-filled).
    assert rows["Americano"][3:] == (20, 0)


@pytest.mark.django_db
def test_analysis_workbook_sheets_and_totals(restaurant, catalog):
    _sell(catalog["arepa"], "a1", 2026, 1, 5, 10)  # revenue 100, cost 30, margin 70
    _sell(catalog["cafe"], "c1", 2026, 1, 7, 20)  # revenue 80, cost 20, margin 60

    wb = build_analysis_workbook(restaurant)
    assert wb.sheetnames == ["Por producto", "Por categoría", "Rankings"]

    products = wb["Por producto"]
    header = [c.value for c in products[1]]
    assert header == [
        "Producto", "Categoría", "Cantidad", "Ingreso", "Costo", "Margen $", "Margen %"
    ]
    # Highest revenue first: Arepa (100) before Americano (80).
    first = [c.value for c in products[2]]
    assert first[0] == "Arepa de Choclo"
    assert first[3] == 100.0  # ingreso
    assert first[5] == 70.0  # margen $
    assert first[6] == 70.0  # margen % = 70/100

    categories = wb["Por categoría"]
    assert categories[1][0].value == "Categoría"

    rankings = wb["Rankings"]
    flat = [c for row in rankings.iter_rows(values_only=True) for c in row]
    assert "Top 10 por ingreso" in flat
    assert "Top 10 por margen $" in flat


@pytest.mark.django_db
def test_export_endpoints_return_xlsx(logged_client, catalog):
    _sell(catalog["arepa"], "a1", 2026, 1, 5, 10)
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    matrix = logged_client.get(reverse("analytics:export_productos_vendidos"))
    assert matrix.status_code == 200
    assert matrix["Content-Type"] == xlsx
    assert "productos_vendidos.xlsx" in matrix["Content-Disposition"]
    assert matrix.content[:2] == b"PK"  # xlsx is a zip

    report = logged_client.get(reverse("analytics:export_analysis"))
    assert report.status_code == 200
    assert report["Content-Type"] == xlsx


@pytest.mark.django_db
def test_export_requires_authentication(client):
    response = client.get(reverse("analytics:export_productos_vendidos"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url
