"""Quote views: list, build from a budget, and keep the menu mapped to products."""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from catalog.models import Product

from . import services
from .models import Availability, Course, MenuItem, PricingMode, Quote, QuoteLine, Venue
from .pdf import render_quote_pdf

#: Margin to judge a quote against, taken from events this restaurant already billed.
TARGET_MARGIN = Decimal(60)

#: Lazy, because this dict is built once at import: gettext here would freeze
#: the labels in whatever language happened to be active at startup.
PROFILE_LABELS = {
    "cocktail": gettext_lazy("Standing cocktail"),
    "seated": gettext_lazy("Seated lunch or dinner"),
    "steak": gettext_lazy("Steak dinner"),
}


def _decimal(raw, fallback: str = "0") -> Decimal:
    try:
        return Decimal(str(raw).replace(",", "").strip() or fallback)
    except (InvalidOperation, ValueError):
        return Decimal(fallback)


def _next_number(restaurant) -> str:
    """Continue the CA-### series, so two quotes never share a number."""
    numbers = []
    for value in Quote.objects.filter(restaurant=restaurant).values_list("number", flat=True):
        tail = value.rsplit("-", 1)[-1]
        if tail.isdigit():
            numbers.append(int(tail))
    return f"CA-{max(numbers) + 1}" if numbers else "CA-119"


def _quote_context(quote: Quote) -> dict:
    lines = list(quote.lines.select_related("menu_item").all())
    by_course = []
    for value, label in Course.choices:
        course_lines = [line for line in lines if line.course == value]
        if course_lines:
            by_course.append({"label": label, "lines": course_lines})

    margin = quote.margin_pct
    if not quote.is_costed:
        verdict = "unknown"
    elif margin >= TARGET_MARGIN:
        verdict = "good"
    elif margin >= TARGET_MARGIN - 10:
        verdict = "fair"
    else:
        verdict = "poor"

    return {
        "quote": quote,
        "courses": by_course,
        "uncosted_lines": [line for line in lines if line.unit_cost is None],
        "margin_verdict": verdict,
        "target_margin": TARGET_MARGIN,
        "profiles": PROFILE_LABELS.items(),
    }


@login_required
def quote_list(request: HttpRequest) -> HttpResponse:
    quotes = Quote.objects.filter(restaurant=request.restaurant).prefetch_related("lines")
    return render(
        request,
        "quotes/quote_list.html",
        {
            "quotes": quotes,
            "unmapped_count": MenuItem.objects.filter(
                restaurant=request.restaurant, is_active=True, product__isnull=True
            ).count(),
            "menu_count": MenuItem.objects.filter(
                restaurant=request.restaurant, is_active=True
            ).count(),
        },
    )


@login_required
def quote_create(request: HttpRequest) -> HttpResponse:
    quote = Quote.objects.create(
        restaurant=request.restaurant,
        number=_next_number(request.restaurant),
        payment_terms=_("50% deposit, 50% on the event"),
    )
    return redirect("quotes:quote_detail", pk=quote.pk)


def _apply_event_fields(request: HttpRequest, quote: Quote) -> None:
    """Save whatever the event form is carrying.

    The page is one form with several buttons, so adding a dish or a charge
    posts the event fields along with it. Without this, everything typed above
    and not yet saved would be thrown away by the redirect.
    """
    if "client_name" not in request.POST:
        return

    quote.client_name = request.POST.get("client_name", "").strip()
    quote.concept = request.POST.get("concept", "").strip()
    quote.event_date = parse_date(request.POST.get("event_date", "") or "")
    quote.guests = max(1, int(_decimal(request.POST.get("guests"), "1")))
    quote.days = max(1, int(_decimal(request.POST.get("days"), "1")))
    quote.payment_terms = request.POST.get("payment_terms", "").strip()
    quote.notes = request.POST.get("notes", "").strip()
    quote.charges_tip = request.POST.get("charges_tip") == "on"
    quote.show_quantities = request.POST.get("show_quantities") == "on"
    quote.price_per_guest = _decimal(request.POST.get("price_per_guest"))
    quote.pricing_mode = (
        PricingMode.PER_GUEST
        if request.POST.get("pricing_mode") == PricingMode.PER_GUEST
        else PricingMode.CONSUMPTION
    )
    venue = request.POST.get("venue")
    if venue in Venue.values:
        quote.venue = venue
    quote.save()


