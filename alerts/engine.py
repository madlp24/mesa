"""The profitability report: what lost money, and what jumped (US54).

Two kinds of warning, read off the same sales:

* **Lost profitability** -- a product whose cost per portion rose, whose price
  fell, or whose margin shrank between the period being watched and the one
  it is compared with. Slow drifts are what eat a margin: a cut 6% dearer
  every month never looks like news on any single day.
* **Abrupt changes** -- one day where a product's POS cost or price jumps
  against its recent level, and one supplier purchase that costs much more or
  less than the previous purchase of the same supply. These are news.

The period watched is the last 7 or 30 days up to the newest report (not up to
today: reports arrive in batches), against the period before or the same one a
year earlier. Each warning says what it costs a month, so the list reads
biggest money first, and, when the product has a recipe, which supply moved.
"""
from __future__ import annotations

import datetime
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone

from analytics.periods import latest_sale_day
from catalog.models import RecipeLine, SupplyPrice
from catalog.portions import portions
from sales.models import SaleItem

from .models import AlertSettings, Baseline, Cadence

_MONEY = DecimalField(max_digits=16, decimal_places=2)
_REVENUE = ExpressionWrapper(F("unit_price") * F("quantity"), output_field=_MONEY)
_COST = ExpressionWrapper(F("unit_cost") * F("quantity"), output_field=_MONEY)

#: Days of history a day's price is judged against, and the fewest it needs.
_REFERENCE_DAYS = 10
_MIN_REFERENCE = 3
_LOOKBACK = datetime.timedelta(days=60)

COST_RISE = "cost_rise"
PRICE_DROP = "price_drop"
MARGIN_DROP = "margin_drop"


@dataclass(frozen=True)
class Span:
    start: datetime.date
    end: datetime.date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def spans(settings: AlertSettings, newest: datetime.date) -> tuple[Span, Span]:
    """The period watched and the one it is compared with."""
    length = 7 if settings.cadence == Cadence.WEEK else 30
    current = Span(newest - datetime.timedelta(days=length - 1), newest)
    if settings.baseline == Baseline.LAST_YEAR:
        # 364 days keeps the weekdays aligned: Saturdays against Saturdays.
        shift = datetime.timedelta(days=364)
        return current, Span(current.start - shift, current.end - shift)
    before_length = 28 if settings.cadence == Cadence.WEEK else 30
    end = current.start - datetime.timedelta(days=1)
    return current, Span(end - datetime.timedelta(days=before_length - 1), end)


def _pct(now, before) -> Decimal | None:
    if not before:
        return None
    return (Decimal(now) - Decimal(before)) / Decimal(before) * 100


@dataclass
class Totals:
    name: str
    units: int = 0
    revenue: Decimal = Decimal("0")
    cost: Decimal = Decimal("0")

    @property
    def portions(self) -> Decimal:
        return portions(self.units, self.name)

    @property
    def unit_cost(self) -> Decimal:
        return self.cost / self.portions if self.portions else Decimal("0")

    @property
    def unit_price(self) -> Decimal:
        return self.revenue / self.portions if self.portions else Decimal("0")

    @property
    def margin_pct(self) -> Decimal | None:
        if self.revenue <= 0 or self.cost <= 0:
            return None
        return (self.revenue - self.cost) / self.revenue * 100


def _totals(restaurant, span: Span) -> dict[int, Totals]:
    rows = (
        SaleItem.objects.filter(
            sale__restaurant=restaurant,
            sale__occurred_at__date__gte=span.start,
            sale__occurred_at__date__lte=span.end,
            quantity__gt=0,
        )
        .values("product_id", "product__name")
        .annotate(units=Sum("quantity"), revenue=Sum(_REVENUE), cost=Sum(_COST))
        .order_by()
    )
    return {
        r["product_id"]: Totals(
            name=r["product__name"],
            units=r["units"] or 0,
            revenue=r["revenue"] or Decimal("0"),
            cost=r["cost"] or Decimal("0"),
        )
        for r in rows
    }


@dataclass(frozen=True)
class SupplyMove:
    """A supply in a product's recipe whose purchase price moved."""

    name: str
    before: Decimal
    after: Decimal
    supplier: str
    invoice: str
    date: datetime.date | None

    @property
    def change(self) -> Decimal | None:
        return _pct(self.after, self.before)


