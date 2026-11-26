"""Tests for the periods and the overview the dashboard reads (US49)."""
import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from analytics.overview import overview
from analytics.periods import window_for
from catalog.models import Category, Product
from sales.models import DailySummary, Sale, SaleItem

TODAY = datetime.date(2026, 11, 25)


def _sale(product, day, *, price="10000", cost="4000", qty=1, key=None):
    moment = timezone.make_aware(datetime.datetime.combine(day, datetime.time(12)))
    sale = Sale.objects.create(
        restaurant=product.restaurant, external_id=key or f"{day}:{product.sku}",
        occurred_at=moment, total=Decimal(price) * qty,
    )
    SaleItem.objects.create(
        sale=sale, product=product, quantity=qty,
        unit_price=Decimal(price), unit_cost=Decimal(cost),
    )


@pytest.fixture
def product(restaurant):
    category = Category.objects.create(restaurant=restaurant, name="Cortes")
    return Product.objects.create(
        restaurant=restaurant, name="PICANHA", sku="1", category=category,
        cost_price=Decimal("4000"), sale_price=Decimal("10000"),
    )


# -- periods ----------------------------------------------------------------


@pytest.mark.django_db
def test_the_default_window_ends_on_the_newest_sale(restaurant, product):
    _sale(product, datetime.date(2026, 9, 26))

    window = window_for(restaurant, {}, today=TODAY)

    assert (window.start, window.end) == (datetime.date(2026, 8, 28), datetime.date(2026, 9, 26))
    assert window.days_behind == 59


@pytest.mark.django_db
def test_calendar_presets_follow_the_calendar(restaurant, product):
    _sale(product, datetime.date(2026, 9, 26))

    last_month = window_for(restaurant, {"period": "last_month"}, today=TODAY)
    this_year = window_for(restaurant, {"period": "year"}, today=TODAY)

    assert (last_month.start, last_month.end) == (datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
    assert this_year.start == datetime.date(2026, 1, 1)


@pytest.mark.django_db
def test_explicit_dates_win_and_are_put_in_order(restaurant):
    window = window_for(restaurant, {"start": "2026-03-31", "end": "2026-03-01"}, today=TODAY)

    assert (window.start, window.end, window.preset) == (
        datetime.date(2026, 3, 1), datetime.date(2026, 3, 31), "custom",
    )
    assert window.query == "start=2026-03-01&end=2026-03-31"


@pytest.mark.django_db
def test_the_previous_window_has_the_same_length(restaurant):
    window = window_for(restaurant, {"start": "2026-03-01", "end": "2026-03-10"}, today=TODAY)

    assert window.previous == (datetime.date(2026, 2, 19), datetime.date(2026, 2, 28))


# -- overview ---------------------------------------------------------------


@pytest.mark.django_db
def test_sales_are_compared_with_the_period_before(restaurant, product):
    _sale(product, datetime.date(2026, 3, 5), qty=3)   # 30.000 in the window
    _sale(product, datetime.date(2026, 2, 25), qty=2)  # 20.000 in the one before
    window = window_for(restaurant, {"start": "2026-03-01", "end": "2026-03-10"}, today=TODAY)

    result = overview(restaurant, window)

    assert result.revenue == Decimal("30000")
    assert result.revenue_change == Decimal("50")


@pytest.mark.django_db
def test_closed_days_stay_in_the_series_as_gaps(restaurant, product):
    _sale(product, datetime.date(2026, 3, 1))
    _sale(product, datetime.date(2026, 3, 3), qty=4)
    window = window_for(restaurant, {"start": "2026-03-01", "end": "2026-03-03"}, today=TODAY)

    result = overview(restaurant, window)

    assert [d["open"] for d in result.days] == [True, False, True]
    assert result.best_day["date"] == datetime.date(2026, 3, 3)


@pytest.mark.django_db
def test_the_bill_comes_from_the_covers_not_from_synthetic_sales(restaurant, product):
    _sale(product, datetime.date(2026, 3, 1), qty=10)
    DailySummary.objects.create(
        restaurant=restaurant, date=datetime.date(2026, 3, 1), guests=8, accounts=4,
        bar_sales=Decimal("40000"), kitchen_sales=Decimal("60000"),
    )
    window = window_for(restaurant, {"start": "2026-03-01", "end": "2026-03-01"}, today=TODAY)

    result = overview(restaurant, window)

    assert result.covers.per_account == Decimal("25000")
    assert result.covers.per_guest == Decimal("12500")


@pytest.mark.django_db
def test_products_sold_at_a_loss_are_listed_to_review(restaurant, product):
    _sale(product, datetime.date(2026, 3, 1), price="10000", cost="12000")
    window = window_for(restaurant, {"start": "2026-03-01", "end": "2026-03-01"}, today=TODAY)

    result = overview(restaurant, window)

    assert [p.name for p in result.at_a_loss] == ["PICANHA"]
    assert result.to_review >= 1


@pytest.mark.django_db
def test_the_dashboard_says_how_far_behind_the_reports_are(logged_client, product):
    _sale(product, timezone.localdate() - datetime.timedelta(days=40))

    body = logged_client.get(reverse("analytics:dashboard")).content.decode()

    assert "39 days are missing since then" in body
    assert reverse("sales:upload") in body


@pytest.mark.django_db
def test_a_preset_is_one_click(logged_client, product):
    _sale(product, timezone.localdate())

    response = logged_client.get(reverse("analytics:dashboard"), {"period": "7d"})

    assert response.context["window"].days == 7
    assert 'href="?period=7d" aria-current="true"' in response.content.decode()


@pytest.mark.django_db
def test_the_workbook_form_offers_the_month_of_the_newest_report(logged_client, product):
    _sale(product, datetime.date(2026, 9, 26))

    form = logged_client.get(reverse("analytics:workbook_update")).context["form"]

    assert (form.initial["year"], form.initial["month"]) == (2026, 9)
