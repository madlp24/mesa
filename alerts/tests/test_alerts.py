"""Tests for the profitability alerts (US54)."""
import datetime
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from alerts.engine import COST_RISE, MARGIN_DROP, PRICE_DROP, build_report, spans
from alerts.models import AlertSettings, Baseline, Cadence
from catalog.models import Category, Product, RecipeLine, Supply, SupplyPrice
from catalog.supplies import sync_supplies
from sales.models import Sale, SaleItem

NEWEST = datetime.date(2026, 7, 5)  # a Sunday


def _product(restaurant, name="PICANHA", group="CORTES"):
    category, _ = Category.objects.get_or_create(restaurant=restaurant, name=group)
    return Product.objects.create(
        restaurant=restaurant, name=name, sku=name[:20], category=category,
        cost_price=Decimal("1"), sale_price=Decimal("1"),
    )


def _sell(product, day, *, qty=10, price="100000", cost="30000"):
    sale = Sale.objects.create(
        restaurant=product.restaurant, external_id=f"{day}:{product.sku}",
        occurred_at=timezone.make_aware(datetime.datetime.combine(day, datetime.time(12))),
        total=Decimal(price) * qty,
    )
    SaleItem.objects.create(sale=sale, product=product, quantity=qty,
                            unit_price=Decimal(price), unit_cost=Decimal(cost))


def _days(start, end):
    day = start
    while day <= end:
        yield day
        day += datetime.timedelta(days=1)


def _history(product, *, before_cost="30000", now_cost="30000", before_price="100000",
             now_price="100000", qty=10):
    """Four weeks at one level, then the week watched at another."""
    for day in _days(NEWEST - datetime.timedelta(days=34), NEWEST - datetime.timedelta(days=7)):
        _sell(product, day, qty=qty, price=before_price, cost=before_cost)
    for day in _days(NEWEST - datetime.timedelta(days=6), NEWEST):
        _sell(product, day, qty=qty, price=now_price, cost=now_cost)


# -- the periods ---------------------------------------------------------------


@pytest.mark.django_db
def test_a_week_is_compared_with_the_four_before(restaurant):
    settings = AlertSettings.for_restaurant(restaurant)

    current, baseline = spans(settings, NEWEST)

    assert (current.start, current.end) == (datetime.date(2026, 6, 29), NEWEST)
    assert (baseline.start, baseline.end) == (datetime.date(2026, 6, 1), datetime.date(2026, 6, 28))


@pytest.mark.django_db
def test_a_month_against_last_year_keeps_the_weekdays(restaurant):
    settings = AlertSettings.for_restaurant(restaurant)
    settings.cadence, settings.baseline = Cadence.MONTH, Baseline.LAST_YEAR

    current, baseline = spans(settings, NEWEST)

    assert current.days == 30
    assert baseline.end == NEWEST - datetime.timedelta(days=364)
    assert baseline.end.weekday() == NEWEST.weekday()


# -- lost profitability --------------------------------------------------------


@pytest.mark.django_db
def test_a_cost_rise_is_flagged_with_what_it_costs_a_month(restaurant):
    _history(_product(restaurant), before_cost="30000", now_cost="34500")  # +15%

    report = build_report(restaurant, today=NEWEST)
    [alert] = report.products

    assert alert.reasons == [COST_RISE, MARGIN_DROP]
    assert alert.cost_change == Decimal("15")
    # 4.500 more on each of 70 portions in 7 days, over a 30-day month.
    assert round(alert.monthly_loss) == 1350000


@pytest.mark.django_db
def test_a_price_drop_is_flagged(restaurant):
    _history(_product(restaurant), before_price="100000", now_price="90000")

    [alert] = build_report(restaurant, today=NEWEST).products

    assert PRICE_DROP in alert.reasons


@pytest.mark.django_db
def test_small_moves_are_not_news(restaurant):
    _history(_product(restaurant), before_cost="30000", now_cost="30900")  # +3%

    assert build_report(restaurant, today=NEWEST).products == []


@pytest.mark.django_db
def test_small_sellers_are_left_out(restaurant):
    _history(_product(restaurant), before_cost="30000", now_cost="40000", qty=1,
             before_price="20000", now_price="20000")  # 140.000 a week

    assert build_report(restaurant, today=NEWEST).products == []


@pytest.mark.django_db
def test_a_product_sold_without_a_cost_is_listed(restaurant):
    _history(_product(restaurant), before_cost="0", now_cost="0")

    report = build_report(restaurant, today=NEWEST)

    assert [stats.name for _pid, stats in report.uncosted] == ["PICANHA"]
    assert report.products == []


@pytest.mark.django_db
def test_the_recipe_says_which_supply_moved(restaurant):
    product = _product(restaurant)
    _history(product, before_cost="30000", now_cost="36000")
    supply = Supply.objects.create(restaurant=restaurant, clave="PIC", name="PICANHA ENTERA",
                                   unit="g", unit_cost=Decimal("78"))
    RecipeLine.objects.create(product=product, supply=supply, quantity=Decimal("450"))
    SupplyPrice.objects.create(supply=supply, date=datetime.date(2026, 5, 20),
                               unit_cost=Decimal("65"), supplier="Carnes X", invoice="FE-1")
    SupplyPrice.objects.create(supply=supply, date=datetime.date(2026, 7, 1),
                               unit_cost=Decimal("78"), supplier="Carnes X", invoice="FE-9")

    [alert] = build_report(restaurant, today=NEWEST).products
    [move] = alert.causes

    assert (move.name, move.before, move.after, move.invoice) == ("PICANHA ENTERA", Decimal("65"), Decimal("78"), "FE-9")


