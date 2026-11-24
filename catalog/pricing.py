"""Keep each product's cost and price on what the POS reports today (US47).

``Product.cost_price`` and ``sale_price`` used to be written once, when the
importer first met a product, and never again -- so the margin page judged a
steak on what it cost the month it first appeared. They now follow the
product's **newest sale day**:

* newest by the date of the sale, not by the order files were imported: the
  owner loads report folders out of order, and importing February after
  November must not put February's cost back;
* averaged over that day weighted by quantity, because fused aliases can sell
  the same product at two prices on one day;
* a zero never counts. A courtesy rings up at price 0 and an uncosted line at
  cost 0; either would read as a real figure and wipe out the one before it.

A complete recipe still beats the POS cost, but through
:attr:`Product.effective_cost` -- ``cost_price`` itself belongs to the POS.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Product

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class PriceChange:
    """One product whose figures moved, before and after."""

    name: str
    old_cost: Decimal
    new_cost: Decimal
    old_price: Decimal
    new_price: Decimal

    @property
    def cost_moved(self) -> bool:
        return self.old_cost != self.new_cost

    @property
    def price_moved(self) -> bool:
        return self.old_price != self.new_price


def _newest_day_average(rows: list[tuple]) -> Decimal | None:
    """Quantity-weighted average of the newest day with a positive figure.

    ``rows`` are ``(day, quantity, value)`` for one product, newest first.
    """
    day = None
    amount = Decimal("0")
    units = 0
    for row_day, quantity, value in rows:
        if not value or value <= 0 or not quantity or quantity <= 0:
            continue
        if day is None:
            day = row_day
        elif row_day != day:
            break
        amount += value * quantity
        units += quantity
    if not units:
        return None
    return (amount / units).quantize(_CENT)


@transaction.atomic
def refresh_product_prices(
    restaurant,
    product_ids: Iterable[int] | None = None,
    *,
    dry_run: bool = False,
) -> list[PriceChange]:
    """Point products at the cost and price of their newest sale day.

    ``product_ids`` limits the work to the products an operation touched; left
    out, the whole catalog is refreshed. A product with no usable sale keeps
    what it has. Returns what moved (or would move, with ``dry_run``).
    """
    from sales.models import SaleItem  # sales depends on catalog, not the reverse

    products = Product.objects.filter(restaurant=restaurant)
    if product_ids is not None:
        product_ids = set(product_ids)
        if not product_ids:
            return []
        products = products.filter(pk__in=product_ids)

    items = (
        SaleItem.objects.filter(sale__restaurant=restaurant, product__in=products)
        .order_by("product_id", "-sale__occurred_at", "-pk")
        .values_list(
            "product_id", "sale__occurred_at", "quantity", "unit_cost", "unit_price"
        )
    )
    costs: dict[int, list[tuple]] = {}
    prices: dict[int, list[tuple]] = {}
    for product_id, occurred_at, quantity, unit_cost, unit_price in items.iterator():
        day = timezone.localtime(occurred_at).date()
        costs.setdefault(product_id, []).append((day, quantity, unit_cost))
        prices.setdefault(product_id, []).append((day, quantity, unit_price))

    changes: list[PriceChange] = []
    for product in products.order_by("name"):
        new_cost = _newest_day_average(costs.get(product.pk, []))
        new_price = _newest_day_average(prices.get(product.pk, []))
        new_cost = product.cost_price if new_cost is None else new_cost
        new_price = product.sale_price if new_price is None else new_price
        if new_cost == product.cost_price and new_price == product.sale_price:
            continue
        changes.append(
            PriceChange(
                name=product.name,
                old_cost=product.cost_price,
                new_cost=new_cost,
                old_price=product.sale_price,
                new_price=new_price,
            )
        )
        if not dry_run:
            product.cost_price = new_cost
            product.sale_price = new_price
            product.save(update_fields=["cost_price", "sale_price"])
    return changes
