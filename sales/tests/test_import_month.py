"""Importing a folder of daily reports without falling into its traps (US38)."""
from io import StringIO

import pytest
from django.core.management import call_command
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas

from sales.models import Sale
from sales.services import AggregateReportError, run_import


def _report(path, *, start, end, price="20,000.00", quantity="5.00"):
    """A Productos-Vendidos report covering the given period."""
    lines = [
        "TRES CUATRO CINCO STEAKHOUSE",
        f"PRODUCTOS VENDIDOS DEL {start} 06:00:00 AM AL {end} 06:00:00 AM",
        "GRUPO:COCTELES",
        f"8100 NEGRONI ${price} {quantity} $100,000.00 $6,000.00 "
        "$0.00 $0.00 $0.00 $0.00",
        "BEBIDAS: $100,000.00 (100%) 5 $30,000.00 $70,000.00",
        "ALIMENTOS: $0.00 (0%) 0 $0.00 $0.00",
    ]
    pdf = canvas.Canvas(str(path), pagesize=landscape(letter))
    pdf.setFont("Helvetica", 8)
    y = 560
    for line in lines:
        pdf.drawString(30, y, line)
        y -= 14
    pdf.save()
    return path


@pytest.mark.django_db
def test_an_aggregate_is_refused(tmp_path, restaurant):
    """A month printed in the daily layout must not become one giant day."""
    monthly = _report(tmp_path / "mes.pdf", start="01/06/2026", end="01/07/2026")

    with pytest.raises(AggregateReportError, match="30 days"):
        run_import(monthly, restaurant, filename="mes.pdf", source="cli")

    assert Sale.objects.count() == 0


@pytest.mark.django_db
def test_an_aggregate_can_be_imported_on_purpose(tmp_path, restaurant):
    monthly = _report(tmp_path / "mes.pdf", start="01/06/2026", end="01/07/2026")

    run_import(
        monthly, restaurant, filename="mes.pdf", source="cli", allow_aggregate=True
    )

    assert Sale.objects.count() == 1


@pytest.mark.django_db
def test_folder_skips_the_aggregate_and_imports_the_days(tmp_path, restaurant):
    _report(tmp_path / "dia01.pdf", start="01/06/2026", end="02/06/2026")
    _report(tmp_path / "dia02.pdf", start="02/06/2026", end="03/06/2026")
    _report(tmp_path / "mes.pdf", start="01/06/2026", end="01/07/2026")
    out = StringIO()

    call_command(
        "import_month", "--dir", str(tmp_path), "--restaurant", restaurant.slug,
        stdout=out,
    )

    assert Sale.objects.filter(restaurant=restaurant).count() == 2
    assert "an aggregate" in out.getvalue()


@pytest.mark.django_db
def test_the_fullest_file_wins_a_repeated_date(tmp_path, restaurant):
    """One file is a slice of the day ("por una cuenta"); the full day must win."""
    _report(tmp_path / "17 (por una cuenta).pdf", start="17/04/2026",
            end="18/04/2026", price="1,000.00", quantity="1.00")
    full = tmp_path / "17.pdf"
    _report(full, start="17/04/2026", end="18/04/2026")
    # Make the full day unmistakably larger in the footer the tie-break reads.
    out = StringIO()

    call_command(
        "import_month", "--dir", str(tmp_path), "--restaurant", restaurant.slug,
        stdout=out,
    )

    # Only one day landed, and the partial was reported as skipped.
    assert Sale.objects.filter(restaurant=restaurant).count() == 1
    assert "partial report for 2026-04-17" in out.getvalue()


@pytest.mark.django_db
def test_dry_run_touches_nothing(tmp_path, restaurant):
    _report(tmp_path / "dia01.pdf", start="01/06/2026", end="02/06/2026")
    out = StringIO()

    call_command(
        "import_month", "--dir", str(tmp_path), "--restaurant", restaurant.slug,
        "--dry-run", stdout=out,
    )

    assert Sale.objects.count() == 0
    assert "Dry run" in out.getvalue()
