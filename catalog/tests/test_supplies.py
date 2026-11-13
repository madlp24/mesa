"""Tests for costing products from AutoFacturas supplies (US45)."""
import json
import urllib.error
from decimal import Decimal
from io import BytesIO

import pytest
from django.urls import reverse

from catalog.models import Category, Product, RecipeLine, Supply
from catalog.supplies import (
    SupplyCostError,
    fetch_costs,
    recost_products,
    sync_costs,
    sync_supplies,
)


def _payload(*insumos, **envelope):
    body = {
        "ok": True,
        "empresa": {"id": 1, "nombre": "Casablanca Capital SAS"},
        "generado_en": "2026-11-13T09:00:00.000Z",
        "iva_es_costo": True,
        "dias_promedio": 90,
        "insumos": list(insumos),
        "sin_costear": 0,
    }
    body.update(envelope)
    return body


def _insumo(clave="GIN-01", nombre="GIN TANQUERAY", unidad="ml", costo=52.4137, **extra):
    row = {
        "clave": clave,
        "nombre": nombre,
        "unidad_consumo": unidad,
        "grupo": "LICORES",
        "ultimo_costo_con_impuestos": costo,
        "ultimo_costo_sin_impuestos": 44.0451,
        "ultima_compra_fecha": "2026-10-28",
        "ultima_compra_proveedor": "DISLICORES",
        "ultima_compra_nit": "890900608",
        "ultima_compra_factura": "FE-9912",
        "ultima_compra_producto": "GIN TANQUERAY 700ML",
        "costo_promedio_90d": 50.0,
        "compras_90d": 3,
        "compras": 11,
        "avisos": [],
    }
    row.update(extra)
    return row


@pytest.fixture
def product(restaurant):
    category = Category.objects.create(restaurant=restaurant, name="Cocteles")
    return Product.objects.create(
        restaurant=restaurant, name="NEGRONI", sku="8100", category=category,
        cost_price=Decimal("6000.00"), sale_price=Decimal("42000.00"),
    )


# -- reading the connector ------------------------------------------------


@pytest.mark.django_db
def test_sync_creates_a_supply_per_insumo(restaurant):
    summary = sync_supplies(restaurant, _payload(_insumo()))

    supply = Supply.objects.get(restaurant=restaurant, clave="GIN-01")
    assert supply.name == "GIN TANQUERAY"
    assert supply.unit == "ml"
    assert supply.unit_cost == Decimal("52.4137")
    assert supply.average_cost == Decimal("50.0000")
    assert supply.last_purchase_supplier == "DISLICORES"
    assert summary.created == 1


@pytest.mark.django_db
def test_sync_matches_on_clave_not_name(restaurant):
    sync_supplies(restaurant, _payload(_insumo()))
    sync_supplies(restaurant, _payload(_insumo(nombre="GIN TANQUERAY LONDON DRY")))

    assert Supply.objects.filter(restaurant=restaurant).count() == 1
    assert Supply.objects.get().name == "GIN TANQUERAY LONDON DRY"


@pytest.mark.django_db
def test_sync_separates_a_changed_supply_from_an_untouched_one(restaurant):
    sync_supplies(restaurant, _payload(_insumo(), _insumo(clave="LIM-01", nombre="LIMON")))
    summary = sync_supplies(
        restaurant, _payload(_insumo(costo=60.0), _insumo(clave="LIM-01", nombre="LIMON"))
    )

    assert (summary.updated, summary.unchanged, summary.created) == (1, 1, 0)


@pytest.mark.django_db
def test_a_zero_cost_is_no_cost(restaurant):
    # The connector sends null for what it could not cost; a zero that slipped
    # through would read as free.
    sync_supplies(restaurant, _payload(_insumo(ultimo_costo_con_impuestos=0)))

    supply = Supply.objects.get()
    assert supply.unit_cost is None
    assert not supply.is_costed


@pytest.mark.django_db
def test_an_unknown_unit_is_dropped_rather_than_stored(restaurant):
    sync_supplies(restaurant, _payload(_insumo(unidad_consumo="cajas")))

    assert Supply.objects.get().unit == ""


@pytest.mark.django_db
def test_sync_keeps_supplies_the_payload_stopped_mentioning(restaurant):
    # AutoFacturas drops an insumo it cannot cost; deleting it here would take
    # the recipes that use it with it.
    sync_supplies(restaurant, _payload(_insumo(), _insumo(clave="LIM-01", nombre="LIMON")))
    sync_supplies(restaurant, _payload(_insumo()))

    assert Supply.objects.filter(restaurant=restaurant).count() == 2


