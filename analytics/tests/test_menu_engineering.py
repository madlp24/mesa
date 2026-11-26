"""Tests for menu engineering (US50)."""
import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from analytics.menu_engineering import DOG, PLOWHORSE, PUZZLE, STAR, menu_engineering
from catalog.models import Category, Product
from catalog.portions import portions, sold_by_gram
from sales.models import Sale, SaleItem

DAY = datetime.date(2026, 3, 10)


def _dish(restaurant, group, name, *, qty, price, cost, day=DAY):
    category, _ = Category.objects.get_or_create(restaurant=restaurant, name=group)
    product = Product.objects.create(
        restaurant=restaurant, name=name, sku=name[:20], category=category,
        cost_price=Decimal(cost), sale_price=Decimal(price),
    )
    sale = Sale.objects.create(
        restaurant=restaurant, external_id=f"{day}:{name}",
        occurred_at=timezone.make_aware(datetime.datetime.combine(day, datetime.time(12))),
        total=Decimal(price) * qty,
    )
    SaleItem.objects.create(
        sale=sale, product=product, quantity=qty,
        unit_price=Decimal(price), unit_cost=Decimal(cost),
    )
    return product


def _kinds(group):
    return {dish.name: dish.kind for dish in group.dishes}


@pytest.mark.django_db
def test_each_dish_lands_in_its_quadrant(restaurant):
    # Four dishes: an even share is 25%, so popular means at least 17.5%.
    _dish(restaurant, "CORTES", "RIBEYE", qty=40, price="100000", cost="40000")   # 60k, popular
    _dish(restaurant, "CORTES", "PICANHA", qty=40, price="50000", cost="30000")   # 20k, popular
    _dish(restaurant, "CORTES", "WAGYU", qty=5, price="300000", cost="150000")    # 150k, rare
    _dish(restaurant, "CORTES", "BIFE", qty=5, price="40000", cost="30000")       # 10k, rare

    [group] = menu_engineering(restaurant)

    assert _kinds(group) == {
        "RIBEYE": STAR, "PICANHA": PLOWHORSE, "WAGYU": PUZZLE, "BIFE": DOG,
    }
    assert group.popularity_threshold == Decimal("17.5")


@pytest.mark.django_db
def test_the_profit_line_is_the_average_weighted_by_portions(restaurant):
    _dish(restaurant, "POSTRES", "TORTA", qty=30, price="20000", cost="8000")     # 12k each
    _dish(restaurant, "POSTRES", "HELADO", qty=10, price="12000", cost="8000")    # 4k each

    [group] = menu_engineering(restaurant)

    # (30 x 12.000 + 10 x 4.000) / 40 portions = 10.000, not the plain 8.000.
    assert group.contribution_threshold == Decimal("10000")


@pytest.mark.django_db
def test_gram_cuts_are_counted_in_portions(restaurant):
    _dish(restaurant, "CORTES", "PORTERHOUSE *GR", qty=28000, price="400", cost="200")
    _dish(restaurant, "CORTES", "PICANHA", qty=100, price="100000", cost="40000")

    [group] = menu_engineering(restaurant)
    porterhouse = next(d for d in group.dishes if d.name == "PORTERHOUSE *GR")

    assert porterhouse.portions == Decimal("100")  # 28.000 g / 280 g
    assert porterhouse.contribution == Decimal("56000")  # 200 per gram x 280 g
    assert porterhouse.mix_pct == Decimal("50")


def test_gram_markers():
    assert sold_by_gram("TOMAHAWK AMERICANO * GR")
    assert not sold_by_gram("PICANHA AMERICANA *420GR")
    assert portions(560, "DENVER STEAK *GR") == Decimal("2")


@pytest.mark.django_db
def test_groups_are_judged_apart_and_ordered_by_takings(restaurant):
    _dish(restaurant, "BEBIDAS", "LIMONADA", qty=50, price="9000", cost="2000")
    _dish(restaurant, "CORTES", "RIBEYE", qty=10, price="240000", cost="70000")

    groups = menu_engineering(restaurant)

    assert [g.name for g in groups] == ["CORTES", "BEBIDAS"]
    assert all(len(g.dishes) == 1 and g.dishes[0].kind == STAR for g in groups)


@pytest.mark.django_db
def test_a_dish_without_cost_is_listed_apart(restaurant):
    _dish(restaurant, "COCTELES", "NEGRONI", qty=20, price="40000", cost="9000")
    _dish(restaurant, "COCTELES", "VESPER", qty=20, price="40000", cost="0")

    [group] = menu_engineering(restaurant)

    assert [d.name for d in group.dishes] == ["NEGRONI"]
    assert [d.name for d in group.uncosted] == ["VESPER"]


@pytest.mark.django_db
def test_the_period_limits_the_sales(restaurant):
    _dish(restaurant, "CORTES", "RIBEYE", qty=10, price="100", cost="40", day=DAY)
    _dish(restaurant, "CORTES", "VIEJO", qty=10, price="100", cost="40", day=DAY - datetime.timedelta(days=200))

    [group] = menu_engineering(restaurant, DAY - datetime.timedelta(days=30), DAY)

    assert [d.name for d in group.dishes] == ["RIBEYE"]


# -- the page -----------------------------------------------------------------


@pytest.mark.django_db
def test_the_page_defaults_to_ninety_days(logged_client, restaurant):
    _dish(restaurant, "CORTES", "RIBEYE", qty=10, price="100", cost="40", day=timezone.localdate())

    response = logged_client.get(reverse("analytics:menu_engineering"))

    assert response.status_code == 200
    assert response.context["window"].preset == "90d"
    assert response.context["group"].name == "CORTES"


@pytest.mark.django_db
def test_a_group_can_be_picked(logged_client, restaurant):
    today = timezone.localdate()
    _dish(restaurant, "CORTES", "RIBEYE", qty=10, price="100000", cost="40", day=today)
    _dish(restaurant, "POSTRES", "TORTA", qty=10, price="100", cost="40", day=today)

    response = logged_client.get(reverse("analytics:menu_engineering"), {"group": "POSTRES"})

    assert response.context["group"].name == "POSTRES"
    assert "TORTA" in response.content.decode()


@pytest.mark.django_db
def test_an_empty_period_says_so(logged_client):
    response = logged_client.get(reverse("analytics:menu_engineering"))

    assert response.status_code == 200
    assert "No sales in this period" in response.content.decode()
