"""Tests for days of the week and holidays (US51)."""
import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from analytics.days import (
    between_weekdays,
    holiday_calendar,
    holiday_report,
    open_days,
    upcoming_holidays,
    weekday_profile,
)
from sales.models import DailySummary

# 2026-03-23 is San José, moved to Monday by the Emiliani law.
SAN_JOSE = datetime.date(2026, 3, 23)


def _covers(restaurant, day, sales, guests=20):
    DailySummary.objects.create(
        restaurant=restaurant, date=day, guests=guests, accounts=guests // 2,
        bar_sales=Decimal(sales) / 2, kitchen_sales=Decimal(sales) / 2,
    )


def test_the_calendar_knows_emiliani_mondays():
    calendar = holiday_calendar(datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))
    assert SAN_JOSE in calendar
    assert SAN_JOSE.weekday() == 0


@pytest.mark.django_db
def test_a_day_with_no_sales_and_no_people_is_not_open(restaurant):
    _covers(restaurant, datetime.date(2026, 3, 20), "5000000")
    _covers(restaurant, datetime.date(2026, 3, 21), "0", guests=0)

    days = open_days(restaurant)

    assert [d.date for d in days] == [datetime.date(2026, 3, 20)]


@pytest.mark.django_db
def test_weekday_averages_leave_holidays_out(restaurant):
    _covers(restaurant, datetime.date(2026, 3, 16), "9000000")  # ordinary Monday
    _covers(restaurant, SAN_JOSE, "3000000")                     # holiday Monday
    _covers(restaurant, datetime.date(2026, 3, 21), "10000000")  # Saturday

    profile = weekday_profile(open_days(restaurant))

    assert profile[0].days == 1 and profile[0].avg_sales == Decimal("9000000")
    assert profile[5].avg_sales == Decimal("10000000")


@pytest.mark.django_db
def test_a_holiday_is_compared_with_an_ordinary_day(restaurant):
    _covers(restaurant, datetime.date(2026, 3, 20), "4000000")
    _covers(restaurant, datetime.date(2026, 3, 21), "8000000")
    _covers(restaurant, SAN_JOSE, "3000000")
    days = open_days(restaurant)

    [holiday] = holiday_report(days, datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))

    assert holiday.opened and holiday.name
    assert holiday.change == Decimal("-50")  # against the 6.000.000 ordinary average


@pytest.mark.django_db
def test_a_holiday_after_the_newest_report_is_not_called_closed(restaurant):
    _covers(restaurant, datetime.date(2026, 3, 1), "4000000")
    days = open_days(restaurant)

    [holiday] = holiday_report(days, datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))

    assert not holiday.opened
    assert not holiday.reported


def test_a_figure_is_placed_between_two_weekdays():
    from analytics.days import Weekday

    profile = [
        Weekday(1, 4, Decimal("2000000"), None),
        Weekday(2, 4, Decimal("6000000"), None),
        Weekday(5, 4, Decimal("10000000"), None),
    ]

    below, above = between_weekdays(Decimal("4000000"), profile)

    assert (below.weekday, above.weekday) == (1, 2)


@pytest.mark.django_db
def test_upcoming_holidays_expect_what_the_same_weekday_sold(restaurant):
    _covers(restaurant, SAN_JOSE, "3000000")
    _covers(restaurant, datetime.date(2026, 6, 8), "5000000")  # Corpus Christi, Monday

    upcoming = upcoming_holidays(restaurant, today=datetime.date(2026, 11, 26))
    mondays = [u for u in upcoming if u.date.weekday() == 0]

    assert mondays and mondays[0].expected == Decimal("4000000")
    assert mondays[0].samples == 2


@pytest.mark.django_db
def test_the_page_says_what_a_holiday_monday_sells(logged_client, restaurant):
    _covers(restaurant, datetime.date(2026, 3, 17), "2000000")  # Tuesday
    _covers(restaurant, datetime.date(2026, 3, 18), "6000000")  # Wednesday
    _covers(restaurant, SAN_JOSE, "4000000")

    body = logged_client.get(reverse("analytics:days")).content.decode()

    assert "More than an ordinary Tuesday, less than an ordinary Wednesday" in body


@pytest.mark.django_db
def test_without_covers_the_pos_sales_are_used(logged_client, restaurant):
    from catalog.models import Category, Product
    from sales.models import Sale, SaleItem
    from django.utils import timezone

    category = Category.objects.create(restaurant=restaurant, name="Cortes")
    product = Product.objects.create(
        restaurant=restaurant, name="RIBEYE", sku="1", category=category,
        cost_price=Decimal("1"), sale_price=Decimal("10"),
    )
    sale = Sale.objects.create(
        restaurant=restaurant, external_id="x",
        occurred_at=timezone.make_aware(datetime.datetime(2026, 3, 21, 12)),
        total=Decimal("100"),
    )
    SaleItem.objects.create(sale=sale, product=product, quantity=10,
                            unit_price=Decimal("10"), unit_cost=Decimal("1"))

    days = open_days(restaurant)

    assert [(d.date, d.sales, d.guests) for d in days] == [
        (datetime.date(2026, 3, 21), Decimal("100.00"), None)
    ]
