"""Tests for UI product-identity management: list, merge, re-point, split (US29)."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.urls import reverse

from catalog import services
from catalog.models import Category, Product, ProductAlias
from sales.models import Sale, SaleItem
from tenants.models import Restaurant


@pytest.fixture
def category(restaurant):
    return Category.objects.create(restaurant=restaurant, name="Whisky")


def _product(restaurant, category, name, sku):
    return Product.objects.create(
        restaurant=restaurant,
        name=name,
        sku=sku,
        category=category,
        cost_price=Decimal("2.00"),
        sale_price=Decimal("8.00"),
    )


def _alias(restaurant, product, clave, raw_name):
    return ProductAlias.objects.create(
        restaurant=restaurant,
        product=product,
        pos_clave=clave,
        raw_name=raw_name,
        normalized_name=raw_name.upper(),
    )


def _sale_item(restaurant, product, external_id, day, qty):
    sale = Sale.objects.create(
        restaurant=restaurant,
        external_id=external_id,
        occurred_at=datetime(2026, 1, day, 12, tzinfo=timezone.utc),
        total=Decimal("0.00"),
    )
    return SaleItem.objects.create(
        sale=sale,
        product=product,
        quantity=qty,
        unit_price=Decimal("8.00"),
        unit_cost=Decimal("2.00"),
    )


# --- product list ----------------------------------------------------------


@pytest.mark.django_db
def test_product_list_requires_authentication(client):
    response = client.get(reverse("catalog:product_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_product_list_scopes_and_annotates(logged_client, restaurant, category):
    a = _product(restaurant, category, "Buchanans", "B1")
    _alias(restaurant, a, "B1", "BUCHANANS")
    _sale_item(restaurant, a, "2026-01-10:B1", 10, 3)
    # Another tenant's product must not leak in.
    other = Restaurant.objects.create(name="Other", slug="other")
    other_cat = Category.objects.create(restaurant=other, name="Whisky")
    _product(other, other_cat, "Hidden", "H1")

    response = logged_client.get(reverse("catalog:product_list"))
    assert response.status_code == 200
    products = list(response.context["products"])
    assert [p.name for p in products] == ["Buchanans"]
    assert products[0].alias_count == 1
    assert products[0].units == 3


# --- merge -----------------------------------------------------------------


@pytest.mark.django_db
def test_merge_shows_confirmation_before_acting(logged_client, restaurant, category):
    a = _product(restaurant, category, "Negroni", "N1")
    b = _product(restaurant, category, "Negroni Tanqueray", "N2")

    response = logged_client.post(
        reverse("catalog:merge_products"), {"product_ids": [a.pk, b.pk]}
    )
    assert response.status_code == 200
    assert "catalog/merge_confirm.html" in [t.name for t in response.templates]
    # Nothing merged yet.
    assert Product.objects.filter(restaurant=restaurant).count() == 2


@pytest.mark.django_db
def test_merge_moves_sales_and_aliases_then_deletes(logged_client, restaurant, category):
    keep = _product(restaurant, category, "Negroni", "N1")
    gone = _product(restaurant, category, "Negroni Tanqueray", "N2")
    _alias(restaurant, gone, "N2", "NEGRONI TANQUERAY")
    _sale_item(restaurant, gone, "2026-01-10:N2", 10, 4)

    response = logged_client.post(
        reverse("catalog:merge_products"),
        {"product_ids": [keep.pk, gone.pk], "canonical": keep.pk},
    )
    assert response.status_code == 302
    assert not Product.objects.filter(pk=gone.pk).exists()
    assert SaleItem.objects.filter(product=keep).count() == 1
    assert ProductAlias.objects.filter(product=keep, pos_clave="N2").exists()


@pytest.mark.django_db
def test_merge_rejects_cross_tenant_product(restaurant):
    other = Restaurant.objects.create(name="Other", slug="other")
    cat_a = Category.objects.create(restaurant=restaurant, name="Whisky")
    cat_b = Category.objects.create(restaurant=other, name="Whisky")
    keep = _product(restaurant, cat_a, "Mine", "M1")
    foreign = _product(other, cat_b, "Theirs", "T1")

    with pytest.raises(services.IdentityError):
        services.merge_products(restaurant, keep, [foreign])
    assert Product.objects.filter(pk=foreign.pk).exists()


# --- re-point / split ------------------------------------------------------


@pytest.mark.django_db
def test_repoint_alias_moves_alias_and_clave_sales(logged_client, restaurant, category):
    src = _product(restaurant, category, "Fused", "F1")
    dst = _product(restaurant, category, "Correct", "C1")
    alias = _alias(restaurant, src, "F1", "CORRECT ITEM")
    mine = _sale_item(restaurant, src, "2026-01-10:F1", 10, 2)
    # A different clave on the same source must stay put.
    stays = _sale_item(restaurant, src, "2026-01-10:F9", 10, 5)

    response = logged_client.post(
        reverse("catalog:alias_action", args=[alias.pk]),
        {"action": "move", "target": dst.pk},
    )
    assert response.status_code == 302
    alias.refresh_from_db()
    mine.refresh_from_db()
    stays.refresh_from_db()
    assert alias.product_id == dst.pk
    assert mine.product_id == dst.pk
    assert stays.product_id == src.pk


@pytest.mark.django_db
def test_split_alias_creates_new_product_with_its_sales(logged_client, restaurant, category):
    src = _product(restaurant, category, "Two In One", "X1")
    alias = _alias(restaurant, src, "X2", "SECOND ITEM")
    item = _sale_item(restaurant, src, "2026-01-10:X2", 10, 7)

    response = logged_client.post(
        reverse("catalog:alias_action", args=[alias.pk]),
        {"action": "split", "new_name": "Second Item"},
    )
    assert response.status_code == 302
    new = Product.objects.get(restaurant=restaurant, name="Second Item")
    alias.refresh_from_db()
    item.refresh_from_db()
    assert alias.product_id == new.pk
    assert item.product_id == new.pk
    assert new.sku == "X2"


@pytest.mark.django_db
def test_detail_renders_alias_section(logged_client, restaurant, category):
    product = _product(restaurant, category, "Alpha", "A1")
    _product(restaurant, category, "Beta", "B1")  # a move target
    _alias(restaurant, product, "A1", "ALPHA")

    response = logged_client.get(
        reverse("catalog:product_detail", args=[product.pk])
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "ALPHA" in body
    assert reverse("catalog:alias_action", args=[product.aliases.first().pk]) in body
    assert "Beta" in body  # move-target dropdown option


@pytest.mark.django_db
def test_split_unique_sku_when_clave_taken(restaurant, category):
    _product(restaurant, category, "Existing", "DUP")
    src = _product(restaurant, category, "Host", "H1")
    alias = _alias(restaurant, src, "DUP", "SPLIT ME")

    new = services.split_alias(restaurant, alias)
    assert new.sku == "DUP-2"
    assert new.name == "SPLIT ME"
