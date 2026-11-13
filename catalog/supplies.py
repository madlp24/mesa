"""Cost Mesa's products from AutoFacturas' supply costs (US45).

AutoFacturas reads the restaurant's purchase invoices and publishes, at
``GET /conector/costos``, what one unit of consumption of each insumo costs --
a millilitre of gin, a gram of lomo, one bottle of beer -- with the taxes a
restaurant on the consumption-tax regime cannot discount already inside. The
call is authenticated with a Bearer token issued per company, so the token
lives on the :class:`tenants.Restaurant`, not in settings.

Three steps, kept apart so each can be tested and re-run on its own:

* :func:`fetch_costs` talks to the connector and returns its payload.
* :func:`sync_supplies` writes that payload into :class:`catalog.Supply`,
  matching on ``clave`` -- the only field that survives a rename.
* :func:`recost_products` rebuilds ``Product.cost_price`` from the recipes.

Only products that *have* a recipe are re-costed. The rest keep the cost the
POS reported, which is the only one they have.
"""
from __future__ import annotations

import datetime
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from catalog.models import Product, Supply, SupplyUnit

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://auto-facturas.com"
COSTS_PATH = "/conector/costos"
DEFAULT_TIMEOUT = 30
DEFAULT_DAYS = 90

_UNITS = {choice.value for choice in SupplyUnit}


class SupplyCostError(Exception):
    """The connector could not be read, or answered something unusable."""


@dataclass
class SyncSummary:
    """What one run changed, in the words the command and the page both use."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    uncosted: int = 0
    recosted: list[tuple[str, Decimal, Decimal]] = field(default_factory=list)
    blocked: list[tuple[str, list[str]]] = field(default_factory=list)
    generated_at: str = ""
    company: str = ""
    taxes_are_cost: bool = True
    days: int = DEFAULT_DAYS

    @property
    def supplies_seen(self) -> int:
        return self.created + self.updated + self.unchanged


def fetch_costs(
    token: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    days: int = DEFAULT_DAYS,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Read ``GET /conector/costos`` for the company the token belongs to."""
    if not token:
        raise SupplyCostError(
            "This restaurant has no AutoFacturas token; add it in Settings."
        )
    query = urllib.parse.urlencode({"dias": days})
    url = f"{base_url.rstrip('/')}{COSTS_PATH}?{query}"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # The connector answers 401 with a body explaining itself; a bare status
        # code would send the owner looking for the wrong problem. The token is
        # never echoed back, here or in the logs.
        detail = _error_detail(exc)
        if exc.code == 401:
            raise SupplyCostError(
                "AutoFacturas rejected the token for this restaurant."
            ) from exc
        raise SupplyCostError(f"AutoFacturas answered {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SupplyCostError(f"Could not reach {base_url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise SupplyCostError("AutoFacturas did not answer JSON.") from exc

    if not isinstance(payload, dict) or not payload.get("ok"):
        raise SupplyCostError(
            payload.get("error", "AutoFacturas reported a failure.")
            if isinstance(payload, dict)
            else "AutoFacturas did not answer an object."
        )
    if not isinstance(payload.get("insumos"), list):
        raise SupplyCostError("The answer carries no 'insumos' list.")
    return payload


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(exc.read().decode("utf-8"))
        return str(body.get("error") or exc.reason)
    except Exception:  # noqa: BLE001 - the body is best-effort context
        return str(exc.reason)


def _decimal(value) -> Decimal | None:
    """A money figure from the payload, or ``None`` when it carries none.

    Zero is not a cost: the connector sends ``null`` for what it could not
    cost, and a zero that slipped through would read as free.
    """
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount > 0 else None


def _date(value) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _unit(value) -> str:
    unit = str(value or "").strip().lower()
    return unit if unit in _UNITS else ""


@transaction.atomic
def sync_supplies(restaurant, payload: dict) -> SyncSummary:
    """Write the connector's insumos into this restaurant's supplies.

    Matched by ``clave``: a renamed insumo is the same insumo, and a new clave
    is a new one. Supplies Mesa already knows that the payload no longer
    mentions are left alone -- AutoFacturas drops an insumo from the list when
    it cannot cost it, and deleting it here would take its recipes with it.
    """
    summary = SyncSummary(
        generated_at=str(payload.get("generado_en") or ""),
        company=str((payload.get("empresa") or {}).get("nombre") or ""),
        taxes_are_cost=bool(payload.get("iva_es_costo", True)),
        days=int(payload.get("dias_promedio") or DEFAULT_DAYS),
    )
    now = timezone.now()
    existing = {s.clave: s for s in Supply.objects.filter(restaurant=restaurant)}

    for row in payload["insumos"]:
        clave = str(row.get("clave") or "").strip()
        if not clave:
            continue
        fields = {
            "name": str(row.get("nombre") or "")[:200],
            "unit": _unit(row.get("unidad_consumo")),
            "group": str(row.get("grupo") or "")[:100],
            "unit_cost": _decimal(row.get("ultimo_costo_con_impuestos")),
            "unit_cost_untaxed": _decimal(row.get("ultimo_costo_sin_impuestos")),
            "average_cost": _decimal(row.get("costo_promedio_90d")),
            "last_purchase_date": _date(row.get("ultima_compra_fecha")),
            "last_purchase_supplier": str(row.get("ultima_compra_proveedor") or "")[:200],
            "last_purchase_invoice": str(row.get("ultima_compra_factura") or "")[:60],
            "last_purchase_description": str(row.get("ultima_compra_producto") or "")[:300],
        }
        supply = existing.get(clave)
        if supply is None:
            Supply.objects.create(
                restaurant=restaurant, clave=clave, synced_at=now, **fields
            )
            summary.created += 1
        else:
            changed = [f for f, v in fields.items() if getattr(supply, f) != v]
            for name, value in fields.items():
                setattr(supply, name, value)
            supply.synced_at = now
            supply.save(update_fields=[*fields, "synced_at"])
            if changed:
                summary.updated += 1
            else:
                summary.unchanged += 1
        if fields["unit_cost"] is None:
            summary.uncosted += 1

    return summary


@transaction.atomic
def recost_products(restaurant, summary: SyncSummary | None = None) -> SyncSummary:
    """Rebuild ``cost_price`` for every product that has a recipe.

    A recipe whose supplies are not all costed leaves the product's existing
    cost alone and is reported instead: overwriting a POS cost with a partial
    recipe would make the product look cheaper than it is.
    """
    summary = summary or SyncSummary()
    products = (
        Product.objects.filter(restaurant=restaurant, recipe__isnull=False)
        .distinct()
        .prefetch_related("recipe__supply")
    )
    for product in products:
        cost = product.recipe_cost
        if cost is None:
            summary.blocked.append(
                (product.name, [line.supply.name for line in product.uncosted_supplies])
            )
            continue
        new_cost = Decimal(cost).quantize(Decimal("0.01"))
        if new_cost == product.cost_price:
            continue
        summary.recosted.append((product.name, product.cost_price, new_cost))
        product.cost_price = new_cost
        product.save(update_fields=["cost_price"])
    return summary


def sync_costs(
    restaurant,
    *,
    base_url: str = DEFAULT_BASE_URL,
    days: int = DEFAULT_DAYS,
    payload: dict | None = None,
) -> SyncSummary:
    """Fetch, store and re-cost in one go.

    ``payload`` short-circuits the HTTP call, so a saved answer can be replayed
    without reaching the connector.
    """
    if payload is None:
        payload = fetch_costs(
            restaurant.autofacturas_token, base_url=base_url, days=days
        )
    summary = sync_supplies(restaurant, payload)
    return recost_products(restaurant, summary)
