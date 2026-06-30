from django.db import models


class ImportBatch(models.Model):
    """One report import, kept so the owner can review history and undo it."""

    SOURCE_CHOICES = [("web", "Web upload"), ("cli", "Command line")]

    restaurant = models.ForeignKey(
        "tenants.Restaurant", on_delete=models.CASCADE, related_name="import_batches"
    )
    filename = models.CharField(max_length=255)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="web")
    created_at = models.DateTimeField(auto_now_add=True)
    sales_created = models.PositiveIntegerField(default=0)
    items_created = models.PositiveIntegerField(default=0)
    skipped_duplicate = models.PositiveIntegerField(default=0)
    skipped_rows = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.filename} ({self.created_at:%Y-%m-%d %H:%M})"


class Sale(models.Model):
    restaurant = models.ForeignKey(
        "tenants.Restaurant", on_delete=models.CASCADE, related_name="sales"
    )
    import_batch = models.ForeignKey(
        ImportBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales",
    )
    external_id = models.CharField(max_length=100)
    occurred_at = models.DateTimeField(db_index=True)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=50, blank=True)
    server_name = models.CharField(max_length=100, blank=True)
    table_number = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [models.Index(fields=["occurred_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "external_id"],
                name="unique_external_id_per_restaurant",
            )
        ]

    def __str__(self):
        return f"Sale {self.external_id} @ {self.occurred_at:%Y-%m-%d %H:%M}"


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="sale_items"
    )
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def line_revenue(self):
        return self.unit_price * self.quantity

    @property
    def line_cost(self):
        return self.unit_cost * self.quantity

    @property
    def line_margin(self):
        return self.line_revenue - self.line_cost

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"
