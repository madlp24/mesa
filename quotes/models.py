"""Event quotes built from the restaurant's own catalog.

A quote is what the client sees; a ``catalog.Product`` is what the POS sells.
They are not the same thing: the POS calls a dish ``CROQUETAS DE LOMO AHUMADO
*4U`` while the proposal has to read "Croquetas de lomo ahumado" with a line of
description under it. ``MenuItem`` is that presentation layer, and its link to a
product is what lets a quote know its own cost.
"""
from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

#: Impuesto al consumo. Menu and quote prices are quoted with it already inside;
#: the POS stores ``sale_price`` net of it.
TAX_RATE = Decimal("0.08")

#: Suggested tip, applied over the pre-tax base (not over the taxed price).
DEFAULT_TIP_RATE = Decimal("0.10")

ZERO = Decimal(0)


class Course(models.TextChoices):
    STARTERS = "starters", _("Starters")
    MAINS = "mains", _("Mains")
    SIDES = "sides", _("Sides")
    DESSERTS = "desserts", _("Desserts")
    ALCOHOL = "alcohol", _("Alcoholic drinks")
    SOFT = "soft", _("Soft drinks")
    OTHER = "other", _("Other")


class PricingMode(models.TextChoices):
    CONSUMPTION = "consumption", _("By consumption")
    PER_GUEST = "per_guest", _("Price per guest")


class MenuItem(models.Model):
    """A dish or drink as it appears on a quote, priced tax-inclusive.

    ``product`` is the POS product this item is served from — the only source of
    cost. ``product_units`` bridges the two when their units differ: a menu item
    sold by the kilo whose product is a 420 g portion consumes 1000/420 units.
    """

    restaurant = models.ForeignKey(
        "tenants.Restaurant", on_delete=models.CASCADE, related_name="menu_items"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    course = models.CharField(max_length=20, choices=Course.choices, default=Course.STARTERS)
    price = models.DecimalField(
        max_digits=12, decimal_places=2, help_text=_("Quoted price, tax included")
    )
    servings = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal(1),
        help_text=_("How many guests one unit serves"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="menu_items",
    )
    product_units = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        default=Decimal(1),
        help_text=_("Product units consumed by one unit of this item"),
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["course", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "name"], name="unique_menu_item_per_restaurant"
            )
        ]

    def __str__(self):
        return self.name

    @property
    def unit_cost(self) -> Decimal | None:
        """Cost of one unit, or ``None`` when it is not known.

        A product carrying no cost is unknown, not free: counting it as zero
        would quietly inflate the margin of every quote that uses it.
        """
        if self.product_id is None:
            return None
        cost = self.product.cost_price
        if cost is None or cost <= ZERO:
            return None
        return cost * self.product_units

    @property
    def is_mapped(self) -> bool:
        return self.product_id is not None


class Quote(models.Model):
    restaurant = models.ForeignKey(
        "tenants.Restaurant", on_delete=models.CASCADE, related_name="quotes"
    )
    number = models.CharField(max_length=30)
    client_name = models.CharField(max_length=200, blank=True)
    concept = models.CharField(max_length=200, blank=True)
    event_date = models.DateField(null=True, blank=True)
    guests = models.PositiveIntegerField(default=1)
    pricing_mode = models.CharField(
        max_length=20, choices=PricingMode.choices, default=PricingMode.CONSUMPTION
    )
    price_per_guest = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    payment_terms = models.CharField(max_length=200, blank=True)
    tip_rate = models.DecimalField(max_digits=4, decimal_places=3, default=DEFAULT_TIP_RATE)
    charges_tip = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "number"], name="unique_quote_number_per_restaurant"
            )
        ]

    def __str__(self):
        return f"{self.number} - {self.client_name or _('No client')}"

    # -- what the client pays -------------------------------------------------

    @property
    def lines_total(self) -> Decimal:
        return sum((line.line_total for line in self.lines.all()), ZERO)

    @property
    def subtotal(self) -> Decimal:
        """What the quote charges before the tip, tax already inside."""
        if self.pricing_mode == PricingMode.PER_GUEST:
            return self.price_per_guest * self.guests
        return self.lines_total

    @property
    def taxable_base(self) -> Decimal:
        return self.subtotal / (Decimal(1) + TAX_RATE)

    @property
    def tax_included(self) -> Decimal:
        """The IPO already contained in ``subtotal``. Shown, never added again."""
        return self.subtotal - self.taxable_base

    @property
    def tip(self) -> Decimal:
        return self.taxable_base * self.tip_rate if self.charges_tip else ZERO

    @property
    def total(self) -> Decimal:
        return self.subtotal + self.tip

    # -- what it leaves -------------------------------------------------------

    @property
    def cost(self) -> Decimal:
        """Food cost of the event, from the mapped products."""
        return sum((line.line_cost for line in self.lines.all()), ZERO)

    @property
    def is_costed(self) -> bool:
        """False when any line is missing its product mapping."""
        return self.lines.exists() and all(line.unit_cost is not None for line in self.lines.all())

    @property
    def profit(self) -> Decimal:
        """Revenue net of tax and tip, minus cost. The tip is not the house's."""
        return self.taxable_base - self.cost

    @property
    def margin_pct(self) -> Decimal:
        base = self.taxable_base
        return (self.profit / base * 100) if base else ZERO

    @property
    def cost_per_guest(self) -> Decimal:
        return self.cost / self.guests if self.guests else ZERO

    @property
    def total_per_guest(self) -> Decimal:
        return self.total / self.guests if self.guests else ZERO


class QuoteLine(models.Model):
    """One line of a quote.

    Name, price and cost are copied in rather than read through the menu item:
    a quote sent to a client must not change when the catalog does.
    """

    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="lines")
    menu_item = models.ForeignKey(
        MenuItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="quote_lines"
    )
    course = models.CharField(max_length=20, choices=Course.choices, default=Course.OTHER)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal(1))
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.name} x{self.quantity}"

    @property
    def line_total(self) -> Decimal:
        return self.quantity * self.unit_price

    @property
    def line_cost(self) -> Decimal:
        return self.quantity * (self.unit_cost or ZERO)
