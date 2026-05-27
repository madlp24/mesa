from django.db import models


class Sale(models.Model):
    external_id = models.CharField(max_length=100, unique=True)
    occurred_at = models.DateTimeField(db_index=True)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=50, blank=True)
    server_name = models.CharField(max_length=100, blank=True)
    table_number = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [models.Index(fields=["occurred_at"])]

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
