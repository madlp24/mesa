import io
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from catalog.families import family_of, is_hidden
from catalog.models import Category
from sales.models import Sale

from .exports import build_analysis_workbook, build_productos_vendidos_workbook
from .alerts import DEFAULT_THRESHOLD, margin_alerts
from .comparisons import GRAINS, compare
from .forms import WorkbookUpdateForm
from .days import between_weekdays, holiday_report, open_days, upcoming_holidays, weekday_profile
from .menu_engineering import (
    menu_engineering,
    price_moves,
    weakest_dogs,
    with_movement,
)
from .overview import overview
from .periods import PRESETS, latest_sale_day, window_for
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
    """The active date window, from ``?period=`` or ``?start=&end=``.

    With neither, the 30 days ending on the newest day with sales: ending on
    *today* showed nothing but zeros whenever the reports were behind (US49).
    """
    window = window_for(request.restaurant, request.GET)
    return window.start, window.end


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    window = window_for(request.restaurant, request.GET)
    has_data = window.latest is not None
    summary = overview(request.restaurant, window) if has_data else None
    context = {
        "kpis": compute_kpis(request.restaurant, window.start, window.end),
        "has_data": has_data,
        "window": window,
        "overview": summary,
        "presets": PRESETS,
        "start": window.start,
        "end": window.end,
        "series": [
            {
                "date": day["date"].isoformat(),
                "revenue": float(day["revenue"]),
                "open": day["open"],
            }
            for day in (summary.days if summary else [])
        ],
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
    window = window_for(request.restaurant, request.GET)
    start, end = window.start, window.end

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
        "window": window,
        "presets": PRESETS,
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

    The month offered is the one of the newest report: the form used to open
    on January of next year, the first entry of each list (US52).
    """
    newest = latest_sale_day(request.restaurant) or timezone.localdate()
    form = WorkbookUpdateForm(initial={"year": newest.year, "month": newest.month})
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
    window = None
    if any(request.GET.get(key) for key in ("period", "start", "end")):
        window = window_for(request.restaurant, request.GET)
    start, end = (window.start, window.end) if window else (None, None)
    threshold = _threshold(request)
    alerts = margin_alerts(
        request.restaurant, threshold=threshold, start=start, end=end
    )
    return render(
        request,
        "analytics/margin_alerts.html",
        {
            "alerts": alerts,
            "start": start,
            "end": end,
            "threshold": threshold,
            "window": window,
            "presets": PRESETS,
        },
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


@login_required
def menu_engineering_view(request: HttpRequest) -> HttpResponse:
    """Each dish of a menu family as a star, plowhorse, puzzle or dog (US50),
    how it moved against the period before, and the prices worth changing
    (US53).

    Defaults to 90 days: a month is a thin sample for a dish ordered twice a
    week.
    """
    restaurant = request.restaurant
    window = window_for(restaurant, request.GET, default="90d")
    groups = menu_engineering(restaurant, window.start, window.end)
    wanted = request.GET.get("group", "")
    group = next((g for g in groups if g.name == wanted), groups[0] if groups else None)

    moves, dogs, sim = [], [], {}
    if group:
        before_start, before_end = window.previous
        previous = next(
            (g for g in menu_engineering(restaurant, before_start, before_end)
             if g.name == group.name),
            None,
        )
        with_movement(group, previous)
        cap, step = restaurant.price_rise_cap, restaurant.menu_price_step
        moves = price_moves(group, days=window.days, cap_pct=cap, step=step)
        dogs = weakest_dogs(group, days=window.days)
        sim = {
            "days": window.days,
            "step": step,
            "cap": float(cap),
            "popularity": float(group.popularity_threshold),
            "target": float(group.target_cost_pct),
            "totalPortions": float(group.total_portions),
            "dishes": [
                {
                    "name": d.name,
                    "portions": float(d.portions),
                    "unitCost": float(d.unit_cost),
                    "costPct": float(d.cost_pct),
                    "mix": float(d.mix_pct),
                    "kind": d.kind,
                    "price": float(d.menu_price),
                    "factor": float(d.menu_factor),
                    "byGram": d.by_gram,
                }
                for d in sorted(group.dishes, key=lambda d: d.revenue, reverse=True)
                if d.menu_price > 0
            ],
        }
    months = window.days / 30
    return render(
        request,
        "analytics/menu_engineering.html",
        {
            "window": window,
            "presets": PRESETS,
            "groups": groups,
            "group": group,
            "moves": moves,
            "moves_total": sum((m.extra_per_month for m in moves), Decimal("0")),
            "weak_dogs": dogs,
            "cost_drift_month": (group.cost_drift / Decimal(months)) if group and months else None,
            "cap": restaurant.price_rise_cap,
            "sim": sim,
        },
    )


def _target(raw) -> Decimal | None:
    """A typed target cost %, or ``None`` (use the restaurant's) when blank or
    out of range."""
    try:
        value = Decimal(str(raw).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return value if 0 < value <= 100 else None


@login_required
def menu_families(request: HttpRequest) -> HttpResponse:
    """Which POS groups make up each menu family, and which are left out (US53)."""
    categories = list(
        Category.objects.filter(restaurant=request.restaurant).order_by("name")
    )
    if request.method == "POST":
        for category in categories:
            family = (request.POST.get(f"family-{category.pk}") or "").strip()[:60]
            category.menu_family = family or family_of(category)
            category.menu_hidden = request.POST.get(f"hidden-{category.pk}") == "on"
            category.target_cost_pct = _target(request.POST.get(f"target-{category.pk}"))
            category.save(update_fields=["menu_family", "menu_hidden", "target_cost_pct"])
        messages.success(request, gettext("Menu families saved."))
        return redirect("analytics:menu_engineering")
    rows = [
        {"category": c, "family": family_of(c), "hidden": is_hidden(c)} for c in categories
    ]
    return render(
        request,
        "analytics/menu_families.html",
        {
            "rows": rows,
            "families": sorted({row["family"] for row in rows}),
            "default_target": request.restaurant.target_cost_pct,
        },
    )


@login_required
def days_view(request: HttpRequest) -> HttpResponse:
    """Sales by weekday and how the holidays compare (US51).

    The whole history by default: holidays are a handful a year, and every
    one of them is a sample.
    """
    language = "es" if (request.LANGUAGE_CODE or "").startswith("es") else "en_US"
    window = None
    if any(request.GET.get(key) for key in ("period", "start", "end")):
        window = window_for(request.restaurant, request.GET)
    start, end = (window.start, window.end) if window else (None, None)
    days = open_days(request.restaurant, start, end, language)
    profile = weekday_profile(days)
    holidays_seen = (
        holiday_report(days, start or days[0].date, end or timezone.localdate(), language)
        if days
        else []
    )
    opened = [h for h in holidays_seen if h.opened and h.sales]
    monday_sales = [h.sales for h in opened if h.date.weekday() == 0]
    monday_avg = sum(monday_sales) / len(monday_sales) if monday_sales else None
    below, above = between_weekdays(monday_avg, profile)
    best = max((w for w in profile if w.avg_sales), key=lambda w: w.avg_sales, default=None)
    return render(
        request,
        "analytics/days.html",
        {
            "window": window,
            "presets": PRESETS,
            "days": days,
            "profile": profile,
            "best": best,
            "holidays": holidays_seen,
            "opened_count": len(opened),
            "reported_count": sum(1 for h in holidays_seen if h.reported),
            "monday_avg": monday_avg,
            "monday_count": len(monday_sales),
            "monday_below": below,
            "monday_above": above,
            "upcoming": upcoming_holidays(request.restaurant, language=language),
            "has_people": any(d.guests for d in days),
        },
    )
