"""Update an existing Productos-Vendidos workbook in place (writes a copy)."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analytics.excel_update import ExcelUpdateError, update_productos_vendidos
from tenants.utils import resolve_restaurant


class Command(BaseCommand):
    help = (
        "Write the new months into an existing 'Productos vendidos' .xlsx, "
        "matching rows by name. Writes a copy '<name> (actualizado).xlsx'."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to the existing .xlsx")
        parser.add_argument(
            "--restaurant", help="Restaurant slug (optional if there is only one)."
        )

    def handle(self, *args, **options):
        restaurant = resolve_restaurant(options.get("restaurant"))
        try:
            summary = update_productos_vendidos(Path(options["file"]), restaurant)
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
