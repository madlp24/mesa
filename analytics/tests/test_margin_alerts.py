"""Mesa saying which products have a poor margin (US40)."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.urls import reverse

from analytics.alerts import margin_alerts
from catalog.models import Category, Product
from sales.models import Sale, SaleItem

URL = "analytics:margin_alerts"


def _sold(restaurant, name, price, cost, *, units=10, day=5, sku=None):
    category, _ = Category.objects.get_or_create(restaurant=restaurant, name="BAR")
    product = Product.objects.create(
        restaurant=restaurant, name=name, sku=sku or name[:20], category=category,
        cost_price=Decimal(cost), sale_price=Decimal(price),
    )
    sale = Sale.objects.create(
        restaurant=restaurant, external_id=f"2026-03-{day:02d}:{product.sku}",
        occurred_at=datetime(2026, 3, day, 12, tzinfo=timezone.utc), total=Decimal("1"),
    )
    SaleItem.objects.create(
        sale=sale, product=product, quantity=units,
        unit_price=Decimal(price), unit_cost=Decimal(cost),
    )
    return product


@pytest.fixture
def catalog(restaurant):
    """One of each case Mesa should have an opinion about."""
    return {
        "loss": _sold(restaurant, "CHELADA", "100", "140", sku="L1"),
        "thin": _sold(restaurant, "ZUMO", "100", "70", sku="T1"),       # 30%
        "nocost": _sold(restaurant, "VENTA VINO", "100", "0", sku="N1"),
        "healthy": _sold(restaurant, "NEGRONI", "100", "20", sku="H1"),  # 80%
    }


@pytest.mark.django_db
def test_each_product_lands_in_its_group(restaurant, catalog):
    alerts = margin_alerts(restaurant)

    assert [e.name for e in alerts.at_a_loss] == ["CHELADA"]
    assert [e.name for e in alerts.thin] == ["ZUMO"]
    assert [e.name for e in alerts.without_cost] == ["VENTA VINO"]
    # The healthy one is never mentioned.
    assert "NEGRONI" not in {e.name for e in alerts.at_a_loss + alerts.thin}


@pytest.mark.django_db
def test_the_threshold_decides_what_is_thin(restaurant, catalog):
    """At 20% the 30%-margin product is fine; at 50% it is not."""
    assert [e.name for e in margin_alerts(restaurant, threshold=Decimal("20")).thin] == []
    assert [e.name for e in margin_alerts(restaurant, threshold=Decimal("50")).thin] == ["ZUMO"]


@pytest.mark.django_db
def test_lists_are_ordered_by_revenue(restaurant):
    _sold(restaurant, "POCO", "100", "140", units=1, sku="P1")
    _sold(restaurant, "MUCHO", "100", "140", units=50, sku="M1")

    assert [e.name for e in margin_alerts(restaurant).at_a_loss] == ["MUCHO", "POCO"]


@pytest.mark.django_db
def test_a_date_range_narrows_the_period(restaurant):
    _sold(restaurant, "CHELADA", "100", "140", day=5, sku="L1")

    from datetime import date
    assert margin_alerts(restaurant, start=date(2026, 3, 1), end=date(2026, 3, 10)).total == 1
    assert margin_alerts(restaurant, start=date(2026, 4, 1)).total == 0


@pytest.mark.django_db
def test_page_requires_authentication(client):
    response = client.get(reverse(URL))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_page_shows_the_three_groups(logged_client, restaurant, catalog):
    response = logged_client.get(reverse(URL))

    assert response.status_code == 200
    body = response.content.decode()
    for name in ("CHELADA", "ZUMO", "VENTA VINO"):
        assert name in body
    assert response.context["alerts"].total == 3


@pytest.mark.django_db
def test_a_nonsense_threshold_falls_back_to_the_default(logged_client, restaurant, catalog):
    response = logged_client.get(reverse(URL), {"threshold": "abc"})

    assert response.status_code == 200
    assert response.context["threshold"] == Decimal("50")
