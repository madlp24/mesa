"""Spotting a dish renamed in the POS (US37), using the real cases from Jun/Jul 2026."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.urls import reverse

from catalog.duplicates import find_possible_duplicates
from catalog.models import Category, Product
from sales.models import Sale, SaleItem


def _sold(restaurant, name, group, months, units=10, sku=None):
    """A product sold in the given (year, month) pairs."""
    category, _ = Category.objects.get_or_create(restaurant=restaurant, name=group)
    product = Product.objects.create(
        restaurant=restaurant, name=name, sku=sku or name[:20],
        category=category, cost_price=Decimal("1"), sale_price=Decimal("5"),
    )
    for year, month in months:
        sale = Sale.objects.create(
            restaurant=restaurant, external_id=f"{year}-{month:02d}-01:{product.sku}",
            occurred_at=datetime(year, month, 1, 12, tzinfo=timezone.utc),
            total=Decimal("5"),
        )
        SaleItem.objects.create(
            sale=sale, product=product, quantity=units,
            unit_price=Decimal("5"), unit_cost=Decimal("1"),
        )
    return product


@pytest.mark.django_db
def test_detects_a_rename(restaurant):
    """The real one: the old row dies in May, the new is born in June."""
    old = _sold(restaurant, "EXTRA DE AGUACATE", "ACOMPAÑAMIENTOS",
                [(2026, 4), (2026, 5)], sku="A1")
    new = _sold(restaurant, "EXTRA AGUACATE", "ACOMPAÑAMIENTOS",
                [(2026, 6), (2026, 7)], sku="A2")

    found = find_possible_duplicates(restaurant)

    assert len(found) == 1
    assert found[0].keep == old      # the longer history survives
    assert found[0].merge == new


@pytest.mark.django_db
def test_glass_is_not_the_bottle(restaurant):
    """COPA LOUIS LATOUR (x trago) is not LOUIS LATOUR (x botella)."""
    _sold(restaurant, "COPA LOUIS LATOUR", "VINOS Y ESPUMOSOS X TRAGO",
          [(2026, 6)], sku="V1")
    _sold(restaurant, "LOUIS LATOUR", "VINOS Y ESPUMOSOS X BOTELLA",
          [(2026, 4)], sku="V2")

    assert find_possible_duplicates(restaurant) == []


@pytest.mark.django_db
def test_products_that_sell_at_the_same_time_coexist(restaurant):
    """EL ENEMIGO and EL ENEMIGO CHENIN were both sold in June -- different wines."""
    _sold(restaurant, "EL ENEMIGO", "VINOS Y ESPUMOSOS X BOTELLA",
          [(2026, 5), (2026, 6)], sku="W1")
    _sold(restaurant, "EL ENEMIGO CHENIN", "VINOS Y ESPUMOSOS X BOTELLA",
          [(2026, 6)], sku="W2")

    assert find_possible_duplicates(restaurant) == []


@pytest.mark.django_db
def test_unrelated_names_are_not_paired(restaurant):
    _sold(restaurant, "POSTRE DE LIMON", "POSTRES", [(2026, 4)], sku="P1")
    _sold(restaurant, "POSTRE DE MANGO", "POSTRES", [(2026, 6)], sku="P2")

    assert find_possible_duplicates(restaurant) == []


@pytest.mark.django_db
def test_closest_false_positive_stays_out(restaurant):
    """Two Garzon wines score 0.76 -- the highest any different pair reached."""
    _sold(restaurant, "GARZON RESERVA", "VINOS Y ESPUMOSOS X BOTELLA",
          [(2026, 5)], sku="G1")
    _sold(restaurant, "GARZON MARSELAN", "VINOS Y ESPUMOSOS X BOTELLA",
          [(2026, 7)], sku="G2")

    assert find_possible_duplicates(restaurant) == []


@pytest.mark.django_db
def test_two_ages_of_the_same_whisky_are_different(restaurant):
    """Found on the real catalog: 0.93 similar, but 12 years is not 15."""
    _sold(restaurant, "GLENFIDDICH 12 X TRAGO", "DESTILADOS X TRAGO",
          [(2026, 5)], sku="D1")
    _sold(restaurant, "GLENFIDDICH 15 X TRAGO", "DESTILADOS X TRAGO",
          [(2026, 7)], sku="D2")

    assert find_possible_duplicates(restaurant) == []


@pytest.mark.django_db
def test_two_vineyards_of_the_same_label_are_different(restaurant):
    """Also from the real catalog: each name carries a vineyard of its own."""
    _sold(restaurant, "CATENA APELLATION SAN CARLOS", "VINOS Y ESPUMOSOS X BOTELLA",
          [(2026, 5)], sku="C1")
    _sold(restaurant, "CATENA APELLATION VISTA FLORES", "VINOS Y ESPUMOSOS X BOTELLA",
          [(2026, 7)], sku="C2")

    assert find_possible_duplicates(restaurant) == []


@pytest.mark.django_db
def test_a_spelled_out_size_is_still_a_rename(restaurant):
    """The POS started writing the size: same water, new name."""
    _sold(restaurant, "ACQUA PANNA", "LIMONADAS, SODAS Y AGUA", [(2026, 5)], sku="S1")
    _sold(restaurant, "ACQUA PANNA * 505 ML", "LIMONADAS, SODAS Y AGUA",
          [(2026, 7)], sku="S2")

    assert len(find_possible_duplicates(restaurant)) == 1


@pytest.mark.django_db
def test_page_requires_authentication(client):
    response = client.get(reverse("catalog:duplicates"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_page_lists_the_pair(logged_client, restaurant):
    _sold(restaurant, "EXTRA DE AGUACATE", "ACOMPAÑAMIENTOS", [(2026, 5)], sku="A1")
    _sold(restaurant, "EXTRA AGUACATE", "ACOMPAÑAMIENTOS", [(2026, 6)], sku="A2")

    response = logged_client.get(reverse("catalog:duplicates"))

    assert response.status_code == 200
    assert len(response.context["candidates"]) == 1


@pytest.mark.django_db
def test_merging_keeps_the_history_and_moves_the_sales(logged_client, restaurant):
    old = _sold(restaurant, "EXTRA DE AGUACATE", "ACOMPAÑAMIENTOS",
                [(2026, 5)], units=6, sku="A1")
    new = _sold(restaurant, "EXTRA AGUACATE", "ACOMPAÑAMIENTOS",
                [(2026, 6)], units=7, sku="A2")

    response = logged_client.post(
        reverse("catalog:merge_pair"), {"keep": old.pk, "merge": new.pk}
    )

    assert response.status_code == 302
    assert not Product.objects.filter(pk=new.pk).exists()
    # Both months now hang off the surviving product.
    assert SaleItem.objects.filter(product=old).count() == 2
