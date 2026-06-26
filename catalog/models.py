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
