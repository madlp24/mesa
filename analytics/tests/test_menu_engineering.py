"""Tests for menu engineering (US50)."""
import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from analytics.menu_engineering import (
    DOG,
    PLOWHORSE,
    PUZZLE,
    STAR,
    menu_engineering,
    needed_menu_price,
    price_moves,
    weakest_dogs,
    with_movement,
)
from catalog.families import suggest_family, suggest_hidden
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
    # Profitable means a food cost at or under the 30% target (US55).
    _dish(restaurant, "CORTES", "RIBEYE", qty=40, price="100000", cost="28000")   # 28%, popular
    _dish(restaurant, "CORTES", "PICANHA", qty=40, price="50000", cost="20000")   # 40%, popular
    _dish(restaurant, "CORTES", "WAGYU", qty=5, price="300000", cost="75000")     # 25%, rare
    _dish(restaurant, "CORTES", "BIFE", qty=5, price="40000", cost="16000")       # 40%, rare

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

    assert [g.name for g in groups] == ["Cuts", "Soft drinks"]
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
    assert response.context["group"].name == "Cuts"


@pytest.mark.django_db
def test_a_group_can_be_picked(logged_client, restaurant):
    today = timezone.localdate()
    _dish(restaurant, "CORTES", "RIBEYE", qty=10, price="100000", cost="40", day=today)
    _dish(restaurant, "POSTRES", "TORTA", qty=10, price="100", cost="40", day=today)

    response = logged_client.get(reverse("analytics:menu_engineering"), {"group": "Desserts"})

    assert response.context["group"].name == "Desserts"
    assert "TORTA" in response.content.decode()


@pytest.mark.django_db
def test_an_empty_period_says_so(logged_client):
    response = logged_client.get(reverse("analytics:menu_engineering"))

    assert response.status_code == 200
    assert "No sales in this period" in response.content.decode()


# -- families (US53) ----------------------------------------------------------


def test_pos_groups_are_filed_into_families():
    assert suggest_family("CORTES") == "Cuts"
    assert suggest_family("CARNE PRIME") == "Premium cuts"
    assert suggest_family("VINOS Y ESPUMOSOS X BOTELLA") == "Wine by the bottle"
    assert suggest_family("VINOS Y ESPUMOSOS X TRAGO") == "Wine by the glass and sangria"
    assert suggest_family("ENSALADAS") == "Salads"
    assert suggest_family("PICOTEO") == suggest_family("ENTRADAS") == "Starters and snacks"
    assert suggest_family("COCTELES") == "Cocktails"  # not "CORTE"
    assert suggest_family("KAREN") == "Karen"  # unknown: its own name
    assert suggest_hidden("ANULAR") and suggest_hidden("DESCORCHE")
    assert not suggest_hidden("ADICIONES")


@pytest.mark.django_db
def test_groups_that_are_not_dishes_are_left_out(restaurant):
    _dish(restaurant, "CORTES", "RIBEYE", qty=10, price="100", cost="40")
    _dish(restaurant, "DESCORCHE", "DESCORCHE VINO", qty=10, price="100", cost="40")

    assert [g.name for g in menu_engineering(restaurant)] == ["Cuts"]


@pytest.mark.django_db
def test_what_the_owner_sets_wins_over_the_suggestion(restaurant):
    _dish(restaurant, "CORTES", "RIBEYE", qty=10, price="100", cost="40")
    _dish(restaurant, "CARNE PRIME", "WAGYU", qty=10, price="300", cost="150")
    _dish(restaurant, "KAREN", "CARNE DR", qty=10, price="100", cost="40")
    Category.objects.filter(name__in=["CORTES", "CARNE PRIME"]).update(menu_family="Parrilla")
    Category.objects.filter(name="KAREN").update(menu_hidden=True)

    [group] = menu_engineering(restaurant)

    assert group.name == "Parrilla"
    assert {d.name for d in group.dishes} == {"RIBEYE", "WAGYU"}


