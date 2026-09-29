"""How this period compares with the same one a year ago (US42).

The owner watches three things: how many people came, what each left on
average, and what the day billed. All three are only meaningful next to
something -- a good month is only good against last year's.

Everything is read from :class:`sales.DailySummary`, which holds both the
turnout and the money for the same day, so the average ticket never mixes a
period's people with another's takings.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from sales.models import DailySummary

GRAINS = ("day", "week", "month")


@dataclass(frozen=True)
class Period:
    """One day, week or month, and the same one a year earlier."""

    key: datetime.date          # the period's first day
    label: str
    guests: int
    accounts: int
    sales: Decimal | None
    prev_guests: int | None = None
    prev_sales: Decimal | None = None

    def _per(self, total):
        """A total spread over the people it belongs to."""
        if total is None or not self.guests:
            return None
        return total / self.guests

    @property
    def ticket_per_guest(self):
        return self._per(self.sales)

    @property
    def ticket_per_account(self):
        if self.sales is None or not self.accounts:
            return None
        return self.sales / self.accounts

    @property
    def guests_change(self):
        """Change in turnout against a year ago, as a percentage."""
        if not self.prev_guests:
            return None
        return (self.guests - self.prev_guests) / self.prev_guests * 100

    @property
    def sales_change(self):
        if self.sales is None or not self.prev_sales:
            return None
        return (self.sales - self.prev_sales) / self.prev_sales * 100


def _bucket(day: datetime.date, grain: str) -> datetime.date:
    """The first day of the period a date falls in."""
    if grain == "day":
        return day
    if grain == "week":
        return day - datetime.timedelta(days=day.weekday())
    return day.replace(day=1)


def _a_year_before(key: datetime.date, grain: str) -> datetime.date:
    """The same period one year earlier.

    Weeks are matched by their position in the year, not by subtracting 365
    days, so a Monday still lines up with a Monday.
    """
    if grain == "week":
        year, week, _ = key.isocalendar()
        try:
            return datetime.date.fromisocalendar(year - 1, week, 1)
        except ValueError:  # week 53 has no twin
            return datetime.date.fromisocalendar(year - 1, 52, 1)
    try:
        return key.replace(year=key.year - 1)
    except ValueError:  # 29 February
        return key.replace(year=key.year - 1, day=28)


def _totals(restaurant, grain: str) -> dict[datetime.date, dict]:
    """Guests, accounts and sales per period, in one pass over the days."""
    buckets: dict[datetime.date, dict] = {}
    rows = DailySummary.objects.filter(restaurant=restaurant).only(
        "date", "guests", "accounts", "bar_sales", "kitchen_sales"
    )
    for row in rows:
        key = _bucket(row.date, grain)
        bucket = buckets.setdefault(
            key, {"guests": 0, "accounts": 0, "sales": None}
        )
        bucket["guests"] += row.guests
        bucket["accounts"] += row.accounts
        if row.sales is not None:
            bucket["sales"] = (bucket["sales"] or Decimal("0")) + row.sales
    return buckets


def _label(key: datetime.date, grain: str) -> str:
    if grain == "day":
        return key.strftime("%Y-%m-%d")
    if grain == "week":
        year, week, _ = key.isocalendar()
        return f"{year} · S{week:02d}"
    return key.strftime("%Y-%m")


def compare(restaurant, grain: str = "month", limit: int = 24) -> list[Period]:
    """The most recent periods, newest first, each against a year earlier."""
    if grain not in GRAINS:
        grain = "month"
    buckets = _totals(restaurant, grain)

    periods = []
    for key in sorted(buckets, reverse=True)[:limit]:
        now = buckets[key]
        before = buckets.get(_a_year_before(key, grain))
        periods.append(
            Period(
                key=key,
                label=_label(key, grain),
                guests=now["guests"],
                accounts=now["accounts"],
                sales=now["sales"],
                prev_guests=before["guests"] if before else None,
                prev_sales=before["sales"] if before else None,
            )
        )
    return periods
