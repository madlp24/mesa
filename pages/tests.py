"""Tests for the public landing and help pages (US33)."""
import pytest
from django.urls import reverse

from pages.views import CONTACT_EMAIL


@pytest.mark.django_db
def test_landing_is_public(client):
    response = client.get(reverse("pages:landing"))
    assert response.status_code == 200
    assert b"Mesa" in response.content
    # Public CTAs to sign up / log in are present.
    assert reverse("account_signup").encode() in response.content


@pytest.mark.django_db
def test_landing_redirects_authenticated_user_to_dashboard(logged_client):
    response = logged_client.get(reverse("pages:landing"))
    assert response.status_code == 302
    assert response.url == reverse("analytics:dashboard")


@pytest.mark.django_db
def test_help_is_public_and_shows_contact_email(client):
    response = client.get(reverse("pages:help"))
    assert response.status_code == 200
    assert CONTACT_EMAIL.encode() in response.content
    assert f"mailto:{CONTACT_EMAIL}".encode() in response.content


@pytest.mark.django_db
def test_dashboard_moved_off_the_root_url(client):
    # Root is now the public landing, not the dashboard.
    assert reverse("pages:landing") == "/"
    assert reverse("analytics:dashboard") == "/dashboard/"


@pytest.mark.django_db
def test_dashboard_still_requires_login_at_new_url(client):
    response = client.get(reverse("analytics:dashboard"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url
