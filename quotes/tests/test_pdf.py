"""The client-facing PDF: it must carry prices and never cost."""
from decimal import Decimal
from io import BytesIO

import pdfplumber
import pytest
from django.utils import translation
from django.urls import reverse

from quotes.models import Course, PricingMode, Quote, QuoteLine
from quotes.pdf import QuoteCanvas, render_quote_pdf
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


@pytest.mark.django_db
class TestBranding:
    def test_the_totals_name_the_pre_tax_subtotal(self, restaurant):
        """The client asked to see what the food costs before tax and tip."""
        quote = Quote.objects.create(
            restaurant=restaurant, number="CA-130", guests=10,
            pricing_mode=PricingMode.PER_GUEST, price_per_guest=Decimal("108000"),
            charges_tip=False,
        )
        QuoteLine.objects.create(
            quote=quote, course=Course.MAINS, name="Corte", quantity=Decimal("10"),
            unit_price=Decimal("108000"), unit_cost=Decimal("30000"),
        )

        text = _text_of(render_quote_pdf(quote))

        assert "1.000.000" in text      # subtotal before tax
        assert "80.000" in text         # the tax contained in it
        assert "1.080.000" in text      # total

    def test_a_restaurant_without_a_logo_still_renders(self, restaurant):
        assert restaurant.logo is None
        assert render_quote_pdf(_quote_with_lines(restaurant)).startswith(b"%PDF")

    def test_an_unreadable_logo_does_not_break_the_quote(self, restaurant):
        """A bad image must never cost the client their document."""
        restaurant.logo = b"not an image at all"
        restaurant.save()

        assert render_quote_pdf(_quote_with_lines(restaurant)).startswith(b"%PDF")

    def test_a_logo_is_drawn_when_present(self, restaurant):
        from io import BytesIO as _B

        from PIL import Image

        buf = _B()
        Image.new("RGBA", (200, 200), (224, 16, 32, 255)).save(buf, "PNG")
        restaurant.logo = buf.getvalue()
        restaurant.save()

        data = render_quote_pdf(_quote_with_lines(restaurant))

        assert b"/Image" in data or b"/XObject" in data


@pytest.mark.django_db
class TestAutoFit:
    def _quote_with(self, restaurant, number, count):
        quote = Quote.objects.create(
            restaurant=restaurant, number=number, guests=45,
            pricing_mode=PricingMode.PER_GUEST, price_per_guest=Decimal("180000"),
            charges_tip=False,
        )
        courses = [
            Course.STARTERS, Course.STARTERS, Course.STARTERS, Course.MAINS,
            Course.SIDES, Course.SIDES, Course.DESSERTS, Course.SOFT,
        ]
        for i in range(count):
            QuoteLine.objects.create(
                quote=quote, course=courses[i % len(courses)], name=f"Plato número {i}",
                description="Una descripción de la longitud que llevan los platos de la carta, "
                            "que ocupa dos renglones completos en el documento.",
                quantity=Decimal("12"), unit_price=Decimal("44000"),
                unit_cost=Decimal("9574"), position=i,
            )
        return quote

    def test_the_gosh_quote_is_squeezed_onto_one_page(self, restaurant):
        """CA-121 line for line: eight dishes for 45 guests, which overflowed
        the designed spacing by 26 points and left the totals alone on page 2."""
        quote = Quote.objects.create(
            restaurant=restaurant, number="CA-121", client_name="Daniela García",
            concept="Almuerzo · Gosh Agencia", guests=45, days=1,
            payment_terms="50% anticipo, 50% en el evento",
            pricing_mode=PricingMode.PER_GUEST, price_per_guest=Decimal("180000"),
            charges_tip=False,
        )
        lines = [
            (Course.STARTERS, "Croquetas de lomo ahumado (3 und)",
             "Lomo de res ahumado, bechamel, sashimi de atún, salsa ponzu y salsa de aguacate y tomatillo.", 45),
            (Course.STARTERS, "Berenjenas asadas a fuego de leña",
             "Caramelizadas con miso, queso costeño, ensalada cítrica con duraznos ahumados, arándanos deshidratados y salsa de yogur de búfala.", 30),
            (Course.STARTERS, "Ensalada de la casa",
             "Mix asiático, supremas de naranja, pistachos, tomate cherry, encurtido de cebolla y rábano, vinagreta cítrica.", 12),
            (Course.MAINS, "Picanha americana (420 g)", "", 22),
            (Course.SIDES, "Patatas fritas con grana padano", "", 12),
            (Course.SIDES, "Vegetales ahumados", "", 12),
            (Course.DESSERTS, "Postre de limón deconstruido",
             "Galleta de mantequilla con canela, crema de limón, merengue tostado y polvo de limón. Para compartir.", 30),
            (Course.SOFT, "Bebidas sin alcohol a elección",
             "Para escoger entre aguas, sodas y sodas de la casa.", 45),
        ]
        for position, (course, name, description, qty) in enumerate(lines):
            QuoteLine.objects.create(
                quote=quote, course=course, name=name, description=description,
                quantity=Decimal(qty), unit_price=Decimal("44000"),
                unit_cost=Decimal("9574"), position=position,
            )

        with pdfplumber.open(BytesIO(render_quote_pdf(quote))) as pdf:
            assert len(pdf.pages) == 1
            text = pdf.pages[0].extract_text()
            assert "TOTAL" in text
            assert "8.100.000" in text

    def test_a_quote_that_truly_needs_two_pages_gets_them(self, restaurant):
        """Squeezing has a floor; past it the reader gets a second sheet."""
        quote = self._quote_with(restaurant, "CA-122", 30)

        with pdfplumber.open(BytesIO(render_quote_pdf(quote))) as pdf:
            assert len(pdf.pages) > 1
            assert "TOTAL" in pdf.pages[-1].extract_text()

    def test_a_short_quote_is_not_squeezed(self, restaurant):
        """Nothing to gain, so it keeps the spacing it was designed with."""
        short = self._quote_with(restaurant, "CA-123", 3)

        roomy = QuoteCanvas(short, tight=1.0).build()

        assert len(render_quote_pdf(short)) == len(roomy)


@pytest.mark.django_db
class TestSqueezedLayout:
    def test_the_note_never_lands_on_the_header_labels(self, restaurant):
        """Cell labels sit at a fixed depth, so the block that follows them
        must not shrink past where they end."""
        quote = Quote.objects.create(
            restaurant=restaurant, number="CA-140", client_name="Daniela García",
            concept="Almuerzo · Gosh Agencia", guests=45,
            payment_terms="50% anticipo, 50% en el evento",
        )
        QuoteLine.objects.create(
            quote=quote, course=Course.MAINS, name="Corte", quantity=Decimal("22"),
            unit_price=Decimal("126000"), unit_cost=Decimal("30845"),
        )

        # Spanish is the worst case: its labels and note run longest.
        with translation.override("es"):
            for tight in (1.0, 0.86, 0.72):
                data = QuoteCanvas(quote, tight=tight).build()
                with pdfplumber.open(BytesIO(data)) as pdf:
                    words = pdf.pages[0].extract_words()
                label = max(w["bottom"] for w in words if w["text"] == "PAGO")
                note = min(w["top"] for w in words if w["text"] == "Para")
                assert note > label, f"the note lands on the labels at tight={tight}"
