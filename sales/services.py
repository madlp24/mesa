"""Import orchestration shared by the web upload and the CLI command (US28)."""
from pathlib import Path

from django.db import transaction

from .importers import get_importer_for, persist
from .models import ImportBatch, Sale


class AggregateReportError(ValueError):
    """A report covering a whole period was offered where a day was expected."""


def run_import(
    path: Path,
    restaurant,
    *,
    filename: str,
    source: str,
    allow_aggregate: bool = False,
) -> ImportBatch:
    """Import a report file into ``restaurant`` and record an ImportBatch.

    Parsing happens first (may raise); the batch and the inserted sales are then
    committed atomically and the batch's counts are filled in.

    A report covering more than a day (the POS prints a month in the same layout)
    is refused unless ``allow_aggregate``: every line would be filed under the
    period's first day, so the month would show up as one enormous day and would
    be counted twice next to the days themselves.
    """
    importer = get_importer_for(path)
    canonical = importer.normalize(path)
    span = getattr(importer, "period_days", None)
    if not allow_aggregate and span is not None and span > 1:
        raise AggregateReportError(
            f"'{filename}' covers {span} days, not one. It looks like a monthly "
            "report: importing it would file the whole period under its first "
            "day. Upload the daily reports instead."
        )
    with transaction.atomic():
        batch = ImportBatch.objects.create(
            restaurant=restaurant, filename=filename, source=source
        )
        result = persist(canonical, restaurant, import_batch=batch)
        batch.sales_created = result["new"]
        batch.items_created = result["items"]
        batch.skipped_duplicate = result["skipped_duplicate"]
        batch.skipped_rows = getattr(importer, "skipped_rows", 0)
        batch.save(
            update_fields=[
                "sales_created",
                "items_created",
                "skipped_duplicate",
                "skipped_rows",
            ]
        )
    return batch


def undo_import(batch: ImportBatch) -> int:
    """Delete the sales created by ``batch`` (items cascade), then the batch.

    Products and identities created during the import are kept; only the sales
    are removed. Returns the number of sales deleted.
    """
    with transaction.atomic():
        sales = Sale.objects.filter(import_batch=batch)
        count = sales.count()
        sales.delete()  # SaleItems cascade
        batch.delete()
    return count
