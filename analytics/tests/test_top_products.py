from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from catalog.models import Category, Product
from sales.models import Sale, SaleItem


@pytest.fixture
def category(restaurant):
    return Category.objects.create(restaurant=restaurant, name="Mains")


def _product(category, name, sku):
    return Product.objects.create(
        restaurant=category.restaurant,
        name=name,
        sku=sku,
        category=category,
        cost_price=Decimal("1.00"),
        sale_price=Decimal("10.00"),
    )


def _sell(product, external_id, day, quantity, unit_price):
    sale = Sale.objects.create(
        restaurant=product.restaurant,
        external_id=external_id,
        occurred_at=datetime(2026, 1, day, 12, 0, tzinfo=UTC),
        total=unit_price * quantity,
    )
    SaleItem.objects.create(
        sale=sale,
        product=product,
        quantity=quantity,
        unit_price=unit_price,
        unit_cost=Decimal("1.00"),
    )


JAN = {"start": "2026-01-01", "end": "2026-01-31"}


@pytest.mark.django_db
def test_top_products_requires_authentication(client):
    response = client.get(reverse("analytics:top_products"))

    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_top_products_ranked_by_revenue_desc(logged_client, category):
    burger = _product(category, "Burger", "BUR-01")
    wine = _product(category, "Wine", "WIN-01")
    water = _product(category, "Water", "WAT-01")
    _sell(burger, "B1", 10, 2, Decimal("10.00"))  # revenue 20
    _sell(wine, "W1", 10, 1, Decimal("50.00"))  # revenue 50
    _sell(water, "WT1", 10, 3, Decimal("2.00"))  # revenue 6

    response = logged_client.get(reverse("analytics:top_products"), JAN)

    assert response.status_code == 200
    payload = response.json()
    assert payload["labels"] == ["Wine", "Burger", "Water"]
    assert payload["data"] == [50.0, 20.0, 6.0]


@pytest.mark.django_db
def test_top_products_sums_revenue_across_sales(logged_client, category):
    burger = _product(category, "Burger", "BUR-01")
    _sell(burger, "B1", 10, 2, Decimal("10.00"))  # 20
    _sell(burger, "B2", 11, 1, Decimal("10.00"))  # 10

    response = logged_client.get(reverse("analytics:top_products"), JAN)

    payload = response.json()
    assert payload["labels"] == ["Burger"]
    assert payload["data"] == [30.0]


@pytest.mark.django_db
def test_top_products_limited_to_ten(logged_client, category):
    # 11 products with strictly increasing revenue; the cheapest must drop off.
    for i in range(1, 12):
        product = _product(category, f"P{i:02d}", f"SKU-{i:02d}")
        _sell(product, f"S{i}", 10, 1, Decimal(i * 10))

    response = logged_client.get(reverse("analytics:top_products"), JAN)

    payload = response.json()
    assert len(payload["labels"]) == 10
    assert payload["labels"][0] == "P11"  # highest revenue first
    assert "P01" not in payload["labels"]  # lowest dropped


@pytest.mark.django_db
def test_top_products_respects_date_range(logged_client, category):
    burger = _product(category, "Burger", "BUR-01")
    _sell(burger, "IN", 20, 4, Decimal("10.00"))  # in window
    _sell(burger, "OUT", 5, 9, Decimal("10.00"))  # out of window

    response = logged_client.get(
        reverse("analytics:top_products"),
        {"start": "2026-01-15", "end": "2026-01-31"},
    )

    payload = response.json()
    assert payload["data"] == [40.0]
