"""Fill one month's units into the 'Productos vendidos' sheet of the owner's
unified-analysis workbook (US30). Writes a copy; never touches the original."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analytics.unified_excel import UnifiedUpdateError, update_productos_vendidos
from tenants.utils import resolve_restaurant


class Command(BaseCommand):
    help = (
        "Fill the (year, month) column of the 'Productos vendidos' matrix in the "
        "unified-analysis workbook with Mesa's per-product units, matching rows by "
        "name. Writes a copy '<name> (Mesa <Month> <Year>).xlsx'."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to the master .xlsx")
        parser.add_argument(
            "--restaurant", help="Restaurant slug (optional if there is only one)."
        )
        parser.add_argument("--year", required=True, type=int)
        parser.add_argument("--month", required=True, type=int, help="1-12")

    def handle(self, *args, **options):
        restaurant = resolve_restaurant(options.get("restaurant"))
        try:
            summary = update_productos_vendidos(
                Path(options["file"]), restaurant, options["year"], options["month"]
            )
        except UnifiedUpdateError as exc:
            raise CommandError(str(exc)) from exc

        for warning in summary["warnings"]:
            self.stdout.write(self.style.WARNING(f"WARNING: {warning}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated copy written to {summary['copy']}\n"
                f"Column {summary['column']}: "
                f"{summary['matched']} rows matched, "
                f"{summary['appended']} new rows appended"
            )
        )
        if summary["appended_names"]:
            self.stdout.write(
                "Appended as NEW rows (review for name-drift duplicates):"
            )
            for name in summary["appended_names"]:
                self.stdout.write(f"  - {name}")
