"""Identity-management operations exposed to the UI (US29).

These correct mistakes made by the name-based resolver (``catalog.identity``):

* :func:`merge_products` fixes *over-separation* -- two products that are really
  the same are combined into one, moving all sales and POS aliases across.
* :func:`repoint_alias` / :func:`split_alias` fix *over-fusion* -- a single POS
  identity is moved out of a product onto another (existing or brand-new) one.

Every operation is scoped to a single ``restaurant`` and runs in a transaction.
Historical sales follow an alias by matching the POS clave against the sale's
``external_id`` (``"<date>:<clave>"``; see ``sales.importers.pdf_daily``), so a
split is a real re-assignment of past data, not just a future-import hint.
"""
from __future__ import annotations

from django.db import transaction

from sales.models import SaleItem

from .models import Product, ProductAlias


class IdentityError(ValueError):
    """A merge/re-point request that is invalid (e.g. cross-tenant or empty)."""


@transaction.atomic
def merge_products(restaurant, canonical: Product, others: list[Product]) -> int:
    """Merge ``others`` into ``canonical``; return the number merged away.

    Sale items and aliases of each merged product are reassigned to
    ``canonical`` and the merged product is deleted. All products must belong to
    ``restaurant`` and ``canonical`` must not be among ``others``.
    """
    if canonical.restaurant_id != restaurant.id:
        raise IdentityError("Canonical product belongs to another restaurant.")
    merged = [p for p in others if p.pk != canonical.pk]
    if not merged:
        raise IdentityError("Select at least one other product to merge.")
    for product in merged:
        if product.restaurant_id != restaurant.id:
            raise IdentityError("A selected product belongs to another restaurant.")

    for product in merged:
        SaleItem.objects.filter(product=product).update(product=canonical)
        ProductAlias.objects.filter(product=product).update(product=canonical)
        product.delete()
    return len(merged)


@transaction.atomic
def repoint_alias(restaurant, alias: ProductAlias, target: Product) -> int:
    """Move ``alias`` (and its historical sales) onto ``target``.

    Sales recorded for this alias's POS clave are reassigned from the alias's
    current product to ``target``; future imports of the identity resolve to
    ``target`` too. Returns the number of sale items moved.
    """
    if alias.restaurant_id != restaurant.id or target.restaurant_id != restaurant.id:
        raise IdentityError("Alias or target belongs to another restaurant.")
    if alias.product_id == target.pk:
        return 0

    moved = _move_clave_sales(restaurant, alias.pos_clave, alias.product, target)
    alias.product = target
    alias.save(update_fields=["product"])
    return moved


@transaction.atomic
def split_alias(restaurant, alias: ProductAlias, new_name: str = "") -> Product:
    """Split ``alias`` off into a brand-new product and re-point it there.

    The new product inherits the source product's category and prices; its name
    defaults to the alias's raw name. Returns the created product.
    """
    if alias.restaurant_id != restaurant.id:
        raise IdentityError("Alias belongs to another restaurant.")
    source = alias.product
    name = (new_name or alias.raw_name).strip() or alias.raw_name
    product = Product.objects.create(
        restaurant=restaurant,
        name=name,
        sku=_unique_sku(restaurant, alias.pos_clave),
        category=source.category,
        cost_price=source.cost_price,
        sale_price=source.sale_price,
    )
    repoint_alias(restaurant, alias, product)
    return product


def _move_clave_sales(
    restaurant, clave: str, source: Product, target: Product
) -> int:
    """Reassign ``source``'s sale items whose sale is for ``clave`` to ``target``."""
    return SaleItem.objects.filter(
        product=source,
        sale__restaurant=restaurant,
        sale__external_id__endswith=f":{clave}",
    ).update(product=target)


def _unique_sku(restaurant, clave: str) -> str:
    """A free SKU for a split-off product within ``restaurant``."""
    clave = (clave or "SIN-CLAVE").strip() or "SIN-CLAVE"
    taken = set(
        Product.objects.filter(restaurant=restaurant).values_list("sku", flat=True)
    )
    if clave not in taken:
        return clave
    suffix = 2
    while f"{clave}-{suffix}" in taken:
        suffix += 1
    return f"{clave}-{suffix}"
