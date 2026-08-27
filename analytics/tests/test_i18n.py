"""Tests for the bilingual EN/ES UI (US21)."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.conf import settings
from django.urls import reverse

from catalog.models import Category, Product
from sales.models import Sale, SaleItem


@pytest.fixture
def dashboard_data(restaurant):
    """One sale so the dashboard renders KPIs/charts (not the empty state)."""
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


@pytest.mark.django_db
def test_dashboard_renders_english_by_default(logged_client, dashboard_data):
    response = logged_client.get(reverse("analytics:dashboard"))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Total revenue" in body
    assert "Average ticket" in body


@pytest.mark.django_db
def test_switcher_changes_active_language_to_spanish(logged_client):
    # Posting to Django's set_language view should persist the choice.
    response = logged_client.post(
        reverse("set_language"),
        {"language": "es", "next": reverse("analytics:dashboard")},
    )

    assert response.status_code == 302
    cookie = response.cookies.get(settings.LANGUAGE_COOKIE_NAME)
    assert cookie is not None
    assert cookie.value == "es"


@pytest.mark.django_db
def test_dashboard_renders_spanish_when_language_is_es(logged_client, dashboard_data):
    logged_client.post(
        reverse("set_language"),
        {"language": "es", "next": reverse("analytics:dashboard")},
    )

    response = logged_client.get(reverse("analytics:dashboard"))
    body = response.content.decode()

    assert response.status_code == 200
    # Translated user-facing strings from locale/es/LC_MESSAGES/django.po
    assert "Ingresos totales" in body  # "Total revenue"
    assert "Ticket promedio" in body  # "Average ticket"
    assert "Margen bruto" in body  # "Gross margin"
    # And no leftover English on the dashboard.
    assert "Total revenue" not in body


@pytest.mark.django_db
def test_margin_columns_translated_in_spanish(logged_client):
    logged_client.post(
        reverse("set_language"),
        {"language": "es", "next": reverse("analytics:margin_analysis")},
    )

    response = logged_client.get(reverse("analytics:margin_analysis"))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Análisis de márgenes" in body
    assert "Precio de venta" in body  # column header "Sale price" -> gettext_lazy
