"""Helpers for resolving the active restaurant in management commands."""
from django.core.management.base import CommandError

from .models import Restaurant


def resolve_restaurant(slug: str | None) -> Restaurant:
    """Return the restaurant for ``slug``, or the only one if ``slug`` is None.

    Raises :class:`CommandError` when the slug is unknown, when none exist, or
    when several exist and no slug was given.
    """
    if slug:
        try:
            return Restaurant.objects.get(slug=slug)
        except Restaurant.DoesNotExist as exc:
            raise CommandError(f"No restaurant with slug '{slug}'") from exc
    restaurants = list(Restaurant.objects.all()[:2])
    if not restaurants:
        raise CommandError("No restaurants exist; create one first.")
    if len(restaurants) > 1:
        raise CommandError("Multiple restaurants exist; pass --restaurant <slug>.")
    return restaurants[0]
