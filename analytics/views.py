import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from .services import (
    MARGIN_SORT_KEYS,
    compute_kpis,
    product_margins,
    revenue_by_category,
    revenue_by_day,
    top_products_by_revenue,
)

# (key, label) pairs driving the margin table header, in display order.
MARGIN_COLUMNS = (
    ("name", "Name"),
    ("category", "Category"),
    ("cost", "Cost"),
    ("sale_price", "Sale price"),
    ("margin_amount", "Margin $"),
    ("margin_pct", "Margin %"),
    ("units_sold", "Units sold"),
    ("total_margin", "Total margin"),
)

# Default dashboard window when the user has not picked a range: the last 30
# days, inclusive of today.
DEFAULT_RANGE_DAYS = 30


def _resolve_range(request: HttpRequest) -> tuple:
    """Resolve the active date window from ?start=&end= query params.

    When neither bound is supplied we fall back to the last 30 days so the
    dashboard always opens on a sensible, bounded period rather than all-time.
    """
    start = parse_date(request.GET.get("start", "") or "")
    end = parse_date(request.GET.get("end", "") or "")
    if start is None and end is None:
        today = timezone.localdate()
        end = today
        start = today - datetime.timedelta(days=DEFAULT_RANGE_DAYS - 1)
    return start, end


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    start, end = _resolve_range(request)
    context = {
        "kpis": compute_kpis(start, end),
        "start": start,
        "end": end,
    }
    return render(request, "analytics/dashboard.html", context)


@login_required
def revenue_over_time(request: HttpRequest) -> JsonResponse:
    """Daily revenue (COP) for the active range, as JSON for the line chart."""
    start, end = _resolve_range(request)
    rows = revenue_by_day(start, end)
    return JsonResponse(
        {
            "labels": [row["day"].isoformat() for row in rows],
            "data": [float(row["revenue"]) for row in rows],
        }
    )


@login_required
def top_products(request: HttpRequest) -> JsonResponse:
    """Top 10 products by revenue for the active range, as JSON for the chart."""
    start, end = _resolve_range(request)
    rows = top_products_by_revenue(start, end)
    return JsonResponse(
        {
            "labels": [row["name"] for row in rows],
            "data": [float(row["revenue"]) for row in rows],
        }
    )


@login_required
def margin_analysis(request: HttpRequest) -> HttpResponse:
    """Sortable table ranking active products by gross margin for the range."""
    start, end = _resolve_range(request)

    sort = request.GET.get("sort", "margin_pct")
    if sort not in MARGIN_SORT_KEYS:
        sort = "margin_pct"
    direction = request.GET.get("dir", "desc")
    if direction not in ("asc", "desc"):
        direction = "desc"

    rows = product_margins(start, end, sort=sort, descending=direction == "desc")
    context = {
        "columns": MARGIN_COLUMNS,
        "rows": rows,
        "sort": sort,
        "direction": direction,
        "start": start,
        "end": end,
    }
    return render(request, "analytics/margin_analysis.html", context)


@login_required
def revenue_by_category_api(request: HttpRequest) -> JsonResponse:
    """Revenue per category for the active range, as JSON for the doughnut."""
    start, end = _resolve_range(request)
    rows = revenue_by_category(start, end)
    return JsonResponse(
        {
            "labels": [row["name"] for row in rows],
            "data": [float(row["revenue"]) for row in rows],
        }
    )
