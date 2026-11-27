"""Tests for the cuts in kilos (US57)."""
import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from analytics.meat import meat_report
from catalog.models import Category, Product
from catalog.portions import grams_per_unit
from sales.models import Sale, SaleItem

DAY = datetime.date(2026, 3, 10)
BEFORE = (datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))


def _cut(restaurant, name, *, price="100000", group="CORTES", unit_grams=None):
    category, _ = Category.objects.get_or_create(restaurant=restaurant, name=group)
    return Product.objects.create(
        restaurant=restaurant, name=name, sku=name[:20], category=category,
        cost_price=Decimal("1"), sale_price=Decimal(price), unit_grams=unit_grams,
    )


def _sell(product, day, qty, price="100000", cost="30000"):
    sale = Sale.objects.create(
        restaurant=product.restaurant, external_id=f"{day}:{product.sku}:{qty}",
        occurred_at=timezone.make_aware(datetime.datetime.combine(day, datetime.time(12))),
        total=Decimal(price) * qty,
    )
    SaleItem.objects.create(sale=sale, product=product, quantity=qty,
                            unit_price=Decimal(price), unit_cost=Decimal(cost))


# -- grams per unit ----------------------------------------------------------------


@pytest.mark.django_db
def test_grams_per_unit_come_from_the_owner_the_name_or_the_price(restaurant):
    assert grams_per_unit(_cut(restaurant, "PORTERHOUSE *GR", price="398")) == (1, "name")
    assert grams_per_unit(_cut(restaurant, "PICANHA AMERICANA *420GR")) == (420, "name")
    # No marker, but no steak costs 700 a unit: the price is per gram.
    assert grams_per_unit(_cut(restaurant, "TOMAHAWK MADURADO 45 DIAS", price="700")) == (1, "price")
    assert grams_per_unit(_cut(restaurant, "RIBEYE AMERICANO", price="222222")) == (None, "missing")
    assert grams_per_unit(_cut(restaurant, "ENTRANA", unit_grams=350)) == (350, "set")


# -- the report --------------------------------------------------------------------


@pytest.mark.django_db
def test_kilos_add_up_gram_and_portion_sales(restaurant):
    _sell(_cut(restaurant, "PORTERHOUSE *GR", price="400"), DAY, 2500, price="400", cost="100")
    _sell(_cut(restaurant, "PICANHA *420GR"), DAY, 10)  # 4,2 kg

    report = meat_report(restaurant, datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), previous=BEFORE)

    assert report.kilos == Decimal("6.7")
    assert [c.name for c in report.cuts] == ["PICANHA *420GR", "PORTERHOUSE *GR"]
    assert report.cuts[1].price_per_kilo == Decimal("400000")
    assert report.cuts[1].cost_per_kilo == Decimal("100000")


@pytest.mark.django_db
def test_a_portion_without_a_weight_is_listed_not_guessed(restaurant):
    _sell(_cut(restaurant, "RIBEYE AMERICANO", price="222222"), DAY, 10)

    report = meat_report(restaurant, datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), previous=BEFORE)

    assert report.kilos == 0
    assert [c.name for c in report.unweighed] == ["RIBEYE AMERICANO"]


@pytest.mark.django_db
def test_only_cuts_count(restaurant):
    _sell(_cut(restaurant, "PICANHA *420GR"), DAY, 10)
    _sell(_cut(restaurant, "CROQUETAS *4UND", group="ENTRADAS"), DAY, 10)

    report = meat_report(restaurant, datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), previous=BEFORE)

    assert [c.name for c in report.cuts] == ["PICANHA *420GR"]


@pytest.mark.django_db
def test_the_change_is_against_the_period_before(restaurant):
    picanha = _cut(restaurant, "PICANHA *420GR")
    _sell(picanha, datetime.date(2026, 2, 10), 10)
    _sell(picanha, DAY, 15)

    report = meat_report(restaurant, datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), previous=BEFORE)

    assert (report.kilos, report.before_kilos, report.change) == (Decimal("6.3"), Decimal("4.2"), Decimal("50"))


@pytest.mark.django_db
def test_kilos_are_grouped_by_month_or_week(restaurant):
    picanha = _cut(restaurant, "PICANHA *420GR")
    _sell(picanha, datetime.date(2026, 3, 2), 10)
    _sell(picanha, datetime.date(2026, 3, 10), 5)

    by_month = meat_report(restaurant, datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), previous=BEFORE)
    by_week = meat_report(restaurant, datetime.date(2026, 3, 1), datetime.date(2026, 3, 31),
                          previous=BEFORE, grain="week")

    assert by_month.series()["series"][0]["data"] == [6.3]
    weeks = dict(zip(by_week.series()["labels"], by_week.series()["series"][0]["data"]))
    assert (weeks["2026-03-02"], weeks["2026-03-09"]) == (4.2, 2.1)


# -- the page ----------------------------------------------------------------------


@pytest.mark.django_db
def test_the_page_shows_kilos_and_asks_for_missing_weights(logged_client, restaurant):
    today = timezone.localdate()
    _sell(_cut(restaurant, "PICANHA *420GR"), today, 10)
    _sell(_cut(restaurant, "RIBEYE AMERICANO", price="222222"), today, 5)

    response = logged_client.get(reverse("analytics:meat"))
    body = response.content.decode()

    assert response.status_code == 200
    assert "4.2 kg" in body
    assert "RIBEYE AMERICANO" in body and "does not know how much a portion weighs" in body


@pytest.mark.django_db
def test_a_typed_weight_is_saved(logged_client, restaurant):
    ribeye = _cut(restaurant, "RIBEYE AMERICANO", price="222222")
    theirs = Product.objects.create(
        restaurant=Category.objects.create(restaurant=restaurant.__class__.objects.create(
            name="Otro", slug="otro"), name="CORTES").restaurant,
        name="X", sku="X", category=Category.objects.get(restaurant__slug="otro"),
        cost_price=Decimal("1"), sale_price=Decimal("1"),
    )

    logged_client.post(reverse("analytics:meat"), {f"grams-{ribeye.pk}": "450", f"grams-{theirs.pk}": "300"})

    ribeye.refresh_from_db()
    theirs.refresh_from_db()
    assert ribeye.unit_grams == 450
    assert theirs.unit_grams is None  # another restaurant's product is never touched
