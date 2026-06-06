from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from catalog.models import Category, Product
from sales.models import Sale, SaleItem


@pytest.fixture
def product(db):
    category = Category.objects.create(name="Mains")
    return Product.objects.create(
        name="Burger",
        sku="BUR-01",
        category=category,
        cost_price=Decimal("4.00"),
        sale_price=Decimal("10.00"),
    )


def _add_sale(product, external_id, day, quantity):
    sale = Sale.objects.create(
        external_id=external_id,
        occurred_at=datetime(2026, 1, day, 12, 0, tzinfo=timezone.utc),
        total=Decimal("0.00"),
    )
    SaleItem.objects.create(
        sale=sale,
        product=product,
        quantity=quantity,
        unit_price=Decimal("10.00"),
        unit_cost=Decimal("4.00"),
    )


@pytest.fixture
def logged_client(client, db):
    user = get_user_model().objects.create_user(
        username="owner", email="owner@example.com", password="secret123"
    )
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_detail_requires_authentication(client, product):
    response = client.get(reverse("catalog:product_detail", args=[product.pk]))

    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_series_requires_authentication(client, product):
    response = client.get(reverse("catalog:product_sales_series", args=[product.pk]))

    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_detail_computes_kpis(logged_client, product):
    _add_sale(product, "S1", 10, 3)
    _add_sale(product, "S2", 11, 2)

    response = logged_client.get(reverse("catalog:product_detail", args=[product.pk]))

    assert response.status_code == 200
    assert response.context["units_sold"] == 5
    assert response.context["total_revenue"] == Decimal("50.00")
    assert response.context["total_margin"] == Decimal("30.00")


@pytest.mark.django_db
def test_detail_kpis_are_zero_without_sales(logged_client, product):
    response = logged_client.get(reverse("catalog:product_detail", args=[product.pk]))

    assert response.context["units_sold"] == 0
    assert response.context["total_revenue"] == 0
    assert response.context["total_margin"] == 0


@pytest.mark.django_db
def test_date_range_filters_kpis(logged_client, product):
    _add_sale(product, "S1", 10, 3)
    _add_sale(product, "S2", 20, 2)

    url = reverse("catalog:product_detail", args=[product.pk])
    response = logged_client.get(url, {"start": "2026-01-15", "end": "2026-01-31"})

    assert response.context["units_sold"] == 2
    assert response.context["total_revenue"] == Decimal("20.00")


@pytest.mark.django_db
def test_series_returns_units_per_day(logged_client, product):
    _add_sale(product, "S1", 10, 3)
    _add_sale(product, "S2", 11, 2)

    response = logged_client.get(
        reverse("catalog:product_sales_series", args=[product.pk])
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["labels"] == ["2026-01-10", "2026-01-11"]
    assert payload["data"] == [3, 2]
