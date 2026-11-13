"""Tests for the quote margin read off today's costs, and the minimum (US46)."""
from decimal import Decimal

import pytest
from django.urls import reverse

from catalog.models import Category, Product, RecipeLine, Supply
from quotes.models import Course, MenuItem, PricingMode, Quote, QuoteLine


@pytest.fixture
def dish(restaurant):
    """A menu item whose product is costed by a one-ingredient recipe."""
    category = Category.objects.create(restaurant=restaurant, name="Carnes")
    product = Product.objects.create(
        restaurant=restaurant, name="LOMO", sku="1", category=category,
        cost_price=Decimal("7000.00"), sale_price=Decimal("40000.00"),
    )
    supply = Supply.objects.create(
        restaurant=restaurant, clave="LOM-01", name="LOMO FINO", unit="g",
        unit_cost=Decimal("50.0000"),
    )
    RecipeLine.objects.create(product=product, supply=supply, quantity=Decimal("200"))
    item = MenuItem.objects.create(
        restaurant=restaurant, name="Lomo al grill", course=Course.MAINS,
        price=Decimal("48000"), product=product, product_units=Decimal("1"),
    )
    return item, product, supply


def _quote(restaurant, item, *, unit_cost, price_per_guest="50000", guests=10):
    quote = Quote.objects.create(
        restaurant=restaurant, number="CA-1", guests=guests,
        pricing_mode=PricingMode.PER_GUEST,
        price_per_guest=Decimal(price_per_guest), charges_tip=False,
    )
    QuoteLine.objects.create(
        quote=quote, menu_item=item, course=Course.MAINS, name=item.name,
        quantity=Decimal(guests), unit_price=item.price,
        unit_cost=None if unit_cost is None else Decimal(unit_cost),
    )
    return quote


# -- cost read through to the menu ----------------------------------------


@pytest.mark.django_db
def test_current_cost_follows_the_recipe_not_the_snapshot(restaurant, dish):
    item, _product, _supply = dish
    quote = _quote(restaurant, item, unit_cost="3000")

    # The line was priced at 3.000; the recipe says 200 g at 50 = 10.000.
    assert quote.cost == Decimal("30000")
    assert quote.current_cost == Decimal("100000")


@pytest.mark.django_db
def test_the_stored_cost_is_left_alone(restaurant, dish):
    item, _product, _supply = dish
    quote = _quote(restaurant, item, unit_cost="3000")

    quote.current_cost  # noqa: B018 - reading must not write
    quote.refresh_from_db()

    assert quote.lines.get().unit_cost == Decimal("3000")


@pytest.mark.django_db
def test_the_drift_says_how_far_the_quote_is_out(restaurant, dish):
    item, _product, _supply = dish
    quote = _quote(restaurant, item, unit_cost="3000")

    assert quote.cost_drift == Decimal("70000")


@pytest.mark.django_db
def test_a_supply_price_rise_moves_the_quote_cost(restaurant, dish):
    item, _product, supply = dish
    quote = _quote(restaurant, item, unit_cost="10000")
    assert quote.current_cost == Decimal("100000")

    supply.unit_cost = Decimal("75.0000")
    supply.save()

    quote = Quote.objects.get(pk=quote.pk)
    assert quote.current_cost == Decimal("150000")


@pytest.mark.django_db
def test_an_uncosted_recipe_falls_back_to_the_pos_cost(restaurant, dish):
    # The recipe cannot be costed, but the POS cost is still a real cost: the
    # quote drops back to it rather than going blank.
    item, _product, supply = dish
    supply.unit_cost = None
    supply.save()
    _quote(restaurant, item, unit_cost="3000")

    quote = Quote.objects.get()
    assert quote.current_cost == Decimal("70000")  # 10 x 7.000


@pytest.mark.django_db
def test_a_hand_typed_line_keeps_its_own_cost(restaurant):
    quote = Quote.objects.create(
        restaurant=restaurant, number="CA-2", guests=10, charges_tip=False,
        pricing_mode=PricingMode.PER_GUEST, price_per_guest=Decimal("50000"),
    )
    QuoteLine.objects.create(
        quote=quote, menu_item=None, course=Course.MAINS, name="Plato a mano",
        quantity=Decimal("10"), unit_price=Decimal("20000"), unit_cost=Decimal("5000"),
    )

    assert quote.current_cost == Decimal("50000")
    assert quote.lines.get().cost_is_stale is False


# -- the minimum ----------------------------------------------------------


@pytest.mark.django_db
def test_a_quote_under_the_minimum_is_flagged(restaurant, dish):
    item, _product, _supply = dish
    # 500.000 base, 100.000 cost -> 80% margin on the taxed base... the taxable
    # base is 500.000/1.08 = 462.962, so the margin is 78.4%.
    quote = _quote(restaurant, item, unit_cost="10000")

    assert not quote.is_below(Decimal("60"))
    assert quote.is_below(Decimal("90"))


