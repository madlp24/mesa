"""Fill the 'Datos totales' sheet (N/O/S/T = Venta/Costo Bar y Cocina) of the
unified-analysis workbook from folders of daily POS reports (US32).

Reads each day's footer (BEBIDAS/ALIMENTOS block) -- authoritative POS
aggregates, not derived from Mesa's per-product data -- and writes them per day.
Writes a copy; never touches the original.
"""
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analytics.unified_excel import UnifiedUpdateError, update_datos_totales
from sales.importers.folder import select_daily_reports
from sales.importers.pdf_daily import parse_daily_totals


class Command(BaseCommand):
    help = (
        "Fill 'Datos totales' N/O/S/T from the footer of every daily report in "
        "the given folders. Writes a copy '<name> (Mesa Datos totales).xlsx'."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to the master .xlsx")
        parser.add_argument(
            "--pdf-dir",
            required=True,
            action="append",
            help="Folder with daily PDFs. Repeat for several months.",
        )

    def handle(self, *args, **options):
        totals_by_date: dict[date, object] = {}
        skipped: list[tuple[str, str]] = []
        for raw in options["pdf_dir"]:
            folder = Path(raw)
            if not folder.is_dir():
                raise CommandError(f"Not a folder: {folder}")
            chosen, folder_skips = select_daily_reports(folder)
            skipped.extend(folder_skips)
            for day, pdf in chosen.items():
                totals = parse_daily_totals(pdf)
                if totals is None:
                    skipped.append((pdf.name, "no BEBIDAS/ALIMENTOS footer"))
                    continue
                totals_by_date[day] = totals

        if not totals_by_date:
            raise CommandError("No daily report footers found in the given folders")

        try:
            summary = update_datos_totales(Path(options["file"]), totals_by_date)
        except UnifiedUpdateError as exc:
            raise CommandError(str(exc)) from exc

        for warning in summary["warnings"]:
            self.stdout.write(self.style.WARNING(f"WARNING: {warning}"))
        for name, why in skipped:
            self.stdout.write(self.style.WARNING(f"  skipped {name}: {why}"))

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
            for day in summary["appended"][:12]:
                self.stdout.write(f"  - {day}")
            if len(summary["appended"]) > 12:
                self.stdout.write(f"  ... and {len(summary['appended']) - 12} more")
