"""Tests for correcting a re-imported day instead of skipping it (US48)."""
import datetime
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from catalog.models import Product
from sales.importers.canonical import CanonicalSale, CanonicalSaleItem
from sales.importers.persistence import persist
from sales.models import ImportBatch, Sale, SaleItem
from sales.services import undo_import


def _sale(day, clave, *, qty, price="10000", cost="4000", name=None):
    moment = timezone.make_aware(
        datetime.datetime.combine(datetime.date.fromisoformat(day), datetime.time(12))
    )
    item = CanonicalSaleItem(
        product_sku=clave, quantity=qty,
        unit_price=Decimal(price), unit_cost=Decimal(cost),
        product_name=name or f"PRODUCTO {clave}", category_name="COCINA",
    )
    return CanonicalSale(
        external_id=f"{day}:{clave}", occurred_at=moment,
        total=Decimal(price) * qty, items=[item],
    )


def _qty(restaurant, external_id):
    return SaleItem.objects.get(
        sale__restaurant=restaurant, sale__external_id=external_id
    ).quantity


# -- the partial report ---------------------------------------------------


@pytest.mark.django_db
def test_the_full_report_replaces_the_partial_one(restaurant):
    # Printed mid-service: the burger had sold 3; by close it had sold 8.
    persist([_sale("2026-09-26", "100", qty=3)], restaurant)

    result = persist(
        [_sale("2026-09-26", "100", qty=8), _sale("2026-09-26", "101", qty=2)],
        restaurant,
    )

    assert _qty(restaurant, "2026-09-26:100") == 8
    assert Sale.objects.get(external_id="2026-09-26:100").total == Decimal("80000")
    assert result["corrected"] == 1
    assert result["new"] == 1  # what the partial report had not seen yet
    assert result["skipped_duplicate"] == 0


@pytest.mark.django_db
def test_identical_figures_are_still_a_duplicate(restaurant):
    persist([_sale("2026-09-26", "100", qty=3)], restaurant)

    result = persist([_sale("2026-09-26", "100", qty=3)], restaurant)

    assert result["skipped_duplicate"] == 1
    assert result["corrected"] == 0


@pytest.mark.django_db
def test_a_figure_stored_rounded_is_still_a_duplicate(restaurant):
    # A spreadsheet carries 4166.666667; the database keeps 4166.67. The same
    # file imported twice must not "correct" itself.
    persist([_sale("2026-09-26", "100", qty=3, price="4166.666667")], restaurant)

    result = persist(
        [_sale("2026-09-26", "100", qty=3, price="4166.666667")], restaurant
    )

    assert result["skipped_duplicate"] == 1
    assert result["corrected"] == 0


@pytest.mark.django_db
def test_a_new_cost_on_the_same_takings_is_corrected(restaurant):
    # Same sales, cost recalculated in Soft: the total does not move, the
    # cost does, and the day's total is not lower -- so it is applied.
    persist([_sale("2026-09-26", "100", qty=3, cost="4000")], restaurant)

    result = persist([_sale("2026-09-26", "100", qty=3, cost="4500")], restaurant)

    assert result["corrected"] == 1
    item = SaleItem.objects.get(sale__external_id="2026-09-26:100")
    assert item.unit_cost == Decimal("4500")


@pytest.mark.django_db
def test_an_older_partial_copy_does_not_shrink_the_day(restaurant):
    persist(
        [_sale("2026-09-26", "100", qty=8), _sale("2026-09-26", "101", qty=2)],
        restaurant,
    )

    result = persist([_sale("2026-09-26", "100", qty=3)], restaurant)

    assert _qty(restaurant, "2026-09-26:100") == 8
    assert result["older_copy"] == 1
    assert result["corrected"] == 0


@pytest.mark.django_db
def test_each_day_is_judged_on_its_own(restaurant):
    persist(
        [_sale("2026-09-25", "100", qty=8), _sale("2026-09-26", "100", qty=3)],
        restaurant,
    )

    # One file carrying an older copy of the 25th and the full 26th.
    result = persist(
        [_sale("2026-09-25", "100", qty=5), _sale("2026-09-26", "100", qty=8)],
        restaurant,
    )

    assert _qty(restaurant, "2026-09-25:100") == 8
    assert _qty(restaurant, "2026-09-26:100") == 8
    assert (result["older_copy"], result["corrected"]) == (1, 1)


