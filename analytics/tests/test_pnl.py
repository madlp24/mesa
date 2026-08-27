from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from analytics.services import monthly_pnl
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


def _sell(product, external_id, year, month, day, quantity):
    sale = Sale.objects.create(
        restaurant=product.restaurant,
        external_id=external_id,
        occurred_at=datetime(year, month, day, 12, 0, tzinfo=UTC),
        total=product.sale_price * quantity,
    )
    SaleItem.objects.create(
        sale=sale,
        product=product,
        quantity=quantity,
        unit_price=product.sale_price,
        unit_cost=product.cost_price,
    )


# --- service tests ---------------------------------------------------------


@pytest.mark.django_db
def test_monthly_pnl_aggregates_revenue_cogs_margin(product):
    # Two sales in the same month bucket: revenue 30+20=50, cogs 12+8=20.
    _sell(product, "A", 2026, 3, 5, 3)  # rev 30, cogs 12
    _sell(product, "B", 2026, 3, 20, 2)  # rev 20, cogs 8

    rows = monthly_pnl(product.restaurant, year=2026)
    march = next(r for r in rows if r["month"] == date(2026, 3, 1))

    assert march["revenue"] == Decimal("50.00")
    assert march["cogs"] == Decimal("20.00")
    assert march["gross_margin"] == Decimal("30.00")
    assert march["gross_margin_pct"] == Decimal("60.00")  # 30 / 50 * 100


@pytest.mark.django_db
def test_year_filter_returns_twelve_months_ascending(product):
    _sell(product, "A", 2026, 1, 5, 1)
    rows = monthly_pnl(product.restaurant, year=2026)

    assert len(rows) == 12
    assert [r["month"].month for r in rows] == list(range(1, 13))
    assert all(r["month"].year == 2026 for r in rows)


@pytest.mark.django_db
def test_months_without_sales_are_zero_filled(product):
    _sell(product, "A", 2026, 1, 5, 1)
    rows = monthly_pnl(product.restaurant, year=2026)
    february = next(r for r in rows if r["month"] == date(2026, 2, 1))

    assert february["revenue"] == Decimal("0")
    assert february["cogs"] == Decimal("0")
    assert february["gross_margin"] == Decimal("0")
    assert february["gross_margin_pct"] == Decimal("0")


@pytest.mark.django_db
def test_default_is_trailing_twelve_months(product):
    today = date(2026, 6, 19)
    rows = monthly_pnl(product.restaurant, today=today)

    assert len(rows) == 12
    assert rows[0]["month"] == date(2025, 7, 1)  # 11 months back
    assert rows[-1]["month"] == date(2026, 6, 1)  # current month last


# --- view test -------------------------------------------------------------


@pytest.mark.django_db
def test_pnl_page_requires_authentication(client):
    response = client.get(reverse("analytics:pnl_summary"))

    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_pnl_page_renders_year_filter(logged_client, product):
    _sell(product, "A", 2026, 3, 5, 3)

    response = logged_client.get(reverse("analytics:pnl_summary"), {"year": "2026"})

    assert response.status_code == 200
    assert response.context["selected_year"] == 2026
    assert len(response.context["rows"]) == 12
    assert 2026 in response.context["years"]
    assert "Mar 2026" in response.content.decode()
