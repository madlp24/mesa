"""The period a page looks at, and the one before it (US49).

The dashboard used to open on the thirty days ending *today*. When the reports
stop earlier -- they arrive in batches, from a USB stick -- every figure read
zero and the owner had to type two dates to see anything. A window now ends on
the latest day that has sales, and the page says how far behind the reports
are.

Presets are what an owner actually asks for: the last week, month or quarter,
this calendar month, the previous one, this year. The rolling ones (7, 30 and
90 days) end on the latest day with data; the calendar ones are the calendar.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.db.models import Max
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _

from sales.models import Sale

DEFAULT_PRESET = "30d"

#: (key, label) in the order the page offers them.
PRESETS = (
    ("7d", _("7 days")),
    ("30d", _("30 days")),
    ("90d", _("90 days")),
    ("month", _("This month")),
    ("last_month", _("Last month")),
    ("year", _("This year")),
)
_PRESET_KEYS = {key for key, _label in PRESETS}


@dataclass(frozen=True)
class Window:
    """A date range, how it was chosen, and how fresh the data behind it is."""

    start: datetime.date
    end: datetime.date
    preset: str  # one of the preset keys, or "custom"
    latest: datetime.date | None  # newest day with sales, if any
    today: datetime.date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def previous(self) -> tuple[datetime.date, datetime.date]:
        """The window of the same length that ends the day before this one."""
        end = self.start - datetime.timedelta(days=1)
        return end - datetime.timedelta(days=self.days - 1), end

    @property
    def query(self) -> str:
        """The query string that reopens this same window on another page."""
        if self.preset == "custom":
            return f"start={self.start.isoformat()}&end={self.end.isoformat()}"
        return f"period={self.preset}"

    @property
    def days_behind(self) -> int:
        """Days between the newest report and yesterday (0 when up to date)."""
        if self.latest is None:
            return 0
        return max((self.today - self.latest).days - 1, 0)


def latest_sale_day(restaurant) -> datetime.date | None:
    newest = Sale.objects.filter(restaurant=restaurant).aggregate(
        newest=Max("occurred_at")
    )["newest"]
    return timezone.localtime(newest).date() if newest else None


def _month_start(day: datetime.date) -> datetime.date:
    return day.replace(day=1)


def window_for(
    restaurant,
    params,
    *,
    today: datetime.date | None = None,
    default: str = DEFAULT_PRESET,
) -> Window:
    """Resolve ``?period=`` or ``?start=&end=`` into a :class:`Window`.

    Explicit dates win. With neither, ``default`` applies -- the 30 days ending
    on the latest day with sales (or today, when that is earlier).
    """
    today = today or timezone.localdate()
    latest = latest_sale_day(restaurant)
    anchor = min(today, latest) if latest else today

    start = parse_date(params.get("start", "") or "")
    end = parse_date(params.get("end", "") or "")
    if start or end:
        end = end or anchor
        start = start or end - datetime.timedelta(days=29)
        if start > end:
            start, end = end, start
        return Window(start, end, "custom", latest, today)

    preset = params.get("period", "")
    if preset not in _PRESET_KEYS:
        preset = default
    if preset == "7d":
        start, end = anchor - datetime.timedelta(days=6), anchor
    elif preset == "90d":
        start, end = anchor - datetime.timedelta(days=89), anchor
    elif preset == "month":
        start, end = _month_start(today), today
    elif preset == "last_month":
        end = _month_start(today) - datetime.timedelta(days=1)
        start = _month_start(end)
    elif preset == "year":
        start, end = today.replace(month=1, day=1), today
    else:
        start, end = anchor - datetime.timedelta(days=29), anchor
    return Window(start, end, preset, latest, today)
