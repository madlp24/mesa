"""Identity resolution exercised through the full PDF import path (US22)."""
from io import StringIO

import pytest
from django.core.management import call_command
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas

from catalog.models import Product, ProductAlias
from sales.models import SaleItem


def _product_line(clave, desc, price, qty, total, unit_cost):
    # CLAVE DESC $price qty $total $unit_cost then four trailing money columns.
    return (
        f"{clave} {desc} ${price} {qty} ${total} ${unit_cost} "
        f"$0.00 $0.00 $0.00 $0.00"
    )


def _write_report(path, period_start, lines):
    pdf = canvas.Canvas(str(path), pagesize=landscape(letter))
    pdf.setFont("Helvetica", 8)
    y = 560
    header = (
        f"PRODUCTOS VENDIDOS DEL {period_start} 06:00:00 AM AL "
        "01/07/2026 06:00:00 AM"
    )
    for line in ["TRES CUATRO CINCO STEAKHOUSE", header, *lines]:
        pdf.drawString(30, y, line)
        y -= 14
    pdf.save()


@pytest.mark.django_db
def test_prefix_variant_fuses_across_two_imports(tmp_path):
    # May report: bare "Negroni" under clave 8100.
    may = tmp_path / "may.pdf"
    _write_report(
        may,
        "01/05/2026",
        ["GRUPO:COCTELES", _product_line("8100", "NEGRONI", "20,000.00", "5.00",
                                         "100,000.00", "6,000.00")],
    )
    # June report: same clave, brand appended -> "Negroni Tanqueray".
    june = tmp_path / "june.pdf"
    _write_report(
        june,
        "01/06/2026",
        ["GRUPO:COCTELES", _product_line("8100", "NEGRONI TANQUERAY", "22,000.00",
                                         "7.00", "154,000.00", "7,000.00")],
    )

    call_command("import_sales", "--file", str(may), stdout=StringIO())
    call_command("import_sales", "--file", str(june), stdout=StringIO())

    # One canonical product, two POS identities recorded, two sales attributed.
    assert Product.objects.count() == 1
    product = Product.objects.get()
    assert product.sale_items.count() == 2
    assert ProductAlias.objects.filter(product=product).count() == 2


@pytest.mark.django_db
def test_meat_quantity_stays_in_grams(tmp_path):
    report = tmp_path / "meat.pdf"
    _write_report(
        report,
        "01/06/2026",
        [
            "GRUPO:CARNE PRIME",
            _product_line("2001", "TOMAHAWK*GR", "180.00", "2656.00",
                          "478,080.00", "70.00"),
        ],
    )

    call_command("import_sales", "--file", str(report), stdout=StringIO())

    item = SaleItem.objects.get()
    assert item.quantity == 2656  # grams, as reported
    # The "*GR" marker is preserved in the stored name but ignored for matching.
    assert Product.objects.get().name == "TOMAHAWK*GR"
