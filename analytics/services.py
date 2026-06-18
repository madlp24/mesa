"""KPI calculation services for the analytics dashboard.

Keeping the math here (and out of the view) means the headline numbers can be
unit-tested directly against fixture data. All functions accept an optional
``start``/``end`` date window; ``None`` means "unbounded on that side".
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    QuerySet,
    Sum,
)
from django.db.models.functions import TruncDate

from sales.models import SaleItem

_REVENUE = ExpressionWrapper(
    F("unit_price") * F("quantity"),
    output_field=DecimalField(max_digits=14, decimal_places=2),
)
_MARGIN = ExpressionWrapper(
    (F("unit_price") - F("unit_cost")) * F("quantity"),
    output_field=DecimalField(max_digits=14, decimal_places=2),
)


def sale_items_in_range(
    start: datetime.date | None = None,
    end: datetime.date | None = None,
) -> QuerySet:
    """Return the SaleItem queryset filtered to the inclusive date window."""
    items = SaleItem.objects.all()
    if start:
        items = items.filter(sale__occurred_at__date__gte=start)
    if end:
        items = items.filter(sale__occurred_at__date__lte=end)
    return items


def compute_kpis(
    start: datetime.date | None = None,
    end: datetime.date | None = None,
) -> dict:
    """Compute the four headline KPIs for the given date window.

    Returns a dict with:
      - ``total_revenue``    Decimal, sum of unit_price * quantity
      - ``items_sold``       int, sum of quantity
      - ``average_ticket``   Decimal, revenue divided by number of sales
      - ``gross_margin_pct`` Decimal, margin / revenue as a percentage
    """
    items = sale_items_in_range(start, end)
    totals = items.aggregate(
        revenue=Sum(_REVENUE),
        margin=Sum(_MARGIN),
        units=Sum("quantity"),
        sales=Count("sale", distinct=True),
    )

    revenue = totals["revenue"] or Decimal("0")
    margin = totals["margin"] or Decimal("0")
    units = totals["units"] or 0
    sales = totals["sales"] or 0

    average_ticket = (revenue / sales) if sales else Decimal("0")
    gross_margin_pct = (margin / revenue * 100) if revenue else Decimal("0")

    return {
        "total_revenue": revenue,
        "items_sold": units,
        "average_ticket": average_ticket,
        "gross_margin_pct": gross_margin_pct,
    }


def revenue_by_day(
    start: datetime.date | None = None,
    end: datetime.date | None = None,
) -> list[dict]:
    """Daily revenue within the window, ordered by date.

    Returns a list of ``{"day": date, "revenue": Decimal}`` rows with one entry
    per day that actually had sales (gaps are not back-filled).
    """
    rows = (
        sale_items_in_range(start, end)
        .annotate(day=TruncDate("sale__occurred_at"))
        .values("day")
        .annotate(revenue=Sum(_REVENUE))
        .order_by("day")
    )
    return list(rows)


def top_products_by_revenue(
    start: datetime.date | None = None,
    end: datetime.date | None = None,
    limit: int = 10,
) -> list[dict]:
    """Top ``limit`` products by revenue within the window, highest first.

    Returns a list of ``{"name": str, "revenue": Decimal}`` rows. Ranking is by
    revenue (not units) because weight-based products report quantity in grams.
    """
    rows = (
        sale_items_in_range(start, end)
        .values("product__id", "product__name")
        .annotate(revenue=Sum(_REVENUE))
        .order_by("-revenue")[:limit]
    )
    return [{"name": row["product__name"], "revenue": row["revenue"]} for row in rows]


def revenue_by_category(
    start: datetime.date | None = None,
    end: datetime.date | None = None,
) -> list[dict]:
    """Revenue grouped by product category within the window, highest first.

    Returns a list of ``{"name": str, "revenue": Decimal}`` rows, one per
    category that had sales.
    """
    rows = (
        sale_items_in_range(start, end)
        .values("product__category__id", "product__category__name")
        .annotate(revenue=Sum(_REVENUE))
        .order_by("-revenue")
    )
    return [
        {"name": row["product__category__name"], "revenue": row["revenue"]}
        for row in rows
    ]
