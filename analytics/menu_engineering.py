"""Menu engineering: what to keep, reprice, promote or drop (US50).

The Kasavana and Smith method, done within each menu group, because a bottle
of wine and a lemonade do not compete for the same order:

* a dish is **popular** when its share of the group's portions reaches 70% of
  an even share (1 / dishes in the group);
* it is **profitable** when what one portion leaves (price minus cost) reaches
  the group's average, weighted by portions.

That gives stars (both), plowhorses (popular, thin), puzzles (profitable,
little sold) and dogs (neither). Prices and costs are what was actually
charged and costed in the period, read off the sale lines. A dish with no cost
cannot be placed: it is listed apart rather than counted as pure margin.
"""
from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum

from catalog.portions import portions, sold_by_gram
from sales.models import SaleItem

POPULARITY_FACTOR = Decimal("0.7")

STAR = "star"
PLOWHORSE = "plowhorse"
PUZZLE = "puzzle"
DOG = "dog"
CLASSES = (STAR, PLOWHORSE, PUZZLE, DOG)

_MONEY = DecimalField(max_digits=16, decimal_places=2)
_REVENUE = ExpressionWrapper(F("unit_price") * F("quantity"), output_field=_MONEY)
_COST = ExpressionWrapper(F("unit_cost") * F("quantity"), output_field=_MONEY)


@dataclass
class Dish:
    product_id: int
    name: str
    portions: Decimal
    revenue: Decimal
    cost: Decimal
    by_gram: bool
    mix_pct: Decimal = Decimal("0")
    kind: str = ""

    @property
    def contribution(self) -> Decimal:
        """What one portion leaves after its cost."""
        return (self.revenue - self.cost) / self.portions if self.portions else Decimal("0")

    @property
    def total_contribution(self) -> Decimal:
        return self.revenue - self.cost


@dataclass
class Group:
    name: str
    dishes: list[Dish] = field(default_factory=list)
    uncosted: list[Dish] = field(default_factory=list)
    popularity_threshold: Decimal = Decimal("0")  # % of the group's portions
    contribution_threshold: Decimal = Decimal("0")  # per portion

    @property
    def revenue(self) -> Decimal:
        return sum((d.revenue for d in self.dishes + self.uncosted), Decimal("0"))

    def of_kind(self, kind: str) -> list[Dish]:
        return sorted(
            (d for d in self.dishes if d.kind == kind),
            key=lambda d: d.total_contribution,
            reverse=True,
        )

    @property
    def stars(self) -> list[Dish]:
        return self.of_kind(STAR)

    @property
    def plowhorses(self) -> list[Dish]:
        return self.of_kind(PLOWHORSE)

    @property
    def puzzles(self) -> list[Dish]:
        return self.of_kind(PUZZLE)

    @property
    def dogs(self) -> list[Dish]:
        return self.of_kind(DOG)


def classify(group: Group) -> Group:
    """Set each costed dish's share and kind, and the group's two thresholds."""
    dishes = group.dishes
    if not dishes:
        return group
    total_portions = sum((d.portions for d in dishes), Decimal("0"))
    total_contribution = sum((d.total_contribution for d in dishes), Decimal("0"))
    group.popularity_threshold = Decimal(100) / len(dishes) * POPULARITY_FACTOR
    group.contribution_threshold = (
        total_contribution / total_portions if total_portions else Decimal("0")
    )
    for dish in dishes:
        dish.mix_pct = dish.portions / total_portions * 100 if total_portions else Decimal("0")
        popular = dish.mix_pct >= group.popularity_threshold
        profitable = dish.contribution >= group.contribution_threshold
        if popular and profitable:
            dish.kind = STAR
        elif popular:
            dish.kind = PLOWHORSE
        elif profitable:
            dish.kind = PUZZLE
        else:
            dish.kind = DOG
    return group


def menu_engineering(
    restaurant,
    start: datetime.date | None = None,
    end: datetime.date | None = None,
) -> list[Group]:
    """Every menu group that sold in the period, biggest takings first."""
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

    groups: dict[str, Group] = defaultdict(lambda: Group(name=""))
    for row in rows:
        revenue = row["revenue"] or Decimal("0")
        if revenue <= 0 or not row["units"]:
            continue  # a giveaway has nothing to engineer
        name = row["product__name"]
        group_name = row["product__category__name"] or ""
        group = groups[group_name]
        group.name = group_name
        dish = Dish(
            product_id=row["product_id"],
            name=name,
            portions=portions(row["units"], name),
            revenue=revenue,
            cost=row["cost"] or Decimal("0"),
            by_gram=sold_by_gram(name),
        )
        (group.dishes if dish.cost > 0 else group.uncosted).append(dish)

    return sorted(
        (classify(group) for group in groups.values()),
        key=lambda g: g.revenue,
        reverse=True,
    )
