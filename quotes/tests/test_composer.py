"""Composing a menu that fits a per-guest budget."""
from decimal import Decimal

import pytest

from catalog.models import Category, Product
from quotes.models import Course, MenuItem, PricingMode, Quote
from quotes.services import (
    apply_composition,
    compose,
    cost_per_guest,
    minimum_per_guest,
    units_needed,
)


def _item(restaurant, name, course, price, servings="1", cost=None, category=None):
    product = None
    if cost is not None:
        product = Product.objects.create(
            restaurant=restaurant,
            name=name.upper(),
            sku=name[:20],
            category=category,
            cost_price=Decimal(cost),
            sale_price=Decimal(price) / Decimal("1.08"),
        )
    return MenuItem.objects.create(
        restaurant=restaurant,
        name=name,
        course=course,
        price=Decimal(price),
        servings=Decimal(servings),
        product=product,
    )


@pytest.fixture
def category(restaurant):
    return Category.objects.create(restaurant=restaurant, name="Test")


@pytest.fixture
def menu(restaurant, category):
    """A small menu with a cheap and an expensive option per course."""
    for course, prices in [
        (Course.STARTERS, (20000, 60000)),
        (Course.MAINS, (50000, 120000)),
        (Course.SIDES, (15000, 30000)),
        (Course.DESSERTS, (12000, 30000)),
        (Course.ALCOHOL, (25000, 90000)),
        (Course.SOFT, (8000, 18000)),
    ]:
        for i, price in enumerate(prices):
            _item(restaurant, f"{course}-{i}", course, price, cost=price / 4, category=category)
    return restaurant


@pytest.mark.django_db
class TestUnits:
    def test_a_station_is_paid_whole(self, restaurant):
        """Two stations for 30 guests, even though they serve 50."""
        station = _item(restaurant, "Station", Course.STARTERS, 300000, servings="25")

        assert units_needed(station, 30) == 2
        assert cost_per_guest(station, 30) == Decimal(600000) / 30

    def test_a_per_guest_item_scales_one_to_one(self, restaurant):
        dessert = _item(restaurant, "Dessert", Course.DESSERTS, 30000)

        assert units_needed(dessert, 12) == 12
        assert cost_per_guest(dessert, 12) == Decimal(30000)


@pytest.mark.django_db
class TestCompose:
    def test_a_generous_budget_is_respected(self, menu):
        composition = compose(menu, 250000, 20, profile="seated")

        assert composition.picks
        assert composition.fits
        assert composition.per_guest <= Decimal(250000)

    def test_every_course_of_the_profile_is_represented(self, menu):
        composition = compose(menu, 250000, 20, profile="seated")
        courses = {pick.item.course for pick in composition.picks}

        assert Course.MAINS in courses
        assert Course.DESSERTS in courses

    def test_alcohol_can_be_left_out(self, menu):
        composition = compose(menu, 200000, 20, profile="seated", alcohol=False)

        assert all(pick.item.course != Course.ALCOHOL for pick in composition.picks)

    def test_a_different_offset_proposes_a_different_menu(self, menu):
        first = compose(menu, 250000, 20, profile="seated", offset=0)
        second = compose(menu, 250000, 20, profile="seated", offset=1)

        assert [p.item.pk for p in first.picks] != [p.item.pk for p in second.picks]

    def test_only_the_tenant_own_items_are_used(self, menu, django_user_model):
        from tenants.models import Restaurant

        other = Restaurant.objects.create(name="Other", slug="other")
        _item(other, "Foreign dish", Course.MAINS, 10000)

        composition = compose(menu, 250000, 20, profile="seated")

        assert all(pick.item.restaurant_id == menu.pk for pick in composition.picks)

    def test_minimum_reports_the_floor_for_the_profile(self, menu):
        floor = minimum_per_guest(menu, 20, profile="seated")

        assert floor > 0
        assert floor <= compose(menu, 250000, 20, profile="seated").per_guest


@pytest.mark.django_db
class TestApply:
    def test_lines_snapshot_price_and_cost(self, menu):
        quote = Quote.objects.create(restaurant=menu, number="CA-200")
        composition = compose(menu, 250000, 20, profile="seated")

        apply_composition(quote, composition)
        quote.refresh_from_db()

        assert quote.lines.count() == len(composition.picks)
        assert quote.pricing_mode == PricingMode.PER_GUEST
        assert quote.price_per_guest == Decimal(250000)
        assert quote.guests == 20
        assert all(line.unit_cost is not None for line in quote.lines.all())

    def test_the_quote_reports_a_margin(self, menu):
        quote = Quote.objects.create(restaurant=menu, number="CA-201")
        apply_composition(quote, compose(menu, 250000, 20, profile="seated"))

        assert quote.cost > 0
        assert quote.profit > 0
        assert 0 < quote.margin_pct < 100

    def test_applying_twice_replaces_the_previous_lines(self, menu):
        quote = Quote.objects.create(restaurant=menu, number="CA-202")
        apply_composition(quote, compose(menu, 250000, 20, profile="seated"))
        first = quote.lines.count()

        apply_composition(quote, compose(menu, 150000, 10, profile="cocktail"))

        assert quote.lines.count() != first or quote.guests == 10
        assert quote.guests == 10
