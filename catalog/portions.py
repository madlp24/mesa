"""How much of a product one serving is (US50).

The POS reports cuts sold by weight in grams: 107,882 "units" of porterhouse
next to 974 picanhas sold as pieces. Counting them side by side makes any
ranking by popularity meaningless, so a gram-sold cut is turned into portions
of the size a guest eats -- the same 280 g the event quotes plan per guest
(``quotes.management.commands.seed_menu``).
"""
import re
from decimal import Decimal

GRAM_MARKERS = ("* GR", "*GR", " X GR", "POR GR", "/GR")
GRAMS_PER_PORTION = Decimal(280)


def sold_by_gram(product_name: str) -> bool:
    upper = (product_name or "").upper()
    return any(marker in upper for marker in GRAM_MARKERS)


def portions(quantity, product_name: str) -> Decimal:
    """Servings in ``quantity`` as the POS reports it for this product."""
    amount = Decimal(quantity or 0)
    return amount / GRAMS_PER_PORTION if sold_by_gram(product_name) else amount


#: No steak costs this little a unit: below it, the POS price is per gram.
_PER_GRAM_PRICE = Decimal(2000)
_GRAMS_IN_NAME = re.compile(r"\*\s*(\d{2,4})\s*G")


def grams_per_unit(product) -> tuple[Decimal | None, str]:
    """Grams in one unit the POS sells, and how Mesa knows (US57).

    ``"set"`` by the owner, ``"name"`` from a gram marker or ``*420GR`` in the
    name, ``"price"`` when the unit price can only be per gram, or
    ``(None, "missing")``: a portion whose weight nobody has said, which is left
    out of the kilos rather than guessed.
    """
    if product.unit_grams:
        return Decimal(product.unit_grams), "set"
    if sold_by_gram(product.name):
        return Decimal(1), "name"
    match = _GRAMS_IN_NAME.search((product.name or "").upper())
    if match:
        return Decimal(match.group(1)), "name"
    if product.sale_price and 0 < product.sale_price < _PER_GRAM_PRICE:
        return Decimal(1), "price"
    return None, "missing"
