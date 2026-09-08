"""Restaurant settings, and letting other people into the restaurant."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .forms import RestaurantSettingsForm
from .models import Invitation, Membership
from .services import accept_invitation as accept


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
    return render(
        request,
        "tenants/settings.html",
        {
            "form": form,
            "members": Membership.objects.filter(restaurant=restaurant)
            .select_related("user")
            .order_by("created_at"),
            "invitations": Invitation.objects.filter(
                restaurant=restaurant, accepted_at__isnull=True
            ),
        },
    )


@login_required
@require_POST
def invite(request: HttpRequest) -> HttpResponse:
    """Create a link that puts someone into this restaurant."""
    invitation = Invitation.objects.create(
        restaurant=request.restaurant,
        email=request.POST.get("email", "").strip(),
        invited_by=request.user,
    )
    messages.success(
        request,
        _("Invitation ready. Copy the link and send it to %(who)s.")
        % {"who": invitation.email or _("them")},
    )
    return redirect("tenants:settings")


@login_required
@require_POST
def revoke_invitation(request: HttpRequest, pk: int) -> HttpResponse:
    invitation = get_object_or_404(
        Invitation, pk=pk, restaurant=request.restaurant, accepted_at__isnull=True
    )
    invitation.delete()
    messages.success(request, _("Invitation cancelled."))
    return redirect("tenants:settings")


@login_required
@require_POST
def remove_member(request: HttpRequest, pk: int) -> HttpResponse:
    """Take someone out of the restaurant. Never yourself: that locks the door
    from the inside and leaves the workspace with nobody who can open it."""
    membership = get_object_or_404(Membership, pk=pk, restaurant=request.restaurant)
    if membership.user_id == request.user.pk:
        messages.error(request, _("You cannot remove yourself."))
        return redirect("tenants:settings")

    name = membership.user.get_username()
    membership.delete()
    messages.success(request, _("%(name)s no longer has access.") % {"name": name})
    return redirect("tenants:settings")


def accept_invitation(request: HttpRequest, token: str) -> HttpResponse:
    """Land here from the link. Signing in first if need be."""
    invitation = Invitation.objects.filter(token=token).select_related("restaurant").first()

    if invitation is None or not invitation.is_open:
        return render(request, "tenants/invitation_invalid.html", status=404)

    if not request.user.is_authenticated:
        return render(request, "tenants/invitation_landing.html", {"invitation": invitation})

    restaurant = accept(invitation, request.user)
    messages.success(
        request, _("You are now working in %(name)s.") % {"name": restaurant.name}
    )
    return redirect("analytics:dashboard")