@pytest.mark.django_db
def test_the_families_page_saves_names_and_exclusions(logged_client, restaurant):
    _dish(restaurant, "CORTES", "RIBEYE", qty=10, price="100", cost="40")
    category = Category.objects.get(name="CORTES")

    logged_client.post(
        reverse("analytics:menu_families"),
        {f"family-{category.pk}": "Parrilla", f"hidden-{category.pk}": "on"},
    )

    category.refresh_from_db()
    assert (category.menu_family, category.menu_hidden) == ("Parrilla", True)


# -- movement and decisions (US53) ---------------------------------------------


def _four_cuts(restaurant):
    _dish(restaurant, "CORTES", "RIBEYE", qty=40, price="100000", cost="28000")
    _dish(restaurant, "CORTES", "PICANHA", qty=40, price="50000", cost="20000")
    _dish(restaurant, "CORTES", "WAGYU", qty=5, price="300000", cost="75000")
    _dish(restaurant, "CORTES", "BIFE", qty=2, price="40000", cost="16000")
    [group] = menu_engineering(restaurant)
    return group


@pytest.mark.django_db
def test_a_dish_over_its_target_gets_a_capped_rounded_menu_price(restaurant):
    group = _four_cuts(restaurant)

    moves = price_moves(group, days=30, cap_pct=8, step=1000)
    move = moves[0]

    assert [m.dish.name for m in moves] == ["PICANHA", "BIFE"]  # the two over 30%
    assert move.current == Decimal("54000")  # 50.000 in the POS, tax on the menu
    # 20.000 / 30% = 66.667 without tax, 72.000 on the menu; 8% allows 58.000.
    assert (move.needed, move.proposed) == (Decimal("72000"), Decimal("58000"))
    assert not move.reaches_target
    assert round(move.cost_pct_now, 1) == Decimal("40.0")
    assert round(move.cost_pct_after, 1) == Decimal("37.2")
    # 4.000 on the menu is 3.703,70 before tax, over 40 portions a month.
    assert round(move.extra_per_month) == 148148


@pytest.mark.django_db
def test_a_generous_cap_lets_the_price_reach_the_target(restaurant):
    group = _four_cuts(restaurant)

    move = price_moves(group, days=30, cap_pct=60, step=1000)[0]

    assert move.proposed == Decimal("72000") and move.reaches_target
    assert round(move.cost_pct_after, 1) == Decimal("30.0")


@pytest.mark.django_db
def test_the_owners_arithmetic(restaurant):
    # 27.300 of raw material at 30% is 91.000 without tax: 98.280 on the menu,
    # 99.000 rounded to the thousand.
    _dish(restaurant, "CORTES", "PICANHA", qty=10, price="90000", cost="27300")
    [group] = menu_engineering(restaurant)
    [dish] = group.dishes

    assert needed_menu_price(dish, 1000) == Decimal("99000")


@pytest.mark.django_db
def test_a_dish_within_target_gets_no_suggestion(restaurant):
    _dish(restaurant, "CORTES", "PICANHA", qty=10, price="125926", cost="36800")  # 29,2%
    [group] = menu_engineering(restaurant)

    assert group.dishes[0].kind == STAR
    assert price_moves(group, days=30, cap_pct=8, step=1000) == []


@pytest.mark.django_db
def test_a_family_can_have_its_own_target(restaurant):
    _dish(restaurant, "VINOS X BOTELLA", "MALBEC", qty=10, price="200000", cost="88000")  # 44%
    Category.objects.filter(name="VINOS X BOTELLA").update(target_cost_pct=Decimal("45"))

    [group] = menu_engineering(restaurant)

    assert group.target_cost_pct == Decimal("45")
    assert not group.dishes[0].over_target


@pytest.mark.django_db
def test_the_families_page_saves_a_target(logged_client, restaurant):
    _dish(restaurant, "CORTES", "RIBEYE", qty=10, price="100", cost="40")
    category = Category.objects.get(name="CORTES")

    logged_client.post(
        reverse("analytics:menu_families"),
        {f"family-{category.pk}": "Cortes", f"target-{category.pk}": "32,5"},
    )

    category.refresh_from_db()
    assert category.target_cost_pct == Decimal("32.5")


