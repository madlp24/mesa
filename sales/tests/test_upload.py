"""Tests for the self-service web upload (US25)."""
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas

from catalog.models import Product
from sales.models import Sale


def _report_pdf_bytes(day="01", month="05"):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=landscape(letter))
    pdf.setFont("Helvetica", 8)
    lines = [
        "TRES CUATRO CINCO STEAKHOUSE",
        (
            f"PRODUCTOS VENDIDOS DEL {day}/{month}/2026 06:00:00 AM AL "
            f"28/{month}/2026 06:00:00 AM"
        ),
        "GRUPO:COCTELES",
        (
            "8100 NEGRONI $20,000.00 5.00 $100,000.00 $6,000.00 "
            "$0.00 $0.00 $0.00 $0.00"
        ),
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
    assert b"multiple" in response.content  # accepts several files at once


@pytest.mark.django_db
def test_upload_imports_into_my_restaurant(logged_client, restaurant):
    upload = SimpleUploadedFile(
        "ventas.pdf", _report_pdf_bytes(), content_type="application/pdf"
    )
    response = logged_client.post(reverse("sales:upload"), {"report": upload})

    assert response.status_code == 200
    summaries = response.context["summaries"]
    assert len(summaries) == 1
    assert summaries[0]["new"] == 1
    assert summaries[0]["items"] == 1
    # Data landed in the uploader's restaurant.
    assert Sale.objects.filter(restaurant=restaurant).count() == 1
    product = Product.objects.get(restaurant=restaurant)
    assert product.name == "NEGRONI"


@pytest.mark.django_db
def test_upload_imports_several_files_at_once(logged_client, restaurant):
    files = [
        SimpleUploadedFile(
            "marzo-01.pdf", _report_pdf_bytes("01", "03"), content_type="application/pdf"
        ),
        SimpleUploadedFile(
            "marzo-02.pdf", _report_pdf_bytes("02", "03"), content_type="application/pdf"
        ),
    ]
    response = logged_client.post(reverse("sales:upload"), {"report": files})

    assert response.status_code == 200
    assert len(response.context["summaries"]) == 2
    # One sale per day -> two sales, each its own import batch.
    assert Sale.objects.filter(restaurant=restaurant).count() == 2
    from sales.models import ImportBatch
    assert ImportBatch.objects.filter(restaurant=restaurant).count() == 2


@pytest.mark.django_db
def test_upload_partial_failure_imports_the_good_files(logged_client, restaurant):
    good = SimpleUploadedFile(
        "ok.pdf", _report_pdf_bytes("05", "03"), content_type="application/pdf"
    )
    bad = SimpleUploadedFile(
        "broken.pdf", b"not a real pdf", content_type="application/pdf"
    )
    response = logged_client.post(reverse("sales:upload"), {"report": [good, bad]})

    assert response.status_code == 200
    # The good file imported; the bad one is reported but does not abort the batch.
    assert len(response.context["summaries"]) == 1
    assert Sale.objects.filter(restaurant=restaurant).count() == 1
    assert "broken.pdf" in response.content.decode()


@pytest.mark.django_db
def test_upload_rejects_unsupported_file_type(logged_client):
    upload = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")
    response = logged_client.post(reverse("sales:upload"), {"report": upload})

    assert response.status_code == 200
    assert response.context["summaries"] == []
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
    assert response.context["summaries"] == []
    assert Sale.objects.count() == 0
