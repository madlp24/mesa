import secrets
from datetime import timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.db import models
from django.utils.text import slugify


class Restaurant(models.Model):
    """A tenant: one restaurant's private workspace.

    Mesa is multi-tenant via shared-database, row-level scoping. Every
    tenant-owned record (categories, products, aliases, sales) carries a
    ``restaurant`` FK and every query is filtered by the current user's
    restaurant, so one restaurant never sees another's data.
    """

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    #: The restaurant's mark, used as the watermark on quotes it sends out.
    #: Kept in the row rather than on disk: Heroku's filesystem is ephemeral,
    #: and a logo is small enough that a bucket would be a lot of machinery
    #: for one image per tenant.
    logo = models.BinaryField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)

    def _unique_slug(self) -> str:
        base = slugify(self.name) or "restaurante"
        slug = base
        suffix = 2
        while Restaurant.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

    def __str__(self):
        return self.name


class Membership(models.Model):
    """Links a user to their restaurant. MVP: one restaurant per user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="membership",
    )
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name="memberships"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} -> {self.restaurant}"


class Invitation(models.Model):
    """A link that puts someone into an existing restaurant.

    Signing up provisions a restaurant of your own, which is right for the first
    person and wrong for everyone after them: the second person to join a
    restaurant ends up alone in an empty copy, often under the same name, and
    nothing on screen says so. An invitation is how somebody joins a workspace
    that already exists.

    The link is the invitation. There is no mail server here, and a restaurant
    owner sends it over WhatsApp anyway.
    """

    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name="invitations"
    )
    token = models.CharField(max_length=64, unique=True, editable=False)
    #: Only a label for whoever is looking at the list; nothing is sent to it.
    email = models.EmailField(blank=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="invitations_sent",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invitations_accepted",
    )

    DAYS_VALID = 14

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email or self.token[:8]} -> {self.restaurant}"

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=self.DAYS_VALID)
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_open(self) -> bool:
        return self.accepted_at is None and not self.is_expired

    def path(self) -> str:
        return reverse("accept_invitation", args=[self.token])