@pytest.mark.django_db
def test_gram_cuts_are_priced_per_hundred_grams(restaurant):
    _dish(restaurant, "CORTES", "PORTERHOUSE *GR", qty=28000, price="400", cost="200")
    [group] = menu_engineering(restaurant)
    [dish] = group.dishes

    assert dish.menu_price == Decimal("43200")  # 400 x 100 g x 1,08
    # One peso more per 100 g is 2,8 pesos on a 280 g portion, less the tax.
    assert round(dish.menu_factor, 4) == Decimal("2.5926")


@pytest.mark.django_db
def test_the_weakest_dogs_say_what_they_leave_a_month(restaurant):
    group = _four_cuts(restaurant)

    [(dish, monthly)] = weakest_dogs(group, days=90)

    assert dish.name == "BIFE"
    assert round(monthly) == 16000  # 48.000 over three months


@pytest.mark.django_db
def test_a_dog_that_still_brings_in_money_is_not_a_candidate_to_drop(restaurant):
    _dish(restaurant, "CORTES", "RIBEYE", qty=40, price="100000", cost="40000")
    _dish(restaurant, "CORTES", "PICANHA", qty=40, price="90000", cost="40000")
    _dish(restaurant, "CORTES", "TOMAHAWK", qty=8, price="80000", cost="40000")  # 6% of the margin
    [group] = menu_engineering(restaurant)

    assert [d.name for d in group.dogs] == ["TOMAHAWK"]
    assert weakest_dogs(group, days=90) == []


@pytest.mark.django_db
def test_movement_shows_a_cost_rise_and_what_it_takes_a_month(restaurant):
    product = _dish(restaurant, "CORTES", "PICANHA", qty=30, price="100000", cost="46000")
    earlier = DAY - datetime.timedelta(days=40)
    sale = Sale.objects.create(
        restaurant=restaurant, external_id="before",
        occurred_at=timezone.make_aware(datetime.datetime.combine(earlier, datetime.time(12))),
        total=Decimal("0"),
    )
    SaleItem.objects.create(sale=sale, product=product, quantity=20,
                            unit_price=Decimal("100000"), unit_cost=Decimal("40000"))
    start = DAY - datetime.timedelta(days=29)
    [now] = menu_engineering(restaurant, start, DAY)
    [before] = menu_engineering(restaurant, start - datetime.timedelta(days=30), start - datetime.timedelta(days=1))

    group = with_movement(now, before)
    [dish] = group.dishes

    assert dish.cost_change == Decimal("15") and dish.cost_alarm
    assert dish.portions_shift == Decimal("50")
    assert group.cost_drift == Decimal("180000")  # 6.000 more on 30 portions


@pytest.mark.django_db
def test_the_page_ends_in_decisions(logged_client, restaurant):
    today = timezone.localdate()
    _dish(restaurant, "CORTES", "RIBEYE", qty=40, price="100000", cost="28000", day=today)
    _dish(restaurant, "CORTES", "PICANHA", qty=40, price="50000", cost="20000", day=today)
    _dish(restaurant, "CORTES", "WAGYU", qty=5, price="300000", cost="75000", day=today)

    response = logged_client.get(reverse("analytics:menu_engineering"))
    body = response.content.decode()

    assert [m.dish.name for m in response.context["moves"]] == ["PICANHA"]
    assert "from $54,000 to $58,000 on the menu" in body
    assert "Each price is cost divided by the target of 30%" in body
    assert "Its cost goes from 40.0% to 37.2% of the price" in body


@pytest.mark.django_db
def test_the_cap_and_the_step_come_from_the_restaurant(logged_client, restaurant):
    logged_client.post(
        reverse("tenants:settings"),
        {"name": restaurant.name, "price_rise_cap": "5", "menu_price_step": "500",
         "target_cost_pct": "32"},
    )

    restaurant.refresh_from_db()
    assert (restaurant.price_rise_cap, restaurant.menu_price_step) == (Decimal("5.0"), 500)
    assert restaurant.target_cost_pct == Decimal("32.0")
