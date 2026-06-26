"""Shared pytest fixtures for the multi-tenant test suite."""
import pytest
from django.contrib.auth import get_user_model

from tenants.models import Membership, Restaurant


@pytest.fixture
def restaurant(db):
    """A tenant to attach test data to."""
    return Restaurant.objects.create(name="Test Restaurant", slug="test-restaurant")


@pytest.fixture
def user(db, restaurant):
    """A user whose membership points at the ``restaurant`` fixture.

    Creating a user auto-provisions a restaurant (see tenants.signals); we
    repoint the membership so the logged-in user and the test data share one
    tenant.
    """
    user = get_user_model().objects.create_user(
        username="owner", email="owner@example.com", password="secret123"
    )
    Membership.objects.update_or_create(user=user, defaults={"restaurant": restaurant})
    return user


@pytest.fixture
def logged_client(client, user):
    client.force_login(user)
    return client
