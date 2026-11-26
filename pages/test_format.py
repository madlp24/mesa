"""Tests for number formatting and the side navigation (US49)."""
import pytest
from django.urls import reverse
from django.utils import translation

from pages.templatetags.mesa import change, cop, cop_short, pct, signed


def test_pesos_have_no_cents_and_follow_the_language():
    with translation.override("es"):
        assert cop("276436985.75") == "$276.436.986"
        assert cop_short("276436985.75") == "$276,4 M"
        assert pct("68.61") == "68,6 %"
    with translation.override("en"):
        assert cop("276436985.75") == "$276,436,986"
        assert pct("68.61") == "68.6%"


def test_missing_figures_print_a_dash_not_zero():
    assert cop(None) == "–"
    assert change(None) == "–"


def test_changes_carry_their_sign():
    with translation.override("en"):
        assert change("8.24") == "+8.2%"
        assert change("-3.1") == "−3.1%"
        assert signed("0.3") == "+0.3"
        assert cop(-1500) == "−$1,500"


@pytest.mark.django_db
def test_the_current_section_and_its_tabs_are_marked(logged_client):
    body = logged_client.get(reverse("analytics:margin_alerts")).content.decode()

    assert f'<a href="{reverse("analytics:margin_alerts")}" aria-current="page">' in body
    assert reverse("analytics:margin_analysis") in body  # the sibling tab


@pytest.mark.django_db
def test_visitors_get_no_side_navigation(client):
    body = client.get(reverse("pages:help")).content.decode()

    assert 'id="rail"' not in body
