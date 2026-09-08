"""Letting a second person into a restaurant that already exists."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from catalog.models import Category, Product
from quotes.models import Quote
from tenants.models import Invitation, Membership, Restaurant
from tenants.services import accept_invitation, restaurant_is_empty


def _user(username):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@example.com", password="secret123"
    )


@pytest.fixture
def invitation(db, restaurant, user):
    return Invitation.objects.create(restaurant=restaurant, invited_by=user)


@pytest.mark.django_db
class TestInvitationModel:
    def test_it_gets_a_token_and_an_expiry(self, invitation):
        assert invitation.token
        assert invitation.is_open is True
        assert invitation.expires_at > timezone.now()

    def test_an_expired_one_is_closed(self, invitation):
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        invitation.save()

        assert invitation.is_open is False

    def test_an_accepted_one_is_closed(self, invitation, restaurant):
        accept_invitation(invitation, _user("nicole"))
        invitation.refresh_from_db()

        assert invitation.is_open is False

    def test_tokens_do_not_repeat(self, restaurant):
        tokens = {Invitation.objects.create(restaurant=restaurant).token for _ in range(20)}

        assert len(tokens) == 20


@pytest.mark.django_db
class TestAccepting:
    def test_the_invited_user_lands_in_the_restaurant(self, invitation, restaurant):
        nicole = _user("nicole")

        accept_invitation(invitation, nicole)

        assert Membership.objects.get(user=nicole).restaurant == restaurant

    def test_the_empty_workspace_signup_gave_them_is_cleared_away(self, invitation, restaurant):
        """Signing up hands everyone a restaurant; for an invitee it is an accident."""
        nicole = _user("nicole")
        theirs = Membership.objects.get(user=nicole).restaurant

        accept_invitation(invitation, nicole)

        assert not Restaurant.objects.filter(pk=theirs.pk).exists()

    def test_a_workspace_with_work_in_it_is_kept(self, invitation, restaurant):
        """Somebody switching restaurants must not lose the one they leave."""
        nicole = _user("nicole")
        theirs = Membership.objects.get(user=nicole).restaurant
        Quote.objects.create(restaurant=theirs, number="CA-1", client_name="Suyo")

        accept_invitation(invitation, nicole)

        assert Restaurant.objects.filter(pk=theirs.pk).exists()
        assert Membership.objects.get(user=nicole).restaurant == restaurant

    def test_a_workspace_still_holding_someone_is_kept(self, invitation, restaurant):
        nicole = _user("nicole")
        shared = Membership.objects.get(user=nicole).restaurant
        otro = _user("otro")
        Membership.objects.update_or_create(user=otro, defaults={"restaurant": shared})

        accept_invitation(invitation, nicole)

        assert Restaurant.objects.filter(pk=shared.pk).exists()

    def test_a_restaurant_with_products_is_not_empty(self, restaurant):
        category = Category.objects.create(restaurant=restaurant, name="C")
        Product.objects.create(
            restaurant=restaurant, name="P", sku="P1", category=category,
            cost_price=Decimal("1"), sale_price=Decimal("2"),
        )

        assert restaurant_is_empty(restaurant) is False


@pytest.mark.django_db
class TestInvitationViews:
    def test_the_owner_creates_one(self, logged_client, restaurant):
        logged_client.post(reverse("tenants:invite"), {"email": "nicole@example.com"})

        invitation = Invitation.objects.get(restaurant=restaurant)
        assert invitation.email == "nicole@example.com"
        assert invitation.is_open

    def test_the_link_appears_on_the_settings_page(self, logged_client, restaurant, invitation):
        response = logged_client.get(reverse("tenants:settings"))

        assert invitation.token in response.content.decode()

    def test_a_stranger_sees_a_sign_in_prompt(self, client, invitation, restaurant):
        response = client.get(reverse("accept_invitation", args=[invitation.token]))

        assert response.status_code == 200
        assert restaurant.name.encode() in response.content

    def test_a_signed_in_user_joins_straight_away(self, client, invitation, restaurant):
        nicole = _user("nicole")
        client.force_login(nicole)

        response = client.get(reverse("accept_invitation", args=[invitation.token]))

        assert response.status_code == 302
        assert Membership.objects.get(user=nicole).restaurant == restaurant

    def test_a_bad_token_is_refused(self, client):
        assert client.get(reverse("accept_invitation", args=["nope"])).status_code == 404

    def test_a_used_link_cannot_be_used_again(self, client, invitation, restaurant):
        accept_invitation(invitation, _user("nicole"))
        intruso = _user("intruso")
        suyo = Membership.objects.get(user=intruso).restaurant
        client.force_login(intruso)

        response = client.get(reverse("accept_invitation", args=[invitation.token]))

        assert response.status_code == 404
        assert Membership.objects.get(user=intruso).restaurant == suyo

    def test_revoking_closes_the_door(self, logged_client, restaurant, invitation, client):
        logged_client.post(reverse("tenants:revoke_invitation", args=[invitation.pk]))

        client.force_login(_user("nicole"))
        assert client.get(reverse("accept_invitation", args=[invitation.token])).status_code == 404

    def test_another_restaurant_invitation_cannot_be_revoked(self, logged_client):
        otro = Restaurant.objects.create(name="Otro", slug="otro-inv")
        ajena = Invitation.objects.create(restaurant=otro)

        response = logged_client.post(reverse("tenants:revoke_invitation", args=[ajena.pk]))

        assert response.status_code == 404
        assert Invitation.objects.filter(pk=ajena.pk).exists()


@pytest.mark.django_db
class TestMembers:
    def test_someone_can_be_removed(self, logged_client, restaurant):
        nicole = _user("nicole")
        membership, _ = Membership.objects.update_or_create(
            user=nicole, defaults={"restaurant": restaurant}
        )

        logged_client.post(reverse("tenants:remove_member", args=[membership.pk]))

        assert not Membership.objects.filter(user=nicole).exists()

    def test_you_cannot_remove_yourself(self, logged_client, restaurant, user):
        """Otherwise the last person out locks the door behind them."""
        mine = Membership.objects.get(user=user)

        logged_client.post(reverse("tenants:remove_member", args=[mine.pk]))

        assert Membership.objects.filter(pk=mine.pk).exists()

    def test_a_member_of_another_restaurant_is_out_of_reach(self, logged_client):
        otro = Restaurant.objects.create(name="Otro", slug="otro-mem")
        ajeno = _user("ajeno")
        membership, _ = Membership.objects.update_or_create(
            user=ajeno, defaults={"restaurant": otro}
        )

        response = logged_client.post(reverse("tenants:remove_member", args=[membership.pk]))

        assert response.status_code == 404
        assert Membership.objects.filter(pk=membership.pk).exists()
