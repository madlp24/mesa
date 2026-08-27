"""The client-facing PDF: it must carry prices and never cost."""
from decimal import Decimal
from io import BytesIO

import pdfplumber
import pytest
from django.urls import reverse

from quotes.models import Course, PricingMode, Quote, QuoteLine
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


@pytest.mark.django_db
class TestFitsOnePage:
    def test_the_first_real_quote_fits_on_one_page(self, restaurant):
        """CA-120, line for line. A second page holding only the totals reads
        as a mistake on a document that goes to a client, and this quote missed
        fitting by under two points."""
        quote = Quote.objects.create(
            restaurant=restaurant, number="CA-120", client_name="Fundación Karisma",
            concept="Almuerzo corporativo · 1 y 2 de septiembre", guests=12, days=2,
            payment_terms="50% anticipo, 50% en el evento",
            pricing_mode=PricingMode.PER_GUEST, price_per_guest=Decimal("180000"),
            charges_tip=False,
        )
        lines = [
            (Course.STARTERS, "Croquetas de lomo ahumado (3 und)",
             "Lomo de res ahumado, bechamel, sashimi de atún, salsa ponzu y salsa de aguacate y tomatillo.", 12, 44000),
            (Course.STARTERS, "Ensalada de la casa",
             "Mix asiático, supremas de naranja, pistachos, tomate cherry, encurtido de cebolla y rábano, vinagreta cítrica.", 4, 29000),
            (Course.MAINS, "Picanha americana (420 g)", "", 6, 126000),
            (Course.SIDES, "Patatas fritas con grana padano", "", 4, 21000),
            (Course.SIDES, "Vegetales ahumados", "", 4, 21000),
            (Course.DESSERTS, "Postre de limón deconstruido",
             "Galleta de mantequilla con canela, crema de limón, merengue tostado y polvo de limón.", 12, 30000),
            (Course.SOFT, "Bebidas sin alcohol a elección",
             "Para escoger entre aguas, sodas y sodas de la casa.", 12, 10000),
        ]
        for position, (course, name, description, qty, price) in enumerate(lines):
            QuoteLine.objects.create(
                quote=quote, course=course, name=name, description=description,
                quantity=Decimal(qty), unit_price=Decimal(price),
                unit_cost=Decimal(price) / 4, position=position,
            )

        with pdfplumber.open(BytesIO(render_quote_pdf(quote))) as pdf:
            assert len(pdf.pages) == 1
            text = pdf.pages[0].extract_text()
            assert "TOTAL" in text
            assert "4.320.000" in text

    def test_the_totals_never_land_on_the_footer(self, restaurant):
        """The block may sit low, but not on top of the footer rule."""
        quote = Quote.objects.create(restaurant=restaurant, number="CA-121", guests=1)
        for i in range(9):
            QuoteLine.objects.create(
                quote=quote, course=Course.MAINS, name=f"Dish {i}",
                description="A description that wraps onto a second line of its own. " * 2,
                quantity=Decimal("1"), unit_price=Decimal("50000"), unit_cost=Decimal("10000"),
                position=i,
            )

        with pdfplumber.open(BytesIO(render_quote_pdf(quote))) as pdf:
            page = [p for p in pdf.pages if "TOTAL" in (p.extract_text() or "")][0]
            lowest = min(w["bottom"] for w in page.extract_words())
            footer_top = page.height - 54 - 40  # page bottom margin, then the rule
            assert lowest < footer_top
