import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


@pytest.mark.django_db
def test_anonymous_user_redirected_to_login(client):
    response = client.get(reverse("analytics:dashboard"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_authenticated_user_reaches_dashboard(client):
    User = get_user_model()
    User.objects.create_user(username="tomas", email="tomas@example.com", password="secret123")
    client.login(username="tomas", password="secret123")
    response = client.get(reverse("analytics:dashboard"))
    assert response.status_code == 200
