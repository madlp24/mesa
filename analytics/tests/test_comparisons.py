"""Comparing a period with the same one a year earlier (US42)."""
import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from analytics.comparisons import compare
from sales.models import DailySummary


def _day(restaurant, when, guests, accounts=1, sales=None):
    return DailySummary.objects.create(
        restaurant=restaurant, date=when, guests=guests, accounts=accounts,
        bar_sales=None if sales is None else Decimal(sales),
        kitchen_sales=None if sales is None else Decimal("0"),
    )


@pytest.mark.django_db
def test_a_month_is_compared_with_the_same_month_last_year(restaurant):
    _day(restaurant, datetime.date(2025, 8, 5), 100, 40, "1000")
    _day(restaurant, datetime.date(2026, 8, 5), 150, 50, "1500")

    august = compare(restaurant, "month")[0]

    assert august.label == "2026-08"
    assert august.guests == 150
    assert august.guests_change == pytest.approx(50)   # 100 -> 150
    assert august.sales_change == pytest.approx(50)


@pytest.mark.django_db
def test_days_inside_a_period_add_up(restaurant):
    _day(restaurant, datetime.date(2026, 8, 5), 10, 4, "100")
    _day(restaurant, datetime.date(2026, 8, 6), 15, 5, "200")

    august = compare(restaurant, "month")[0]

    assert (august.guests, august.accounts) == (25, 9)
    assert august.sales == Decimal("300")
    assert august.ticket_per_guest == Decimal("12")     # 300 / 25
    assert august.ticket_per_account == Decimal("300") / 9


@pytest.mark.django_db
def test_a_period_without_takings_still_reports_turnout(restaurant):
    """Turnout reaches back further than the money; say so instead of guessing."""
    _day(restaurant, datetime.date(2026, 8, 5), 10, 4, sales=None)

    august = compare(restaurant, "month")[0]

    assert august.guests == 10
    assert august.sales is None
    assert august.ticket_per_guest is None


@pytest.mark.django_db
def test_no_twin_last_year_means_no_change_shown(restaurant):
    _day(restaurant, datetime.date(2026, 8, 5), 10, 4, "100")

    august = compare(restaurant, "month")[0]

    assert august.guests_change is None
    assert august.sales_change is None


@pytest.mark.django_db
def test_weeks_line_up_by_their_position_in_the_year(restaurant):
    """Week 32 of 2026 compares with week 32 of 2025, not with 365 days back."""
    last_year = datetime.date.fromisocalendar(2025, 32, 1)
    this_year = datetime.date.fromisocalendar(2026, 32, 1)
    _day(restaurant, last_year, 40, 10, "400")
    _day(restaurant, this_year, 60, 15, "600")

    week = compare(restaurant, "week")[0]

    assert week.guests == 60
    assert week.guests_change == pytest.approx(50)


@pytest.mark.django_db
def test_page_requires_authentication(client):
    response = client.get(reverse("analytics:comparisons"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_page_renders_the_periods(logged_client, restaurant):
    _day(restaurant, datetime.date(2026, 8, 5), 150, 50, "1500")

    response = logged_client.get(reverse("analytics:comparisons"))

    assert response.status_code == 200
    assert "2026-08" in response.content.decode()
    assert response.context["grain"] == "month"


@pytest.mark.django_db
def test_an_unknown_grain_falls_back_to_months(logged_client, restaurant):
    response = logged_client.get(reverse("analytics:comparisons"), {"grain": "siglo"})
    assert response.context["grain"] == "month"
