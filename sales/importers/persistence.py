from django.db import transaction

from catalog.models import Category, Product
from sales.models import Sale, SaleItem

from .canonical import CanonicalSale, CanonicalSaleItem

_DEFAULT_CATEGORY = "Sin categoría"


@transaction.atomic
def persist(canonical_sales: list[CanonicalSale]) -> dict:
    """Insert canonical sales into the database, idempotent by external_id."""
    new_count = 0
    item_count = 0
    skipped_count = 0
    products_by_sku = {p.sku: p for p in Product.objects.all()}

    for cs in canonical_sales:
        if Sale.objects.filter(external_id=cs.external_id).exists():
            skipped_count += 1
            continue
        sale = Sale.objects.create(
            external_id=cs.external_id,
            occurred_at=cs.occurred_at,
            total=cs.total,
            payment_method=cs.payment_method,
            server_name=cs.server_name,
            table_number=cs.table_number,
        )
        for item in cs.items:
            product = products_by_sku.get(item.product_sku)
            if product is None:
                product = _get_or_create_product(item)
                if product is None:
                    continue
                products_by_sku[item.product_sku] = product
            SaleItem.objects.create(
                sale=sale,
                product=product,
                quantity=item.quantity,
                unit_price=item.unit_price,
                unit_cost=item.unit_cost,
            )
            item_count += 1
        new_count += 1

    return {"new": new_count, "items": item_count, "skipped_duplicate": skipped_count}


def _get_or_create_product(item: CanonicalSaleItem) -> Product | None:
    """Create a Product (and its Category) from an item's catalog hints.

    Returns None when the item carries no product name, in which case the row
    references an unknown SKU and is skipped, preserving the prior behavior for
    importers that do not embed the catalog (e.g. the Excel importer).
    """
    if not item.product_name:
        return None
    category, _ = Category.objects.get_or_create(
        name=item.category_name or _DEFAULT_CATEGORY
    )
    return Product.objects.create(
        sku=item.product_sku,
        name=item.product_name,
        category=category,
        cost_price=item.unit_cost,
        sale_price=item.unit_price,
    )
