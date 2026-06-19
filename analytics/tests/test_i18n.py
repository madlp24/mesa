"""Tests for the bilingual EN/ES UI (US21)."""
import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse


@pytest.fixture
def logged_client(client, db):
    user = get_user_model().objects.create_user(
        username="owner", email="owner@example.com", password="secret123"
    )
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_dashboard_renders_english_by_default(logged_client):
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
def test_dashboard_renders_spanish_when_language_is_es(logged_client):
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
