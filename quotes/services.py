"""Turning a budget into a menu, and a menu into a quote.

The composer reasons in cost per guest: an item's price divided by how many
guests one unit serves. That is the only way a station priced at 300.000 and a
dessert priced at 30.000 can be compared against the same per-guest budget.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal

from .models import Course, MenuItem, PricingMode, Quote, QuoteLine

ZERO = Decimal("0")

#: How a per-guest budget is split across the courses, by event type. Weights
#: sum to 1 with alcohol included; without it they are renormalised.
PROFILES: dict[str, list[dict]] = {
    "cocktail": [
        {"course": Course.STARTERS, "slots": 5, "weight": Decimal("0.58")},
        {"course": Course.DESSERTS, "slots": 1, "weight": Decimal("0.08")},
        {"course": Course.SOFT, "slots": 1, "weight": Decimal("0.10")},
        {"course": Course.ALCOHOL, "slots": 1, "weight": Decimal("0.24"), "alcohol": True},
    ],
    "seated": [
        {"course": Course.STARTERS, "slots": 2, "weight": Decimal("0.20")},
        {"course": Course.MAINS, "slots": 2, "weight": Decimal("0.38")},
        {"course": Course.SIDES, "slots": 2, "weight": Decimal("0.10")},
        {"course": Course.DESSERTS, "slots": 1, "weight": Decimal("0.09")},
        {"course": Course.SOFT, "slots": 1, "weight": Decimal("0.05")},
        {"course": Course.ALCOHOL, "slots": 1, "weight": Decimal("0.18"), "alcohol": True},
    ],
    "steak": [
        {"course": Course.STARTERS, "slots": 2, "weight": Decimal("0.17")},
        {"course": Course.MAINS, "slots": 2, "weight": Decimal("0.38")},
        {"course": Course.SIDES, "slots": 2, "weight": Decimal("0.11")},
        {"course": Course.DESSERTS, "slots": 1, "weight": Decimal("0.08")},
        {"course": Course.SOFT, "slots": 1, "weight": Decimal("0.05")},
        {"course": Course.ALCOHOL, "slots": 1, "weight": Decimal("0.21"), "alcohol": True},
    ],
}


@dataclass
class Pick:
    item: MenuItem
    quantity: int

    @property
    def total(self) -> Decimal:
        return self.item.price * self.quantity


@dataclass
class Composition:
    picks: list[Pick] = field(default_factory=list)
    guests: int = 1
    budget_per_guest: Decimal = ZERO

    @property
    def total(self) -> Decimal:
        return sum((p.total for p in self.picks), ZERO)

    @property
    def per_guest(self) -> Decimal:
        return self.total / self.guests if self.guests else ZERO

    @property
    def budget(self) -> Decimal:
        return self.budget_per_guest * self.guests

    @property
    def fits(self) -> bool:
        return self.total <= self.budget


def units_needed(item: MenuItem, guests: int) -> int:
    """Units to serve ``guests``, rounded up — you pay for the whole station."""
    servings = item.servings or Decimal("1")
    return max(1, math.ceil(Decimal(guests) / servings))


def cost_per_guest(item: MenuItem, guests: int) -> Decimal:
    """What the item really costs per guest once quantities are rounded up."""
    return units_needed(item, guests) * item.price / Decimal(guests)


def _choose(pool: list[MenuItem], purse: Decimal, slots: int, guests: int, offset: int) -> list[MenuItem]:
    """Pick up to ``slots`` distinct items without spending more than ``purse``.

    Each round aims at the average of what is left, so the budget spreads across
    the courses instead of being burnt on the first pick.
    """
    chosen: list[MenuItem] = []
    used: set[int] = set()
    left = purse

    for i in range(slots):
        target = left / (slots - i)
        free = [(it, cost_per_guest(it, guests)) for it in pool if it.pk not in used]
        if not free:
            break

        affordable = [x for x in free if x[1] <= left]
        if not affordable:
            # Stop rather than overshoot, unless the course is still empty.
            if chosen:
                break
            affordable = [min(free, key=lambda x: x[1])]

        affordable.sort(key=lambda x: abs(x[1] - target))
        near = affordable[: min(3, len(affordable))]
        item, spent = near[(offset + i) % len(near)]

        used.add(item.pk)
        chosen.append(item)
        left = max(ZERO, left - spent)

    return chosen


def compose(restaurant, budget_per_guest, guests, profile="seated", alcohol=True, offset=0) -> Composition:
    """Build a menu that fits ``budget_per_guest`` for ``guests`` people."""
    budget_per_guest = Decimal(budget_per_guest)
    guests = max(1, int(guests))

    blocks = [b for b in PROFILES.get(profile, PROFILES["seated"]) if alcohol or not b.get("alcohol")]
    weights = sum(b["weight"] for b in blocks) or Decimal("1")

    items = MenuItem.objects.filter(restaurant=restaurant, is_active=True, price__gt=0)
    by_course: dict[str, list[MenuItem]] = {}
    for item in items:
        by_course.setdefault(item.course, []).append(item)

    composition = Composition(guests=guests, budget_per_guest=budget_per_guest)
    carry = ZERO

    # Biggest courses first; whatever they leave over funds the next one.
    for block in sorted(blocks, key=lambda b: b["weight"], reverse=True):
        purse = budget_per_guest * (block["weight"] / weights) + carry
        pool = by_course.get(block["course"], [])
        if not pool:
            carry = purse
            continue

        spent = ZERO
        for item in _choose(pool, purse, block["slots"], guests, offset):
            spent += cost_per_guest(item, guests)
            composition.picks.append(Pick(item=item, quantity=units_needed(item, guests)))
        carry = max(ZERO, purse - spent)

    _trim(composition)

    order = list(Course.values)
    composition.picks.sort(key=lambda p: order.index(p.item.course))
    return composition


def _trim(composition: Composition) -> None:
    """Bring a composition back under budget after a course had to overshoot.

    A course with nothing in it takes its cheapest item even when the purse does
    not cover it, which can push the whole menu over. Swapping the priciest pick
    for a cheaper one in the same course recovers the difference without leaving
    a course empty.
    """
    if composition.fits or not composition.picks:
        return

    guests = composition.guests
    for _ in range(len(composition.picks)):
        if composition.fits:
            return

        worst = max(composition.picks, key=lambda p: cost_per_guest(p.item, guests))
        taken = {p.item.pk for p in composition.picks}
        cheaper = [
            it
            for it in MenuItem.objects.filter(
                restaurant=worst.item.restaurant_id,
                course=worst.item.course,
                is_active=True,
                price__gt=0,
            )
            if it.pk not in taken and cost_per_guest(it, guests) < cost_per_guest(worst.item, guests)
        ]
        if not cheaper:
            return

        best = max(cheaper, key=lambda it: cost_per_guest(it, guests))
        worst.item = best
        worst.quantity = units_needed(best, guests)


def minimum_per_guest(restaurant, guests, profile="seated", alcohol=True) -> Decimal:
    """The cheapest this kind of event can be — the floor to quote against."""
    blocks = [b for b in PROFILES.get(profile, PROFILES["seated"]) if alcohol or not b.get("alcohol")]
    items = MenuItem.objects.filter(restaurant=restaurant, is_active=True, price__gt=0)

    by_course: dict[str, list[MenuItem]] = {}
    for item in items:
        by_course.setdefault(item.course, []).append(item)

    total = ZERO
    for block in blocks:
        pool = by_course.get(block["course"], [])
        if pool:
            total += min(cost_per_guest(it, guests) for it in pool)
    return total


def apply_composition(quote: Quote, composition: Composition) -> None:
    """Replace a quote's lines with a composed menu, snapshotting price and cost."""
    quote.lines.all().delete()
    for position, pick in enumerate(composition.picks):
        QuoteLine.objects.create(
            quote=quote,
            menu_item=pick.item,
            course=pick.item.course,
            name=pick.item.name,
            description=pick.item.description,
            quantity=Decimal(pick.quantity),
            unit_price=pick.item.price,
            unit_cost=pick.item.unit_cost,
            position=position,
        )
    quote.guests = composition.guests
    quote.pricing_mode = PricingMode.PER_GUEST
    quote.price_per_guest = composition.budget_per_guest
    quote.charges_tip = False
    quote.save()
