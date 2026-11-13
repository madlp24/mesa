"""Catalog views: product list/detail, identity management, supply costs, charts."""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, DecimalField, ExpressionWrapper, F, QuerySet, Sum
from django.db.models.functions import TruncDate
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from sales.models import SaleItem

from . import services
from .duplicates import find_possible_duplicates
from .models import Product, ProductAlias, RecipeLine, Supply
from .supplies import SupplyCostError, sync_costs

_REVENUE = ExpressionWrapper(
    F("unit_price") * F("quantity"),
    output_field=DecimalField(max_digits=14, decimal_places=2),
)
_MARGIN = ExpressionWrapper(
    (F("unit_price") - F("unit_cost")) * F("quantity"),
    output_field=DecimalField(max_digits=14, decimal_places=2),
)


def _date_range(request: HttpRequest) -> tuple:
    """Parse optional ?start=&end= (YYYY-MM-DD) query params; None when absent."""
    return (
        parse_date(request.GET.get("start", "") or ""),
        parse_date(request.GET.get("end", "") or ""),
    )


def _items_in_range(product: Product, start, end) -> QuerySet:
    items = SaleItem.objects.filter(product=product)
    if start:
        items = items.filter(sale__occurred_at__date__gte=start)
    if end:
        items = items.filter(sale__occurred_at__date__lte=end)
    return items


