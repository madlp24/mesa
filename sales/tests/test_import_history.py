"""Import history and undo tests (US28)."""
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas

from sales.models import ImportBatch, Sale
from tenants.models import Restaurant


def _report_pdf(clave="8100", name="NEGRONI", qty="5.00"):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=landscape(letter))
    pdf.setFont("Helvetica", 8)
    lines = [
        "TRES CUATRO CINCO STEAKHOUSE",
        "PRODUCTOS VENDIDOS DEL 01/05/2026 06:00:00 AM AL 01/06/2026 06:00:00 AM",
        "GRUPO:COCTELES",
        f"{clave} {name} $20,000.00 {qty} $100,000.00 $6,000.00 $0 $0 $0 $0",
    ]
    y = 560
    for line in lines:
        pdf.drawString(30, y, line)
        y -= 14
    pdf.save()
    return SimpleUploadedFile(f"{name}.pdf", buffer.getvalue(), content_type="application/pdf")


@pytest.mark.django_db
def test_upload_records_an_import_batch(logged_client, restaurant):
    logged_client.post(reverse("sales:upload"), {"report": _report_pdf()})

    batch = ImportBatch.objects.get(restaurant=restaurant)
    assert batch.source == "web"
    assert batch.sales_created == 1
    assert batch.items_created == 1
    # Each created sale is tagged with the batch.
    assert Sale.objects.filter(import_batch=batch).count() == 1


@pytest.mark.django_db
def test_history_lists_imports(logged_client, restaurant):
    logged_client.post(reverse("sales:upload"), {"report": _report_pdf()})
    response = logged_client.get(reverse("sales:upload"))
    assert list(response.context["imports"]) != []
    assert "NEGRONI.pdf" in response.content.decode()


@pytest.mark.django_db
def test_undo_removes_only_that_batchs_sales(logged_client, restaurant):
    logged_client.post(reverse("sales:upload"), {"report": _report_pdf("8100", "NEGRONI")})
    logged_client.post(reverse("sales:upload"), {"report": _report_pdf("8200", "MOJITO")})
    first = ImportBatch.objects.get(filename="NEGRONI.pdf")
    assert Sale.objects.count() == 2

    response = logged_client.post(reverse("sales:undo_import", args=[first.pk]))

    assert response.status_code == 302
    assert not ImportBatch.objects.filter(pk=first.pk).exists()
    assert Sale.objects.count() == 1  # only MOJITO's sale remains
    assert Sale.objects.filter(import_batch__filename="MOJITO.pdf").count() == 1


@pytest.mark.django_db
def test_undo_requires_post(logged_client, restaurant):
    logged_client.post(reverse("sales:upload"), {"report": _report_pdf()})
    batch = ImportBatch.objects.get()
    response = logged_client.get(reverse("sales:undo_import", args=[batch.pk]))
    assert response.status_code == 405  # GET not allowed


@pytest.mark.django_db
def test_cannot_undo_another_restaurants_import(logged_client, restaurant):
    other = Restaurant.objects.create(name="Otro", slug="otro")
    foreign = ImportBatch.objects.create(restaurant=other, filename="x.pdf", source="web")

    response = logged_client.post(reverse("sales:undo_import", args=[foreign.pk]))

    assert response.status_code == 404
    assert ImportBatch.objects.filter(pk=foreign.pk).exists()