# -- abrupt changes ------------------------------------------------------------


@pytest.mark.django_db
def test_a_day_whose_pos_cost_jumps_is_an_abrupt_change(restaurant):
    product = _product(restaurant)
    _history(product)
    SaleItem.objects.filter(sale__external_id=f"{NEWEST}:{product.sku}").update(unit_cost=Decimal("36000"))

    report = build_report(restaurant, today=NEWEST)
    [jump] = [j for j in report.jumps if j.kind == "cost"]

    assert (jump.date, jump.before, jump.after) == (NEWEST, Decimal("30000"), Decimal("36000"))
    assert jump.change == Decimal("20") and jump.is_bad


@pytest.mark.django_db
def test_a_supplier_purchase_that_jumps_is_an_abrupt_change(restaurant):
    _history(_product(restaurant))
    supply = Supply.objects.create(restaurant=restaurant, clave="PIC", name="PICANHA ENTERA", unit="g")
    SupplyPrice.objects.create(supply=supply, date=datetime.date(2026, 6, 10), unit_cost=Decimal("65"))
    SupplyPrice.objects.create(supply=supply, date=datetime.date(2026, 7, 2), unit_cost=Decimal("80"),
                               supplier="Carnes X", invoice="FE-9")

    [jump] = [j for j in build_report(restaurant, today=NEWEST).jumps if j.kind == "supplier"]

    assert (jump.name, jump.supplier, round(jump.change, 1)) == ("PICANHA ENTERA", "Carnes X", Decimal("23.1"))


@pytest.mark.django_db
def test_the_threshold_for_abrupt_changes_is_the_restaurants(restaurant):
    product = _product(restaurant)
    _history(product)
    SaleItem.objects.filter(sale__external_id=f"{NEWEST}:{product.sku}").update(unit_cost=Decimal("36000"))
    settings = AlertSettings.for_restaurant(restaurant)
    settings.abrupt_change = Decimal("25")
    settings.save()

    assert build_report(restaurant, today=NEWEST).jumps == []


# -- supplier price history ------------------------------------------------------


def _payload(cost, date, invoice):
    return {"ok": True, "insumos": [{
        "clave": "PIC", "nombre": "PICANHA ENTERA", "unidad_consumo": "g",
        "ultimo_costo_con_impuestos": cost, "ultima_compra_fecha": date,
        "ultima_compra_proveedor": "Carnes X", "ultima_compra_factura": invoice,
    }]}


@pytest.mark.django_db
def test_each_new_purchase_is_kept(restaurant):
    sync_supplies(restaurant, _payload(65, "2026-06-10", "FE-1"))
    sync_supplies(restaurant, _payload(65, "2026-06-10", "FE-1"))  # same purchase again
    sync_supplies(restaurant, _payload(80, "2026-07-02", "FE-9"))

    prices = list(SupplyPrice.objects.values_list("unit_cost", "invoice"))

    assert prices == [(Decimal("65.0000"), "FE-1"), (Decimal("80.0000"), "FE-9")]


@pytest.mark.django_db
def test_the_daily_sync_skips_restaurants_without_a_token(restaurant, capsys):
    call_command("sync_all_supplies")

    assert "0 synced, 0 failed" in capsys.readouterr().out


# -- the page --------------------------------------------------------------------


@pytest.mark.django_db
def test_the_page_shows_what_slipped(logged_client, restaurant):
    _history(_product(restaurant), before_cost="30000", now_cost="34500")

    response = logged_client.get(reverse("alerts:report"), {"as_of": NEWEST.isoformat()})
    body = response.content.decode()

    assert response.status_code == 200
    assert "PICANHA" in body
    assert "Products that lost profitability" in body
    assert response.context["report"].days_behind == 0  # a past period is never behind


@pytest.mark.django_db
def test_another_restaurants_sales_stay_out(logged_client, restaurant, other_restaurant):
    _history(_product(other_restaurant), before_cost="30000", now_cost="34500")

    response = logged_client.get(reverse("alerts:report"))

    assert response.context["report"] is None


@pytest.mark.django_db
def test_the_settings_are_saved(logged_client, restaurant):
    logged_client.post(reverse("alerts:settings"), {
        "cadence": "month", "baseline": "last_year", "cost_rise": "8",
        "margin_drop": "4", "abrupt_change": "20", "min_weekly_sales": "500000",
    })

    settings = AlertSettings.for_restaurant(restaurant)
    assert (settings.cadence, settings.baseline, settings.abrupt_change) == ("month", "last_year", Decimal("20"))


@pytest.mark.django_db
def test_the_report_downloads_as_excel_and_pdf(logged_client, restaurant):
    _history(_product(restaurant), before_cost="30000", now_cost="34500")
    query = {"as_of": NEWEST.isoformat()}

    excel = logged_client.get(reverse("alerts:export_xlsx"), query)
    pdf = logged_client.get(reverse("alerts:export_pdf"), query)

    assert excel["Content-Type"].startswith("application/vnd.openxmlformats")
    assert excel.content[:2] == b"PK"
    assert pdf["Content-Type"] == "application/pdf" and pdf.content[:4] == b"%PDF"
