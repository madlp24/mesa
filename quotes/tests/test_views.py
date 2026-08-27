"""Quote views: building a quote, and never seeing another tenant's."""
from decimal import Decimal

import pytest
from django.urls import reverse

from catalog.models import Category, Product
from quotes.models import Course, MenuItem, PricingMode, Quote, QuoteLine
from tenants.models import Restaurant


@pytest.fixture
def menu(restaurant):
    category = Category.objects.create(restaurant=restaurant, name="Test")
    for course, price in [
        (Course.STARTERS, 30000),
        (Course.MAINS, 90000),
        (Course.SIDES, 20000),
        (Course.DESSERTS, 25000),
        (Course.SOFT, 10000),
        (Course.ALCOHOL, 50000),
    ]:
        product = Product.objects.create(
            restaurant=restaurant,
            name=f"P-{course}",
            sku=f"P-{course}",
            category=category,
            cost_price=Decimal(price) / 4,
            sale_price=Decimal(price) / Decimal("1.08"),
        )
        MenuItem.objects.create(
            restaurant=restaurant,
            name=f"Item {course}",
            course=course,
            price=Decimal(price),
            product=product,
        )
    return restaurant


@pytest.mark.django_db
class TestQuoteList:
    def test_requires_login(self, client):
        response = client.get(reverse("quotes:quote_list"))
        assert response.status_code == 302

    def test_lists_only_this_restaurant_quotes(self, logged_client, restaurant):
        Quote.objects.create(restaurant=restaurant, number="CA-119", client_name="Mine")
        other = Restaurant.objects.create(name="Other", slug="other-r")
        Quote.objects.create(restaurant=other, number="CA-500", client_name="Theirs")

        response = logged_client.get(reverse("quotes:quote_list"))

        assert b"Mine" in response.content
        assert b"Theirs" not in response.content


@pytest.mark.django_db
class TestQuoteCreate:
    def test_numbers_continue_the_series(self, logged_client, restaurant):
        Quote.objects.create(restaurant=restaurant, number="CA-130")

        logged_client.get(reverse("quotes:quote_create"))

        assert Quote.objects.filter(restaurant=restaurant, number="CA-131").exists()

    def test_first_quote_starts_the_series(self, logged_client, restaurant):
        logged_client.get(reverse("quotes:quote_create"))

        assert Quote.objects.filter(restaurant=restaurant, number="CA-119").exists()


