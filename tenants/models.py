from django.conf import settings
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