@pytest.mark.django_db
def test_supplies_are_scoped_to_their_restaurant(restaurant, other_restaurant):
    sync_supplies(restaurant, _payload(_insumo()))
    sync_supplies(other_restaurant, _payload(_insumo(costo=99.0)))

    assert Supply.objects.get(restaurant=restaurant).unit_cost == Decimal("52.4137")
    assert Supply.objects.get(restaurant=other_restaurant).unit_cost == Decimal("99.0000")


# -- recipes --------------------------------------------------------------


@pytest.mark.django_db
def test_a_single_ingredient_recipe_costs_the_portion(restaurant, product):
    sync_supplies(restaurant, _payload(_insumo()))
    supply = Supply.objects.get()
    RecipeLine.objects.create(product=product, supply=supply, quantity=Decimal("45"))

    # 45 ml at 52.4137 per ml
    assert product.recipe_cost == Decimal("2358.6165")


@pytest.mark.django_db
def test_a_cocktail_adds_up_its_ingredients(restaurant, product):
    sync_supplies(restaurant, _payload(
        _insumo(clave="GIN", costo=50),
        _insumo(clave="VER", nombre="VERMUT", costo=30),
        _insumo(clave="CAM", nombre="CAMPARI", costo=40),
        _insumo(clave="HIE", nombre="HIELO", unidad="g", costo=0.5),
        _insumo(clave="NAR", nombre="NARANJA", unidad="unidad", costo=900),
    ))
    by_clave = {s.clave: s for s in Supply.objects.all()}
    for clave, qty in [("GIN", 30), ("VER", 30), ("CAM", 30), ("HIE", 200), ("NAR", "0.25")]:
        RecipeLine.objects.create(
            product=product, supply=by_clave[clave], quantity=Decimal(str(qty))
        )

    # 1500 + 900 + 1200 + 100 + 225
    assert product.recipe_cost == Decimal("3925.0000")


@pytest.mark.django_db
def test_a_recipe_missing_one_cost_reports_no_cost_at_all(restaurant, product):
    # Not a partial sum: that would read as a real cost and overstate the margin.
    sync_supplies(restaurant, _payload(
        _insumo(clave="GIN", costo=50),
        _insumo(clave="HIE", nombre="HIELO", unidad="g", ultimo_costo_con_impuestos=None,
                costo_promedio_90d=None),
    ))
    by_clave = {s.clave: s for s in Supply.objects.all()}
    RecipeLine.objects.create(product=product, supply=by_clave["GIN"], quantity=Decimal("30"))
    RecipeLine.objects.create(product=product, supply=by_clave["HIE"], quantity=Decimal("200"))

    assert product.recipe_cost is None
    assert [line.supply.name for line in product.uncosted_supplies] == ["HIELO"]


@pytest.mark.django_db
def test_a_product_with_no_recipe_has_no_recipe_cost(product):
    assert product.recipe_cost is None


@pytest.mark.django_db
def test_the_average_stands_in_when_the_last_cost_is_missing(restaurant, product):
    sync_supplies(restaurant, _payload(
        _insumo(ultimo_costo_con_impuestos=None, costo_promedio_90d=48.0)
    ))
    supply = Supply.objects.get()
    RecipeLine.objects.create(product=product, supply=supply, quantity=Decimal("10"))

    assert product.recipe_cost == Decimal("480.0000")


# -- re-costing -----------------------------------------------------------


@pytest.mark.django_db
def test_recost_writes_the_recipe_cost_onto_the_product(restaurant, product):
    sync_supplies(restaurant, _payload(_insumo()))
    RecipeLine.objects.create(
        product=product, supply=Supply.objects.get(), quantity=Decimal("45")
    )

    summary = recost_products(restaurant)

    product.refresh_from_db()
    assert product.cost_price == Decimal("2358.62")
    assert summary.recosted == [("NEGRONI", Decimal("6000.00"), Decimal("2358.62"))]


@pytest.mark.django_db
def test_recost_leaves_a_product_without_a_recipe_alone(restaurant, product):
    # Its only cost is the one the POS reported; there is nothing to improve on.
    sync_supplies(restaurant, _payload(_insumo()))

    recost_products(restaurant)

    product.refresh_from_db()
    assert product.cost_price == Decimal("6000.00")


