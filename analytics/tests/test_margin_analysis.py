from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from catalog.models import Category, Product
from sales.models import Sale, SaleItem


@pytest.fixture
def logged_client(client, db):
    user = get_user_model().objects.create_user(
        username="owner", email="owner@example.com", password="secret123"
    )
    client.force_login(user)
    return client


@pytest.fixture
def catalog(db):
    category = Category.objects.create(name="Mains")
    # margin %: burger 60, wine 75, water 50
    burger = Product.objects.create(
        name="Burger", sku="BUR-01", category=category,
        cost_price=Decimal("4.00"), sale_price=Decimal("10.00"),
    )
    wine = Product.objects.create(
        name="Wine", sku="WIN-01", category=category,
        cost_price=Decimal("5.00"), sale_price=Decimal("20.00"),
    )
    water = Product.objects.create(
        name="Water", sku="WAT-01", category=category,
        cost_price=Decimal("1.00"), sale_price=Decimal("2.00"),
    )
    return burger, wine, water


def _sell(product, external_id, day, quantity):
    sale = Sale.objects.create(
        external_id=external_id,
        occurred_at=datetime(2026, 1, day, 12, 0, tzinfo=timezone.utc),
        total=product.sale_price * quantity,
    )
    SaleItem.objects.create(
        sale=sale,
        product=product,
        quantity=quantity,
        unit_price=product.sale_price,
        unit_cost=product.cost_price,
    )


JAN = {"start": "2026-01-01", "end": "2026-01-31"}


@pytest.mark.django_db
def test_margin_page_requires_authentication(client):
    response = client.get(reverse("analytics:margin_analysis"))

    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_margin_table_renders_all_active_products(logged_client, catalog):
    response = logged_client.get(reverse("analytics:margin_analysis"), JAN)

    assert response.status_code == 200
    rows = response.context["rows"]
    assert {row["name"] for row in rows} == {"Burger", "Wine", "Water"}
    content = response.content.decode()
    assert "Burger" in content and "Wine" in content and "Water" in content


@pytest.mark.django_db
def test_default_sort_is_margin_pct_descending(logged_client, catalog):
    response = logged_client.get(reverse("analytics:margin_analysis"), JAN)

    rows = response.context["rows"]
    assert [row["name"] for row in rows] == ["Wine", "Burger", "Water"]
    assert response.context["sort"] == "margin_pct"
    assert response.context["direction"] == "desc"


@pytest.mark.django_db
def test_inactive_products_excluded(logged_client, catalog):
    burger, wine, water = catalog
    water.is_active = False
    water.save()

    response = logged_client.get(reverse("analytics:margin_analysis"), JAN)

    names = [row["name"] for row in response.context["rows"]]
    assert "Water" not in names


@pytest.mark.django_db
def test_sort_by_name_ascending(logged_client, catalog):
    response = logged_client.get(
        reverse("analytics:margin_analysis"), {**JAN, "sort": "name", "dir": "asc"}
    )

    rows = response.context["rows"]
    assert [row["name"] for row in rows] == ["Burger", "Water", "Wine"]


@pytest.mark.django_db
def test_units_and_total_margin_respect_date_range(logged_client, catalog):
    burger, wine, water = catalog
    _sell(burger, "IN", 20, 3)  # in window: units 3, margin 6*3=18
    _sell(burger, "OUT", 5, 7)  # out of window

    response = logged_client.get(
        reverse("analytics:margin_analysis"),
        {"start": "2026-01-15", "end": "2026-01-31", "sort": "total_margin"},
    )

    rows = {row["name"]: row for row in response.context["rows"]}
    assert rows["Burger"]["units_sold"] == 3
    assert rows["Burger"]["total_margin"] == Decimal("18.00")
    assert rows["Wine"]["units_sold"] == 0
    assert rows["Wine"]["total_margin"] == Decimal("0")
