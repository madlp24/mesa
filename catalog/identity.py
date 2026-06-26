"""Product identity resolution for POS imports.

The POS clave is not a reliable identity (codes get reassigned to new products,
and duplicates exist), so a product is identified by its NAME. This module
normalizes raw POS names, decides when two names are the same product (fusion)
or genuinely different (kept separate), and resolves each ``(clave, raw_name)``
to a canonical :class:`~catalog.models.Product`, recording the decision as a
:class:`~catalog.models.ProductAlias` so it is never re-guessed.

Resolution order, given a raw ``(clave, name)``:

1. Exact alias hit ``(clave, raw_name)`` -> its product.
2. Match an existing product by name (exact-normalized, same token set/word
   order, a close typo, or -- when the clave matches -- a prefix relation),
   provided the two are not a *distinct variant* (different number/age/size or a
   different serving group keep products separate).
3. Otherwise create a new product.

The matched product's category is updated to the latest report's group.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections import defaultdict

from .models import Category, Product, ProductAlias

# Standalone tokens that carry no identity (unit/serving markers). They are
# dropped before comparing names so "PUNTA DE ANCA*GR" == "PUNTA DE ANCA" and
# "NEGRONI X TRAGO" == "NEGRONI".
_NOISE_TOKENS = frozenset(
    {"GR", "G", "GRS", "ML", "L", "CC", "KG", "UND", "UN", "U", "X", "TRAGO"}
)
# Serving families: when two products share a name but their groups name a
# different serving, they are different products (bottle vs glass/trago).
_SERVING_KEYWORDS = ("BOTELLA", "COPA", "TRAGO", "MEDIA")
# Typo tolerance for same-first-token names with identical numbers.
_FUZZY_THRESHOLD = 0.86


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def normalize_name(raw: str) -> str:
    """Normalize a raw POS name for identity comparison.

    Uppercases, strips accents, drops ``*`` and punctuation, and removes
    standalone unit/serving marker tokens. ``"Punta de Anca*GR"`` and
    ``"PUNTA DE ANCA"`` both normalize to ``"PUNTA DE ANCA"``.
    """
    text = _strip_accents(str(raw)).upper()
    text = re.sub(r"[^0-9A-Z\s]", " ", text)  # "NO.21" -> "NO 21"
    tokens = [t for t in text.split() if t not in _NOISE_TOKENS]
    return " ".join(tokens)


def _tokens(normalized: str) -> list[str]:
    return normalized.split()


def _numbers(normalized: str) -> list[str]:
    """Sorted numeric tokens; distinguishes ages/sizes (18 vs 12, 505 vs 750)."""
    return sorted(re.findall(r"\d+", normalized))


def _serving_key(group_name: str) -> str:
    """The serving family a group names (BOTELLA/COPA/TRAGO...), or ''."""
    g = _strip_accents(str(group_name)).upper()
    for keyword in _SERVING_KEYWORDS:
        if keyword in g:
            return keyword
    return ""


def is_distinct_variant(norm_a: str, norm_b: str) -> bool:
    """True when two names are genuinely different products, never to be fused.

    The decisive signal is differing numeric tokens: different age/edition
    (Glenlivet 18 vs 12, No.21 vs No.1) or size (505ML vs 750ML). A number on
    one side and none on the other also counts (Don Julio 70 vs Silver).
    """
    return _numbers(norm_a) != _numbers(norm_b)


def _is_prefix(short: list[str], long: list[str]) -> bool:
    """True when token list ``short`` is a leading slice of ``long``."""
    return len(short) < len(long) and long[: len(short)] == short


def names_match(
    norm_a: str,
    norm_b: str,
    same_clave: bool = False,
) -> bool:
    """Decide whether two normalized names denote the same product.

    Fuses exact matches, word-order variants (same token set), close typos, and
    -- only when the clave is shared -- a prefix relation ("Negroni" ->
    "Negroni Tanqueray"). Distinct variants (see :func:`is_distinct_variant`)
    are never fused.
    """
    if not norm_a or not norm_b:
        return False
    if is_distinct_variant(norm_a, norm_b):
        return False
    if norm_a == norm_b:
        return True

    tokens_a, tokens_b = _tokens(norm_a), _tokens(norm_b)
    # Word order: same bag of tokens ("LIMONADA CEREZADA" == "CEREZADA LIMONADA").
    if sorted(tokens_a) == sorted(tokens_b):
        return True
    # Prefix relation requires the shared clave as corroboration, so unrelated
    # products that merely share a first word are not fused.
    if same_clave and (_is_prefix(tokens_a, tokens_b) or _is_prefix(tokens_b, tokens_a)):
        return True
    # Typos: very close strings with the same token count and first letter, so
    # minor misspellings fuse without pulling in unrelated names.
    if len(tokens_a) == len(tokens_b) and norm_a[0] == norm_b[0]:
        ratio = difflib.SequenceMatcher(None, norm_a, norm_b).ratio()
        if ratio >= _FUZZY_THRESHOLD:
            return True
    return False


class ProductResolver:
    """Resolves ``(clave, raw_name, group)`` to a canonical product.

    Loads the catalog and known aliases once, then resolves each POS line in
    memory, creating products/aliases as needed and keeping its caches current
    so a batch import stays consistent without re-querying per line.
    """

    def __init__(self, restaurant) -> None:
        self.restaurant = restaurant
        self._products: list[Product] = list(
            Product.objects.filter(restaurant=restaurant).select_related("category")
        )
        self._norm: dict[int, str] = {
            p.id: normalize_name(p.name) for p in self._products
        }
        self._claves: dict[int, set[str]] = defaultdict(set)
        for product in self._products:
            self._claves[product.id].add(product.sku)
        self._alias_index: dict[tuple[str, str], int] = {}
        for alias in ProductAlias.objects.filter(restaurant=restaurant):
            self._alias_index[(alias.pos_clave, alias.raw_name)] = alias.product_id
            self._claves[alias.product_id].add(alias.pos_clave)
        self._by_id: dict[int, Product] = {p.id: p for p in self._products}
        self._skus: set[str] = {p.sku for p in self._products}

    def resolve(
        self,
        clave: str,
        raw_name: str,
        group_name: str,
        unit_price,
        unit_cost,
    ) -> Product:
        clave = str(clave).strip()
        raw_name = str(raw_name).strip()

        product_id = self._alias_index.get((clave, raw_name))
        if product_id is not None:
            product = self._by_id[product_id]
            self._update_group(product, group_name)
            return product

        norm = normalize_name(raw_name)
        product = self._find_match(clave, norm, group_name)
        if product is None:
            product = self._create_product(
                clave, raw_name, norm, group_name, unit_price, unit_cost
            )
        else:
            self._update_group(product, group_name)
        self._record_alias(product, clave, raw_name, norm)
        return product

    def _find_match(self, clave: str, norm: str, group_name: str) -> Product | None:
        serving = _serving_key(group_name)
        for product in self._products:
            same_clave = clave in self._claves[product.id]
            if not names_match(norm, self._norm[product.id], same_clave=same_clave):
                continue
            # Same name but a different serving family => different product.
            other_serving = _serving_key(product.category.name)
            if serving and other_serving and serving != other_serving:
                continue
            return product
        return None

    def _update_group(self, product: Product, group_name: str) -> None:
        """Point the product at the latest report's group (last write wins)."""
        group_name = (group_name or "").strip()
        if not group_name or product.category.name == group_name:
            return
        category = self._get_or_create_category(group_name)
        product.category = category
        product.save(update_fields=["category"])

    def _create_product(
        self, clave, raw_name, norm, group_name, unit_price, unit_cost
    ) -> Product:
        category = self._get_or_create_category(group_name)
        product = Product.objects.create(
            restaurant=self.restaurant,
            sku=self._unique_sku(clave),
            name=raw_name,
            category=category,
            cost_price=unit_cost,
            sale_price=unit_price,
        )
        self._products.append(product)
        self._by_id[product.id] = product
        self._norm[product.id] = norm
        self._claves[product.id].add(clave)
        self._claves[product.id].add(product.sku)
        self._skus.add(product.sku)
        return product

    def _record_alias(self, product: Product, clave, raw_name, norm) -> None:
        ProductAlias.objects.get_or_create(
            restaurant=self.restaurant,
            pos_clave=clave,
            raw_name=raw_name,
            defaults={"product": product, "normalized_name": norm},
        )
        self._alias_index[(clave, raw_name)] = product.id
        self._claves[product.id].add(clave)

    def _unique_sku(self, clave: str) -> str:
        """A free SKU for a new product; the POS clave, or a suffixed variant.

        Duplicate claves are real in the source data, but ``Product.sku`` is
        unique, so collisions get a ``-2``, ``-3``... suffix. The original POS
        clave is still recorded on the alias.
        """
        clave = clave or "SIN-CLAVE"
        if clave not in self._skus:
            return clave
        suffix = 2
        while f"{clave}-{suffix}" in self._skus:
            suffix += 1
        return f"{clave}-{suffix}"

    def _get_or_create_category(self, group_name: str) -> Category:
        name = (group_name or "").strip() or "Sin categoría"
        category, _ = Category.objects.get_or_create(
            restaurant=self.restaurant, name=name
        )
        return category