@pytest.mark.django_db
def test_an_incomplete_recipe_holds_the_old_cost_and_is_reported(restaurant, product):
    sync_supplies(restaurant, _payload(_insumo(ultimo_costo_con_impuestos=None,
                                               costo_promedio_90d=None)))
    RecipeLine.objects.create(
        product=product, supply=Supply.objects.get(), quantity=Decimal("45")
    )

    summary = recost_products(restaurant)

    product.refresh_from_db()
    assert product.cost_price == Decimal("6000.00")
    assert summary.blocked == [("NEGRONI", ["GIN TANQUERAY"])]


@pytest.mark.django_db
def test_recost_reports_nothing_when_the_cost_did_not_move(restaurant, product):
    sync_supplies(restaurant, _payload(_insumo(costo=100)))
    RecipeLine.objects.create(
        product=product, supply=Supply.objects.get(), quantity=Decimal("60")
    )
    recost_products(restaurant)

    summary = recost_products(restaurant)

    assert summary.recosted == []


@pytest.mark.django_db
def test_the_menu_item_cost_follows_through_product_units(restaurant, product):
    from quotes.models import MenuItem

    item = MenuItem.objects.create(
        restaurant=restaurant, name="Negroni", price=Decimal("48000"),
        product=product, product_units=Decimal("1"),
    )
    sync_supplies(restaurant, _payload(_insumo()))
    RecipeLine.objects.create(
        product=product, supply=Supply.objects.get(), quantity=Decimal("45")
    )
    recost_products(restaurant)

    item.refresh_from_db()
    # Read live off the recipe, so it carries the full precision; the rounded
    # 2358.62 is what gets persisted onto the product for the rest of the app.
    assert item.unit_cost == Decimal("2358.6165")
    assert item.product.cost_price == Decimal("2358.62")


# -- the HTTP call --------------------------------------------------------


class _Response:
    def __init__(self, body):
        self._body = BytesIO(json.dumps(body).encode())

    def read(self):
        return self._body.read()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.mark.django_db
