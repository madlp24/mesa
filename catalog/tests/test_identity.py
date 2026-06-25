"""Tests for product identity resolution (US22)."""
from decimal import Decimal

import pytest

from catalog.identity import (
    ProductResolver,
    is_distinct_variant,
    names_match,
    normalize_name,
)
from catalog.models import Category, Product, ProductAlias

# --- normalize_name --------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Punta de Anca*GR", "PUNTA DE ANCA"),
        ("Café con Leche", "CAFE CON LECHE"),
        ("NEGRONI X TRAGO", "NEGRONI"),
        ("No.21", "NO 21"),
        ("  Arroz   Frito  ", "ARROZ FRITO"),
        ("Agua 505ML", "AGUA 505ML"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


# --- distinct variants (never fused) ---------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        ("GLENLIVET 18", "GLENLIVET 12"),
        ("NO 21", "NO 1"),
        ("DON JULIO 70", "DON JULIO SILVER"),
        ("AGUA 505ML", "AGUA 750ML"),
    ],
)
def test_distinct_variants_kept_separate(a, b):
    assert is_distinct_variant(a, b) is True
    assert names_match(a, b, same_clave=True) is False


# --- name matching / fusion ------------------------------------------------


def test_exact_and_word_order_match():
    assert names_match("AREPA DE CHOCLO", "AREPA DE CHOCLO")
    assert names_match("LIMONADA CEREZADA", "CEREZADA LIMONADA")


def test_prefix_match_requires_shared_clave():
    # "Negroni" -> "Negroni Tanqueray": only fused when the clave corroborates.
    assert names_match("NEGRONI", "NEGRONI TANQUERAY", same_clave=True)
    assert not names_match("NEGRONI", "NEGRONI TANQUERAY", same_clave=False)


def test_typo_match():
    assert names_match("TOMAHAWK", "TOMAHAWWK")


# --- ProductResolver (DB) --------------------------------------------------


@pytest.fixture
def resolver(db):
    return ProductResolver()


@pytest.mark.django_db
def test_resolver_creates_product_and_alias():
    product = ProductResolver().resolve(
        "03028", "Arepa de Choclo", "ACOMPAÑAMIENTOS", Decimal("10"), Decimal("3")
    )
    assert product.pk is not None
    assert product.sku == "03028"
    assert product.category.name == "ACOMPAÑAMIENTOS"
    alias = ProductAlias.objects.get(pos_clave="03028", raw_name="Arepa de Choclo")
    assert alias.product == product


@pytest.mark.django_db
def test_resolver_fuses_prefix_with_same_clave():
    r = ProductResolver()
    first = r.resolve("8100", "Negroni", "COCTELES", Decimal("20"), Decimal("6"))
    second = r.resolve("8100", "Negroni Tanqueray", "COCTELES", Decimal("22"), Decimal("7"))
    assert first == second
    assert Product.objects.count() == 1


@pytest.mark.django_db
def test_resolver_matches_by_name_despite_reassigned_clave():
    r = ProductResolver()
    first = r.resolve("8007", "Glenfiddich 12", "WHISKY", Decimal("30"), Decimal("10"))
    # Same product re-appears under a different (reassigned) clave: still one row.
    second = r.resolve("9001", "Glenfiddich 12", "WHISKY", Decimal("31"), Decimal("11"))
    assert first == second
    assert Product.objects.count() == 1


@pytest.mark.django_db
def test_resolver_keeps_distinct_ages_separate():
    r = ProductResolver()
    r.resolve("5001", "Glenlivet 18", "WHISKY", Decimal("40"), Decimal("15"))
    r.resolve("5002", "Glenlivet 12", "WHISKY", Decimal("30"), Decimal("10"))
    assert Product.objects.count() == 2


@pytest.mark.django_db
def test_resolver_keeps_bottle_and_glass_separate():
    r = ProductResolver()
    r.resolve("7001", "Macallan 12", "WHISKY BOTELLA", Decimal("300"), Decimal("100"))
    r.resolve("7002", "Macallan 12", "WHISKY COPA", Decimal("30"), Decimal("10"))
    assert Product.objects.count() == 2


@pytest.mark.django_db
def test_resolver_updates_group_on_match():
    r = ProductResolver()
    r.resolve("03021", "Arroz Frito", "ACOMPAÑAMIENTOS", Decimal("10"), Decimal("3"))
    product = r.resolve("03021", "Arroz Frito", "ENTRADAS", Decimal("10"), Decimal("3"))
    assert product.category.name == "ENTRADAS"
    assert Product.objects.count() == 1


@pytest.mark.django_db
def test_resolver_suffixes_sku_on_duplicate_clave():
    r = ProductResolver()
    r.resolve("8007", "Don Julio Silver", "TEQUILA", Decimal("25"), Decimal("8"))
    # Same clave reassigned to a genuinely different product (distinct name).
    other = r.resolve("8007", "Glenfiddich 12", "WHISKY", Decimal("30"), Decimal("10"))
    assert Product.objects.count() == 2
    assert other.sku == "8007-2"
    # Both POS identities are recorded against their resolved products.
    assert ProductAlias.objects.filter(pos_clave="8007").count() == 2


@pytest.mark.django_db
def test_alias_hit_short_circuits_resolution():
    r = ProductResolver()
    first = r.resolve("100", "Old Fashioned", "COCTELES", Decimal("20"), Decimal("6"))
    # A fresh resolver (reloads aliases) must reuse the recorded identity.
    again = ProductResolver().resolve(
        "100", "Old Fashioned", "COCTELES", Decimal("20"), Decimal("6")
    )
    assert again == first
    assert Category.objects.count() == 1
