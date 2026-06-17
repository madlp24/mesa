"""Importer for historical sales delivered as an Excel workbook.

One worksheet row becomes one :class:`CanonicalSale` carrying a single
:class:`CanonicalSaleItem`. The first row is treated as a header and columns
are matched by name, so column order does not matter. Rows missing any required
field are skipped and logged with their 1-based worksheet row number; the count
is exposed via :attr:`skipped_rows` for the caller's summary.
"""
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.utils import timezone
from openpyxl import load_workbook

from .base import BaseImporter
from .canonical import CanonicalSale, CanonicalSaleItem
from .registry import register

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = (
    "external_id",
    "occurred_at",
    "product_sku",
    "quantity",
    "unit_price",
    "unit_cost",
)
OPTIONAL_FIELDS = ("payment_method", "server_name", "table_number")


@register(".xlsx")
class ExcelHistoricalImporter(BaseImporter):
    """Parse a historical-sales Excel workbook into canonical sales."""

    def __init__(self) -> None:
        self.skipped_rows = 0

    def normalize(self, path: Path) -> list[CanonicalSale]:
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            rows = workbook.active.iter_rows(values_only=True)
            try:
                header = next(rows)
            except StopIteration:
                return []
            columns = {
                str(name).strip(): index
                for index, name in enumerate(header)
                if name is not None
            }
            sales = []
            for row_number, row in enumerate(rows, start=2):
                sale = self._build_sale(row, columns, row_number)
                if sale is not None:
                    sales.append(sale)
            return sales
        finally:
            workbook.close()

    def _build_sale(self, row, columns, row_number) -> CanonicalSale | None:
        def cell(name: str):
            index = columns.get(name)
            if index is None or index >= len(row):
                return None
            return row[index]

        missing = [name for name in REQUIRED_FIELDS if cell(name) in (None, "")]
        if missing:
            self.skipped_rows += 1
            logger.warning("Row %s skipped: missing %s", row_number, ", ".join(missing))
            return None

        try:
            quantity = int(cell("quantity"))
            unit_price = Decimal(str(cell("unit_price")))
            unit_cost = Decimal(str(cell("unit_cost")))
            occurred_at = self._as_aware_datetime(cell("occurred_at"))
        except (ValueError, InvalidOperation, TypeError):
            self.skipped_rows += 1
            logger.warning("Row %s skipped: invalid number or date", row_number)
            return None

        item = CanonicalSaleItem(
            product_sku=str(cell("product_sku")).strip(),
            quantity=quantity,
            unit_price=unit_price,
            unit_cost=unit_cost,
        )
        return CanonicalSale(
            external_id=str(cell("external_id")).strip(),
            occurred_at=occurred_at,
            total=unit_price * quantity,
            payment_method=str(cell("payment_method") or ""),
            server_name=str(cell("server_name") or ""),
            table_number=str(cell("table_number") or ""),
            items=[item],
        )

    @staticmethod
    def _as_aware_datetime(value) -> datetime:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
        return parsed
