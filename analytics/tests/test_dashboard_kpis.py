from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from django.urls import reverse

from analytics.services import compute_kpis
from catalog.models import Category, Product
from sales.models import Sale, SaleItem


@pytest.fixture
def products(restaurant):
    category = Category.objects.create(restaurant=restaurant, name="Mains")
    burger = Product.objects.create(
        restaurant=restaurant,
        name="Burger",
        sku="BUR-01",
        category=category,
        cost_price=Decimal("400.00"),
        sale_price=Decimal("1000.00"),
    )
    wine = Product.objects.create(
        restaurant=restaurant,
        name="Wine",
        sku="WIN-01",
        category=category,
        cost_price=Decimal("500.00"),
        sale_price=Decimal("2000.00"),
    )
    return burger, wine


def _add_sale(product, external_id, day, quantity, unit_price, unit_cost):
    sale = Sale.objects.create(
        restaurant=product.restaurant,
        external_id=external_id,
        occurred_at=datetime(2026, 1, day, 12, 0, tzinfo=timezone.utc),
        total=unit_price * quantity,
    )
    SaleItem.objects.create(
        sale=sale,
        product=product,
        quantity=quantity,
        unit_price=unit_price,
        unit_cost=unit_cost,
    )


@pytest.fixture
def sales(products):
    burger, wine = products
    # day 10: 2 burgers -> rev 2000, margin 1200
    _add_sale(burger, "S1", 10, 2, Decimal("1000.00"), Decimal("400.00"))
    # day 11: 3 wines  -> rev 6000, margin 4500
    _add_sale(wine, "S2", 11, 3, Decimal("2000.00"), Decimal("500.00"))
    # day 20: 1 burger -> rev 1000, margin 600
    _add_sale(burger, "S3", 20, 1, Decimal("1000.00"), Decimal("400.00"))


# --- service tests ---------------------------------------------------------


@pytest.mark.django_db
def test_compute_kpis_aggregates_all_metrics(restaurant, sales):
    kpis = compute_kpis(restaurant)

    assert kpis["total_revenue"] == Decimal("9000.00")
    assert kpis["items_sold"] == 6
    assert kpis["average_ticket"] == Decimal("3000.00")  # 9000 / 3 sales
    assert kpis["gross_margin_pct"] == Decimal("70.00")  # 6300 / 9000 * 100


@pytest.mark.django_db
def test_compute_kpis_zero_without_sales(restaurant):
    kpis = compute_kpis(restaurant)

    assert kpis["total_revenue"] == Decimal("0")
    assert kpis["items_sold"] == 0
    assert kpis["average_ticket"] == Decimal("0")
    assert kpis["gross_margin_pct"] == Decimal("0")


@pytest.mark.django_db
def test_compute_kpis_respects_date_range(restaurant, sales):
    # Only the day-20 sale falls in this window.
    kpis = compute_kpis(restaurant, start=date(2026, 1, 15), end=date(2026, 1, 31))

    assert kpis["total_revenue"] == Decimal("1000.00")
    assert kpis["items_sold"] == 1
    assert kpis["average_ticket"] == Decimal("1000.00")
    assert kpis["gross_margin_pct"] == Decimal("60.00")  # 600 / 1000 * 100


# --- view tests ------------------------------------------------------------


@pytest.mark.django_db
def test_dashboard_renders_four_kpis(logged_client, sales):
    # Pass an explicit range covering the fixture data; the default window is
    # the last 30 days (see US13), which would exclude these January sales.
    response = logged_client.get(
        reverse("analytics:dashboard"), {"start": "2026-01-01", "end": "2026-01-31"}
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "$9,000.00" in content  # total revenue, thousands separator
    assert ">6</p>" in content  # items sold
    assert "$3,000.00" in content  # average ticket
    assert "70.0%" in content  # gross margin


@pytest.mark.django_db
def test_dashboard_respects_date_range(logged_client, sales):
    response = logged_client.get(
        reverse("analytics:dashboard"), {"start": "2026-01-15", "end": "2026-01-31"}
    )

    kpis = response.context["kpis"]
    assert kpis["total_revenue"] == Decimal("1000.00")
    assert kpis["items_sold"] == 1
    assert "$1,000.00" in response.content.decode()
