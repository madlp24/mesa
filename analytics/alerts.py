"""Products whose margin deserves the owner's attention (US40).

Mesa has the price and the cost of everything sold but never said anything
about them. Running the numbers by hand over 2026 found a drink sold at -39.7%
and twenty-two products carrying no cost at all -- counted as pure margin and
quietly inflating every figure.

Margin is taken from what was actually charged (the sale items), not the
product's list price, so a dish sold below its menu price shows the truth.
Each list is ordered by **revenue**: a 2% margin on a product nobody buys
matters less than a thin one that moves.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum

from sales.models import SaleItem

# The median product margin in the real catalog is 65% and the 10th percentile
# 49.7%, so 50% flags the worst tenth rather than half the menu.
DEFAULT_THRESHOLD = Decimal("50")

_REVENUE = ExpressionWrapper(
    F("unit_price") * F("quantity"),
    output_field=DecimalField(max_digits=16, decimal_places=2),
)
_COST = ExpressionWrapper(
    F("unit_cost") * F("quantity"),
    output_field=DecimalField(max_digits=16, decimal_places=2),
)


@dataclass(frozen=True)
class ProductMargin:
    """One product's takings over the period, with the margin they imply."""

    product_id: int
    name: str
    category: str
    units: int
    revenue: Decimal
    cost: Decimal
    margin_pct: Decimal | None  # None when no cost is loaded


@dataclass(frozen=True)
class MarginAlerts:
    """What the owner should look at, worst money first."""

    at_a_loss: list[ProductMargin]
    thin: list[ProductMargin]
    without_cost: list[ProductMargin]
    threshold: Decimal

    @property
    def total(self) -> int:
        return len(self.at_a_loss) + len(self.thin) + len(self.without_cost)


def margin_alerts(
    restaurant,
    *,
    threshold: Decimal = DEFAULT_THRESHOLD,
    start: datetime.date | None = None,
    end: datetime.date | None = None,
) -> MarginAlerts:
    """Group the restaurant's products by how much their margin worries us."""
    items = SaleItem.objects.filter(sale__restaurant=restaurant)
    if start:
        items = items.filter(sale__occurred_at__date__gte=start)
    if end:
        items = items.filter(sale__occurred_at__date__lte=end)

    rows = (
        items.values("product_id", "product__name", "product__category__name")
        .annotate(units=Sum("quantity"), revenue=Sum(_REVENUE), cost=Sum(_COST))
        .order_by()
    )

    at_a_loss: list[ProductMargin] = []
    thin: list[ProductMargin] = []
    without_cost: list[ProductMargin] = []

    for row in rows:
        revenue = row["revenue"] or Decimal("0")
        cost = row["cost"] or Decimal("0")
        if revenue <= 0:
            continue  # a giveaway has no margin to judge

        margin = None if cost <= 0 else (revenue - cost) / revenue * 100
        entry = ProductMargin(
            product_id=row["product_id"],
            name=row["product__name"],
            category=row["product__category__name"] or "",
            units=row["units"] or 0,
            revenue=revenue,
            cost=cost,
            margin_pct=None if margin is None else round(margin, 1),
        )
        if margin is None:
            without_cost.append(entry)
        elif margin < 0:
            at_a_loss.append(entry)
        elif margin < threshold:
            thin.append(entry)

    for group in (at_a_loss, thin, without_cost):
        group.sort(key=lambda e: e.revenue, reverse=True)

    return MarginAlerts(
        at_a_loss=at_a_loss,
        thin=thin,
        without_cost=without_cost,
        threshold=threshold,
    )
