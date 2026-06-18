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


def _product(category, name, sku):
    return Product.objects.create(
        name=name,
        sku=sku,
        category=category,
        cost_price=Decimal("1.00"),
        sale_price=Decimal("10.00"),
    )


def _sell(product, external_id, day, quantity, unit_price):
    sale = Sale.objects.create(
        external_id=external_id,
        occurred_at=datetime(2026, 1, day, 12, 0, tzinfo=timezone.utc),
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
def test_revenue_by_category_requires_authentication(client):
    response = client.get(reverse("analytics:revenue_by_category"))

    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_revenue_by_category_groups_and_orders(logged_client, db):
    food = Category.objects.create(name="Food")
    drinks = Category.objects.create(name="Drinks")
    burger = _product(food, "Burger", "BUR-01")
    fries = _product(food, "Fries", "FRI-01")
    wine = _product(drinks, "Wine", "WIN-01")
    _sell(burger, "B1", 10, 2, Decimal("10.00"))  # food +20
    _sell(fries, "F1", 10, 1, Decimal("10.00"))  # food +10 -> Food total 30
    _sell(wine, "W1", 10, 1, Decimal("50.00"))  # drinks 50

    response = logged_client.get(reverse("analytics:revenue_by_category"), JAN)

    assert response.status_code == 200
    payload = response.json()
    assert payload["labels"] == ["Drinks", "Food"]  # ordered by revenue desc
    assert payload["data"] == [50.0, 30.0]


@pytest.mark.django_db
def test_revenue_by_category_respects_date_range(logged_client, db):
    food = Category.objects.create(name="Food")
    burger = _product(food, "Burger", "BUR-01")
    _sell(burger, "IN", 20, 4, Decimal("10.00"))  # in window
    _sell(burger, "OUT", 5, 9, Decimal("10.00"))  # out of window

    response = logged_client.get(
        reverse("analytics:revenue_by_category"),
        {"start": "2026-01-15", "end": "2026-01-31"},
    )

    payload = response.json()
    assert payload["labels"] == ["Food"]
    assert payload["data"] == [40.0]


@pytest.mark.django_db
def test_revenue_by_category_empty_without_sales(logged_client, db):
    response = logged_client.get(reverse("analytics:revenue_by_category"), JAN)

    payload = response.json()
    assert payload["labels"] == []
    assert payload["data"] == []
