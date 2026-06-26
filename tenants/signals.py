"""Provision a restaurant for every new user.

On signup (allauth) or any other user creation, ensure the user has a
:class:`~tenants.models.Membership` pointing at a freshly created restaurant, so
the account always has an isolated workspace to land in.
"""
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Membership, Restaurant


def ensure_restaurant(user) -> Restaurant:
    """Return the user's restaurant, creating it and the membership if missing."""
    membership = Membership.objects.filter(user=user).first()
    if membership:
        return membership.restaurant
    name = (user.get_username() or "Mi restaurante").strip()
    restaurant = Restaurant.objects.create(name=name)
    Membership.objects.create(user=user, restaurant=restaurant)
    return restaurant


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_restaurant_for_new_user(sender, instance, created, **kwargs):
    if created:
        ensure_restaurant(instance)
