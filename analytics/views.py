import datetime
import io

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _

from sales.models import Sale

from .exports import build_analysis_workbook, build_productos_vendidos_workbook
from .services import (
    MARGIN_SORT_KEYS,
    compute_kpis,
    monthly_pnl,
    product_margins,
    revenue_by_category,
    revenue_by_day,
    top_products_by_revenue,
)

# (key, label) pairs driving the margin table header, in display order.
MARGIN_COLUMNS = (
    ("name", _("Name")),
    ("category", _("Category")),
    ("cost", _("Cost")),
    ("sale_price", _("Sale price")),
    ("margin_amount", _("Margin $")),
    ("margin_pct", _("Margin %")),
    ("units_sold", _("Units sold")),
    ("total_margin", _("Total margin")),
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
def pnl_summary(request: HttpRequest) -> HttpResponse:
    """Monthly P&L table: trailing 12 months, or a selected year."""
    year_param = request.GET.get("year", "")
    year = int(year_param) if year_param.isdigit() else None

    rows = monthly_pnl(year=year)
    years = [d.year for d in Sale.objects.dates("occurred_at", "year", order="DESC")]
    context = {
        "rows": rows,
        "selected_year": year,
        "years": years,
    }
    return render(request, "analytics/pnl.html", context)


_XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _xlsx_response(workbook, filename: str) -> HttpResponse:
    """Serialize an openpyxl workbook into a downloadable .xlsx response."""
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type=_XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def export_productos_vendidos(request: HttpRequest) -> HttpResponse:
    """Download the Productos-Vendidos units-per-month matrix as .xlsx."""
    return _xlsx_response(
        build_productos_vendidos_workbook(), "productos_vendidos.xlsx"
    )


@login_required
def export_analysis(request: HttpRequest) -> HttpResponse:
    """Download the analysis report for the active range as .xlsx."""
    start, end = _resolve_range(request)
    return _xlsx_response(build_analysis_workbook(start, end), "analisis_mesa.xlsx")


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
