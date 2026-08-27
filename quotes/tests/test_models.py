"""Quote arithmetic: what the client pays, and what is left of it."""
from decimal import Decimal

import pytest

from catalog.models import Category, Product
from quotes.models import Course, MenuItem, PricingMode, Quote, QuoteLine


@pytest.fixture
def category(restaurant):
    return Category.objects.create(restaurant=restaurant, name="Cortes")


def _product(restaurant, category, name, cost, sale):
    return Product.objects.create(
        restaurant=restaurant,
        name=name,
        sku=name[:20],
        category=category,
        cost_price=Decimal(cost),
        sale_price=Decimal(sale),
    )


def _quote(restaurant, **kwargs):
    return Quote.objects.create(
        restaurant=restaurant, number=kwargs.pop("number", "CA-119"), **kwargs
    )


def _line(quote, price, cost, qty=1, name="Item"):
    return QuoteLine.objects.create(
        quote=quote,
        course=Course.MAINS,
        name=name,
        quantity=Decimal(qty),
        unit_price=Decimal(price),
        unit_cost=None if cost is None else Decimal(cost),
    )


@pytest.mark.django_db
class TestTotals:
    def test_tax_is_shown_but_not_added_again(self, restaurant):
        """Menu prices already contain the IPO; the total must not re-add it."""
        quote = _quote(restaurant, guests=1, charges_tip=False)
        _line(quote, price=108, cost=40)

        assert quote.subtotal == Decimal(108)
        assert quote.taxable_base == Decimal(100)
        assert quote.tax_included == Decimal(8)
        assert quote.total == Decimal(108)

    def test_tip_applies_to_the_pre_tax_base(self, restaurant):
        quote = _quote(restaurant, guests=1)
        _line(quote, price=108, cost=40)

        assert quote.tip == Decimal(10)
        assert quote.total == Decimal(118)

    def test_per_guest_mode_ignores_the_line_prices(self, restaurant):
        quote = _quote(
            restaurant,
            guests=20,
            pricing_mode=PricingMode.PER_GUEST,
            price_per_guest=Decimal(180000),
            charges_tip=False,
        )
        _line(quote, price=35000, cost=9000, qty=20)

        assert quote.subtotal == Decimal(3600000)
        assert quote.total == Decimal(3600000)
        assert quote.total_per_guest == Decimal(180000)

    def test_matches_a_real_quote_from_the_spreadsheet(self, restaurant):
        """COT-112: subtotal 7.044.000 -> 7.696.222, not the 8.218.000 charged.

        The old template extracted the contained IPO and then added it back on
        top, overcharging by exactly that amount.
        """
        quote = _quote(restaurant, guests=1)
        _line(quote, price=7044000, cost=0)

        assert round(quote.tax_included) == Decimal(521778)
        assert round(quote.tip) == Decimal(652222)
        assert round(quote.total) == Decimal(7696222)


@pytest.mark.django_db
class TestMargin:
    def test_profit_is_net_of_tax_and_tip(self, restaurant):
        quote = _quote(restaurant, guests=1)
        _line(quote, price=108, cost=40)

        assert quote.cost == Decimal(40)
        assert quote.profit == Decimal(60)
        assert quote.margin_pct == Decimal(60)

    def test_a_line_without_a_mapped_product_leaves_the_quote_uncosted(self, restaurant):
        quote = _quote(restaurant, guests=1)
        _line(quote, price=108, cost=40, name="Mapped")
        _line(quote, price=54, cost=None, name="Not mapped")

        assert quote.is_costed is False
        assert quote.cost == Decimal(40)

    def test_cost_per_guest(self, restaurant):
        quote = _quote(restaurant, guests=10)
        _line(quote, price=1080, cost=400)

        assert quote.cost_per_guest == Decimal(40)


@pytest.mark.django_db
class TestMenuItem:
    def test_unit_cost_comes_from_the_linked_product(self, restaurant, category):
        product = _product(restaurant, category, "PICANHA *420GR", cost=30845, sale=116667)
        item = MenuItem.objects.create(
            restaurant=restaurant,
            name="Picanha americana",
            course=Course.MAINS,
            price=Decimal(136000),
            product=product,
        )

        assert item.unit_cost == Decimal(30845)
        assert item.is_mapped is True

    def test_product_units_bridge_a_unit_mismatch(self, restaurant, category):
        """A kilo of picanha costs 1000/420 of a 420 g portion."""
        product = _product(restaurant, category, "PICANHA *420GR", cost=30845, sale=116667)
        item = MenuItem.objects.create(
            restaurant=restaurant,
            name="Picanha americana por kg",
            course=Course.MAINS,
            price=Decimal(320000),
            product=product,
            product_units=Decimal("2.3810"),
        )

        assert round(item.unit_cost) == Decimal(73442)

    def test_an_unmapped_item_has_no_cost(self, restaurant):
        item = MenuItem.objects.create(
            restaurant=restaurant, name="Ceviche", course=Course.STARTERS, price=Decimal(50000)
        )

        assert item.unit_cost is None
        assert item.is_mapped is False


@pytest.mark.django_db
class TestUnknownCost:
    def test_a_product_without_cost_is_unknown_not_free(self, restaurant, category):
        """Counting a zero-cost product as free inflates the margin silently."""
        product = _product(restaurant, category, "DUBONNET", cost=0, sale=166666)
        item = MenuItem.objects.create(
            restaurant=restaurant,
            name="Dubonnet",
            course=Course.ALCOHOL,
            price=Decimal(180000),
            product=product,
        )

        assert item.unit_cost is None
        assert item.is_mapped is True

    def test_a_quote_with_an_unknown_cost_is_not_costed(self, restaurant):
        quote = _quote(restaurant, guests=1)
        _line(quote, price=108, cost=40, name="Known")
        _line(quote, price=180000, cost=None, name="Unknown cost")

        assert quote.is_costed is False