@login_required
def product_list(request: HttpRequest) -> HttpResponse:
    """Catalog management page: products with identity/merge controls."""
    products = (
        Product.objects.filter(restaurant=request.restaurant)
        .select_related("category")
        .annotate(
            alias_count=Count("aliases", distinct=True),
            units=Sum("sale_items__quantity"),
            revenue=Sum(
                ExpressionWrapper(
                    F("sale_items__unit_price") * F("sale_items__quantity"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            ),
        )
        .order_by("name")
    )
    return render(request, "catalog/product_list.html", {"products": products})


@login_required
@require_POST
def merge_products(request: HttpRequest) -> HttpResponse:
    """Two-step merge: confirm the selection, then merge into a canonical."""
    ids = request.POST.getlist("product_ids")
    selected = list(
        Product.objects.filter(
            restaurant=request.restaurant, pk__in=ids
        ).select_related("category")
    )
    if len(selected) < 2:
        messages.warning(request, _("Select at least two products to merge."))
        return redirect("catalog:product_list")

    canonical_id = request.POST.get("canonical")
    if not canonical_id:
        # Step 1: no canonical chosen yet -> show the confirmation page.
        return render(
            request,
            "catalog/merge_confirm.html",
            {"selected": selected, "product_ids": [p.pk for p in selected]},
        )

    # Step 2: perform the merge.
    by_id = {p.pk: p for p in selected}
    canonical = by_id.get(int(canonical_id))
    if canonical is None:
        messages.warning(request, _("Choose which product to keep."))
        return redirect("catalog:product_list")
    others = [p for p in selected if p.pk != canonical.pk]
    try:
        count = services.merge_products(request.restaurant, canonical, others)
    except services.IdentityError as exc:
        messages.error(request, str(exc))
        return redirect("catalog:product_list")
    messages.success(
        request,
        _("Merged %(count)d product(s) into “%(name)s”.")
        % {"count": count, "name": canonical.name},
    )
    return redirect("catalog:product_detail", pk=canonical.pk)


@login_required
@require_POST
def alias_action(request: HttpRequest, alias_id: int) -> HttpResponse:
    """Re-point an alias to another product, or split it into a new one."""
    alias = get_object_or_404(
        ProductAlias, pk=alias_id, restaurant=request.restaurant
    )
    source_pk = alias.product_id
    action = request.POST.get("action")
    try:
        if action == "split":
            product = services.split_alias(
                request.restaurant, alias, request.POST.get("new_name", "")
            )
            messages.success(
                request,
                _("Split “%(raw)s” into a new product.") % {"raw": alias.raw_name},
            )
            return redirect("catalog:product_detail", pk=product.pk)

        target = get_object_or_404(
            Product, pk=request.POST.get("target"), restaurant=request.restaurant
        )
        services.repoint_alias(request.restaurant, alias, target)
        messages.success(
            request,
            _("Moved “%(raw)s” to “%(name)s”.")
            % {"raw": alias.raw_name, "name": target.name},
        )
        return redirect("catalog:product_detail", pk=target.pk)
    except services.IdentityError as exc:
        messages.error(request, str(exc))
        return redirect("catalog:product_detail", pk=source_pk)


@login_required
def product_detail(request: HttpRequest, pk: int) -> HttpResponse:
    product = get_object_or_404(Product, pk=pk, restaurant=request.restaurant)
    start, end = _date_range(request)
    totals = _items_in_range(product, start, end).aggregate(
        units=Sum("quantity"),
        revenue=Sum(_REVENUE),
        margin=Sum(_MARGIN),
    )
    context = {
        "product": product,
        "units_sold": totals["units"] or 0,
        "total_revenue": totals["revenue"] or 0,
        "total_margin": totals["margin"] or 0,
        "start": start,
        "end": end,
        "aliases": product.aliases.order_by("pos_clave", "raw_name"),
        "other_products": Product.objects.filter(restaurant=request.restaurant)
        .exclude(pk=product.pk)
        .order_by("name"),
        "recipe": product.recipe.select_related("supply"),
        "recipe_cost": product.recipe_cost,
        "uncosted_supplies": product.uncosted_supplies,
        "supplies": Supply.objects.filter(restaurant=request.restaurant).order_by("name"),
    }
    return render(request, "catalog/product_detail.html", context)


@login_required
def product_sales_series(request: HttpRequest, pk: int) -> JsonResponse:
    """Return units sold per day for the product, as JSON for the line chart."""
    product = get_object_or_404(Product, pk=pk, restaurant=request.restaurant)
    start, end = _date_range(request)
    rows = (
        _items_in_range(product, start, end)
        .annotate(day=TruncDate("sale__occurred_at"))
        .values("day")
        .annotate(units=Sum("quantity"))
        .order_by("day")
    )
    return JsonResponse(
        {
            "labels": [row["day"].isoformat() for row in rows],
            "data": [row["units"] for row in rows],
        }
    )


@login_required
def duplicate_review(request: HttpRequest) -> HttpResponse:
    """Products that look like one dish split in two by a rename (US37)."""
    candidates = find_possible_duplicates(request.restaurant)
    return render(
        request, "catalog/duplicates.html", {"candidates": candidates}
    )


@login_required
@require_POST
def merge_pair(request: HttpRequest) -> HttpResponse:
    """Fold the newcomer into the product that carries the history."""
    keep = get_object_or_404(
        Product, pk=request.POST.get("keep"), restaurant=request.restaurant
    )
    merge = get_object_or_404(
        Product, pk=request.POST.get("merge"), restaurant=request.restaurant
    )
    try:
        services.merge_products(request.restaurant, keep, [merge])
    except services.IdentityError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            _("“%(merged)s” is now part of “%(kept)s”.")
            % {"merged": merge.name, "kept": keep.name},
        )
    return redirect("catalog:duplicates")


# --- supply costs from AutoFacturas (US45) --------------------------------


@login_required
def supply_list(request: HttpRequest) -> HttpResponse:
    """The insumos AutoFacturas costs, and the button that refreshes them."""
    supplies = (
        Supply.objects.filter(restaurant=request.restaurant)
        .annotate(used_by=Count("recipe_lines"))
        .order_by("group", "name")
    )
    return render(
        request,
        "catalog/supply_list.html",
        {
            "supplies": supplies,
            "uncosted": sum(1 for s in supplies if not s.is_costed),
            "unused": sum(1 for s in supplies if not s.used_by),
            "has_token": request.restaurant.has_autofacturas_token,
            "last_sync": max(
                (s.synced_at for s in supplies if s.synced_at), default=None
            ),
        },
    )


@login_required
@require_POST
def supply_sync(request: HttpRequest) -> HttpResponse:
    """Fetch the costs now and re-cost whatever the recipes allow."""
    try:
        summary = sync_costs(request.restaurant)
    except SupplyCostError as exc:
        messages.error(request, str(exc))
        return redirect("catalog:supplies")

    messages.success(
        request,
        _("%(seen)d supplies read (%(new)d new), %(recosted)d product(s) re-costed.")
        % {
            "seen": summary.supplies_seen,
            "new": summary.created,
            "recosted": len(summary.recosted),
        },
    )
    if summary.blocked:
        messages.warning(
            request,
            _("%(count)d product(s) kept their old cost: their recipe has a "
              "supply AutoFacturas could not cost.") % {"count": len(summary.blocked)},
        )
    return redirect("catalog:supplies")


@login_required
@require_POST
def recipe_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Add, change or remove one line of a product's recipe."""
    product = get_object_or_404(Product, pk=pk, restaurant=request.restaurant)
    action = request.POST.get("action", "add")

    if action == "remove":
        RecipeLine.objects.filter(
            pk=request.POST.get("line"), product=product
        ).delete()
        messages.success(request, _("Ingredient removed."))
    else:
        supply = Supply.objects.filter(
            pk=request.POST.get("supply"), restaurant=request.restaurant
        ).first()
        quantity = _positive_decimal(request.POST.get("quantity"))
        if supply is None or quantity is None:
            messages.error(request, _("Pick a supply and a quantity above zero."))
        else:
            RecipeLine.objects.update_or_create(
                product=product,
                supply=supply,
                defaults={"quantity": quantity, "note": request.POST.get("note", "")[:200]},
            )
            messages.success(request, _("Recipe updated."))

    # The cost only moves for a recipe that is complete; an incomplete one
    # leaves the POS cost standing rather than replacing it with a short sum.
    cost = product.recipe_cost
    if cost is not None:
        product.cost_price = Decimal(cost).quantize(Decimal("0.01"))
        product.save(update_fields=["cost_price"])
    return redirect("catalog:product_detail", pk=product.pk)


def _positive_decimal(raw) -> Decimal | None:
    try:
        value = Decimal(str(raw).replace(",", "."))
    except (InvalidOperation, AttributeError, TypeError):
        return None
    return value if value > 0 else None