@pytest.mark.django_db
def test_the_minimum_comes_from_the_restaurant(restaurant, dish):
    item, _product, _supply = dish
    _quote(restaurant, item, unit_cost="10000")
    restaurant.minimum_quote_margin = Decimal("90")
    restaurant.save()

    quote = Quote.objects.get()
    assert quote.is_below(restaurant.minimum_quote_margin)


@pytest.mark.django_db
def test_an_uncostable_quote_is_unknown_not_below(restaurant):
    quote = Quote.objects.create(
        restaurant=restaurant, number="CA-3", guests=10, charges_tip=False,
        pricing_mode=PricingMode.PER_GUEST, price_per_guest=Decimal("50000"),
    )
    QuoteLine.objects.create(
        quote=quote, course=Course.MAINS, name="Sin costo",
        quantity=Decimal("10"), unit_price=Decimal("20000"), unit_cost=None,
    )

    # Not costed, so there is no margin to be under a minimum.
    assert not quote.is_costed
    assert quote.current_margin_pct is None
    assert not quote.is_below(Decimal("60"))


@pytest.mark.django_db
def test_the_minimum_defaults_to_sixty(restaurant):
    assert restaurant.minimum_quote_margin == Decimal("60.00")


# -- the pages ------------------------------------------------------------


@pytest.mark.django_db
def test_the_list_flags_a_quote_under_the_minimum(logged_client, restaurant, dish):
    item, _product, _supply = dish
    _quote(restaurant, item, unit_cost="10000")
    restaurant.minimum_quote_margin = Decimal("90")
    restaurant.save()

    response = logged_client.get(reverse("quotes:quote_list"))

    assert response.context["below_count"] == 1
    assert "below minimum" in response.content.decode()


@pytest.mark.django_db
def test_the_list_does_not_flag_a_healthy_quote(logged_client, restaurant, dish):
    item, _product, _supply = dish
    _quote(restaurant, item, unit_cost="10000")

    response = logged_client.get(reverse("quotes:quote_list"))

    assert response.context["below_count"] == 0


@pytest.mark.django_db
def test_the_detail_reports_the_live_margin_and_the_stale_lines(
    logged_client, restaurant, dish
):
    item, _product, _supply = dish
    quote = _quote(restaurant, item, unit_cost="3000")

    response = logged_client.get(reverse("quotes:quote_detail", args=[quote.pk]))

    assert len(response.context["stale_lines"]) == 1
    assert response.context["live_margin"] == quote.current_margin_pct


@pytest.mark.django_db
def test_refreshing_copies_todays_cost_onto_the_lines(logged_client, restaurant, dish):
    item, _product, _supply = dish
    quote = _quote(restaurant, item, unit_cost="3000")

    logged_client.post(reverse("quotes:quote_refresh_costs", args=[quote.pk]))

    assert quote.lines.get().unit_cost == Decimal("10000")


@pytest.mark.django_db
def test_refreshing_an_already_current_quote_says_so(logged_client, restaurant, dish):
    item, _product, _supply = dish
    quote = _quote(restaurant, item, unit_cost="10000")

    response = logged_client.post(
        reverse("quotes:quote_refresh_costs", args=[quote.pk]), follow=True
    )

    assert "already current" in response.content.decode()


@pytest.mark.django_db
def test_refreshing_leaves_a_hand_typed_line_alone(logged_client, restaurant, dish):
    item, _product, _supply = dish
    quote = _quote(restaurant, item, unit_cost="3000")
    manual = QuoteLine.objects.create(
        quote=quote, menu_item=None, course=Course.SIDES, name="Alquiler",
        quantity=Decimal("1"), unit_price=Decimal("100000"), unit_cost=Decimal("40000"),
        add_on=True,
    )

    logged_client.post(reverse("quotes:quote_refresh_costs", args=[quote.pk]))

    manual.refresh_from_db()
    assert manual.unit_cost == Decimal("40000")


@pytest.mark.django_db
def test_another_restaurants_quote_cannot_be_refreshed(
    logged_client, other_restaurant
):
    theirs = Quote.objects.create(
        restaurant=other_restaurant, number="CA-X", guests=5,
    )

    response = logged_client.post(
        reverse("quotes:quote_refresh_costs", args=[theirs.pk])
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_the_minimum_can_be_changed_in_settings(logged_client, restaurant):
    logged_client.post(
        reverse("tenants:settings"),
        {"name": restaurant.name, "minimum_quote_margin": "72.5"},
    )

    restaurant.refresh_from_db()
    assert restaurant.minimum_quote_margin == Decimal("72.50")
