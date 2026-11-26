"""The pages at `/` and `/help/`.

`/` serves double duty: the marketing landing for visitors, and the home hub
for signed-in users. Help is public. These are the only unauthenticated pages
besides the allauth login/signup flow.
"""
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

CONTACT_EMAIL = "mdelapavalondono@gmail.com"


def landing(request: HttpRequest) -> HttpResponse:
    """`/` is the marketing landing for visitors; signed-in users go to the overview.

    Signed-in users used to land on a hub of eight cards asking where to go.
    With every section always visible in the side navigation (US49) that page
    was one more click before anything useful, so the overview opens instead.
    """
    if request.user.is_authenticated:
        return redirect("analytics:dashboard")
    return render(request, "pages/landing.html")


def help_page(request: HttpRequest) -> HttpResponse:
    return render(request, "pages/help.html", {"contact_email": CONTACT_EMAIL})
