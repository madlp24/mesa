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
            {"budget_per_guest": "250000", "compose_guests": "20", "profile": "seated", "alcohol": "on"},
        )
        quote.refresh_from_db()

        assert quote.lines.exists()
        assert quote.pricing_mode == PricingMode.PER_GUEST
        assert quote.guests == 20

    def test_a_missing_budget_is_rejected(self, logged_client, menu):
        quote = Quote.objects.create(restaurant=menu, number="CA-119")

        logged_client.post(
            reverse("quotes:quote_compose", args=[quote.pk]),
            {"budget_per_guest": "0", "compose_guests": "20", "profile": "seated"},
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
            {"charge_name": "Alquiler del espacio", "charge_amount": "1000000", "charge_quantity": "1"},
        )
        line = quote.lines.get()

        assert line.add_on is True
        assert line.unit_price == Decimal("1000000")
        assert line.unit_cost == Decimal("0")

    def test_a_charge_without_a_name_is_rejected(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-151")

        logged_client.post(
            reverse("quotes:quote_add_charge", args=[quote.pk]),
            {"charge_name": "", "charge_amount": "500000", "charge_quantity": "1"},
        )

        assert not quote.lines.exists()

    def test_a_zero_amount_is_accepted_now(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-154")

        logged_client.post(
            reverse("quotes:quote_add_charge", args=[quote.pk]),
            {"charge_name": "Menaje completo", "charge_amount": "0", "charge_quantity": "1"},
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
            {"charge_name": "Personal: 2 cocineros", "charge_amount": "", "charge_quantity": "1"},
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
            {"charge_name": "X", "charge_amount": "1000", "charge_quantity": "1"},
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
            {"charge_name": "Descuento comercial", "charge_amount": "-1000000", "charge_quantity": "1"},
        )
        quote.refresh_from_db()

        assert quote.add_ons_total == Decimal("-1000000")
        assert quote.total == Decimal("5000000")

    def test_a_zero_amount_now_means_an_inclusion(self, logged_client, restaurant):
        """It used to be rejected; the house lists what it throws in."""
        quote = Quote.objects.create(restaurant=restaurant, number="CA-161")

        logged_client.post(
            reverse("quotes:quote_add_charge", args=[quote.pk]),
            {"charge_name": "Menaje completo", "charge_amount": "0", "charge_quantity": "1"},
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
            {"service": str(service.pk), "service_quantity": "2"},
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
            {"service": str(service.pk), "service_quantity": "1"},
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
            {"service": str(dish.pk), "service_quantity": "1"},
        )

        assert response.status_code == 404
        assert not quote.lines.exists()

    def test_another_tenant_service_cannot_be_used(self, logged_client, restaurant):
        other = Restaurant.objects.create(name="Other", slug="other-svc")
        theirs = self._service(other, name="Mesero ajeno")
        quote = Quote.objects.create(restaurant=restaurant, number="CA-173")

        response = logged_client.post(
            reverse("quotes:quote_add_service", args=[quote.pk]),
            {"service": str(theirs.pk), "service_quantity": "1"},
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
            {"dish": str(dish.pk), "dish_quantity": "6"},
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

        logged_client.post(url, {"dish": str(dish.pk), "dish_quantity": "4"})
        logged_client.post(url, {"dish": str(dish.pk), "dish_quantity": "2"})

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
            {"dish": str(theirs.pk), "dish_quantity": "1"},
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
        data = {"charge_name": "Mesero", "charge_amount": "200000", "charge_quantity": "2"}
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

        self._add(logged_client, quote, charge_cost="90000")
        line = quote.lines.get()

        assert line.unit_cost == Decimal("90000")

    def test_remembering_it_makes_it_reusable(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-222", guests=40)

        self._add(logged_client, quote, charge_cost="90000", charge_remember="on")
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

        self._add(logged_client, quote, charge_remember="on")
        self._add(logged_client, quote, charge_amount="250000", charge_remember="on")

        assert MenuItem.objects.get(restaurant=restaurant, name="Mesero").price == Decimal("250000")

    def test_a_service_without_a_price_is_still_remembered(self, logged_client, restaurant):
        """"Personal: 2 cocineros" is worth remembering even at nothing."""
        quote = Quote.objects.create(restaurant=restaurant, number="CA-225", guests=40)

        self._add(logged_client, quote, charge_name="Personal: 2 cocineros", charge_amount="", charge_remember="on")
        saved = MenuItem.objects.get(restaurant=restaurant, name="Personal: 2 cocineros")

        assert saved.price == Decimal(0)
        assert quote.included_lines[0].name == "Personal: 2 cocineros"


@pytest.mark.django_db
class TestOneOffDish:
    """A corporate event is cooked off the menu; the menu should not fill up."""

    def _write(self, client, quote, **extra):
        data = {"cd_name": "Morcilla", "cd_course": "starters", "cd_description": "",
                "cd_price": "200000", "cd_quantity": "4"}
        data.update(extra)
        return client.post(reverse("quotes:quote_add_custom_dish", args=[quote.pk]), data)

    def test_it_lands_on_the_quote(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-230", guests=40)

        self._write(logged_client, quote)
        line = quote.lines.get()

        assert line.name == "Morcilla"
        assert line.add_on is False
        assert line.course == Course.STARTERS
        assert line.quantity == Decimal("4")
        assert line.unit_price == Decimal("200000")

    def test_it_stays_off_the_menu_by_default(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-231", guests=40)

        self._write(logged_client, quote)

        assert not MenuItem.objects.filter(restaurant=restaurant, name="Morcilla").exists()

    def test_it_can_be_kept_on_the_menu(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-232", guests=40)

        self._write(logged_client, quote, cd_cost="70000", cd_remember="on")
        kept = MenuItem.objects.get(restaurant=restaurant, name="Morcilla")

        assert kept.course == Course.STARTERS
        assert kept.price == Decimal("200000")
        assert kept.manual_cost == Decimal("70000")

    def test_a_typed_cost_reaches_the_margin(self, logged_client, restaurant):
        quote = Quote.objects.create(
            restaurant=restaurant, number="CA-233", guests=40, charges_tip=False
        )

        self._write(logged_client, quote, cd_cost="70000")
        quote.refresh_from_db()

        assert quote.is_costed is True
        assert quote.cost == Decimal("280000")

    def test_without_a_cost_the_quote_reports_no_margin(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-234", guests=40)

        self._write(logged_client, quote)
        quote.refresh_from_db()

        assert quote.is_costed is False

    def test_a_dish_needs_a_name(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-235", guests=40)

        self._write(logged_client, quote, cd_name="")

        assert not quote.lines.exists()

    def test_another_tenant_quote_is_out_of_reach(self, logged_client):
        other = Restaurant.objects.create(name="Other", slug="other-custom")
        theirs = Quote.objects.create(restaurant=other, number="CA-500")

        response = self._write(logged_client, theirs)

        assert response.status_code == 404
        assert not theirs.lines.exists()


@pytest.mark.django_db
class TestNewQuoteDefaults:
    def test_a_new_quote_prices_per_guest(self, logged_client, restaurant):
        """Every quote the house sends is agreed at a figure per head."""
        logged_client.get(reverse("quotes:quote_create"))
        quote = Quote.objects.get(restaurant=restaurant)

        assert quote.pricing_mode == PricingMode.PER_GUEST

    def test_by_consumption_is_still_available(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-250", guests=10)

        logged_client.post(
            reverse("quotes:quote_detail", args=[quote.pk]),
            {"client_name": "X", "guests": "10", "pricing_mode": "consumption"},
        )
        quote.refresh_from_db()

        assert quote.pricing_mode == PricingMode.CONSUMPTION


@pytest.mark.django_db
class TestMenuByVenue:
    """A grill at a finca cannot serve the dining room's carpaccio."""

    def _menu(self, restaurant):
        from quotes.models import Availability

        return {
            "ambos": MenuItem.objects.create(
                restaurant=restaurant, name="Picanha", course=Course.MAINS,
                price=Decimal("300000"), availability=Availability.BOTH),
            "casa": MenuItem.objects.create(
                restaurant=restaurant, name="Carpaccio de atún", course=Course.STARTERS,
                price=Decimal("48000"), availability=Availability.IN_HOUSE),
            "fuera": MenuItem.objects.create(
                restaurant=restaurant, name="Morcilla", course=Course.STARTERS,
                price=Decimal("200000"), availability=Availability.OFF_SITE),
        }

    def _names_offered(self, client, quote):
        """Just the dish dropdown -- the page has other prose on it."""
        body = client.get(reverse("quotes:quote_detail", args=[quote.pk])).content.decode()
        start = body.index('id="dish"')
        return body[start:body.index("</select>", start)]

    def test_a_restaurant_quote_hides_the_grill_dishes(self, logged_client, restaurant):
        menu = self._menu(restaurant)
        quote = Quote.objects.create(restaurant=restaurant, number="CA-270", venue=Venue.IN_HOUSE)

        body = self._names_offered(logged_client, quote)

        assert menu["casa"].name in body
        assert menu["ambos"].name in body
        assert menu["fuera"].name not in body

    def test_a_grill_quote_hides_the_dining_room_dishes(self, logged_client, restaurant):
        menu = self._menu(restaurant)
        quote = Quote.objects.create(restaurant=restaurant, number="CA-271", venue=Venue.GRILL)

        body = self._names_offered(logged_client, quote)

        assert menu["fuera"].name in body
        assert menu["ambos"].name in body
        assert menu["casa"].name not in body

    def test_an_event_away_uses_the_same_list_as_a_grill(self, logged_client, restaurant):
        menu = self._menu(restaurant)
        quote = Quote.objects.create(restaurant=restaurant, number="CA-272", venue=Venue.OFF_SITE)

        body = self._names_offered(logged_client, quote)

        assert menu["fuera"].name in body
        assert menu["casa"].name not in body

    def test_where_a_dish_is_served_can_be_changed(self, logged_client, restaurant):
        from quotes.models import Availability

        item = self._menu(restaurant)["casa"]

        logged_client.post(
            reverse("quotes:menu_item_edit", args=[item.pk]),
            {"name": item.name, "course": "starters", "price": "48000", "servings": "1",
             "product": "", "product_units": "1", "manual_cost": "",
             "availability": "off_site", "is_active": "on"},
        )
        item.refresh_from_db()

        assert item.availability == Availability.OFF_SITE


@pytest.mark.django_db
class TestMenuTableRenders:
    def test_the_lines_actually_appear(self, logged_client, restaurant):
        """The course dropdown overwrote the grouped lines and the table went blank."""
        quote = Quote.objects.create(restaurant=restaurant, number="CA-280", guests=16)
        for name in ("Albóndigas al carbón", "Ribeye americano", "Postre de limón"):
            QuoteLine.objects.create(
                quote=quote, course=Course.MAINS, name=name, quantity=Decimal("2"),
                unit_price=Decimal("60000"), unit_cost=Decimal("15000"),
            )

        body = logged_client.get(reverse("quotes:quote_detail", args=[quote.pk])).content.decode()
        table = body[body.index("<tbody>"):body.index("</tbody>")]

        for name in ("Albóndigas al carbón", "Ribeye americano", "Postre de limón"):
            assert name in table


@pytest.mark.django_db
class TestEventFieldsSurviveEveryAction:
    """The page is one form: an action must not discard what was typed above."""

    EVENTO = {
        "client_name": "Juliana Rodríguez",
        "concept": "Cena de grado",
        "event_date": "2026-10-17",
        "guests": "16",
        "days": "1",
        "payment_terms": "50% anticipo",
        "notes": "En el reservado.",
        "pricing_mode": "consumption",
        "price_per_guest": "0",
        "venue": "grill",
        "charges_tip": "on",
        "show_quantities": "on",
    }

    def _assert_kept(self, quote):
        quote.refresh_from_db()
        assert quote.client_name == "Juliana Rodríguez"
        assert quote.concept == "Cena de grado"
        assert str(quote.event_date) == "2026-10-17"
        assert quote.guests == 16
        assert quote.notes == "En el reservado."
        assert quote.venue == Venue.GRILL
        assert quote.charges_tip is True

    def test_adding_a_charge_keeps_the_event(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-290")

        logged_client.post(
            reverse("quotes:quote_add_charge", args=[quote.pk]),
            {**self.EVENTO, "charge_name": "Transporte", "charge_amount": "550000",
             "charge_quantity": "1"},
        )

        self._assert_kept(quote)
        assert quote.add_ons_total == Decimal("550000")

    def test_adding_a_dish_keeps_the_event(self, logged_client, restaurant):
        dish = MenuItem.objects.create(
            restaurant=restaurant, name="Morcilla", course=Course.STARTERS,
            price=Decimal("200000"),
        )
        quote = Quote.objects.create(restaurant=restaurant, number="CA-291")

        logged_client.post(
            reverse("quotes:quote_add_dish", args=[quote.pk]),
            {**self.EVENTO, "dish": str(dish.pk), "dish_quantity": "2"},
        )

        self._assert_kept(quote)
        assert quote.lines.count() == 1

    def test_writing_a_dish_keeps_the_event(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-292")

        logged_client.post(
            reverse("quotes:quote_add_custom_dish", args=[quote.pk]),
            {**self.EVENTO, "cd_name": "Chicharrón al barril", "cd_course": "starters",
             "cd_price": "300000", "cd_quantity": "2"},
        )

        self._assert_kept(quote)

    def test_saving_quantities_keeps_the_event(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-293")
        line = QuoteLine.objects.create(
            quote=quote, name="X", quantity=Decimal("1"), unit_price=Decimal("1000")
        )

        logged_client.post(
            reverse("quotes:quote_update_lines", args=[quote.pk]),
            {**self.EVENTO, f"qty-{line.pk}": "5"},
        )

        self._assert_kept(quote)
        line.refresh_from_db()
        assert line.quantity == Decimal("5")

    def test_choosing_the_venue_switches_the_dish_list_on_the_same_action(
        self, logged_client, restaurant
    ):
        """Picking "grill" and adding a dish must not consult the old venue."""
        from quotes.models import Availability

        MenuItem.objects.create(
            restaurant=restaurant, name="Longaniza artesanal", course=Course.STARTERS,
            price=Decimal("250000"), availability=Availability.OFF_SITE,
        )
        quote = Quote.objects.create(
            restaurant=restaurant, number="CA-294", venue=Venue.IN_HOUSE
        )

        logged_client.post(
            reverse("quotes:quote_add_charge", args=[quote.pk]),
            {**self.EVENTO, "charge_name": "Transporte", "charge_amount": "550000"},
        )
        body = logged_client.get(
            reverse("quotes:quote_detail", args=[quote.pk])
        ).content.decode()
        dropdown = body[body.index('id="dish"'):body.index("</select>", body.index('id="dish"'))]

        assert "Longaniza artesanal" in dropdown


@pytest.mark.django_db
class TestReachingTheWholeMenu:
    """The venue filter must never be a wall the person quoting cannot pass."""

    def _menu(self, restaurant):
        from quotes.models import Availability

        MenuItem.objects.create(
            restaurant=restaurant, name="Carpaccio de atún", course=Course.STARTERS,
            price=Decimal("48000"), availability=Availability.IN_HOUSE)
        MenuItem.objects.create(
            restaurant=restaurant, name="Longaniza artesanal", course=Course.STARTERS,
            price=Decimal("250000"), availability=Availability.OFF_SITE)

    def _dropdown(self, client, quote, query=""):
        body = client.get(
            reverse("quotes:quote_detail", args=[quote.pk]) + query
        ).content.decode()
        start = body.index('id="dish"')
        return body[start:body.index("</select>", start)]

    def test_the_whole_menu_can_be_asked_for(self, logged_client, restaurant):
        self._menu(restaurant)
        quote = Quote.objects.create(
            restaurant=restaurant, number="CA-300", venue=Venue.IN_HOUSE
        )

        acotado = self._dropdown(logged_client, quote)
        completo = self._dropdown(logged_client, quote, "?menu=all")

        assert "Longaniza artesanal" not in acotado
        assert "Longaniza artesanal" in completo
        assert "Carpaccio de atún" in completo

    def test_the_page_says_how_many_are_hidden(self, logged_client, restaurant):
        self._menu(restaurant)
        quote = Quote.objects.create(
            restaurant=restaurant, number="CA-301", venue=Venue.IN_HOUSE
        )

        body = logged_client.get(reverse("quotes:quote_detail", args=[quote.pk])).content.decode()

        assert "menu=all" in body

    def test_changing_the_venue_changes_the_list(self, logged_client, restaurant):
        self._menu(restaurant)
        quote = Quote.objects.create(
            restaurant=restaurant, number="CA-302", venue=Venue.IN_HOUSE
        )

        logged_client.post(
            reverse("quotes:quote_detail", args=[quote.pk]),
            {"client_name": "X", "guests": "10", "pricing_mode": "per_guest", "venue": "grill"},
        )
        dropdown = self._dropdown(logged_client, quote)

        assert "Longaniza artesanal" in dropdown
        assert "Carpaccio de atún" not in dropdown


@pytest.mark.django_db
class TestCostTypedOnTheLine:
    def test_a_written_dish_can_be_costed_where_the_warning_is(self, logged_client, restaurant):
        """A one-off dish has nowhere else to carry a cost."""
        quote = Quote.objects.create(restaurant=restaurant, number="CA-310", guests=20)
        line = QuoteLine.objects.create(
            quote=quote, course=Course.STARTERS, name="Picada mixta",
            quantity=Decimal("1"), unit_price=Decimal("250000"), unit_cost=None,
        )
        assert quote.is_costed is False

        logged_client.post(
            reverse("quotes:quote_update_lines", args=[quote.pk]),
            {f"qty-{line.pk}": "1", f"cost-{line.pk}": "80000"},
        )
        quote.refresh_from_db()

        assert quote.lines.get().unit_cost == Decimal("80000")
        assert quote.is_costed is True

    def test_clearing_it_makes_the_cost_unknown_again(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-311", guests=20)
        line = QuoteLine.objects.create(
            quote=quote, course=Course.STARTERS, name="Picada",
            quantity=Decimal("1"), unit_price=Decimal("250000"), unit_cost=Decimal("80000"),
        )

        logged_client.post(
            reverse("quotes:quote_update_lines", args=[quote.pk]),
            {f"qty-{line.pk}": "1", f"cost-{line.pk}": ""},
        )

        assert quote.lines.get().unit_cost is None

    def test_the_quantity_still_saves_alongside(self, logged_client, restaurant):
        quote = Quote.objects.create(restaurant=restaurant, number="CA-312", guests=20)
        line = QuoteLine.objects.create(
            quote=quote, course=Course.MAINS, name="Picanha",
            quantity=Decimal("1"), unit_price=Decimal("300000"),
        )

        logged_client.post(
            reverse("quotes:quote_update_lines", args=[quote.pk]),
            {f"qty-{line.pk}": "6", f"cost-{line.pk}": "73441"},
        )
        line.refresh_from_db()

        assert (line.quantity, line.unit_cost) == (Decimal("6"), Decimal("73441"))
