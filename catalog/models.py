from django.db import models
from django.utils.text import slugify


class Category(models.Model):
    restaurant = models.ForeignKey(
        "tenants.Restaurant", on_delete=models.CASCADE, related_name="categories"
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField()
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "name"], name="unique_category_name_per_restaurant"
            ),
            models.UniqueConstraint(
                fields=["restaurant", "slug"], name="unique_category_slug_per_restaurant"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(models.Model):
    restaurant = models.ForeignKey(
        "tenants.Restaurant", on_delete=models.CASCADE, related_name="products"
    )
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=50)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )
    cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "sku"], name="unique_sku_per_restaurant"
            )
        ]

    @property
    def recipe_cost(self):
        """Cost of one unit built up from its recipe, or ``None``.

        A product with no recipe is costed by the POS instead, so it answers
        ``None`` here. So does a recipe with an uncosted supply: a partial sum
        would read as a real cost and quietly overstate the margin, which is the
        rule the quotes already follow for an unmapped item.
        """
        lines = list(self.recipe.all())
        if not lines:
            return None
        costs = [line.line_cost for line in lines]
        if any(cost is None for cost in costs):
            return None
        return sum(costs)

    @property
    def uncosted_supplies(self):
        """The recipe lines holding the product's cost back, for the UI to name."""
        return [line for line in self.recipe.all() if line.line_cost is None]

    @property
    def margin_amount(self):
        return self.sale_price - self.cost_price

    @property
    def margin_pct(self):
        if self.sale_price == 0:
            return 0
        return (self.margin_amount / self.sale_price) * 100

    def __str__(self):
        return self.name


class ProductAlias(models.Model):
    """A POS identity (clave + raw name) resolved once to a canonical Product.

    The POS clave is not a reliable identity: codes get reassigned to new
    products and duplicates exist, so identity is resolved by NAME (see
    ``catalog.identity``). Every ``(pos_clave, raw_name)`` pair the importer has
    seen is recorded here pointing at its canonical product, so the resolution
    is made once and never re-guessed on later imports.
    """

    restaurant = models.ForeignKey(
        "tenants.Restaurant", on_delete=models.CASCADE, related_name="product_aliases"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="aliases"
    )
    pos_clave = models.CharField(max_length=50)
    raw_name = models.CharField(max_length=200)
    normalized_name = models.CharField(max_length=200, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "product aliases"
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "pos_clave", "raw_name"],
                name="unique_alias_identity_per_restaurant",
            )
        ]

    def __str__(self):
        return f"{self.pos_clave} / {self.raw_name} -> {self.product.name}"


class SupplyUnit(models.TextChoices):
    """How AutoFacturas measures one unit of consumption of an insumo."""

    UNIT = "unidad", "unidad"
    ML = "ml", "ml"
    G = "g", "g"


class Supply(models.Model):
    """An insumo as AutoFacturas costs it: one purchased input, priced per unit
    of consumption.

    AutoFacturas reads the supplier's invoices and reduces each one to what a
    single unit of consumption costs -- a millilitre of gin, a gram of lomo, one
    bottle of beer -- with the taxes the restaurant cannot discount already
    inside. ``clave`` is its stable key for the insumo and the only thing that
    identifies it across syncs; names get retyped, claves do not.

    Both the last cost and the 90-day weighted average are kept: the last one is
    current, the average is steady, and which one a restaurant wants to cost
    with is its own call.
    """

    restaurant = models.ForeignKey(
        "tenants.Restaurant", on_delete=models.CASCADE, related_name="supplies"
    )
    clave = models.CharField(max_length=60)
    name = models.CharField(max_length=200)
    unit = models.CharField(
        max_length=10, choices=SupplyUnit.choices, blank=True,
        help_text="Unit of consumption the cost is quoted per",
    )
    group = models.CharField(max_length=100, blank=True)
    #: Costs are per unit of consumption, so a millilitre of spirit is a figure
    #: with decimals that matter; AutoFacturas itself rounds to four.
    unit_cost = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True,
        help_text="Last cost per unit of consumption, taxes included",
    )
    unit_cost_untaxed = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True
    )
    average_cost = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True,
        help_text="Weighted average over the window AutoFacturas was asked for",
    )
    last_purchase_date = models.DateField(null=True, blank=True)
    last_purchase_supplier = models.CharField(max_length=200, blank=True)
    last_purchase_invoice = models.CharField(max_length=60, blank=True)
    last_purchase_description = models.CharField(max_length=300, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "supplies"
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "clave"], name="unique_supply_clave_per_restaurant"
            )
        ]

    def __str__(self):
        return f"{self.clave} {self.name}"

    @property
    def is_costed(self) -> bool:
        return self.unit_cost is not None

    def cost_for(self, quantity, prefer_average: bool = False):
        """What ``quantity`` units of consumption of this supply cost.

        ``None`` when the supply has no cost: a recipe that silently treated it
        as free would report a margin the kitchen does not have.
        """
        cost = self.average_cost if prefer_average else self.unit_cost
        if cost is None:
            cost = self.unit_cost if prefer_average else self.average_cost
        if cost is None:
            return None
        return cost * quantity


class RecipeLine(models.Model):
    """How much of one supply a single unit of a product consumes.

    One line covers the simple case -- a bottle of wine poured by the glass is
    750 ml of one insumo. Several lines make a recipe, which is the only way a
    cocktail can carry a cost: a negroni is gin, vermut, campari, hielo and
    orange, and no single insumo is "the" product.

    ``quantity`` is expressed in the supply's own unit of consumption, so it is
    the portion: 45 (ml of gin), 220 (g of lomo), 1 (bottle of beer).
    """

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="recipe"
    )
    supply = models.ForeignKey(
        Supply, on_delete=models.PROTECT, related_name="recipe_lines"
    )
    quantity = models.DecimalField(
        max_digits=12, decimal_places=4,
        help_text="Units of consumption of the supply per unit of the product",
    )
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["supply__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "supply"], name="unique_supply_per_product_recipe"
            )
        ]

    def __str__(self):
        return f"{self.product.name}: {self.quantity} {self.supply.unit} {self.supply.name}"

    @property
    def line_cost(self):
        """What this line contributes, or ``None`` when its supply has no cost."""
        return self.supply.cost_for(self.quantity)
