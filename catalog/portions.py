"""How much of a product one serving is (US50).

The POS reports cuts sold by weight in grams: 107,882 "units" of porterhouse
next to 974 picanhas sold as pieces. Counting them side by side makes any
ranking by popularity meaningless, so a gram-sold cut is turned into portions
of the size a guest eats -- the same 280 g the event quotes plan per guest
(``quotes.management.commands.seed_menu``).
"""
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
