from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.dateparse import parse_date

from .services import compute_kpis


def _date_range(request: HttpRequest) -> tuple:
    """Parse optional ?start=&end= (YYYY-MM-DD) query params; None when absent."""
    return (
        parse_date(request.GET.get("start", "") or ""),
        parse_date(request.GET.get("end", "") or ""),
    )


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    start, end = _date_range(request)
    context = {
        "kpis": compute_kpis(start, end),
        "start": start,
        "end": end,
    }
    return render(request, "analytics/dashboard.html", context)