@login_required
def quote_detail(request: HttpRequest, pk: int) -> HttpResponse:
    quote = get_object_or_404(Quote, pk=pk, restaurant=request.restaurant)

    if request.method == "POST":
        _apply_event_fields(request, quote)
        messages.success(request, _("Quote saved."))
        return redirect("quotes:quote_detail", pk=quote.pk)

    context = _quote_context(quote)
    context["services"] = MenuItem.objects.filter(
        restaurant=request.restaurant, course=Course.SERVICE, is_active=True
    ).order_by("name")
    context["venues"] = Venue.choices
    # Not "courses": that key already holds the quote's lines grouped by course,
    # and overwriting it emptied the menu table.
    context["course_choices"] = Course.choices
    # Only what can be served where this event happens.
    catalogo = (
        MenuItem.for_venue(request.restaurant, quote.is_off_site)
        .exclude(course=Course.SERVICE)
        .order_by("course", "name")
    )
    context["dish_groups"] = [
        (label, [i for i in catalogo if i.course == value])
        for value, label in Course.choices
        if any(i.course == value for i in catalogo)
    ]
    return render(request, "quotes/quote_detail.html", context)


@login_required
@require_POST
def quote_compose(request: HttpRequest, pk: int) -> HttpResponse:
    """Build the menu that fits a per-guest budget, then show what it leaves."""
    quote = get_object_or_404(Quote, pk=pk, restaurant=request.restaurant)

    _apply_event_fields(request, quote)
    budget = _decimal(request.POST.get("budget_per_guest"))
    guests = max(1, int(_decimal(request.POST.get("compose_guests"), "1")))
    profile = request.POST.get("profile", "seated")
    alcohol = request.POST.get("alcohol") == "on"
    offset = int(_decimal(request.POST.get("offset"), "0"))

    if budget <= 0:
        messages.error(request, _("Enter a price per guest first."))
        return redirect("quotes:quote_detail", pk=quote.pk)

    composition = services.compose(
        request.restaurant, budget, guests, profile=profile, alcohol=alcohol,
        offset=offset, off_site=quote.is_off_site,
    )
    if not composition.picks:
        floor = services.minimum_per_guest(
            request.restaurant, guests, profile, alcohol, quote.is_off_site
        )
        messages.error(
            request,
            _("That budget does not cover this kind of event. The floor is about %(floor)s per guest.")
            % {"floor": f"{floor:,.0f}"},
        )
        return redirect("quotes:quote_detail", pk=quote.pk)

    services.apply_composition(quote, composition)
    if not composition.fits:
        floor = services.minimum_per_guest(
            request.restaurant, guests, profile, alcohol, quote.is_off_site
        )
        messages.warning(
            request,
            _("The closest menu costs %(cost)s per guest. The floor for this event is about %(floor)s.")
            % {"cost": f"{composition.per_guest:,.0f}", "floor": f"{floor:,.0f}"},
        )
    else:
        messages.success(request, _("Menu composed."))
    return redirect("quotes:quote_detail", pk=quote.pk)


@login_required
def quote_pdf(request: HttpRequest, pk: int) -> HttpResponse:
    """The client-facing document. Cost and margin never appear in it."""
    quote = get_object_or_404(Quote, pk=pk, restaurant=request.restaurant)
    response = HttpResponse(render_quote_pdf(quote), content_type="application/pdf")
    filename = f"{quote.number}-{slugify(quote.client_name) or 'quote'}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_POST
