"""The cuts in kilos: what was sold, and how it moves (US57).

Money hides volume: a month can bill more because prices rose while fewer
kilos left the kitchen. This turns the cuts and premium cuts into kilos -- the
unit the meat is bought, counted and ordered in -- per month or week, per cut,
with price and POS cost per kilo.

Kilos are kilos *served*, as the POS sold them. What was bought and what was
lost in trimming come later, from AutoFacturas and the monthly count.
A cut sold by the portion with no known weight is listed apart and left out
of the kilos: a guessed weight would look like data.
"""
from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.utils import timezone

from catalog.families import is_meat
from catalog.models import Category, Product
from catalog.portions import grams_per_unit
from sales.models import SaleItem

GRAINS = ("month", "week")
_TOP = 6
_KILO = Decimal(1000)


def _bucket(day: datetime.date, grain: str) -> datetime.date:
    if grain == "week":
        return day - datetime.timedelta(days=day.weekday())
    return day.replace(day=1)


@dataclass
class Cut:
    product_id: int
    name: str
    grams_per_unit: Decimal | None
    source: str
    units: int = 0
    revenue: Decimal = Decimal("0")
    cost: Decimal = Decimal("0")
    before_units: int = 0
    by_bucket: dict = field(default_factory=lambda: defaultdict(int))  # units

    def _kilos(self, units) -> Decimal | None:
        if self.grams_per_unit is None:
            return None
        return Decimal(units) * self.grams_per_unit / _KILO

    @property
    def kilos(self) -> Decimal | None:
        return self._kilos(self.units)

    @property
    def before_kilos(self) -> Decimal | None:
        return self._kilos(self.before_units)

    @property
    def change(self) -> Decimal | None:
        if not self.before_kilos or self.kilos is None:
            return None
        return (self.kilos - self.before_kilos) / self.before_kilos * 100

    @property
    def price_per_kilo(self) -> Decimal | None:
        return self.revenue / self.kilos if self.kilos else None

    @property
    def cost_per_kilo(self) -> Decimal | None:
        return self.cost / self.kilos if self.kilos and self.cost > 0 else None

    @property
    def by_gram(self) -> bool:
        return self.grams_per_unit == 1


@dataclass
class MeatReport:
    start: datetime.date
    end: datetime.date
    grain: str
    buckets: list[datetime.date]
    cuts: list[Cut]  # weighed, most kilos first
    unweighed: list[Cut]  # sold by the portion, weight unknown

    @property
    def kilos(self) -> Decimal:
        return sum((c.kilos for c in self.cuts), Decimal("0"))

    @property
    def before_kilos(self) -> Decimal:
        return sum((c.before_kilos or Decimal("0") for c in self.cuts), Decimal("0"))

    @property
    def change(self) -> Decimal | None:
        if not self.before_kilos:
            return None
        return (self.kilos - self.before_kilos) / self.before_kilos * 100

    @property
    def revenue(self) -> Decimal:
        return sum((c.revenue for c in self.cuts), Decimal("0"))

    @property
    def price_per_kilo(self) -> Decimal | None:
        return self.revenue / self.kilos if self.kilos else None

    @property
    def cost_per_kilo(self) -> Decimal | None:
        costed = [c for c in self.cuts if c.cost > 0]
        kilos = sum((c.kilos for c in costed), Decimal("0"))
        return sum((c.cost for c in costed), Decimal("0")) / kilos if kilos else None

    def series(self) -> dict:
        """Kilos per bucket for the biggest cuts, the rest as one more series."""
        top, rest = self.cuts[:_TOP], self.cuts[_TOP:]
        rows = [
            {"name": c.name, "data": [float(c._kilos(c.by_bucket.get(b, 0))) for b in self.buckets]}
            for c in top
        ]
        if rest:
            rows.append({
                "name": "",  # the template names it
                "data": [
                    float(sum((c._kilos(c.by_bucket.get(b, 0)) for c in rest), Decimal("0")))
                    for b in self.buckets
                ],
            })
        return {"labels": [b.isoformat() for b in self.buckets], "series": rows}


def meat_report(
    restaurant,
    start: datetime.date,
    end: datetime.date,
    *,
    previous: tuple[datetime.date, datetime.date],
    grain: str = "month",
) -> MeatReport:
    grain = grain if grain in GRAINS else "month"
    meat_ids = [c.pk for c in Category.objects.filter(restaurant=restaurant) if is_meat(c)]
    products = {
        p.pk: p for p in Product.objects.filter(restaurant=restaurant, category_id__in=meat_ids)
    }
    cuts: dict[int, Cut] = {}

    def cut_for(product_id: int) -> Cut:
        if product_id not in cuts:
            product = products[product_id]
            grams, source = grams_per_unit(product)
            cuts[product_id] = Cut(product_id, product.name, grams, source)
        return cuts[product_id]

    since = min(start, previous[0])
    rows = SaleItem.objects.filter(
        sale__restaurant=restaurant,
        product_id__in=list(products),
        sale__occurred_at__date__gte=since,
        sale__occurred_at__date__lte=end,
        quantity__gt=0,
    ).values_list("product_id", "sale__occurred_at", "quantity", "unit_price", "unit_cost")
    for product_id, occurred_at, quantity, price, cost in rows.iterator():
        day = timezone.localtime(occurred_at).date()
        cut = cut_for(product_id)
        if start <= day <= end:
            cut.units += quantity
            cut.revenue += (price or 0) * quantity
            cut.cost += (cost or 0) * quantity
            cut.by_bucket[_bucket(day, grain)] += quantity
        elif previous[0] <= day <= previous[1]:
            cut.before_units += quantity

    buckets, day = [], _bucket(start, grain)
    while day <= end:
        buckets.append(day)
        day = (
            day + datetime.timedelta(days=7) if grain == "week"
            else (day.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        )

    sold = [c for c in cuts.values() if c.units]
    weighed = sorted((c for c in sold if c.grams_per_unit), key=lambda c: c.kilos, reverse=True)
    unweighed = sorted((c for c in sold if not c.grams_per_unit), key=lambda c: c.revenue, reverse=True)
    return MeatReport(start, end, grain, buckets, weighed, unweighed)
