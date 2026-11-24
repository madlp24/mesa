"""Tests for keeping product cost and price on the newest sale (US47)."""
import datetime
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from analytics.services import product_margins
from catalog.models import Category, Product, ProductAlias, RecipeLine, Supply
from catalog.pricing import refresh_product_prices
from catalog.services import merge_products, repoint_alias
from sales.importers.canonical import CanonicalSale, CanonicalSaleItem
from sales.importers.persistence import persist
from sales.models import ImportBatch
from sales.services import undo_import


def _day(day: str) -> datetime.datetime:
    date = datetime.date.fromisoformat(day)
    return timezone.make_aware(datetime.datetime(date.year, date.month, date.day, 12))


def _sale(day, *, cost, price, qty=1, clave="100", name="NEW YORK STEAK"):
    item = CanonicalSaleItem(
        product_sku=clave, quantity=qty,
        unit_price=Decimal(price), unit_cost=Decimal(cost),
        product_name=name, category_name="CARNES",
    )
    return CanonicalSale(
        external_id=f"{day}:{clave}", occurred_at=_day(day),
        total=Decimal(price) * qty, items=[item],
    )


def _product(restaurant, name="NEW YORK STEAK"):
    return Product.objects.get(restaurant=restaurant, name=name)


# -- the import keeps the catalog current ---------------------------------


@pytest.mark.django_db
def test_an_import_moves_the_product_to_the_newest_figures(restaurant):
    persist([_sale("2026-03-02", cost="71654", price="184259")], restaurant)

    persist([_sale("2026-09-20", cost="57545", price="199074")], restaurant)

    product = _product(restaurant)
    assert product.cost_price == Decimal("57545.00")
    assert product.sale_price == Decimal("199074.00")


@pytest.mark.django_db
def test_an_older_report_imported_late_does_not_win(restaurant):
    # Folders get imported out of order: February arriving after September
    # must not put February's cost back.
    persist([_sale("2026-09-20", cost="57545", price="199074")], restaurant)

    persist([_sale("2026-02-10", cost="71654", price="184259")], restaurant)

    product = _product(restaurant)
    assert product.cost_price == Decimal("57545.00")
    assert product.sale_price == Decimal("199074.00")


@pytest.mark.django_db
def test_a_courtesy_does_not_wipe_the_price(restaurant):
    persist([_sale("2026-09-20", cost="57545", price="199074")], restaurant)

    persist([_sale("2026-09-21", cost="57545", price="0")], restaurant)

    assert _product(restaurant).sale_price == Decimal("199074.00")


@pytest.mark.django_db
def test_an_uncosted_line_does_not_wipe_the_cost(restaurant):
    persist([_sale("2026-09-20", cost="57545", price="199074")], restaurant)

    persist([_sale("2026-09-21", cost="0", price="205000")], restaurant)

    product = _product(restaurant)
    assert product.cost_price == Decimal("57545.00")
    assert product.sale_price == Decimal("205000.00")


@pytest.mark.django_db
def test_the_newest_day_is_averaged_by_quantity(restaurant):
    # Two aliases fused into one product, sold at two prices the same day.
    persist(
        [
            _sale("2026-09-20", cost="1000", price="10000", qty=3, clave="200",
                  name="LIMONADA NATURAL"),
            _sale("2026-09-20", cost="2000", price="13000", qty=1, clave="201",
                  name="LIMONADA NATURAL X TRAGO"),
        ],
        restaurant,
    )

    product = _product(restaurant, "LIMONADA NATURAL")
    assert product.cost_price == Decimal("1250.00")
    assert product.sale_price == Decimal("10750.00")


@pytest.mark.django_db
def test_another_restaurant_is_left_alone(restaurant, other_restaurant):
    persist([_sale("2026-03-02", cost="71654", price="184259")], other_restaurant)

    persist([_sale("2026-09-20", cost="57545", price="199074")], restaurant)

    theirs = _product(other_restaurant)
    assert theirs.cost_price == Decimal("71654.00")


# -- operations that move sales between products --------------------------


@pytest.mark.django_db
def test_undoing_the_newest_import_falls_back_to_the_one_before(restaurant):
    persist([_sale("2026-03-02", cost="71654", price="184259")], restaurant)
    batch = ImportBatch.objects.create(restaurant=restaurant, filename="sep.pdf")
    persist([_sale("2026-09-20", cost="57545", price="199074")], restaurant, batch)

    undo_import(batch)

    product = _product(restaurant)
    assert product.cost_price == Decimal("71654.00")
    assert product.sale_price == Decimal("184259.00")


@pytest.mark.django_db
def test_a_merge_takes_the_newest_sale_of_either_product(restaurant):
    persist(
        [
            _sale("2026-03-02", cost="1000", price="9000", clave="300", name="SODA LYCHEE"),
            _sale("2026-09-20", cost="1500", price="12000", clave="301",
                  name="LYCHEE TONIC ESPECIAL"),
        ],
        restaurant,
    )
    canonical = _product(restaurant, "SODA LYCHEE")

    merge_products(restaurant, canonical, [_product(restaurant, "LYCHEE TONIC ESPECIAL")])

    canonical.refresh_from_db()
    assert canonical.cost_price == Decimal("1500.00")
    assert canonical.sale_price == Decimal("12000.00")


