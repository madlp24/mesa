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


# --- US34: hamburger menu + change password ---------------------------------


@pytest.mark.django_db
def test_menu_lists_destinations_and_change_password(logged_client):
    body = logged_client.get(reverse("analytics:dashboard")).content.decode()
    # A single hamburger menu holds every destination...
    assert 'id="mainMenu"' in body
    for name in ("analytics:margin_analysis", "catalog:product_list",
                 "sales:upload", "quotes:quote_list", "pages:help"):
        assert reverse(name) in body
    # ...and the self-service change-password link.
    assert reverse("account_change_password") in body


@pytest.mark.django_db
def test_menu_shows_login_and_signup_for_anonymous(client):
    body = client.get(reverse("pages:help")).content.decode()
    assert reverse("account_login") in body
    assert reverse("account_signup") in body
    # No account-only actions leak to anonymous visitors.
    assert reverse("account_change_password") not in body


@pytest.mark.django_db
def test_change_password_page_renders(logged_client):
    response = logged_client.get(reverse("account_change_password"))
    assert response.status_code == 200
