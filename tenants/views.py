"""Restaurant settings (US26)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from .forms import RestaurantSettingsForm


@login_required
def settings(request: HttpRequest) -> HttpResponse:
    """Let the owner rename their restaurant."""
    restaurant = request.restaurant
    if request.method == "POST":
        form = RestaurantSettingsForm(request.POST, instance=restaurant)
        if form.is_valid():
            form.save()
            messages.success(request, _("Restaurant settings saved."))
            return redirect("tenants:settings")
    else:
        form = RestaurantSettingsForm(instance=restaurant)
    return render(request, "tenants/settings.html", {"form": form})
