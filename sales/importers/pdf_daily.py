"""Importer for the POS "Productos Vendidos" PDF report.

The report is an aggregate of products sold over a period (a single day, for the
daily report this story targets), grouped by product family. It is not a ruled
table, so rows are read from the page text with a regex. Each product line
becomes one synthetic :class:`CanonicalSale` carrying a single item:

* the report period's start date  -> ``occurred_at``
* ``"<date>:<clave>"``             -> ``external_id`` (so re-imports are idempotent)
* ``CLAVE``                        -> product SKU       (``GRUPO`` -> category)
* ``CANTIDAD VENDIDA``             -> quantity
* ``PRECIO VENTA PROMEDIO``        -> unit price
* ``COSTO PROMEDIO``               -> unit cost
* ``VENTA TOTAL``                  -> sale total

Because the report embeds the catalog, each item also carries the product name
and category so :func:`persist` can auto-create missing products.
"""
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from .base import BaseImporter
from .canonical import CanonicalSale
from .registry import register
from .rows import RowError, canonical_from_record

logger = logging.getLogger(__name__)

# "... DEL 01/04/2025 06:00:00 AM AL ..." -> capture the period's start date.
_PERIOD = re.compile(r"DEL\s+(\d{2})/(\d{2})/(\d{4})")
# "GRUPO:ACOMPAÑAMIENTOS" (header) and "GRUPO: ACOMPAÑAMIENTOS 290.000 ..."
# (subtotal) both name the current group; capture the leading letters.
_GROUP = re.compile(r"^GRUPO:\s*([^\d$]+?)\s*(?:\d|$)")
# A product line: CLAVE, DESCRIPCION, then 8 numeric columns (one bare quantity
# between money amounts).
_PRODUCT = re.compile(
    r"^(?P<clave>\d+)\s+(?P<desc>.+?)\s+"
    r"\$(?P<unit_price>[\-\d.,]+)\s+(?P<quantity>[\d.,]+)\s+"
    r"\$(?P<total>[\-\d.,]+)\s+\$(?P<unit_cost>[\-\d.,]+)\s+"
    r"\$[\-\d.,]+\s+\$[\-\d.,]+\s+\$[\-\d.,]+\s+\$[\-\d.,]+\s*$"
)
# Looks like a product row (starts with a code and has a money amount) but did
# not fully parse -> a malformed row worth counting and logging.
_CANDIDATE = re.compile(r"^\d+\s.*\$")
# Report footer split by family, e.g.
# "BEBIDAS: $1,651,851.00 (20%) 78 $591,901.87 $1,059,949.12"
# -> family, VENTA, (pct), CANTIDAD, COSTOS, (VENTA-COSTO). We keep VENTA/COSTOS.
# Note the optional space before the colon: some reports print "ALIMENTOS :".
_FOOTER = re.compile(
    r"^(?P<family>BEBIDAS|ALIMENTOS)\s*:\s*\$(?P<venta>[\-\d.,]+)\s*"
    r"\(\d+%\)\s+[\d.,]+\s+\$(?P<costos>[\-\d.,]+)\s+\$[\-\d.,]+"
)


def _clean_number(raw: str) -> str:
    return raw.replace("$", "").replace(",", "").strip()


@dataclass(frozen=True)
class DailyTotals:
    """The per-day Bar/Kitchen split from a report footer (BEBIDAS/ALIMENTOS)."""

    date: str  # ISO "YYYY-MM-DD" (the report period's start date)
    venta_bar: Decimal
    costo_bar: Decimal
    venta_cocina: Decimal
    costo_cocina: Decimal


def parse_daily_totals(path: Path) -> DailyTotals | None:
    """Extract the day's Bar/Kitchen totals from a daily report footer.

    Returns ``None`` when the file is not a daily report with the expected
    footer (e.g. a different format, or the monthly summary of a broken layout).
    """
    period_date: str | None = None
    families: dict[str, tuple[Decimal, Decimal]] = {}
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                line = line.strip()
                if period_date is None:
                    match = _PERIOD.search(line)
                    if match:
                        day, month, year = match.groups()
                        period_date = f"{year}-{month}-{day}"
                footer = _FOOTER.match(line)
                if footer:
                    try:
                        venta = Decimal(_clean_number(footer.group("venta")))
                        costos = Decimal(_clean_number(footer.group("costos")))
                    except InvalidOperation:
                        continue
                    families[footer.group("family")] = (venta, costos)

    if period_date is None or "BEBIDAS" not in families or "ALIMENTOS" not in families:
        return None
    venta_bar, costo_bar = families["BEBIDAS"]
    venta_cocina, costo_cocina = families["ALIMENTOS"]
    return DailyTotals(
        date=period_date,
        venta_bar=venta_bar,
        costo_bar=costo_bar,
        venta_cocina=venta_cocina,
        costo_cocina=costo_cocina,
    )


@register(".pdf")
class PdfDailyImporter(BaseImporter):
    """Parse a daily "Productos Vendidos" PDF report into canonical sales."""

    def __init__(self) -> None:
        self.skipped_rows = 0

    def normalize(self, path: Path) -> list[CanonicalSale]:
        period_date: str | None = None
        category = ""
        sales = []

        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                for line in (page.extract_text() or "").splitlines():
                    line = line.strip()

                    if period_date is None:
                        match = _PERIOD.search(line)
                        if match:
                            day, month, year = match.groups()
                            period_date = f"{year}-{month}-{day}"

                    group = _GROUP.match(line)
                    if group:
                        category = group.group(1).strip()
                        continue

                    product = _PRODUCT.match(line)
                    if product:
                        sale = self._build_sale(product, period_date, category)
                        if sale is not None:
                            sales.append(sale)
                    elif _CANDIDATE.match(line):
                        self.skipped_rows += 1
                        logger.warning("Skipped malformed product row: %s", line)

        return sales

    def _build_sale(self, match, period_date, category) -> CanonicalSale | None:
        if period_date is None:
            self.skipped_rows += 1
            logger.warning("Skipped row before report period was found: %s", match.group(0))
            return None

        clave = match.group("clave")
        record = {
            "external_id": f"{period_date}:{clave}",
            "occurred_at": period_date,
            "product_sku": clave,
            "product_name": match.group("desc").strip(),
            "category_name": category,
            "quantity": _clean_number(match.group("quantity")),
            "unit_price": _clean_number(match.group("unit_price")),
            "unit_cost": _clean_number(match.group("unit_cost")),
            "total": _clean_number(match.group("total")),
        }
        try:
            return canonical_from_record(record)
        except RowError as exc:
            self.skipped_rows += 1
            logger.warning("Skipped product %s: %s", clave, exc)
            return None
