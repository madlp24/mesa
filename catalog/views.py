"""Catalog views: product detail page and its sales-series chart endpoint."""
from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, ExpressionWrapper, F, QuerySet, Sum
from django.db.models.functions import TruncDate
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.dateparse import parse_date

from sales.models import SaleItem

from .models import Product

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
