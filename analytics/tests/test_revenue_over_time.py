from datetime import datetime, timedelta, timezone

import pytest
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone as dj_timezone

from catalog.models import Category, Product
from sales.models import Sale, SaleItem


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


def _add_sale(product, external_id, occurred_at, quantity):
    sale = Sale.objects.create(
        restaurant=product.restaurant,
        external_id=external_id,
        occurred_at=occurred_at,
        total=Decimal("10.00") * quantity,
    )
    SaleItem.objects.create(
        sale=sale,
        product=product,
        quantity=quantity,
        unit_price=Decimal("10.00"),
        unit_cost=Decimal("4.00"),
    )


def _at_noon_days_ago(days_ago):
    return dj_timezone.localtime().replace(
        hour=12, minute=0, second=0, microsecond=0
    ) - timedelta(days=days_ago)


@pytest.mark.django_db
def test_revenue_over_time_requires_authentication(client, product):
    response = client.get(reverse("analytics:revenue_over_time"))

    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_revenue_over_time_aggregates_daily_revenue(logged_client, product):
    day1 = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 1, 11, 12, 0, tzinfo=timezone.utc)
    # Two sales on day1 should sum into a single bucket.
    _add_sale(product, "A", day1, 2)  # revenue 20
    _add_sale(product, "B", day1, 1)  # revenue 10
    _add_sale(product, "C", day2, 3)  # revenue 30

    response = logged_client.get(
        reverse("analytics:revenue_over_time"),
        {"start": "2026-01-01", "end": "2026-01-31"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["labels"] == ["2026-01-10", "2026-01-11"]
    assert payload["data"] == [30.0, 30.0]


@pytest.mark.django_db
def test_revenue_over_time_respects_explicit_range(logged_client, product):
    _add_sale(product, "IN", datetime(2026, 1, 20, 12, 0, tzinfo=timezone.utc), 4)
    _add_sale(product, "OUT", datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc), 9)

    response = logged_client.get(
        reverse("analytics:revenue_over_time"),
        {"start": "2026-01-15", "end": "2026-01-31"},
    )

    payload = response.json()
    assert payload["labels"] == ["2026-01-20"]
    assert payload["data"] == [40.0]


@pytest.mark.django_db
def test_revenue_over_time_defaults_to_last_30_days(logged_client, product):
    _add_sale(product, "RECENT", _at_noon_days_ago(5), 2)  # revenue 20, in window
    _add_sale(product, "OLD", _at_noon_days_ago(60), 9)  # outside window

    response = logged_client.get(reverse("analytics:revenue_over_time"))

    payload = response.json()
    assert payload["data"] == [20.0]
