import datetime
import io
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from sales.models import Sale

from .exports import build_analysis_workbook, build_productos_vendidos_workbook
from .alerts import DEFAULT_THRESHOLD, margin_alerts
from .comparisons import GRAINS, compare
from .forms import WorkbookUpdateForm
from .unified_excel import UnifiedUpdateError, update_productos_vendidos
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
    has_data = Sale.objects.filter(restaurant=request.restaurant).exists()
    context = {
        "kpis": compute_kpis(request.restaurant, start, end),
        "has_data": has_data,
        "start": start,
        "end": end,
    }
    return render(request, "analytics/dashboard.html", context)


@login_required
def revenue_over_time(request: HttpRequest) -> JsonResponse:
    """Daily revenue (COP) for the active range, as JSON for the line chart."""
    start, end = _resolve_range(request)
    rows = revenue_by_day(request.restaurant, start, end)
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
    rows = top_products_by_revenue(request.restaurant, start, end)
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

    rows = product_margins(
        request.restaurant, start, end, sort=sort, descending=direction == "desc"
    )
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

    rows = monthly_pnl(request.restaurant, year=year)
    years = [
        d.year
        for d in Sale.objects.filter(restaurant=request.restaurant).dates(
            "occurred_at", "year", order="DESC"
        )
    ]
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
        build_productos_vendidos_workbook(request.restaurant), "productos_vendidos.xlsx"
    )


@login_required
def export_analysis(request: HttpRequest) -> HttpResponse:
    """Download the analysis report for the active range as .xlsx."""
    start, end = _resolve_range(request)
    return _xlsx_response(
        build_analysis_workbook(request.restaurant, start, end), "analisis_mesa.xlsx"
    )


@login_required
def revenue_by_category_api(request: HttpRequest) -> JsonResponse:
    """Revenue per category for the active range, as JSON for the doughnut."""
    start, end = _resolve_range(request)
    rows = revenue_by_category(request.restaurant, start, end)
    return JsonResponse(
        {
            "labels": [row["name"] for row in rows],
            "data": [float(row["revenue"]) for row in rows],
        }
    )


@login_required
def workbook_update(request: HttpRequest) -> HttpResponse:
    """Fill one month into the owner's master workbook and hand it straight back.

    The workbook is a private business file, so it is never stored: the upload
    lands in a temporary directory, the copy is read into memory, and the
    directory is gone before the response is sent.
    """
    form = WorkbookUpdateForm()
    if request.method == "POST":
        form = WorkbookUpdateForm(request.POST, request.FILES)
        if form.is_valid():
            download = _fill_workbook(request, form.cleaned_data)
            if download is not None:
                return download

    return render(request, "analytics/workbook_update.html", {"form": form})


def _fill_workbook(request: HttpRequest, data: dict):
    """Return the updated workbook as a download, or None when it cannot be."""
    upload = data["workbook"]
    with tempfile.TemporaryDirectory() as tmpdir:
        source = Path(tmpdir) / Path(upload.name).name
        with source.open("wb") as handle:
            for chunk in upload.chunks():
                handle.write(chunk)
        try:
            summary = update_productos_vendidos(
                source, request.restaurant, data["year"], data["month"]
            )
        except UnifiedUpdateError as exc:
            messages.error(request, str(exc))
            return None
        copy = Path(summary["copy"])
        payload = copy.read_bytes()
        name = copy.name

    _report(request, summary)
    return FileResponse(io.BytesIO(payload), as_attachment=True, filename=name)


def _report(request: HttpRequest, summary: dict) -> None:
    """Queue what happened; it shows on the next page the owner opens."""
    for warning in summary["warnings"]:
        messages.warning(request, warning)

    appended = summary["appended_names"]
    text = gettext(
        "%(column)s updated: %(matched)d products matched."
    ) % {"column": summary["column"], "matched": summary["matched"]}
    if appended:
        text += " " + ngettext(
            "%(count)d product was added as a new row -- check it is not a "
            "renamed one: %(names)s",
            "%(count)d products were added as new rows -- check they are not "
            "renamed ones: %(names)s",
            len(appended),
        ) % {"count": len(appended), "names": ", ".join(appended[:8])}
    messages.success(request, text)


def _threshold(request: HttpRequest) -> Decimal:
    """The margin the owner considers thin, from ?threshold=, clamped to 0-100."""
    raw = request.GET.get("threshold")
    if not raw:
        return DEFAULT_THRESHOLD
    try:
        value = Decimal(raw)
    except (InvalidOperation, TypeError):
        return DEFAULT_THRESHOLD
    return min(max(value, Decimal("0")), Decimal("100"))


@login_required
def margin_alerts_view(request: HttpRequest) -> HttpResponse:
    """Products whose margin is worth a look, worst money first (US40).

    Unlike the dashboard this does not default to the last 30 days: a product
    sold at a loss in March is still a problem in September, so the whole
    history is considered unless a range is asked for.
    """
    start = parse_date(request.GET.get("start", "") or "")
    end = parse_date(request.GET.get("end", "") or "")
    threshold = _threshold(request)
    alerts = margin_alerts(
        request.restaurant, threshold=threshold, start=start, end=end
    )
    return render(
        request,
        "analytics/margin_alerts.html",
        {"alerts": alerts, "start": start, "end": end, "threshold": threshold},
    )


@login_required
def comparisons(request: HttpRequest) -> HttpResponse:
    """Turnout, average ticket and takings, each against a year earlier (US42)."""
    grain = request.GET.get("grain", "month")
    if grain not in GRAINS:
        grain = "month"
    limit = 31 if grain == "day" else (26 if grain == "week" else 24)
    return render(
        request,
        "analytics/comparisons.html",
        {"periods": compare(request.restaurant, grain, limit), "grain": grain},
    )
