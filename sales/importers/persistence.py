import datetime
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from catalog.identity import ProductResolver
from catalog.models import Product
from catalog.pricing import refresh_product_prices
from sales.models import Sale, SaleItem

from .canonical import CanonicalSale, CanonicalSaleItem


@transaction.atomic
def persist(canonical_sales: list[CanonicalSale], restaurant, import_batch=None) -> dict:
    """Insert canonical sales for one restaurant, keyed by external_id.

    Product identity is resolved by name through :class:`ProductResolver` for
    items that embed catalog hints (e.g. the PDF report); importers that carry
    only a SKU (e.g. the Excel importer) fall back to a direct SKU lookup. All
    rows are scoped to ``restaurant`` and tagged with ``import_batch`` (when
    given) so the import can be reviewed and undone later.

    A sale already stored with the same figures is a duplicate. One stored with
    *different* figures is corrected in place (US48): the usual cause is a daily
    report printed before the day closed and imported, then the full report
    imported later -- skipping it left the day partial for good. The correction
    keeps the sale's original batch and is not undone by undoing this one; the
    partial figures are not kept.

    An older partial copy imported after the full one must not shrink the day,
    so corrections are applied a day at a time and only when this file's total
    over that day's stored sales is at least what is stored. Otherwise the
    stored sales are kept and counted as ``older_copy``.

    Every product the import touched is then pointed at the cost and price of
    its newest sale day, so the catalog follows the POS instead of keeping the
    figures from the day the product first appeared.
    """
    new_count = 0
    item_count = 0
    skipped_count = 0
    touched: set[int] = set()
    resolver = ProductResolver(restaurant)
    products_by_sku = {
        p.sku: p for p in Product.objects.filter(restaurant=restaurant)
    }
    stored = {
        sale.external_id: sale
        for sale in Sale.objects.filter(
            restaurant=restaurant,
            external_id__in={cs.external_id for cs in canonical_sales},
        ).prefetch_related("items")
    }
    seen: set[str] = set()
    pending: dict[datetime.date, list[tuple[Sale, CanonicalSale]]] = defaultdict(list)
    file_total: dict[datetime.date, Decimal] = defaultdict(Decimal)
    stored_total: dict[datetime.date, Decimal] = defaultdict(Decimal)

    for cs in canonical_sales:
        if cs.external_id in seen:
            skipped_count += 1  # repeated within the file itself
            continue
        seen.add(cs.external_id)

        sale = stored.get(cs.external_id)
        if sale is not None:
            day = _day(cs.occurred_at)
            file_total[day] += cs.total
            stored_total[day] += sale.total
            if _same_figures(sale, cs):
                skipped_count += 1
            else:
                pending[day].append((sale, cs))
            continue

        sale = Sale.objects.create(
            restaurant=restaurant,
            import_batch=import_batch,
            external_id=cs.external_id,
            occurred_at=cs.occurred_at,
            total=cs.total,
            payment_method=cs.payment_method,
            server_name=cs.server_name,
            table_number=cs.table_number,
        )
        item_count += _write_items(sale, cs, resolver, products_by_sku, touched)
        new_count += 1

    corrected_count = 0
    older_count = 0
    for day, corrections in pending.items():
        if file_total[day] < stored_total[day]:
            older_count += len(corrections)
            continue
        for sale, cs in corrections:
            touched.update(item.product_id for item in sale.items.all())
            sale.items.all().delete()
            sale.total = cs.total
            sale.payment_method = cs.payment_method
            sale.server_name = cs.server_name
            sale.table_number = cs.table_number
            sale.save(
                update_fields=["total", "payment_method", "server_name", "table_number"]
            )
            _write_items(sale, cs, resolver, products_by_sku, touched)
            corrected_count += 1

    refresh_product_prices(restaurant, touched)
    return {
        "new": new_count,
        "items": item_count,
        "skipped_duplicate": skipped_count,
        "corrected": corrected_count,
        "older_copy": older_count,
    }


def _day(moment: datetime.datetime) -> datetime.date:
    if timezone.is_aware(moment):
        return timezone.localtime(moment).date()
    return moment.date()


def _same_figures(sale: Sale, cs: CanonicalSale) -> bool:
    """Whether a stored sale already carries what the file says.

    Compared on the figures alone -- quantity, price and cost of each line, and
    the total -- so a duplicate is recognised without resolving its products
    (which would also re-point their category at an old report's group).
    Money is compared to the cent, as stored: a file carrying 4166.666667
    is the same sale as the 4166.67 it was saved as.
    """
    if _cents(sale.total) != _cents(cs.total):
        return False
    stored_lines = sorted(
        (item.quantity, _cents(item.unit_price), _cents(item.unit_cost))
        for item in sale.items.all()
    )
    file_lines = sorted(
        (item.quantity, _cents(item.unit_price), _cents(item.unit_cost))
        for item in cs.items
    )
    return stored_lines == file_lines


def _cents(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _write_items(sale, cs, resolver, products_by_sku, touched: set[int]) -> int:
    """Create the sale's lines from the file; return how many were written."""
    written = 0
    for item in cs.items:
        product = _resolve_product(item, resolver, products_by_sku)
        if product is None:
            continue
        SaleItem.objects.create(
            sale=sale,
            product=product,
            quantity=item.quantity,
            unit_price=item.unit_price,
            unit_cost=item.unit_cost,
        )
        written += 1
        touched.add(product.pk)
    return written


def _resolve_product(
    item: CanonicalSaleItem,
    resolver: ProductResolver,
    products_by_sku: dict,
) -> Product | None:
    """Resolve an item to a canonical product.

    With a product name (catalog-embedded report) identity is resolved by name
    via the resolver; otherwise the item only references a SKU and is matched
    directly, preserving prior behavior for importers that do not embed a
    catalog (the row is skipped when the SKU is unknown).
    """
    if item.product_name:
        return resolver.resolve(
            clave=item.product_sku,
            raw_name=item.product_name,
            group_name=item.category_name,
            unit_price=item.unit_price,
            unit_cost=item.unit_cost,
        )
    return products_by_sku.get(item.product_sku)