@pytest.mark.django_db
def test_a_sale_repeated_inside_one_file_is_a_duplicate(restaurant):
    result = persist(
        [_sale("2026-09-26", "100", qty=3), _sale("2026-09-26", "100", qty=8)],
        restaurant,
    )

    assert result == {
        "new": 1, "items": 1, "skipped_duplicate": 1, "corrected": 0, "older_copy": 0,
    }


@pytest.mark.django_db
def test_another_restaurants_sale_is_never_corrected(restaurant, other_restaurant):
    persist([_sale("2026-09-26", "100", qty=3)], other_restaurant)

    result = persist([_sale("2026-09-26", "100", qty=8)], restaurant)

    assert result["new"] == 1
    assert _qty(other_restaurant, "2026-09-26:100") == 3


@pytest.mark.django_db
def test_a_correction_refreshes_the_product_price(restaurant):
    persist([_sale("2026-09-26", "100", qty=3, price="10000")], restaurant)

    persist([_sale("2026-09-26", "100", qty=8, price="12000")], restaurant)

    product = Product.objects.get(restaurant=restaurant, sku="100")
    assert product.sale_price == Decimal("12000.00")


# -- undo -------------------------------------------------------------------


@pytest.fixture
def corrected_day(restaurant):
    first = ImportBatch.objects.create(restaurant=restaurant, filename="parcial.pdf")
    persist([_sale("2026-09-26", "100", qty=3)], restaurant, first)
    second = ImportBatch.objects.create(restaurant=restaurant, filename="completo.pdf")
    persist(
        [_sale("2026-09-26", "100", qty=8), _sale("2026-09-26", "101", qty=2)],
        restaurant,
        second,
    )
    second.sales_corrected = 1
    second.save()
    return first, second


@pytest.mark.django_db
def test_undoing_the_correcting_import_keeps_the_correction(restaurant, corrected_day):
    _first, second = corrected_day

    deleted = undo_import(second)

    assert deleted == 1  # only the sale it created
    assert _qty(restaurant, "2026-09-26:100") == 8


@pytest.mark.django_db
def test_the_corrected_sale_stays_in_its_original_batch(restaurant, corrected_day):
    first, _second = corrected_day

    undo_import(first)

    assert not Sale.objects.filter(external_id="2026-09-26:100").exists()


@pytest.mark.django_db
def test_the_undo_page_says_a_correction_stays(logged_client, restaurant, corrected_day):
    _first, second = corrected_day

    response = logged_client.post(
        reverse("sales:undo_import", args=[second.pk]), follow=True
    )

    assert "a correction cannot be undone" in response.content.decode()


@pytest.mark.django_db
def test_the_history_flags_a_correcting_import(logged_client, restaurant, corrected_day):
    response = logged_client.get(reverse("sales:upload"))

    body = response.content.decode()
    assert "1 corrected" in body
    assert "the ones it corrected stay corrected" in body


# -- the command ------------------------------------------------------------


@pytest.mark.django_db
def test_run_import_records_the_corrections(restaurant, monkeypatch, tmp_path):
    from sales import services

    class _Importer:
        def __init__(self, sales):
            self.sales = sales

        def normalize(self, path):
            return self.sales

    monkeypatch.setattr(
        services, "get_importer_for",
        lambda path: _Importer([_sale("2026-09-26", "100", qty=3)]),
    )
    services.run_import(tmp_path / "a.pdf", restaurant, filename="a.pdf", source="cli")
    monkeypatch.setattr(
        services, "get_importer_for",
        lambda path: _Importer([_sale("2026-09-26", "100", qty=8)]),
    )

    batch = services.run_import(
        tmp_path / "b.pdf", restaurant, filename="b.pdf", source="cli"
    )

    assert (batch.sales_corrected, batch.skipped_older) == (1, 0)


@pytest.mark.django_db
def test_import_sales_reports_corrections(restaurant, monkeypatch, tmp_path):
    batch = ImportBatch(
        restaurant=restaurant, filename="b.pdf", sales_corrected=4, skipped_older=2
    )
    monkeypatch.setattr(
        "sales.management.commands.import_sales.run_import", lambda *a, **k: batch
    )
    path = tmp_path / "b.pdf"
    path.write_bytes(b"%PDF")
    out = StringIO()

    call_command(
        "import_sales", file=str(path), restaurant=restaurant.slug, stdout=out
    )

    assert "4 sales corrected" in out.getvalue()
    assert "2 sales kept" in out.getvalue()