@pytest.mark.django_db
def test_repointing_an_alias_refreshes_both_products(restaurant):
    persist(
        [
            _sale("2026-03-02", cost="1000", price="9000", clave="400", name="DRY MARTINI"),
            _sale("2026-09-20", cost="3000", price="30000", clave="401",
                  name="VESPER MARTINI"),
        ],
        restaurant,
    )
    dry = _product(restaurant, "DRY MARTINI")
    vesper = _product(restaurant, "VESPER MARTINI")
    alias = ProductAlias.objects.get(restaurant=restaurant, pos_clave="400")

    repoint_alias(restaurant, alias, vesper)

    vesper.refresh_from_db()
    assert vesper.cost_price == Decimal("3000.00")  # September is still newest
    dry.refresh_from_db()
    assert dry.cost_price == Decimal("1000.00")  # no sales left: keeps its own


# -- the margin page --------------------------------------------------------


@pytest.fixture
def category(restaurant):
    return Category.objects.create(restaurant=restaurant, name="Cocteles")


@pytest.mark.django_db
def test_the_margin_page_reads_the_recipe_cost(restaurant, category):
    product = Product.objects.create(
        restaurant=restaurant, name="NEGRONI", sku="8100", category=category,
        cost_price=Decimal("6000"), sale_price=Decimal("40000"),
    )
    supply = Supply.objects.create(
        restaurant=restaurant, clave="GIN", name="GIN", unit="ml",
        unit_cost=Decimal("100"),
    )
    RecipeLine.objects.create(product=product, supply=supply, quantity=Decimal("40"))

    [row] = product_margins(restaurant)

    assert row["cost"] == Decimal("4000")
    assert row["margin_pct"] == Decimal("90")


@pytest.mark.django_db
def test_an_uncosted_product_shows_no_margin_and_sorts_last(restaurant, category):
    Product.objects.create(
        restaurant=restaurant, name="SIN COSTO", sku="1", category=category,
        cost_price=Decimal("0"), sale_price=Decimal("10000"),
    )
    Product.objects.create(
        restaurant=restaurant, name="CON COSTO", sku="2", category=category,
        cost_price=Decimal("4000"), sale_price=Decimal("10000"),
    )

    for descending in (True, False):
        rows = product_margins(restaurant, descending=descending)
        assert [row["name"] for row in rows] == ["CON COSTO", "SIN COSTO"]
        assert rows[1]["cost"] is None
        assert rows[1]["margin_pct"] is None


@pytest.mark.django_db
def test_the_margin_page_renders_an_uncosted_product(logged_client, restaurant, category):
    Product.objects.create(
        restaurant=restaurant, name="SIN COSTO", sku="1", category=category,
        cost_price=Decimal("0"), sale_price=Decimal("10000"),
    )

    response = logged_client.get("/margin/")

    assert response.status_code == 200
    assert "No cost" in response.content.decode()


# -- the backfill -----------------------------------------------------------


@pytest.fixture
def frozen(restaurant):
    """A product whose stored figures predate its newest sale."""
    persist([_sale("2026-09-20", cost="57545", price="199074")], restaurant)
    Product.objects.filter(restaurant=restaurant).update(
        cost_price=Decimal("71654"), sale_price=Decimal("184259")
    )
    return _product(restaurant)


@pytest.mark.django_db
def test_refresh_reports_what_moved(restaurant, frozen):
    [change] = refresh_product_prices(restaurant)

    assert change.name == "NEW YORK STEAK"
    assert (change.old_cost, change.new_cost) == (Decimal("71654.00"), Decimal("57545.00"))
    assert change.cost_moved and change.price_moved


@pytest.mark.django_db
def test_the_command_dry_run_writes_nothing(restaurant, frozen, capsys):
    call_command("refresh_product_costs", restaurant=restaurant.slug, dry_run=True)

    frozen.refresh_from_db()
    assert frozen.cost_price == Decimal("71654.00")
    assert "1 product(s) would change: 1 cost(s), 1 price(s)" in capsys.readouterr().out


@pytest.mark.django_db
def test_the_command_brings_the_catalog_up_to_date(restaurant, frozen, capsys):
    call_command("refresh_product_costs", restaurant=restaurant.slug)

    frozen.refresh_from_db()
    assert frozen.cost_price == Decimal("57545.00")
    assert frozen.sale_price == Decimal("199074.00")
    assert "cost 71,654.00 -> 57,545.00" in capsys.readouterr().out


@pytest.mark.django_db
def test_a_second_run_changes_nothing(restaurant, frozen):
    refresh_product_prices(restaurant)

    assert refresh_product_prices(restaurant) == []
