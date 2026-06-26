from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from analytics.views import DEFAULT_RANGE_DAYS
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


def _add_sale(product, external_id, days_ago, quantity):
    # Anchor to local noon so the ``__date`` lookup is unambiguous regardless
    # of when the test runs.
    occurred = timezone.localtime().replace(
        hour=12, minute=0, second=0, microsecond=0
    ) - timedelta(days=days_ago)
    sale = Sale.objects.create(
        restaurant=product.restaurant,
        external_id=external_id,
        occurred_at=occurred,
        total=Decimal("10.00") * quantity,
    )
    SaleItem.objects.create(
        sale=sale,
        product=product,
        quantity=quantity,
        unit_price=Decimal("10.00"),
        unit_cost=Decimal("4.00"),
    )


@pytest.mark.django_db
def test_dashboard_defaults_to_last_30_days(logged_client, product):
    _add_sale(product, "RECENT", days_ago=5, quantity=2)  # inside window
    _add_sale(product, "OLD", days_ago=60, quantity=7)  # outside window

    response = logged_client.get(reverse("analytics:dashboard"))

    assert response.status_code == 200
    today = timezone.localdate()
    assert response.context["end"] == today
    assert response.context["start"] == today - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    # Only the recent sale counts under the default range.
    assert response.context["kpis"]["items_sold"] == 2


@pytest.mark.django_db
def test_dashboard_explicit_range_overrides_default(logged_client, product):
    _add_sale(product, "RECENT", days_ago=5, quantity=2)
    _add_sale(product, "OLD", days_ago=60, quantity=7)

    today = timezone.localdate()
    start = today - timedelta(days=70)
    end = today - timedelta(days=50)
    response = logged_client.get(
        reverse("analytics:dashboard"),
        {"start": start.isoformat(), "end": end.isoformat()},
    )

    assert response.context["start"] == start
    assert response.context["end"] == end
    # Only the 60-days-ago sale falls in the explicit window.
    assert response.context["kpis"]["items_sold"] == 7


@pytest.mark.django_db
def test_dashboard_range_persists_in_picker(logged_client, product):
    today = timezone.localdate()
    start = today - timedelta(days=7)
    response = logged_client.get(
        reverse("analytics:dashboard"),
        {"start": start.isoformat(), "end": today.isoformat()},
    )

    content = response.content.decode()
    assert f'value="{start.isoformat()}"' in content
    assert f'value="{today.isoformat()}"' in content
