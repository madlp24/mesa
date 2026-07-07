"""Catalog views: product list/detail, identity management, and chart endpoint."""
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
from .models import Product, ProductAlias

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
