"""How each day of the week sells, and how the holidays compare (US51).

The owner opens on ordinary days except Monday and decides holiday by holiday
whether to open, so the question is always the same: is this holiday worth it?
This reads the restaurant's own history to answer it.

Days come from the daily covers report when the restaurant has one -- it
carries people as well as sales -- and otherwise from the POS sales per day.
A day counts as open when it sold something or served someone. Holidays are
the Colombian calendar, Emiliani Mondays included, from the ``holidays``
package; weekday averages use ordinary days only, so a holiday Monday does not
pass for a normal one.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

import holidays
from django.db.models import Sum
from django.utils.dates import WEEKDAYS
from django.db.models.functions import TruncDate
from django.utils import timezone

from sales.models import DailySummary

from .services import _REVENUE, sale_items_in_range

COUNTRY = "CO"


@dataclass(frozen=True)
class Day:
    date: datetime.date
    sales: Decimal | None
    guests: int | None
    holiday: str = ""


def holiday_calendar(start: datetime.date, end: datetime.date, language: str = "es") -> dict:
    """``{date: name}`` for every holiday between ``start`` and ``end``."""
    years = range(start.year, end.year + 1)
    calendar = holidays.country_holidays(COUNTRY, years=years, language=language)
    return {day: name for day, name in sorted(calendar.items()) if start <= day <= end}


def open_days(
    restaurant,
    start: datetime.date | None = None,
    end: datetime.date | None = None,
    language: str = "es",
) -> list[Day]:
    """Every day the restaurant opened, oldest first, with its holiday if any."""
    covers = DailySummary.objects.filter(restaurant=restaurant)
    if covers.exists():
        if start:
            covers = covers.filter(date__gte=start)
        if end:
            covers = covers.filter(date__lte=end)
        rows = [(c.date, c.sales, c.guests) for c in covers.order_by("date")]
    else:
        daily = (
            sale_items_in_range(restaurant, start, end)
            .annotate(day=TruncDate("sale__occurred_at"))
            .values("day")
            .annotate(revenue=Sum(_REVENUE))
            .order_by("day")
        )
        rows = [(r["day"], r["revenue"], None) for r in daily]

    rows = [r for r in rows if (r[1] or 0) > 0 or (r[2] or 0) > 0]
    if not rows:
        return []
    calendar = holiday_calendar(rows[0][0], rows[-1][0], language)
    return [Day(day, sales, guests, calendar.get(day, "")) for day, sales, guests in rows]


def _average(values) -> Decimal | None:
    values = [Decimal(v) for v in values if v is not None]
    return sum(values) / len(values) if values else None


@dataclass(frozen=True)
class Weekday:
    weekday: int  # Monday is 0
    days: int
    avg_sales: Decimal | None
    avg_guests: Decimal | None

    @property
    def label(self) -> str:
        return WEEKDAYS[self.weekday]

    @property
    def per_guest(self) -> Decimal | None:
        if not self.avg_sales or not self.avg_guests:
            return None
        return self.avg_sales / self.avg_guests


def weekday_profile(days: list[Day]) -> list[Weekday]:
    """Monday to Sunday, ordinary open days only."""
    ordinary = [d for d in days if not d.holiday]
    return [
        Weekday(
            weekday=weekday,
            days=len(group := [d for d in ordinary if d.date.weekday() == weekday]),
            avg_sales=_average(d.sales for d in group),
            avg_guests=_average(d.guests for d in group),
        )
        for weekday in range(7)
    ]


@dataclass(frozen=True)
class Holiday:
    date: datetime.date
    name: str
    opened: bool
    sales: Decimal | None
    guests: int | None
    change: Decimal | None  # % against an ordinary open day of the period
    reported: bool = True  # False after the newest report: closed or not, unknown


def holiday_report(
    days: list[Day],
    start: datetime.date,
    end: datetime.date,
    language: str = "es",
) -> list[Holiday]:
    """Every holiday between ``start`` and ``end``, opened or not, newest first.

    A holiday after the newest day with data is not "closed": its report has
    simply not arrived, so it is marked unreported.
    """
    by_date = {d.date: d for d in days}
    newest = days[-1].date if days else None
    baseline = _average(d.sales for d in days if not d.holiday)
    report = []
    for date, name in holiday_calendar(start, end, language).items():
        day = by_date.get(date)
        sales = day.sales if day else None
        report.append(
            Holiday(
                date=date,
                name=name,
                opened=day is not None,
                sales=sales,
                guests=day.guests if day else None,
                change=(
                    (Decimal(sales) - baseline) / baseline * 100
                    if sales is not None and baseline
                    else None
                ),
                reported=newest is not None and date <= newest,
            )
        )
    return sorted(report, key=lambda h: h.date, reverse=True)


@dataclass(frozen=True)
class Upcoming:
    date: datetime.date
    name: str
    expected: Decimal | None  # average of last year's opened holidays on that weekday
    samples: int


def upcoming_holidays(
    restaurant,
    today: datetime.date | None = None,
    months: int = 4,
    language: str = "es",
) -> list[Upcoming]:
    """The next holidays, each with what the same kind of holiday sold last year."""
    today = today or timezone.localdate()
    year_ago = today - datetime.timedelta(days=365)
    past = [d for d in open_days(restaurant, year_ago, today, language) if d.holiday]
    horizon = today + datetime.timedelta(days=months * 31)
    result = []
    for date, name in holiday_calendar(today, horizon, language).items():
        same = [d for d in past if d.date.weekday() == date.weekday() and d.sales]
        result.append(
            Upcoming(
                date=date,
                name=name,
                expected=_average(d.sales for d in same),
                samples=len(same),
            )
        )
    return result


def between_weekdays(amount, profile: list[Weekday]) -> tuple[Weekday | None, Weekday | None]:
    """The ordinary weekdays that sell just under and just over ``amount``.

    "A holiday Monday sells more than a Tuesday and less than a Wednesday" is
    easier to act on than a percentage.
    """
    if amount is None:
        return None, None
    known = sorted((w for w in profile if w.avg_sales), key=lambda w: w.avg_sales)
    below = [w for w in known if w.avg_sales <= amount]
    above = [w for w in known if w.avg_sales > amount]
    return (below[-1] if below else None), (above[0] if above else None)
