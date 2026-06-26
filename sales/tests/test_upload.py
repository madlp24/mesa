"""Tests for the self-service web upload (US25)."""
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas

from catalog.models import Product
from sales.models import Sale


def _report_pdf_bytes():
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=landscape(letter))
    pdf.setFont("Helvetica", 8)
    lines = [
        "TRES CUATRO CINCO STEAKHOUSE",
        "PRODUCTOS VENDIDOS DEL 01/05/2026 06:00:00 AM AL 01/06/2026 06:00:00 AM",
        "GRUPO:COCTELES",
        "8100 NEGRONI $20,000.00 5.00 $100,000.00 $6,000.00 "
        "$0.00 $0.00 $0.00 $0.00",
    ]
    y = 560
    for line in lines:
        pdf.drawString(30, y, line)
        y -= 14
    pdf.save()
    return buffer.getvalue()


@pytest.mark.django_db
def test_upload_requires_authentication(client):
    response = client.get(reverse("sales:upload"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_upload_page_renders(logged_client):
    response = logged_client.get(reverse("sales:upload"))
    assert response.status_code == 200
    assert b"type=\"file\"" in response.content


@pytest.mark.django_db
def test_upload_imports_into_my_restaurant(logged_client, restaurant):
    upload = SimpleUploadedFile(
        "ventas.pdf", _report_pdf_bytes(), content_type="application/pdf"
    )
    response = logged_client.post(reverse("sales:upload"), {"report": upload})

    assert response.status_code == 200
    summary = response.context["summary"]
    assert summary["new"] == 1
    assert summary["items"] == 1
    # Data landed in the uploader's restaurant.
    assert Sale.objects.filter(restaurant=restaurant).count() == 1
    product = Product.objects.get(restaurant=restaurant)
    assert product.name == "NEGRONI"


@pytest.mark.django_db
def test_upload_rejects_unsupported_file_type(logged_client):
    upload = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")
    response = logged_client.post(reverse("sales:upload"), {"report": upload})

    assert response.status_code == 200
    assert response.context["summary"] is None
    assert Sale.objects.count() == 0
    assert "Unsupported file type" in response.content.decode()


@pytest.mark.django_db
def test_upload_handles_unreadable_report(logged_client):
    # A .pdf that is not actually a parseable report -> friendly error, no 500.
    upload = SimpleUploadedFile(
        "broken.pdf", b"not a real pdf", content_type="application/pdf"
    )
    response = logged_client.post(reverse("sales:upload"), {"report": upload})

    assert response.status_code == 200
    assert response.context["summary"] is None
    assert Sale.objects.count() == 0
