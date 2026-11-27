"""Menu engineering: what to keep, reprice, promote or drop (US50, US53).

The Kasavana and Smith method, done within each menu family
(:mod:`catalog.families`), because a bottle of wine and a lemonade do not
compete for the same order:

* a dish is **popular** when its share of the family's portions reaches 70% of
  an even share (1 / dishes in the family);
* it is **profitable** when what one portion leaves (price minus cost) reaches
  the family's average, weighted by portions.

That gives stars (both), plowhorses (popular, thin), puzzles (profitable,
little sold) and dogs (neither). Prices and costs are what was actually
charged and costed in the period, read off the sale lines. A dish with no cost
cannot be placed: it is listed apart rather than counted as pure margin.

On top of the picture come the decisions (US53): how each dish moved against
the previous period, and for every plowhorse the menu price that would make a
portion leave the family average -- held to the restaurant's cap per change
and rounded to its step, because a suggestion nobody would print is noise.
Suggested prices are *menu* prices, consumption tax included; the POS stores
them without it.
"""
from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils.translation import gettext_lazy as _

from catalog.families import family_of, is_hidden
from catalog.models import Category
from catalog.portions import GRAMS_PER_PORTION, portions, sold_by_gram
from sales.models import SaleItem

POPULARITY_FACTOR = Decimal("0.7")
#: Impuesto al consumo: on the menu, not in the POS price.
TAX_RATE = Decimal("0.08")
#: A dog leaving less than this share of its family's margin barely counts.
WEAK_SHARE = Decimal("0.015")
#: Gram-sold cuts are priced on the menu per this many grams.
MENU_GRAMS = Decimal(100)

STAR = "star"
PLOWHORSE = "plowhorse"
PUZZLE = "puzzle"
DOG = "dog"
CLASSES = (STAR, PLOWHORSE, PUZZLE, DOG)
KIND_LABELS = {
    STAR: _("Star"),
    PLOWHORSE: _("Plowhorse"),
    PUZZLE: _("Puzzle"),
    DOG: _("Dog"),
}

_MONEY = DecimalField(max_digits=16, decimal_places=2)
_REVENUE = ExpressionWrapper(F("unit_price") * F("quantity"), output_field=_MONEY)
_COST = ExpressionWrapper(F("unit_cost") * F("quantity"), output_field=_MONEY)


def _pct_change(now, before) -> Decimal | None:
    if not before:
        return None
    return (Decimal(now) - Decimal(before)) / Decimal(before) * 100


@dataclass
class Dish:
    product_id: int
    name: str
    portions: Decimal
    revenue: Decimal
    cost: Decimal
    by_gram: bool
    list_price: Decimal = Decimal("0")  # the product's current POS price
    mix_pct: Decimal = Decimal("0")
    kind: str = ""
    previous: Dish | None = None
    weight: int = 1  # relative size of its tile on the board

    @property
    def contribution(self) -> Decimal:
        """What one portion leaves after its cost."""
        return (self.revenue - self.cost) / self.portions if self.portions else Decimal("0")

    @property
    def total_contribution(self) -> Decimal:
        return self.revenue - self.cost

    @property
    def unit_cost(self) -> Decimal:
        return self.cost / self.portions if self.portions else Decimal("0")

    @property
    def kind_label(self):
        return KIND_LABELS.get(self.kind, "")

    # -- movement against the previous period -----------------------------

    @property
    def cost_change(self) -> Decimal | None:
        """Change in the cost of a portion, as a percentage."""
        return _pct_change(self.unit_cost, self.previous.unit_cost) if self.previous else None

    @property
    def portions_change(self) -> Decimal | None:
        return _pct_change(self.portions, self.previous.portions) if self.previous else None

    @property
    def cost_alarm(self) -> bool:
        """A cost rise worth colouring: 8% or more on a portion."""
        change = self.cost_change
        return change is not None and change >= 8

    @property
    def portions_shift(self) -> Decimal | None:
        """The change in portions when it is big enough to mention (10%)."""
        change = self.portions_change
        return change if change is not None and abs(change) >= 10 else None

    @property
    def moved_from(self):
        """The quadrant it was in before, when it changed; ``None`` otherwise."""
        if self.previous and self.previous.kind and self.previous.kind != self.kind:
            return KIND_LABELS[self.previous.kind]
        return None

    # -- the menu price ----------------------------------------------------

    @property
    def menu_factor(self) -> Decimal:
        """Pesos one portion gains per peso added to the menu price."""
        per_unit = GRAMS_PER_PORTION / MENU_GRAMS if self.by_gram else Decimal(1)
        return per_unit / (1 + TAX_RATE)

    @property
    def menu_price(self) -> Decimal:
        """Today's price as the menu prints it: tax included, per 100 g for
        gram-sold cuts."""
        unit = MENU_GRAMS if self.by_gram else Decimal(1)
        raw = self.list_price * unit * (1 + TAX_RATE)
        return (raw / 100).quantize(Decimal(1)) * 100