@dataclass
class ProductAlert:
    product_id: int
    name: str
    now: Totals
    before: Totals
    reasons: list[str]
    monthly_loss: Decimal
    causes: list[SupplyMove] = field(default_factory=list)

    @property
    def cost_change(self) -> Decimal | None:
        return _pct(self.now.unit_cost, self.before.unit_cost)

    @property
    def price_change(self) -> Decimal | None:
        return _pct(self.now.unit_price, self.before.unit_price)

    @property
    def margin_change(self) -> Decimal | None:
        if self.now.margin_pct is None or self.before.margin_pct is None:
            return None
        return self.now.margin_pct - self.before.margin_pct


@dataclass(frozen=True)
class Jump:
    """One abrupt change: a product's POS cost or price on a day, or a purchase."""

    kind: str  # "cost", "price" or "supplier"
    name: str
    date: datetime.date | None
    before: Decimal
    after: Decimal
    product_id: int | None = None
    supplier: str = ""
    invoice: str = ""

    @property
    def change(self) -> Decimal:
        return _pct(self.after, self.before) or Decimal("0")

    @property
    def is_bad(self) -> bool:
        """A cost going up hurts; a selling price going down hurts."""
        return self.change < 0 if self.kind == "price" else self.change > 0


@dataclass
class Report:
    settings: AlertSettings
    current: Span
    baseline: Span
    newest: datetime.date
    days_behind: int
    products: list[ProductAlert]
    jumps: list[Jump]
    uncosted: list[tuple[int, Totals]]

    @property
    def monthly_loss(self) -> Decimal:
        return sum((a.monthly_loss for a in self.products if a.monthly_loss > 0), Decimal("0"))

    @property
    def count(self) -> int:
        return len(self.products) + len(self.jumps) + len(self.uncosted) + (1 if self.days_behind else 0)


def _recipe_moves(product_ids, since: datetime.date, until: datetime.date) -> dict[int, list[SupplyMove]]:
    """Per product, the recipe supplies whose price moved between two dates."""
    lines = RecipeLine.objects.filter(product_id__in=product_ids).select_related("supply")
    by_supply: dict[int, list[SupplyPrice]] = defaultdict(list)
    supply_ids = {line.supply_id for line in lines}
    for price in SupplyPrice.objects.filter(supply_id__in=supply_ids).order_by("date", "recorded_at"):
        by_supply[price.supply_id].append(price)

    moves: dict[int, list[SupplyMove]] = defaultdict(list)
    for line in lines:
        history = by_supply.get(line.supply_id, [])
        before = [p for p in history if p.date and p.date < since]
        during = [p for p in history if p.date and since <= p.date <= until]
        if not before or not during:
            continue
        first, last = before[-1], during[-1]
        if first.unit_cost == last.unit_cost:
            continue
        moves[line.product_id].append(
            SupplyMove(line.supply.name, first.unit_cost, last.unit_cost,
                       last.supplier, last.invoice, last.date)
        )
    return moves


def _daily_levels(restaurant, product_ids, since: datetime.date, until: datetime.date):
    """Per product and day, the quantity-weighted POS cost and price."""
    rows = (
        SaleItem.objects.filter(
            sale__restaurant=restaurant,
            product_id__in=product_ids,
            sale__occurred_at__date__gte=since,
            sale__occurred_at__date__lte=until,
            quantity__gt=0,
        )
        .values_list("product_id", "sale__occurred_at", "quantity", "unit_cost", "unit_price")
    )
    sums: dict[int, dict[datetime.date, list]] = defaultdict(lambda: defaultdict(lambda: [0, Decimal(0), 0, Decimal(0)]))
    for product_id, occurred_at, quantity, cost, price in rows:
        day = timezone.localtime(occurred_at).date()
        cell = sums[product_id][day]
        if cost and cost > 0:
            cell[0] += quantity
            cell[1] += cost * quantity
        if price and price > 0:
            cell[2] += quantity
            cell[3] += price * quantity
    levels = {}
    for product_id, days in sums.items():
        levels[product_id] = sorted(
            (
                day,
                cell[1] / cell[0] if cell[0] else None,
                cell[3] / cell[2] if cell[2] else None,
            )
            for day, cell in days.items()
        )
    return levels


