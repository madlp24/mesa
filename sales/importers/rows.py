"""Shared row -> canonical-sale normalization used by every file importer.

Each source row (an Excel worksheet row, a PDF table row, ...) is reduced to a
``{field: value}`` record keyed by the column names below, then turned into a
:class:`CanonicalSale` carrying a single :class:`CanonicalSaleItem`. Rows that
cannot be normalized raise :class:`RowError` so the calling importer can count
and log them with their source row number.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from .canonical import CanonicalSale, CanonicalSaleItem

REQUIRED_FIELDS = (
    "external_id",
    "occurred_at",
    "product_sku",
    "quantity",
    "unit_price",
    "unit_cost",
)
OPTIONAL_FIELDS = ("payment_method", "server_name", "table_number")


class RowError(ValueError):
    """A source row that cannot be normalized into a CanonicalSale."""


def canonical_from_record(record: dict) -> CanonicalSale:
    """Build a CanonicalSale from a field->value record, or raise RowError."""
    missing = [name for name in REQUIRED_FIELDS if record.get(name) in (None, "")]
    if missing:
        raise RowError(f"missing {', '.join(missing)}")

    try:
        quantity = int(record["quantity"])
        unit_price = Decimal(str(record["unit_price"]))
        unit_cost = Decimal(str(record["unit_cost"]))
        occurred_at = _as_aware_datetime(record["occurred_at"])
    except (ValueError, InvalidOperation, TypeError) as exc:
        raise RowError("invalid number or date") from exc

    item = CanonicalSaleItem(
        product_sku=str(record["product_sku"]).strip(),
        quantity=quantity,
        unit_price=unit_price,
        unit_cost=unit_cost,
    )
    return CanonicalSale(
        external_id=str(record["external_id"]).strip(),
        occurred_at=occurred_at,
        total=unit_price * quantity,
        payment_method=str(record.get("payment_method") or ""),
        server_name=str(record.get("server_name") or ""),
        table_number=str(record.get("table_number") or ""),
        items=[item],
    )


def _as_aware_datetime(value) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
    return parsed
