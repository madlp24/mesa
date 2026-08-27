"""First-run experience tests (US26): signup naming, empty state, rename."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from catalog.models import Category, Product
from sales.models import Sale, SaleItem
from tenants.models import Membership, Restaurant


@pytest.mark.django_db
def test_signup_sets_restaurant_name(client):
    response = client.post(
        reverse("account_signup"),
        {
            "username": "carlos",
            "email": "carlos@example.com",
            "password1": "SuperSecret123",
            "password2": "SuperSecret123",
            "restaurant_name": "La Parrilla",
        },
    )
    # Successful signup redirects (logged in).
    assert response.status_code == 302
    membership = Membership.objects.get(user__username="carlos")
    assert membership.restaurant.name == "La Parrilla"
    assert membership.restaurant.slug == "la-parrilla"


@pytest.mark.django_db
def test_empty_dashboard_shows_first_run_cta(logged_client):
    response = logged_client.get(reverse("analytics:dashboard"))
    body = response.content.decode()
    assert response.context["has_data"] is False
    assert "Upload your first report" in body
    # No chart canvases when there is no data.
    assert "revenueChart" not in body


@pytest.mark.django_db
def test_dashboard_with_data_hides_cta(logged_client, restaurant):
    category = Category.objects.create(restaurant=restaurant, name="Mains")
    product = Product.objects.create(
        restaurant=restaurant, name="Burger", sku="B1", category=category,
        cost_price=Decimal("4"), sale_price=Decimal("10"),
    )
    sale = Sale.objects.create(
        restaurant=restaurant, external_id="S1",
        occurred_at=datetime(2026, 6, 1, 12, tzinfo=UTC), total=Decimal("10"),
    )
    SaleItem.objects.create(
        sale=sale, product=product, quantity=1,
        unit_price=Decimal("10"), unit_cost=Decimal("4"),
    )

    response = logged_client.get(reverse("analytics:dashboard"))
    body = response.content.decode()
    assert response.context["has_data"] is True
    assert "Upload your first report" not in body
    assert "revenueChart" in body


@pytest.mark.django_db
def test_settings_requires_authentication(client):
    response = client.get(reverse("tenants:settings"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_owner_can_rename_their_restaurant(logged_client, restaurant):
    response = logged_client.post(
        reverse("tenants:settings"), {"name": "Nuevo Nombre"}
    )
    assert response.status_code == 302
    restaurant.refresh_from_db()
    assert restaurant.name == "Nuevo Nombre"


@pytest.mark.django_db
def test_rename_only_touches_my_restaurant(logged_client, restaurant):
    other = Restaurant.objects.create(name="Otro", slug="otro")
    logged_client.post(reverse("tenants:settings"), {"name": "Cambiado"})
    other.refresh_from_db()
    assert other.name == "Otro"  # untouched