@pytest.mark.django_db
class TestQuoteDetail:
    def test_another_tenant_quote_is_not_reachable(self, logged_client):
        other = Restaurant.objects.create(name="Other", slug="other-r")
        theirs = Quote.objects.create(restaurant=other, number="CA-500")

        response = logged_client.get(reverse("quotes:quote_detail", args=[theirs.pk]))

        assert response.status_code == 404

    def test_saving_updates_the_event(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-119")

        logged_client.post(
            reverse("quotes:quote_detail", args=[quote.pk]),
            {"client_name": "Laura", "guests": "30", "pricing_mode": "consumption", "charges_tip": "on"},
        )
        quote.refresh_from_db()

        assert quote.client_name == "Laura"
        assert quote.guests == 30

    def test_margin_is_shown_when_lines_are_costed(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-119", guests=1)
        QuoteLine.objects.create(
            quote=quote, name="X", quantity=1, unit_price=Decimal(108), unit_cost=Decimal(40)
        )

        response = logged_client.get(reverse("quotes:quote_detail", args=[quote.pk]))

        assert response.status_code == 200
        assert quote.is_costed


@pytest.mark.django_db
class TestCompose:
    def test_composing_fills_the_quote(self, logged_client, menu):
        quote = Quote.objects.create(restaurant=menu, number="CA-119")

        logged_client.post(
            reverse("quotes:quote_compose", args=[quote.pk]),
            {"budget_per_guest": "250000", "guests": "20", "profile": "seated", "alcohol": "on"},
        )
        quote.refresh_from_db()

        assert quote.lines.exists()
        assert quote.pricing_mode == PricingMode.PER_GUEST
        assert quote.guests == 20

    def test_a_missing_budget_is_rejected(self, logged_client, menu):
        quote = Quote.objects.create(restaurant=menu, number="CA-119")

        logged_client.post(
            reverse("quotes:quote_compose", args=[quote.pk]),
            {"budget_per_guest": "0", "guests": "20", "profile": "seated"},
        )
        quote.refresh_from_db()

        assert not quote.lines.exists()


@pytest.mark.django_db
class TestMenu:
    def test_mapping_a_product_gives_the_item_a_cost(self, logged_client, restaurant):
        category = Category.objects.create(restaurant=restaurant, name="C")
        product = Product.objects.create(
            restaurant=restaurant, name="POS NAME", sku="S1", category=category,
            cost_price=Decimal(9000), sale_price=Decimal(30000),
        )
        item = MenuItem.objects.create(
            restaurant=restaurant, name="Nice name", course=Course.STARTERS, price=Decimal(32400)
        )

        logged_client.post(
            reverse("quotes:menu_item_edit", args=[item.pk]),
            {
                "name": "Nice name", "description": "", "course": "starters",
                "price": "32400", "servings": "1", "product": str(product.pk),
                "product_units": "1", "is_active": "on",
            },
        )
        item.refresh_from_db()

        assert item.product == product
        assert item.unit_cost == Decimal(9000)

    def test_cannot_map_to_another_tenant_product(self, logged_client, restaurant):
        other = Restaurant.objects.create(name="Other", slug="other-r")
        other_user_category = Category.objects.create(restaurant=other, name="C")
        foreign = Product.objects.create(
            restaurant=other, name="THEIRS", sku="S9", category=other_user_category,
            cost_price=Decimal(1), sale_price=Decimal(2),
        )
        item = MenuItem.objects.create(
            restaurant=restaurant, name="Mine", course=Course.STARTERS, price=Decimal(1000)
        )

        response = logged_client.post(
            reverse("quotes:menu_item_edit", args=[item.pk]),
            {"name": "Mine", "course": "starters", "price": "1000",
             "servings": "1", "product": str(foreign.pk), "product_units": "1"},
        )
        item.refresh_from_db()

        assert response.status_code == 404
        assert item.product is None

    def test_menu_list_shows_unmapped_items(self, logged_client, restaurant):
        MenuItem.objects.create(
            restaurant=restaurant, name="Orphan", course=Course.STARTERS, price=Decimal(1000)
        )

        response = logged_client.get(reverse("quotes:menu_list"))

        assert response.status_code == 200
        assert b"Orphan" in response.content


@pytest.mark.django_db
class TestTranslation:
    def test_event_type_labels_follow_the_request_language(self, logged_client, restaurant):
        """They are built at import time, so they must be lazy to translate."""
        quote = Quote.objects.create(restaurant=restaurant, number="CA-119")

        response = logged_client.get(
            reverse("quotes:quote_detail", args=[quote.pk]), headers={"accept-language": "es"}
        )

        assert "Cóctel de pie".encode() in response.content
        assert b"Standing cocktail" not in response.content


@pytest.mark.django_db
class TestCharges:
    def test_adding_a_charge(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-150", guests=45)

        logged_client.post(
            reverse("quotes:quote_add_charge", args=[quote.pk]),
            {"name": "Alquiler del espacio", "amount": "1000000", "quantity": "1"},
        )
        line = quote.lines.get()

        assert line.add_on is True
        assert line.unit_price == Decimal("1000000")
        assert line.unit_cost == Decimal("0")

    def test_a_charge_without_an_amount_is_rejected(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-151")

        logged_client.post(
            reverse("quotes:quote_add_charge", args=[quote.pk]),
            {"name": "Sin monto", "amount": "0", "quantity": "1"},
        )

        assert not quote.lines.exists()

    def test_removing_a_charge_leaves_the_dishes(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-152", guests=10)
        dish = QuoteLine.objects.create(
            quote=quote, name="Corte", quantity=Decimal("1"), unit_price=Decimal("100000")
        )
        charge = QuoteLine.objects.create(
            quote=quote, name="Espacio", quantity=Decimal("1"),
            unit_price=Decimal("500000"), add_on=True,
        )

        logged_client.post(reverse("quotes:quote_remove_charge", args=[quote.pk, charge.pk]))

        assert list(quote.lines.all()) == [dish]

    def test_a_dish_cannot_be_removed_through_the_charge_route(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-153", guests=10)
        dish = QuoteLine.objects.create(
            quote=quote, name="Corte", quantity=Decimal("1"), unit_price=Decimal("100000")
        )

        logged_client.post(reverse("quotes:quote_remove_charge", args=[quote.pk, dish.pk]))

        assert quote.lines.filter(pk=dish.pk).exists()

    def test_another_tenant_cannot_add_a_charge(self, logged_client):
        other = Restaurant.objects.create(name="Other", slug="other-charges")
        theirs = Quote.objects.create(restaurant=other, number="CA-500")

        response = logged_client.post(
            reverse("quotes:quote_add_charge", args=[theirs.pk]),
            {"name": "X", "amount": "1000", "quantity": "1"},
        )

        assert response.status_code == 404
        assert not theirs.lines.exists()
