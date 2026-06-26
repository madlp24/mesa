"""Update an existing Productos-Vendidos workbook in place (writes a copy)."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analytics.excel_update import ExcelUpdateError, update_productos_vendidos


class Command(BaseCommand):
    help = (
        "Write the new months into an existing 'Productos vendidos' .xlsx, "
        "matching rows by name. Writes a copy '<name> (actualizado).xlsx'."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to the existing .xlsx")

    def handle(self, *args, **options):
        try:
            summary = update_productos_vendidos(Path(options["file"]))
        except ExcelUpdateError as exc:
            raise CommandError(str(exc)) from exc

        for warning in summary["warnings"]:
            self.stdout.write(self.style.WARNING(f"WARNING: {warning}"))

        months = ", ".join(summary["months_added"]) or "none"
        self.stdout.write(
            self.style.SUCCESS(
                f"Updated copy written to {summary['copy']}\n"
                f"Months added: {months}\n"
                f"{summary['matched']} rows matched, {summary['appended']} new rows appended"
            )
        )
