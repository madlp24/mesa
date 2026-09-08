"""Moving people between restaurants."""
from django.db import transaction
from django.utils import timezone

from .models import Invitation, Membership, Restaurant


def restaurant_is_empty(restaurant: Restaurant) -> bool:
    """True when losing this restaurant would lose nothing."""
    return not any(
        [
            restaurant.products.exists(),
            restaurant.categories.exists(),
            restaurant.sales.exists(),
            restaurant.quotes.exists(),
            restaurant.menu_items.exists(),
        ]
    )


@transaction.atomic
def accept_invitation(invitation: Invitation, user) -> Restaurant:
    """Put ``user`` into the invited restaurant, tidying the one they leave.

    Signing up hands everyone a restaurant of their own. For someone who only
    signed up to accept an invitation that workspace is an accident, so it is
    removed -- but only when it is genuinely empty, since somebody may be
    switching from a restaurant they have been using.
    """
    previous = Membership.objects.filter(user=user).select_related("restaurant").first()
    leaving = previous.restaurant if previous else None

    Membership.objects.update_or_create(
        user=user, defaults={"restaurant": invitation.restaurant}
    )

    if leaving and leaving != invitation.restaurant:
        if not leaving.memberships.exists() and restaurant_is_empty(leaving):
            leaving.delete()

    invitation.accepted_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=["accepted_at", "accepted_by"])
    return invitation.restaurant
