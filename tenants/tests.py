"""Multi-tenant isolation tests (US24)."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from analytics.exports import build_productos_vendidos_workbook
from analytics.services import compute_kpis
from catalog.models import Category, Product
from sales.models import Sale, SaleItem
from tenants.models import Membership, Restaurant


def _restaurant_with_sale(slug, product_name, qty, price):
    restaurant = Restaurant.objects.create(name=slug.title(), slug=slug)
    category = Category.objects.create(restaurant=restaurant, name="Mains")
    product = Product.objects.create(
        restaurant=restaurant, name=product_name, sku="P1", category=category,
        cost_price=Decimal("1"), sale_price=price,
    )
    sale = Sale.objects.create(
        restaurant=restaurant, external_id="S1",
        occurred_at=datetime(2026, 1, 5, 12, tzinfo=timezone.utc), total=price * qty,
    )
    SaleItem.objects.create(
        sale=sale, product=product, quantity=qty, unit_price=price, unit_cost=Decimal("1")
    )
    return restaurant


def _user_for(restaurant, username):
    user = get_user_model().objects.create_user(username=username, password="secret123")
    Membership.objects.update_or_create(user=user, defaults={"restaurant": restaurant})
    return user


@pytest.mark.django_db
def test_signup_provisions_a_restaurant():
    user = get_user_model().objects.create_user(username="newbie", password="secret123")
    membership = Membership.objects.get(user=user)
    assert membership.restaurant_id is not None


@pytest.mark.django_db
def test_kpis_are_scoped_per_restaurant():
    a = _restaurant_with_sale("alpha", "Burger", 2, Decimal("100"))
    b = _restaurant_with_sale("bravo", "Pizza", 5, Decimal("200"))

    assert compute_kpis(a)["total_revenue"] == Decimal("200")  # 2 x 100
    assert compute_kpis(b)["total_revenue"] == Decimal("1000")  # 5 x 200


@pytest.mark.django_db
def test_dashboard_shows_only_my_restaurant_data(client):
    a = _restaurant_with_sale("alpha", "Burger", 2, Decimal("100"))
    _restaurant_with_sale("bravo", "Pizza", 5, Decimal("200"))
    client.force_login(_user_for(a, "alice"))

    response = client.get(
        reverse("analytics:dashboard"), {"start": "2026-01-01", "end": "2026-01-31"}
    )

    assert response.context["kpis"]["total_revenue"] == Decimal("200")


@pytest.mark.django_db
def test_export_contains_only_my_products(client):
    a = _restaurant_with_sale("alpha", "Burger", 2, Decimal("100"))
    _restaurant_with_sale("bravo", "Pizza", 5, Decimal("200"))

    ws = build_productos_vendidos_workbook(a).active
    names = [row[2] for row in ws.iter_rows(min_row=2, values_only=True)]
    assert names == ["Burger"]  # never "Pizza"


@pytest.mark.django_db
def test_cannot_open_another_restaurants_product(client):
    a = _restaurant_with_sale("alpha", "Burger", 2, Decimal("100"))
    b = _restaurant_with_sale("bravo", "Pizza", 5, Decimal("200"))
    others_product = Product.objects.get(restaurant=b)
    client.force_login(_user_for(a, "alice"))

    response = client.get(reverse("catalog:product_detail", args=[others_product.pk]))
    assert response.status_code == 404
