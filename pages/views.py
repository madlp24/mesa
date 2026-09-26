"""The pages at `/` and `/help/`.

`/` serves double duty: the marketing landing for visitors, and the home hub
for signed-in users. Help is public. These are the only unauthenticated pages
besides the allauth login/signup flow.
"""
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

CONTACT_EMAIL = "mdelapavalondono@gmail.com"


def landing(request: HttpRequest) -> HttpResponse:
    """`/` is the marketing landing for visitors and the hub for signed-in users.

    Signing in used to drop everyone on the sales dashboard, which is noise for
    someone who came to quote an event, so the hub simply asks where they want
    to go.
    """
    if request.user.is_authenticated:
        return render(request, "pages/home.html")
    return render(request, "pages/landing.html")


def help_page(request: HttpRequest) -> HttpResponse:
    return render(request, "pages/help.html", {"contact_email": CONTACT_EMAIL})
