"""Fill the 'Datos totales' sheet (N/O/S/T = Venta/Costo Bar y Cocina) of the
unified-analysis workbook from a folder of daily POS PDFs (US32).

Reads each daily report's footer (BEBIDAS/ALIMENTOS block) directly -- these are
authoritative POS aggregates, not derived from Mesa's per-product data -- and
writes them per day. Writes a copy; never touches the original.
"""
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analytics.unified_excel import UnifiedUpdateError, update_datos_totales
from sales.importers.pdf_daily import parse_daily_totals


class Command(BaseCommand):
    help = (
        "Fill 'Datos totales' N/O/S/T (Venta/Costo Bar y Cocina) from the footer "
        "of each daily PDF in --pdf-dir. Writes a copy '<name> (Mesa Datos totales).xlsx'."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to the master .xlsx")
        parser.add_argument(
            "--pdf-dir", required=True, help="Folder with the month's daily PDFs"
        )

    def handle(self, *args, **options):
        pdf_dir = Path(options["pdf_dir"])
        if not pdf_dir.is_dir():
            raise CommandError(f"Not a folder: {pdf_dir}")

        totals_by_date: dict[date, object] = {}
        skipped = []
        for pdf in sorted(pdf_dir.glob("*.pdf")):
            if "mes" in pdf.stem.lower().split():  # monthly summary, not a day
                skipped.append(pdf.name)
                continue
            totals = parse_daily_totals(pdf)
            if totals is None:
                skipped.append(pdf.name)
                continue
            totals_by_date[date.fromisoformat(totals.date)] = totals

        if not totals_by_date:
            raise CommandError(f"No daily report footers found in {pdf_dir}")

        try:
            summary = update_datos_totales(Path(options["file"]), totals_by_date)
        except UnifiedUpdateError as exc:
            raise CommandError(str(exc)) from exc

        for warning in summary["warnings"]:
            self.stdout.write(self.style.WARNING(f"WARNING: {warning}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated copy written to {summary['copy']}\n"
                f"{len(totals_by_date)} days parsed, "
                f"{summary['filled']} rows filled in place, "
                f"{len(summary['appended'])} appended"
            )
        )
        if summary["appended"]:
            self.stdout.write(
                "Appended (no existing row for these dates; added at the bottom):"
            )
            for day in summary["appended"]:
                self.stdout.write(f"  - {day}")
        if skipped:
            self.stdout.write(f"Skipped {len(skipped)} file(s) without a daily footer.")
