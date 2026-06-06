import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


@pytest.mark.django_db
def test_logout_ends_session_and_redirects_to_login(client):
    User = get_user_model()
    User.objects.create_user(
        username="tomas", email="tomas@example.com", password="secret123"
    )
    client.login(username="tomas", password="secret123")

    response = client.post(reverse("account_logout"))

    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_dashboard_redirects_to_login_after_logout(client):
    User = get_user_model()
    User.objects.create_user(
        username="tomas", email="tomas@example.com", password="secret123"
    )
    client.login(username="tomas", password="secret123")
    client.post(reverse("account_logout"))

    response = client.get(reverse("analytics:dashboard"))

    assert response.status_code == 302
    assert "/accounts/login/" in response.url
