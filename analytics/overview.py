"""What the dashboard says about a period (US49).

The old dashboard printed four boxes and three charts and left the reading to
the owner. Two of the boxes were misleading on POS reports: "items sold" adds
grams of meat to bottles of wine, and the "average ticket" divided takings by
synthetic sales -- one per product per day -- not by bills. This answers the
questions an owner actually opens it with:

* how much did we sell, and is it more or less than the period before;
* how many people came and what each bill left (from the daily covers);
* what needs fixing: products sold at a loss or without a cost, reports
  missing since the newest one;
* what sold most, by product and by group.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Sum

from sales.models import DailySummary

from .alerts import margin_alerts
from .periods import Window
from .services import (
    compute_kpis,
    revenue_by_category,
    revenue_by_day,
    top_products_by_revenue,
)


def _change(now, before) -> Decimal | None:
    """Percentage change, or ``None`` when there is nothing to compare with."""
    if now is None or not before:
        return None
    return (Decimal(now) - Decimal(before)) / Decimal(before) * 100


@dataclass(frozen=True)
class Covers:
    """People and bills over a period, from the daily covers report."""

    guests: int
    accounts: int
    sales: Decimal | None

    @property
    def per_account(self) -> Decimal | None:
        if self.sales is None or not self.accounts:
            return None
        return self.sales / self.accounts

    @property
    def per_guest(self) -> Decimal | None:
        if self.sales is None or not self.guests:
            return None
        return self.sales / self.guests


def covers(restaurant, start: datetime.date, end: datetime.date) -> Covers | None:
    rows = DailySummary.objects.filter(
        restaurant=restaurant, date__gte=start, date__lte=end
    )
    totals = rows.aggregate(
        guests=Sum("guests"),
        accounts=Sum("accounts"),
        bar=Sum("bar_sales"),
        kitchen=Sum("kitchen_sales"),
    )
    if not totals["guests"] and not totals["accounts"]:
        return None
    money = [v for v in (totals["bar"], totals["kitchen"]) if v is not None]
    return Covers(
        guests=totals["guests"] or 0,
        accounts=totals["accounts"] or 0,
        sales=sum(money) if money else None,
    )


@dataclass(frozen=True)
class Share:
    """One row of a ranking: what it took, and its slice of the period."""

    name: str
    revenue: Decimal
    share: Decimal  # percentage of the period's revenue
    width: Decimal  # percentage of the top row, for drawing the bar


def _ranked(rows: list[dict], total: Decimal) -> list[Share]:
    top = rows[0]["revenue"] if rows else None
    return [
        Share(
            name=row["name"] or "",
            revenue=row["revenue"],
            share=(row["revenue"] / total * 100) if total else Decimal("0"),
            width=(row["revenue"] / top * 100) if top else Decimal("0"),
        )
        for row in rows
    ]


@dataclass
class Overview:
    window: Window
    revenue: Decimal
    revenue_change: Decimal | None
    margin_pct: Decimal | None
    margin_change: Decimal | None  # in points, not percent
    covers: Covers | None
    guests_change: Decimal | None
    per_account_change: Decimal | None
    days: list[dict] = field(default_factory=list)
    best_day: dict | None = None
    at_a_loss: list = field(default_factory=list)
    without_cost: list = field(default_factory=list)
    products: list[Share] = field(default_factory=list)
    categories: list[Share] = field(default_factory=list)

    @property
    def has_sales(self) -> bool:
        return self.revenue > 0

    @property
    def to_review(self) -> int:
        return (
            len(self.at_a_loss)
            + len(self.without_cost)
            + (1 if self.window.days_behind else 0)
        )


def _series(restaurant, window: Window) -> list[dict]:
    """One entry per calendar day of the window, zero on days without sales.

    Closed days stay in the series as gaps: a smoothed line through them made
    every Monday look like a slump.
    """
    by_day = {row["day"]: row["revenue"] for row in revenue_by_day(
        restaurant, window.start, window.end
    )}
    last = min(window.end, window.latest or window.end)
    days = []
    day = window.start
    while day <= window.end:
        revenue = by_day.get(day, Decimal("0"))
        days.append(
            {
                "date": day,
                "revenue": revenue,
                "open": revenue > 0,
                "future": day > last,
            }
        )
        day += datetime.timedelta(days=1)
    return days


def overview(restaurant, window: Window, *, products: int = 8) -> Overview:
    now = compute_kpis(restaurant, window.start, window.end)
    before_start, before_end = window.previous
    before = compute_kpis(restaurant, before_start, before_end)

    revenue = now["total_revenue"]
    margin = now["gross_margin_pct"] if revenue else None
    before_margin = before["gross_margin_pct"] if before["total_revenue"] else None

    people = covers(restaurant, window.start, window.end)
    people_before = covers(restaurant, before_start, before_end)

    days = _series(restaurant, window)
    open_days = [d for d in days if d["open"]]
    alerts = margin_alerts(restaurant, start=window.start, end=window.end)

    return Overview(
        window=window,
        revenue=revenue,
        revenue_change=_change(revenue, before["total_revenue"]),
        margin_pct=margin,
        margin_change=(
            margin - before_margin
            if margin is not None and before_margin is not None
            else None
        ),
        covers=people,
        guests_change=_change(
            people.guests if people else None,
            people_before.guests if people_before else None,
        ),
        per_account_change=_change(
            people.per_account if people else None,
            people_before.per_account if people_before else None,
        ),
        days=days,
        best_day=max(open_days, key=lambda d: d["revenue"]) if open_days else None,
        at_a_loss=alerts.at_a_loss,
        without_cost=alerts.without_cost,
        products=_ranked(
            top_products_by_revenue(restaurant, window.start, window.end, products),
            revenue,
        ),
        categories=_ranked(
            revenue_by_category(restaurant, window.start, window.end), revenue
        ),
    )
