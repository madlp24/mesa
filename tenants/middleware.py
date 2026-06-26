"""Attach the current restaurant to each request.

``request.restaurant`` is the authenticated user's restaurant (or ``None`` for
anonymous requests). Views and the services they call use it to scope every
query to a single tenant.
"""
from .models import Membership


class CurrentRestaurantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.restaurant = self._resolve(request)
        return self.get_response(request)

    @staticmethod
    def _resolve(request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        membership = (
            Membership.objects.select_related("restaurant")
            .filter(user=user)
            .first()
        )
        return membership.restaurant if membership else None