def _pos_jumps(restaurant, names: dict[int, str], current: Span, threshold: Decimal) -> list[Jump]:
    """The first day in the period a product's cost or price broke from its level."""
    levels = _daily_levels(restaurant, list(names), current.start - _LOOKBACK, current.end)
    jumps = []
    for product_id, series in levels.items():
        for kind, column in (("cost", 1), ("price", 2)):
            for index, row in enumerate(series):
                day, value = row[0], row[column]
                if day < current.start or value is None:
                    continue
                history = [r[column] for r in series[:index] if r[column] is not None][-_REFERENCE_DAYS:]
                if len(history) < _MIN_REFERENCE:
                    continue
                reference = Decimal(statistics.median(history))
                change = _pct(value, reference)
                if change is not None and abs(change) >= threshold:
                    jumps.append(Jump(kind, names[product_id], day, reference, value, product_id))
                    break
    return jumps


def _supplier_jumps(restaurant, current: Span, threshold: Decimal) -> list[Jump]:
    """Purchases in the period that cost far more or less than the one before."""
    jumps = []
    prices = SupplyPrice.objects.filter(
        supply__restaurant=restaurant, date__gte=current.start, date__lte=current.end
    ).select_related("supply")
    for price in prices:
        previous = (
            SupplyPrice.objects.filter(supply=price.supply, date__lt=price.date)
            .order_by("-date", "-recorded_at")
            .first()
        )
        if previous is None:
            continue
        change = _pct(price.unit_cost, previous.unit_cost)
        if change is not None and abs(change) >= threshold:
            jumps.append(
                Jump("supplier", price.supply.name, price.date, previous.unit_cost,
                     price.unit_cost, supplier=price.supplier, invoice=price.invoice)
            )
    return jumps


def build_report(
    restaurant,
    *,
    today: datetime.date | None = None,
    as_of: datetime.date | None = None,
) -> Report | None:
    """The report for the newest period with data, or ``None`` with no sales.

    ``as_of`` ends the period earlier, to read a past week as it would have
    been reported then.
    """
    settings = AlertSettings.for_restaurant(restaurant)
    newest = latest_sale_day(restaurant)
    if newest is None:
        return None
    if as_of is not None:
        newest = min(newest, as_of)
    today = today or timezone.localdate()
    current, baseline = spans(settings, newest)
    now, before = _totals(restaurant, current), _totals(restaurant, baseline)
    minimum = Decimal(settings.min_weekly_sales) * current.days / 7
    months = Decimal(30) / Decimal(current.days)

    alerts, uncosted = [], []
    for product_id, stats in now.items():
        if stats.revenue < minimum:
            continue
        if stats.cost <= 0:
            uncosted.append((product_id, stats))
            continue
        old = before.get(product_id)
        if old is None or old.cost <= 0 or old.revenue <= 0:
            continue
        reasons = []
        cost_change = _pct(stats.unit_cost, old.unit_cost)
        price_change = _pct(stats.unit_price, old.unit_price)
        if cost_change is not None and cost_change >= settings.cost_rise:
            reasons.append(COST_RISE)
        if price_change is not None and price_change <= -settings.cost_rise:
            reasons.append(PRICE_DROP)
        if (old.margin_pct - stats.margin_pct) >= settings.margin_drop:
            reasons.append(MARGIN_DROP)
        if not reasons:
            continue
        lost_per_portion = (old.unit_price - old.unit_cost) - (stats.unit_price - stats.unit_cost)
        alerts.append(
            ProductAlert(product_id, stats.name, stats, old, reasons,
                         lost_per_portion * stats.portions * months)
        )

    moves = _recipe_moves([a.product_id for a in alerts], baseline.start, current.end)
    for alert in alerts:
        alert.causes = moves.get(alert.product_id, [])
    alerts.sort(key=lambda a: a.monthly_loss, reverse=True)
    uncosted.sort(key=lambda pair: pair[1].revenue, reverse=True)

    watched = {pid: stats.name for pid, stats in now.items() if stats.revenue >= minimum}
    jumps = _pos_jumps(restaurant, watched, current, settings.abrupt_change)
    jumps += _supplier_jumps(restaurant, current, settings.abrupt_change)
    jumps.sort(key=lambda j: abs(j.change), reverse=True)

    return Report(
        settings=settings,
        current=current,
        baseline=baseline,
        newest=newest,
        # Only the newest period can be behind: a past one was asked for.
        days_behind=0 if as_of is not None else max((today - newest).days - 1, 0),
        products=alerts,
        jumps=jumps,
        uncosted=uncosted,
    )
