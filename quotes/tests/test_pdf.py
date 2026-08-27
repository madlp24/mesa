"""The client-facing PDF: it must carry prices and never cost."""
from decimal import Decimal
from io import BytesIO

import pdfplumber
import pytest
from django.urls import reverse

from quotes.models import Course, Quote, QuoteLine
from quotes.pdf import render_quote_pdf
from tenants.models import Restaurant


def _text_of(data: bytes) -> str:
    """Read the PDF back the way a client would, not as raw bytes.

    reportlab compresses page streams, so grepping the file for a string
    silently passes whether or not the string is on the page.
    """
    with pdfplumber.open(BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _quote_with_lines(restaurant):
    quote = Quote.objects.create(
        restaurant=restaurant, number="CA-119", client_name="Laura", guests=20
    )
    QuoteLine.objects.create(
        quote=quote, course=Course.MAINS, name="Picanha americana",
        description="Cut served at the centre of the table.",
        quantity=Decimal(6), unit_price=Decimal(320000), unit_cost=Decimal(77777),
    )
    return quote


@pytest.mark.django_db
class TestRender:
    def test_produces_a_pdf(self, restaurant):
        data = render_quote_pdf(_quote_with_lines(restaurant))

        assert data.startswith(b"%PDF")
        assert data.rstrip().endswith(b"%%EOF")

    def test_carries_the_client_facing_content(self, restaurant):
        text = _text_of(render_quote_pdf(_quote_with_lines(restaurant)))

        assert "CA-119" in text
        assert "Laura" in text
        assert "Picanha americana" in text
        assert "320.000" in text

    def test_never_leaks_cost_or_margin(self, restaurant):
        """The quote goes to the client; what it costs the house is not theirs."""
        quote = _quote_with_lines(restaurant)
        text = _text_of(render_quote_pdf(quote))

        assert "77.777" not in text
        assert "77777" not in text
        for word in ("Cost", "Costo", "Margin", "Margen", "Profit", "Utilidad"):
            assert word not in text

    def test_a_long_menu_paginates(self, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-120", guests=10)
        for i in range(40):
            QuoteLine.objects.create(
                quote=quote, course=Course.STARTERS, name=f"Dish {i}",
                description="A description long enough to take a couple of lines on the page. " * 2,
                quantity=Decimal(10), unit_price=Decimal(30000), unit_cost=Decimal(9000),
            )

        with pdfplumber.open(BytesIO(render_quote_pdf(quote))) as pdf:
            assert len(pdf.pages) > 1

    def test_an_empty_quote_still_renders(self, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-121")

        assert render_quote_pdf(quote).startswith(b"%PDF")


@pytest.mark.django_db
class TestDownload:
    def test_downloads_as_an_attachment(self, logged_client, restaurant):
        quote = _quote_with_lines(restaurant)

        response = logged_client.get(reverse("quotes:quote_pdf", args=[quote.pk]))

        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert "attachment" in response["Content-Disposition"]
        assert "CA-119" in response["Content-Disposition"]

    def test_another_tenant_quote_cannot_be_downloaded(self, logged_client):
        other = Restaurant.objects.create(name="Other", slug="other-r")
        theirs = Quote.objects.create(restaurant=other, number="CA-500")

        response = logged_client.get(reverse("quotes:quote_pdf", args=[theirs.pk]))

        assert response.status_code == 404
