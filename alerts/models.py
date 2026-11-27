"""What each restaurant wants to be warned about (US54)."""
from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _


class Cadence(models.TextChoices):
    WEEK = "week", _("Weekly: the last 7 days")
    MONTH = "month", _("Monthly: the last 30 days")


class Baseline(models.TextChoices):
    PREVIOUS = "previous", _("Against the period before")
    LAST_YEAR = "last_year", _("Against the same period a year earlier")


class AlertSettings(models.Model):
    """One per restaurant, created with the defaults the first time it is read."""

    restaurant = models.OneToOneField(
        "tenants.Restaurant", on_delete=models.CASCADE, related_name="alert_settings"
    )
    cadence = models.CharField(max_length=10, choices=Cadence.choices, default=Cadence.WEEK)
    baseline = models.CharField(
        max_length=10, choices=Baseline.choices, default=Baseline.PREVIOUS
    )
    #: A product's cost per portion rising this much (%) is worth a warning.
    cost_rise = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal("5"))
    #: Margin points lost.
    margin_drop = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal("3"))
    #: One jump of this size (%) in a single day or a single purchase.
    abrupt_change = models.DecimalField(
        max_digits=5, decimal_places=1, default=Decimal("15")
    )
    #: Products selling less than this a week are left out of the noise.
    min_weekly_sales = models.PositiveIntegerField(default=300000)

    def __str__(self):
        return f"Alerts for {self.restaurant}"

    @classmethod
    def for_restaurant(cls, restaurant) -> "AlertSettings":
        settings, _created = cls.objects.get_or_create(restaurant=restaurant)
        return settings
