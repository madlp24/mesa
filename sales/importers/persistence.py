from django.db import transaction

from catalog.identity import ProductResolver
from catalog.models import Product
from sales.models import Sale, SaleItem

from .canonical import CanonicalSale, CanonicalSaleItem


@transaction.atomic
def persist(canonical_sales: list[CanonicalSale], restaurant) -> dict:
    """Insert canonical sales for one restaurant, idempotent by external_id.

    Product identity is resolved by name through :class:`ProductResolver` for
    items that embed catalog hints (e.g. the PDF report); importers that carry
    only a SKU (e.g. the Excel importer) fall back to a direct SKU lookup. All
    rows are scoped to ``restaurant``.
    """
    new_count = 0
    item_count = 0
    skipped_count = 0
    resolver = ProductResolver(restaurant)
    products_by_sku = {
        p.sku: p for p in Product.objects.filter(restaurant=restaurant)
    }

    for cs in canonical_sales:
        if Sale.objects.filter(
            restaurant=restaurant, external_id=cs.external_id
        ).exists():
            skipped_count += 1
            continue
        sale = Sale.objects.create(
            restaurant=restaurant,
            external_id=cs.external_id,
            occurred_at=cs.occurred_at,
            total=cs.total,
            payment_method=cs.payment_method,
            server_name=cs.server_name,
            table_number=cs.table_number,
        )
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
            item_count += 1
        new_count += 1

    return {"new": new_count, "items": item_count, "skipped_duplicate": skipped_count}


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
