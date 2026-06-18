"""Importer for daily sales reports delivered as a PDF from the POS.

The first ruled table in the document is extracted with ``pdfplumber``; its
first row is the header. Each remaining row is normalized into the same
canonical schema as the Excel importer via :func:`canonical_from_record`. Rows
that cannot be normalized are skipped, counted on :attr:`skipped_rows`, and
logged with their 1-based table row number.
"""
import logging
from pathlib import Path

import pdfplumber

from .base import BaseImporter
from .canonical import CanonicalSale
from .registry import register
from .rows import RowError, canonical_from_record

logger = logging.getLogger(__name__)


@register(".pdf")
class PdfDailyImporter(BaseImporter):
    """Parse a daily-sales PDF report into canonical sales."""

    def __init__(self) -> None:
        self.skipped_rows = 0

    def normalize(self, path: Path) -> list[CanonicalSale]:
        header: list[str] | None = None
        sales = []
        row_number = 1

        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                for raw in page.extract_table() or []:
                    cells = [str(c).strip() if c is not None else "" for c in raw]
                    if header is None:
                        header = cells
                        continue
                    row_number += 1
                    record = dict(zip(header, cells))
                    try:
                        sales.append(canonical_from_record(record))
                    except RowError as exc:
                        self.skipped_rows += 1
                        logger.warning("Row %s skipped: %s", row_number, exc)
        return sales
