from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _

from .engine import build_report
from .exports import report_pdf, report_workbook
from .forms import AlertSettingsForm
from .models import AlertSettings


def _report(request: HttpRequest):
    """The newest period, or one ending on ``?as_of=`` to read a past week."""
    as_of = parse_date(request.GET.get("as_of", "") or "")
    return build_report(request.restaurant, as_of=as_of)


@login_required
def report(request: HttpRequest) -> HttpResponse:
    """What lost profitability and what jumped in the newest period (US54)."""
    return render(
        request, "alerts/report.html",
        {"report": _report(request), "as_of": request.GET.get("as_of", "")},
    )


@login_required
def settings(request: HttpRequest) -> HttpResponse:
    instance = AlertSettings.for_restaurant(request.restaurant)
    form = AlertSettingsForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Alert settings saved."))
        return redirect("alerts:report")
    return render(request, "alerts/settings.html", {"form": form})


def _download(content: bytes, content_type: str, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def export_xlsx(request: HttpRequest) -> HttpResponse:
    data = _report(request)
    if data is None:
        return redirect("alerts:report")
    return _download(
        report_workbook(data),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        f"alertas-{data.current.end.isoformat()}.xlsx",
    )


@login_required
def export_pdf(request: HttpRequest) -> HttpResponse:
    data = _report(request)
    if data is None:
        return redirect("alerts:report")
    return _download(
        report_pdf(data, request.restaurant.name),
        "application/pdf",
        f"alertas-{data.current.end.isoformat()}.pdf",
    )
