import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from .services import compute_kpis

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
