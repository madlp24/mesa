"""Quote views: building a quote, and never seeing another tenant's."""
from decimal import Decimal

import pytest
from django.urls import reverse

from catalog.models import Category, Product
from quotes.models import Course, MenuItem, PricingMode, Quote, QuoteLine, Venue
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

    def test_a_charge_without_a_name_is_rejected(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-151")

        logged_client.post(
            reverse("quotes:quote_add_charge", args=[quote.pk]),
            {"name": "", "amount": "500000", "quantity": "1"},
        )

        assert not quote.lines.exists()

    def test_a_zero_amount_is_accepted_now(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-154")

        logged_client.post(
            reverse("quotes:quote_add_charge", args=[quote.pk]),
            {"name": "Menaje completo", "amount": "0", "quantity": "1"},
        )

        assert quote.lines.count() == 1

    def test_removing_a_charge_leaves_the_dishes(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-152", guests=10)
        dish = QuoteLine.objects.create(
            quote=quote, name="Corte", quantity=Decimal("1"), unit_price=Decimal("100000")
        )
        charge = QuoteLine.objects.create(
            quote=quote, name="Espacio", quantity=Decimal("1"),
            unit_price=Decimal("500000"), add_on=True,
        )

        logged_client.post(reverse("quotes:quote_remove_line", args=[quote.pk, charge.pk]))

        assert list(quote.lines.all()) == [dish]

    def test_a_charge_without_an_amount_is_an_inclusion(self, logged_client, restaurant):
        """"Personal: 2 cocineros" -- listed, not charged."""
        quote = Quote.objects.create(
            restaurant=restaurant, number="CA-153", guests=40,
            pricing_mode=PricingMode.PER_GUEST, price_per_guest=Decimal("150000"),
            charges_tip=False,
        )

        logged_client.post(
            reverse("quotes:quote_add_charge", args=[quote.pk]),
            {"name": "Personal: 2 cocineros", "amount": "", "quantity": "1"},
        )
        quote.refresh_from_db()

        assert [line.name for line in quote.included_lines] == ["Personal: 2 cocineros"]
        assert quote.charged_add_ons == []
        assert quote.total == Decimal("6000000")

    def test_another_tenant_cannot_add_a_charge(self, logged_client):
        other = Restaurant.objects.create(name="Other", slug="other-charges")
        theirs = Quote.objects.create(restaurant=other, number="CA-500")

        response = logged_client.post(
            reverse("quotes:quote_add_charge", args=[theirs.pk]),
            {"name": "X", "amount": "1000", "quantity": "1"},
        )

        assert response.status_code == 404
        assert not theirs.lines.exists()


@pytest.mark.django_db
class TestDiscounts:
    def test_a_negative_amount_is_a_discount(self, logged_client, restaurant):
        quote = Quote.objects.create(
            restaurant=restaurant, number="CA-160", guests=40,
            pricing_mode=PricingMode.PER_GUEST, price_per_guest=Decimal("150000"),
            charges_tip=False,
        )

        logged_client.post(
            reverse("quotes:quote_add_charge", args=[quote.pk]),
            {"name": "Descuento comercial", "amount": "-1000000", "quantity": "1"},
        )
        quote.refresh_from_db()

        assert quote.add_ons_total == Decimal("-1000000")
        assert quote.total == Decimal("5000000")

    def test_a_zero_amount_now_means_an_inclusion(self, logged_client, restaurant):
        """It used to be rejected; the house lists what it throws in."""
        quote = Quote.objects.create(restaurant=restaurant, number="CA-161")

        logged_client.post(
            reverse("quotes:quote_add_charge", args=[quote.pk]),
            {"name": "Menaje completo", "amount": "0", "quantity": "1"},
        )
        quote.refresh_from_db()

        assert [line.name for line in quote.included_lines] == ["Menaje completo"]
        assert quote.add_ons_total == Decimal(0)


@pytest.mark.django_db
class TestManualCostForm:
    def test_a_cost_can_be_typed_for_an_unmapped_item(self, logged_client, restaurant):
        item = MenuItem.objects.create(
            restaurant=restaurant, name="Cocinero", course=Course.OTHER,
            price=Decimal("400000"),
        )

        logged_client.post(
            reverse("quotes:menu_item_edit", args=[item.pk]),
            {"name": "Cocinero", "course": "other", "price": "400000",
             "servings": "1", "product": "", "product_units": "1",
             "manual_cost": "180000", "is_active": "on"},
        )
        item.refresh_from_db()

        assert item.manual_cost == Decimal("180000")
        assert item.unit_cost == Decimal("180000")

    def test_clearing_the_field_makes_the_cost_unknown_again(self, logged_client, restaurant):
        item = MenuItem.objects.create(
            restaurant=restaurant, name="Morcilla", course=Course.STARTERS,
            price=Decimal("200000"), manual_cost=Decimal("50000"),
        )

        logged_client.post(
            reverse("quotes:menu_item_edit", args=[item.pk]),
            {"name": "Morcilla", "course": "starters", "price": "200000",
             "servings": "1", "product": "", "product_units": "1",
             "manual_cost": "", "is_active": "on"},
        )
        item.refresh_from_db()

        assert item.manual_cost is None
        assert item.unit_cost is None


@pytest.mark.django_db
class TestSavedServices:
    def _service(self, restaurant, name="Cocinero", price="400000", cost="180000"):
        return MenuItem.objects.create(
            restaurant=restaurant, name=name, course=Course.SERVICE,
            price=Decimal(price), manual_cost=Decimal(cost),
        )

    def test_a_saved_service_lands_with_its_price_and_cost(self, logged_client, restaurant):
        service = self._service(restaurant)
        quote = Quote.objects.create(restaurant=restaurant, number="CA-170", guests=40)

        logged_client.post(
            reverse("quotes:quote_add_service", args=[quote.pk]),
            {"service": str(service.pk), "quantity": "2"},
        )
        line = quote.lines.get()

        assert line.add_on is True
        assert line.unit_price == Decimal("400000")
        assert line.unit_cost == Decimal("180000")
        assert line.line_total == Decimal("800000")

    def test_a_service_carries_its_cost_into_the_margin(self, logged_client, restaurant):
        service = self._service(restaurant)
        quote = Quote.objects.create(
            restaurant=restaurant, number="CA-171", guests=10,
            pricing_mode=PricingMode.PER_GUEST, price_per_guest=Decimal("100000"),
            charges_tip=False,
        )
        QuoteLine.objects.create(
            quote=quote, name="Corte", quantity=Decimal("10"),
            unit_price=Decimal("100000"), unit_cost=Decimal("25000"),
        )

        logged_client.post(
            reverse("quotes:quote_add_service", args=[quote.pk]),
            {"service": str(service.pk), "quantity": "1"},
        )
        quote.refresh_from_db()

        assert quote.total == Decimal("1400000")
        assert quote.cost == Decimal("430000")   # 250.000 de comida + 180.000 del cocinero

    def test_only_services_can_be_added_this_way(self, logged_client, restaurant):
        dish = MenuItem.objects.create(
            restaurant=restaurant, name="Picanha", course=Course.MAINS, price=Decimal("126000")
        )
        quote = Quote.objects.create(restaurant=restaurant, number="CA-172")

        response = logged_client.post(
            reverse("quotes:quote_add_service", args=[quote.pk]),
            {"service": str(dish.pk), "quantity": "1"},
        )

        assert response.status_code == 404
        assert not quote.lines.exists()

    def test_another_tenant_service_cannot_be_used(self, logged_client, restaurant):
        other = Restaurant.objects.create(name="Other", slug="other-svc")
        theirs = self._service(other, name="Mesero ajeno")
        quote = Quote.objects.create(restaurant=restaurant, number="CA-173")

        response = logged_client.post(
            reverse("quotes:quote_add_service", args=[quote.pk]),
            {"service": str(theirs.pk), "quantity": "1"},
        )

        assert response.status_code == 404


@pytest.mark.django_db
class TestVenue:
    def test_the_venue_is_saved(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-180", guests=40)

        logged_client.post(
            reverse("quotes:quote_detail", args=[quote.pk]),
            {"client_name": "Mateo", "guests": "40", "pricing_mode": "per_guest",
             "venue": "grill"},
        )
        quote.refresh_from_db()

        assert quote.venue == Venue.GRILL
        assert quote.is_off_site is True

    def test_a_quote_starts_at_the_restaurant(self, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-181")

        assert quote.venue == Venue.IN_HOUSE
        assert quote.is_off_site is False


@pytest.mark.django_db
class TestBuildingByHand:
    def _dish(self, restaurant, name="Picanha americana", price="126000", cost="30845"):
        return MenuItem.objects.create(
            restaurant=restaurant, name=name, course=Course.MAINS,
            price=Decimal(price), manual_cost=Decimal(cost),
        )

    def test_a_dish_is_added_from_the_menu(self, logged_client, restaurant):
        dish = self._dish(restaurant)
        quote = Quote.objects.create(restaurant=restaurant, number="CA-190", guests=12)

        logged_client.post(
            reverse("quotes:quote_add_dish", args=[quote.pk]),
            {"dish": str(dish.pk), "quantity": "6"},
        )
        line = quote.lines.get()

        assert line.add_on is False
        assert line.name == "Picanha americana"
        assert line.quantity == Decimal("6")
        assert line.unit_price == Decimal("126000")
        assert line.unit_cost == Decimal("30845")

    def test_adding_the_same_dish_twice_raises_its_quantity(self, logged_client, restaurant):
        """A second helping, not a second row."""
        dish = self._dish(restaurant)
        quote = Quote.objects.create(restaurant=restaurant, number="CA-191", guests=12)
        url = reverse("quotes:quote_add_dish", args=[quote.pk])

        logged_client.post(url, {"dish": str(dish.pk), "quantity": "4"})
        logged_client.post(url, {"dish": str(dish.pk), "quantity": "2"})

        assert quote.lines.count() == 1
        assert quote.lines.get().quantity == Decimal("6")

    def test_quantities_are_saved_together(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-192", guests=12)
        a = QuoteLine.objects.create(quote=quote, name="A", quantity=Decimal("1"),
                                     unit_price=Decimal("10000"))
        b = QuoteLine.objects.create(quote=quote, name="B", quantity=Decimal("1"),
                                     unit_price=Decimal("20000"))

        logged_client.post(
            reverse("quotes:quote_update_lines", args=[quote.pk]),
            {f"qty-{a.pk}": "5", f"qty-{b.pk}": "3"},
        )
        a.refresh_from_db()
        b.refresh_from_db()

        assert (a.quantity, b.quantity) == (Decimal("5"), Decimal("3"))

    def test_a_quantity_of_zero_removes_the_line(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-193", guests=12)
        line = QuoteLine.objects.create(quote=quote, name="A", quantity=Decimal("2"),
                                        unit_price=Decimal("10000"))

        logged_client.post(
            reverse("quotes:quote_update_lines", args=[quote.pk]),
            {f"qty-{line.pk}": "0"},
        )

        assert not quote.lines.exists()

    def test_another_tenant_dish_cannot_be_added(self, logged_client, restaurant):
        other = Restaurant.objects.create(name="Other", slug="other-dish")
        theirs = self._dish(other, name="Plato ajeno")
        quote = Quote.objects.create(restaurant=restaurant, number="CA-194")

        response = logged_client.post(
            reverse("quotes:quote_add_dish", args=[quote.pk]),
            {"dish": str(theirs.pk), "quantity": "1"},
        )

        assert response.status_code == 404
        assert not quote.lines.exists()


@pytest.mark.django_db
class TestQuoteDetailRenders:
    """The page has to render with every kind of line on it, not just dishes.

    A stale `{% url %}` inside the add-on loop shipped to production because no
    test had ever rendered the page with an add-on on the quote.
    """

    def test_it_renders_with_charges_and_inclusions(self, logged_client, restaurant):
        quote = Quote.objects.create(
            restaurant=restaurant, number="CA-210", client_name="Mateo", guests=40,
            pricing_mode=PricingMode.PER_GUEST, price_per_guest=Decimal("150000"),
        )
        QuoteLine.objects.create(
            quote=quote, course=Course.MAINS, name="Picanha", quantity=Decimal("6"),
            unit_price=Decimal("300000"), unit_cost=Decimal("73441"),
        )
        QuoteLine.objects.create(
            quote=quote, course=Course.SERVICE, name="Transporte de parrilla",
            quantity=Decimal("1"), unit_price=Decimal("550000"),
            unit_cost=Decimal(0), add_on=True,
        )
        QuoteLine.objects.create(
            quote=quote, course=Course.SERVICE, name="Personal: 2 cocineros",
            quantity=Decimal("1"), unit_price=Decimal(0), unit_cost=Decimal(0),
            add_on=True,
        )
        QuoteLine.objects.create(
            quote=quote, course=Course.SERVICE, name="Descuento comercial",
            quantity=Decimal("1"), unit_price=Decimal("-500000"),
            unit_cost=Decimal(0), add_on=True,
        )

        response = logged_client.get(reverse("quotes:quote_detail", args=[quote.pk]))

        assert response.status_code == 200
        body = response.content.decode()
        assert "Transporte de parrilla" in body
        assert "Personal: 2 cocineros" in body
        assert "Descuento comercial" in body

    def test_it_renders_an_empty_quote(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-211")

        assert logged_client.get(reverse("quotes:quote_detail", args=[quote.pk])).status_code == 200

    def test_the_menu_page_renders(self, logged_client, restaurant):
        MenuItem.objects.create(
            restaurant=restaurant, name="Cocinero", course=Course.SERVICE,
            price=Decimal("400000"), manual_cost=Decimal("180000"),
        )
        MenuItem.objects.create(
            restaurant=restaurant, name="Picanha", course=Course.MAINS, price=Decimal("126000")
        )

        assert logged_client.get(reverse("quotes:menu_list")).status_code == 200


@pytest.mark.django_db
class TestServicesTypedIn:
    """Prices are typed as the service is added; the list builds itself."""

    def _add(self, client, quote, **extra):
        data = {"name": "Mesero", "amount": "200000", "quantity": "2"}
        data.update(extra)
        return client.post(reverse("quotes:quote_add_charge", args=[quote.pk]), data)

    def test_the_typed_price_lands_on_the_quote(self, logged_client, restaurant):
        quote = Quote.objects.create(
            restaurant=restaurant, number="CA-220", guests=40,
            pricing_mode=PricingMode.PER_GUEST, price_per_guest=Decimal("150000"),
            charges_tip=False,
        )

        self._add(logged_client, quote)
        quote.refresh_from_db()

        assert quote.add_ons_total == Decimal("400000")
        assert quote.total == Decimal("6400000")

    def test_a_typed_cost_counts_in_the_margin(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-221", guests=40)

        self._add(logged_client, quote, cost="90000")
        line = quote.lines.get()

        assert line.unit_cost == Decimal("90000")

    def test_remembering_it_makes_it_reusable(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-222", guests=40)

        self._add(logged_client, quote, cost="90000", remember="on")
        saved = MenuItem.objects.get(restaurant=restaurant, name="Mesero")

        assert saved.course == Course.SERVICE
        assert saved.price == Decimal("200000")
        assert saved.manual_cost == Decimal("90000")

    def test_not_remembering_leaves_no_trace(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-223", guests=40)

        self._add(logged_client, quote)

        assert not MenuItem.objects.filter(restaurant=restaurant, name="Mesero").exists()

    def test_typing_it_again_updates_the_remembered_price(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-224", guests=40)

        self._add(logged_client, quote, remember="on")
        self._add(logged_client, quote, amount="250000", remember="on")

        assert MenuItem.objects.get(restaurant=restaurant, name="Mesero").price == Decimal("250000")

    def test_a_service_without_a_price_is_still_remembered(self, logged_client, restaurant):
        """"Personal: 2 cocineros" is worth remembering even at nothing."""
        quote = Quote.objects.create(restaurant=restaurant, number="CA-225", guests=40)

        self._add(logged_client, quote, name="Personal: 2 cocineros", amount="", remember="on")
        saved = MenuItem.objects.get(restaurant=restaurant, name="Personal: 2 cocineros")

        assert saved.price == Decimal(0)
        assert quote.included_lines[0].name == "Personal: 2 cocineros"