def test_fetch_sends_the_bearer_token_and_the_window(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        return _Response(_payload(_insumo()))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    payload = fetch_costs("sk-abc", base_url="https://auto-facturas.com", days=30)

    assert seen["auth"] == "Bearer sk-abc"
    assert seen["url"] == "https://auto-facturas.com/conector/costos?dias=30"
    assert payload["insumos"][0]["clave"] == "GIN-01"


@pytest.mark.django_db
def test_fetch_without_a_token_says_so():
    with pytest.raises(SupplyCostError, match="no AutoFacturas token"):
        fetch_costs("")


@pytest.mark.django_db
def test_a_rejected_token_is_reported_as_such(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {},
            BytesIO(json.dumps({"ok": False, "error": "Clave invalida."}).encode()),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(SupplyCostError, match="rejected the token"):
        fetch_costs("sk-wrong")


@pytest.mark.django_db
def test_a_failure_body_is_surfaced(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=None: _Response(
            {"ok": False, "error": "Faltan las migraciones 009 y 010."}
        ),
    )
    with pytest.raises(SupplyCostError, match="migraciones"):
        fetch_costs("sk-abc")


@pytest.mark.django_db
def test_an_answer_without_insumos_is_refused(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=None: _Response({"ok": True, "empresa": {}}),
    )
    with pytest.raises(SupplyCostError, match="no 'insumos' list"):
        fetch_costs("sk-abc")


@pytest.mark.django_db
def test_sync_costs_can_replay_a_saved_answer(restaurant, product):
    RecipeLine.objects.create(
        product=product,
        supply=Supply.objects.create(
            restaurant=restaurant, clave="GIN-01", name="GIN", unit="ml"
        ),
        quantity=Decimal("45"),
    )

    summary = sync_costs(restaurant, payload=_payload(_insumo()))

    product.refresh_from_db()
    assert product.cost_price == Decimal("2358.62")
    assert summary.company == "Casablanca Capital SAS"


# -- the screen -----------------------------------------------------------


@pytest.mark.django_db
def test_supply_page_requires_login(client):
    response = client.get(reverse("catalog:supplies"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_supply_page_lists_what_was_synced(logged_client, restaurant):
    sync_supplies(restaurant, _payload(_insumo()))

    response = logged_client.get(reverse("catalog:supplies"))

    assert response.status_code == 200
    assert "GIN TANQUERAY" in response.content.decode()


@pytest.mark.django_db
def test_supply_page_says_when_there_is_no_token(logged_client):
    response = logged_client.get(reverse("catalog:supplies"))

    assert not response.context["has_token"]
    assert "no AutoFacturas token" in response.content.decode()


@pytest.mark.django_db
def test_sync_button_reports_a_connector_failure(logged_client, restaurant, monkeypatch):
    restaurant.autofacturas_token = "sk-abc"
    restaurant.save()
    monkeypatch.setattr(
        "catalog.views.sync_costs",
        lambda *a, **k: (_ for _ in ()).throw(SupplyCostError("AutoFacturas is down.")),
    )

    response = logged_client.post(reverse("catalog:supply_sync"), follow=True)

    assert "AutoFacturas is down." in response.content.decode()


@pytest.mark.django_db
def test_adding_an_ingredient_recosts_the_product(logged_client, restaurant, product):
    sync_supplies(restaurant, _payload(_insumo()))
    supply = Supply.objects.get()

    logged_client.post(
        reverse("catalog:recipe_edit", args=[product.pk]),
        {"supply": supply.pk, "quantity": "45"},
    )

    product.refresh_from_db()
    assert product.recipe.count() == 1
    assert product.cost_price == Decimal("2358.62")


@pytest.mark.django_db
def test_adding_an_ingredient_twice_updates_the_portion(logged_client, restaurant, product):
    sync_supplies(restaurant, _payload(_insumo()))
    supply = Supply.objects.get()
    url = reverse("catalog:recipe_edit", args=[product.pk])

    logged_client.post(url, {"supply": supply.pk, "quantity": "45"})
    logged_client.post(url, {"supply": supply.pk, "quantity": "60"})

    assert product.recipe.count() == 1
    assert product.recipe.get().quantity == Decimal("60")


@pytest.mark.django_db
def test_a_quantity_of_zero_is_refused(logged_client, restaurant, product):
    sync_supplies(restaurant, _payload(_insumo()))

    response = logged_client.post(
        reverse("catalog:recipe_edit", args=[product.pk]),
        {"supply": Supply.objects.get().pk, "quantity": "0"},
        follow=True,
    )

    assert product.recipe.count() == 0
    assert "quantity above zero" in response.content.decode()


@pytest.mark.django_db
def test_a_supply_from_another_restaurant_cannot_be_used(
    logged_client, other_restaurant, product
):
    theirs = Supply.objects.create(
        restaurant=other_restaurant, clave="X", name="SUYO", unit="ml",
        unit_cost=Decimal("10"),
    )

    logged_client.post(
        reverse("catalog:recipe_edit", args=[product.pk]),
        {"supply": theirs.pk, "quantity": "45"},
    )

    assert product.recipe.count() == 0


@pytest.mark.django_db
def test_removing_an_ingredient_leaves_the_rest(logged_client, restaurant, product):
    sync_supplies(restaurant, _payload(_insumo(clave="A"), _insumo(clave="B", nombre="VERMUT")))
    a, b = Supply.objects.order_by("clave")
    url = reverse("catalog:recipe_edit", args=[product.pk])
    logged_client.post(url, {"supply": a.pk, "quantity": "30"})
    logged_client.post(url, {"supply": b.pk, "quantity": "30"})

    line = product.recipe.get(supply=a)
    logged_client.post(url, {"action": "remove", "line": line.pk})

    assert [r.supply.clave for r in product.recipe.all()] == ["B"]


@pytest.mark.django_db
def test_the_token_is_never_rendered_back(logged_client, restaurant):
    restaurant.autofacturas_token = "sk-super-secret"
    restaurant.save()

    response = logged_client.get(reverse("tenants:settings"))

    assert "sk-super-secret" not in response.content.decode()


@pytest.mark.django_db
def test_saving_settings_without_a_token_keeps_the_stored_one(logged_client, restaurant):
    restaurant.autofacturas_token = "sk-keep-me"
    restaurant.save()

    logged_client.post(reverse("tenants:settings"), {"name": "Otro nombre"})

    restaurant.refresh_from_db()
    assert restaurant.autofacturas_token == "sk-keep-me"
    assert restaurant.name == "Otro nombre"
