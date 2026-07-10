"""Public marketing pages: landing (`/`) and help (`/help/`).

These are the only unauthenticated pages besides the allauth login/signup flow.
Authenticated visitors to the landing are sent straight to their dashboard so
returning users land on their data, not the marketing copy.
"""
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

CONTACT_EMAIL = "mdelapavalondono@gmail.com"


def landing(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("analytics:dashboard")
    return render(request, "pages/landing.html")


def help_page(request: HttpRequest) -> HttpResponse:
    return render(request, "pages/help.html", {"contact_email": CONTACT_EMAIL})