def quote_add_charge(request: HttpRequest, pk: int) -> HttpResponse:
    """Add a charge billed on top of the per-guest price."""
    quote = get_object_or_404(Quote, pk=pk, restaurant=request.restaurant)
    _apply_event_fields(request, quote)
    name = request.POST.get("charge_name", "").strip()
    amount = _decimal(request.POST.get("charge_amount"))
    quantity = _decimal(request.POST.get("charge_quantity"), "1") or Decimal(1)

    # A negative amount is a discount. No amount at all is an inclusion: the
    # quote lists it without charging for it, the way the house always has.
    if not name:
        messages.error(request, _("A charge needs a name."))
        return redirect("quotes:quote_detail", pk=quote.pk)

    cost = _decimal(request.POST.get("charge_cost")) if request.POST.get("charge_cost") else None

    QuoteLine.objects.create(
        quote=quote, course=Course.SERVICE, name=name, quantity=quantity,
        unit_price=amount, unit_cost=cost if cost is not None else Decimal(0),
        add_on=True, position=900,
    )

    if request.POST.get("charge_remember") == "on":
        # The list of services builds itself out of what has been typed, so
        # nobody has to sit down and enter a catalogue before quoting.
        MenuItem.objects.update_or_create(
            restaurant=request.restaurant, name=name,
            defaults=dict(course=Course.SERVICE, price=amount, manual_cost=cost,
                          servings=Decimal(1), is_active=True),
        )

    messages.success(request, _("%(name)s added.") % {"name": name})
    return redirect("quotes:quote_detail", pk=quote.pk)


@login_required
@require_POST
def quote_add_service(request: HttpRequest, pk: int) -> HttpResponse:
    """Put a saved service on the quote: staff, a rental, the transport.

    The price and the cost come from the service itself, so whoever is quoting
    picks from a list instead of remembering figures.
    """
    quote = get_object_or_404(Quote, pk=pk, restaurant=request.restaurant)
    _apply_event_fields(request, quote)
    service = get_object_or_404(
        MenuItem, pk=request.POST.get("service"), restaurant=request.restaurant,
        course=Course.SERVICE,
    )
    quantity = _decimal(request.POST.get("service_quantity"), "1") or Decimal(1)

    QuoteLine.objects.create(
        quote=quote, menu_item=service, course=Course.SERVICE, name=service.name,
        description=service.description, quantity=quantity, unit_price=service.price,
        unit_cost=service.unit_cost, add_on=True, position=900,
    )
    messages.success(request, _("%(name)s added.") % {"name": service.name})
    return redirect("quotes:quote_detail", pk=quote.pk)


@login_required
@require_POST
def quote_add_dish(request: HttpRequest, pk: int) -> HttpResponse:
    """Put a dish on the quote, straight from the menu."""
    quote = get_object_or_404(Quote, pk=pk, restaurant=request.restaurant)
    _apply_event_fields(request, quote)
    dish = get_object_or_404(
        MenuItem, pk=request.POST.get("dish"), restaurant=request.restaurant
    )
    quantity = _decimal(request.POST.get("dish_quantity"), "1") or Decimal(1)

    line, created = QuoteLine.objects.get_or_create(
        quote=quote, menu_item=dish, add_on=False,
        defaults=dict(
            course=dish.course, name=dish.name, description=dish.description,
            quantity=quantity, unit_price=dish.price, unit_cost=dish.unit_cost,
            position=quote.lines.count(),
        ),
    )
    if not created:
        # Adding a dish already on the quote means more of it, not a second row.
        line.quantity += quantity
        line.save(update_fields=["quantity"])

    messages.success(request, _("%(name)s added.") % {"name": dish.name})
    return redirect("quotes:quote_detail", pk=quote.pk)