@dataclass
class Group:
    name: str
    dishes: list[Dish] = field(default_factory=list)
    uncosted: list[Dish] = field(default_factory=list)
    popularity_threshold: Decimal = Decimal("0")  # % of the family's portions
    contribution_threshold: Decimal = Decimal("0")  # per portion

    @property
    def revenue(self) -> Decimal:
        return sum((d.revenue for d in self.dishes + self.uncosted), Decimal("0"))

    @property
    def total_portions(self) -> Decimal:
        return sum((d.portions for d in self.dishes), Decimal("0"))

    def of_kind(self, kind: str) -> list[Dish]:
        return sorted(
            (d for d in self.dishes if d.kind == kind),
            key=lambda d: d.revenue,
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

    @property
    def cost_drift(self) -> Decimal:
        """What this period's portions cost beyond the previous period's unit
        costs: the money the cost rises took, at today's sales."""
        return sum(
            ((d.unit_cost - d.previous.unit_cost) * d.portions
             for d in self.dishes if d.previous and d.previous.portions),
            Decimal("0"),
        )


def classify(group: Group) -> Group:
    """Set each costed dish's share and kind, and the family's two thresholds."""
    dishes = group.dishes
    if not dishes:
        return group
    total_portions = group.total_portions
    total_contribution = sum((d.total_contribution for d in dishes), Decimal("0"))
    group.popularity_threshold = Decimal(100) / len(dishes) * POPULARITY_FACTOR
    group.contribution_threshold = (
        total_contribution / total_portions if total_portions else Decimal("0")
    )
    top = max(d.revenue for d in dishes)
    for dish in dishes:
        dish.mix_pct = dish.portions / total_portions * 100 if total_portions else Decimal("0")
        dish.weight = max(1, round(dish.revenue / top * 12)) if top else 1
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
    """Every menu family that sold in the period, biggest takings first."""
    families = {
        c.pk: (family_of(c), is_hidden(c))
        for c in Category.objects.filter(restaurant=restaurant)
    }
    items = SaleItem.objects.filter(sale__restaurant=restaurant)
    if start:
        items = items.filter(sale__occurred_at__date__gte=start)
    if end:
        items = items.filter(sale__occurred_at__date__lte=end)
    rows = (
        items.values(
            "product_id", "product__name", "product__category_id", "product__sale_price"
        )
        .annotate(units=Sum("quantity"), revenue=Sum(_REVENUE), cost=Sum(_COST))
        .order_by()
    )

    groups: dict[str, Group] = {}
    for row in rows:
        revenue = row["revenue"] or Decimal("0")
        if revenue <= 0 or not row["units"]:
            continue  # a giveaway has nothing to engineer
        family, hidden = families.get(row["product__category_id"], ("", False))
        if hidden:
            continue
        name = row["product__name"]
        group = groups.setdefault(family, Group(name=family))
        dish = Dish(
            product_id=row["product_id"],
            name=name,
            portions=portions(row["units"], name),
            revenue=revenue,
            cost=row["cost"] or Decimal("0"),
            by_gram=sold_by_gram(name),
            list_price=row["product__sale_price"] or Decimal("0"),
        )
        (group.dishes if dish.cost > 0 else group.uncosted).append(dish)

    return sorted(
        (classify(group) for group in groups.values()),
        key=lambda g: g.revenue,
        reverse=True,
    )


def with_movement(current: Group, previous: Group | None) -> Group:
    """Attach to each dish what it was in the previous period."""
    before = {d.product_id: d for d in previous.dishes} if previous else {}
    for dish in current.dishes:
        dish.previous = before.get(dish.product_id)
    return current


# -- decisions ---------------------------------------------------------------


@dataclass(frozen=True)
class PriceMove:
    """A suggested menu price for a plowhorse."""

    dish: Dish
    current: Decimal  # menu price today
    proposed: Decimal  # what to print, within the cap
    needed: Decimal  # what it would take to leave the family average
    extra_per_month: Decimal

    @property
    def rise_pct(self) -> Decimal:
        return (self.proposed - self.current) / self.current * 100

    @property
    def reaches_average(self) -> bool:
        return self.proposed >= self.needed


def _ceil_to(value: Decimal, step: int) -> Decimal:
    return Decimal(math.ceil(value / step) * step)


def _floor_to(value: Decimal, step: int) -> Decimal:
    return Decimal(math.floor(value / step) * step)


def price_moves(group: Group, *, days: int, cap_pct, step: int) -> list[PriceMove]:
    """For each plowhorse, the price rise worth making, biggest gain first.

    The estimate assumes the dish keeps selling the same: that is why the rise
    is capped, and why the page says so.
    """
    moves = []
    months = Decimal(days) / Decimal(30)
    for dish in group.plowhorses:
        current = dish.menu_price
        if current <= 0 or not months:
            continue
        gap = group.contribution_threshold - dish.contribution
        needed = _ceil_to(current + gap / dish.menu_factor, step)
        capped = _floor_to(current * (1 + Decimal(cap_pct) / 100), step)
        proposed = min(needed, capped)
        if proposed <= current:
            continue
        moves.append(
            PriceMove(
                dish=dish,
                current=current,
                proposed=proposed,
                needed=needed,
                extra_per_month=(proposed - current) * dish.menu_factor * dish.portions / months,
            )
        )
    return sorted(moves, key=lambda m: m.extra_per_month, reverse=True)


def weakest_dogs(group: Group, *, days: int, limit: int = 3) -> list[tuple[Dish, Decimal]]:
    """The dogs that barely count, with what each leaves per month.

    Only dogs leaving under 1.5% of what the family leaves: a dog that still
    brings in millions a month is below average, not a candidate to drop.
    """
    months = Decimal(days) / Decimal(30)
    total = sum((d.total_contribution for d in group.dishes), Decimal("0"))
    if not months or total <= 0:
        return []
    minor = [d for d in group.dogs if d.total_contribution / total < WEAK_SHARE]
    minor.sort(key=lambda d: d.total_contribution)
    return [(dish, dish.total_contribution / months) for dish in minor[:limit]]
