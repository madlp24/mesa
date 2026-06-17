from django.db import transaction

from catalog.models import Product
from sales.models import Sale, SaleItem

from .canonical import CanonicalSale


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