@login_required
@require_POST
def quote_add_custom_dish(request: HttpRequest, pk: int) -> HttpResponse:
    """A dish written for this quote alone.

    Corporate events are cooked off the menu: a morcilla, a chicharrón al
    barril, things the restaurant does not sell over the counter and has no
    reason to carry in its catalogue afterwards. Written here they stay on the
    quote; ticking "remember" is what puts them on the menu.
    """
    quote = get_object_or_404(Quote, pk=pk, restaurant=request.restaurant)
    _apply_event_fields(request, quote)
    name = request.POST.get("cd_name", "").strip()
    if not name:
        messages.error(request, _("A dish needs a name."))
        return redirect("quotes:quote_detail", pk=quote.pk)

    course = request.POST.get("cd_course")
    if course not in Course.values:
        course = Course.STARTERS
    description = request.POST.get("cd_description", "").strip()
    price = _decimal(request.POST.get("cd_price"))
    cost = _decimal(request.POST.get("cd_cost")) if request.POST.get("cd_cost") else None
    quantity = _decimal(request.POST.get("cd_quantity"), "1") or Decimal(1)

    remembered = None
    if request.POST.get("cd_remember") == "on":
        remembered, _created = MenuItem.objects.update_or_create(
            restaurant=request.restaurant, name=name,
            defaults=dict(description=description, course=course, price=price,
                          manual_cost=cost, servings=Decimal(1), is_active=True),
        )

    QuoteLine.objects.create(
        quote=quote, menu_item=remembered, course=course, name=name,
        description=description, quantity=quantity, unit_price=price,
        unit_cost=cost, position=quote.lines.count(),
    )
    messages.success(request, _("%(name)s added.") % {"name": name})
    return redirect("quotes:quote_detail", pk=quote.pk)


@login_required
@require_POST
def quote_update_lines(request: HttpRequest, pk: int) -> HttpResponse:
    """Save every quantity at once, so the page is one form and one button."""
    quote = get_object_or_404(Quote, pk=pk, restaurant=request.restaurant)
    _apply_event_fields(request, quote)
    for line in quote.lines.all():
        raw = request.POST.get(f"qty-{line.pk}")
        if raw is None:
            continue
        quantity = _decimal(raw, "0")
        if quantity <= 0:
            line.delete()
        elif quantity != line.quantity:
            line.quantity = quantity
            line.save(update_fields=["quantity"])
    messages.success(request, _("Quote updated."))
    return redirect("quotes:quote_detail", pk=quote.pk)


@login_required
@require_POST
def quote_remove_line(request: HttpRequest, pk: int, line_id: int) -> HttpResponse:
    quote = get_object_or_404(Quote, pk=pk, restaurant=request.restaurant)
    quote.lines.filter(pk=line_id).delete()
    return redirect("quotes:quote_detail", pk=quote.pk)


@login_required
def menu_list(request: HttpRequest) -> HttpResponse:
    """The quoting menu, and which items still have no product behind them."""
    items = (
        MenuItem.objects.filter(restaurant=request.restaurant)
        .select_related("product")
        .order_by("course", "name")
    )
    return render(
        request,
        "quotes/menu_list.html",
        {
            "items": items,
            "products": Product.objects.filter(
                restaurant=request.restaurant, is_active=True
            ).order_by("name"),
            "availabilities": Availability.choices,
            "unmapped_count": sum(1 for item in items if not item.is_mapped and item.is_active),
        },
    )


@login_required
@require_POST
def menu_item_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Point a menu item at the product it is served from, and price it."""
    item = get_object_or_404(MenuItem, pk=pk, restaurant=request.restaurant)

    product_id = request.POST.get("product") or ""
    if product_id:
        item.product = get_object_or_404(Product, pk=product_id, restaurant=request.restaurant)
    else:
        item.product = None

    item.name = request.POST.get("name", item.name).strip() or item.name
    item.description = request.POST.get("description", item.description).strip()
    item.course = request.POST.get("course", item.course)
    item.price = _decimal(request.POST.get("price"), str(item.price))
    item.servings = _decimal(request.POST.get("servings"), "1") or Decimal(1)
    item.product_units = _decimal(request.POST.get("product_units"), "1") or Decimal(1)
    raw_cost = (request.POST.get("manual_cost") or "").strip()
    item.manual_cost = _decimal(raw_cost) if raw_cost else None
    availability = request.POST.get("availability")
    if availability in Availability.values:
        item.availability = availability
    item.is_active = request.POST.get("is_active") == "on"
    item.save()

    messages.success(request, _("%(name)s updated.") % {"name": item.name})
    return redirect("quotes:menu_list")
