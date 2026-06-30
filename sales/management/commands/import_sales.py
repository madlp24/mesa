from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from sales.services import run_import
from tenants.utils import resolve_restaurant


class Command(BaseCommand):
    help = "Import sales from a POS report file (Excel, PDF, etc.)."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to the report file")
        parser.add_argument(
            "--restaurant",
            help="Restaurant slug to import into (optional if there is only one).",
        )

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        restaurant = resolve_restaurant(options.get("restaurant"))

        try:
            batch = run_import(
                path, restaurant, filename=path.name, source="cli"
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"{batch.sales_created} sales imported, "
                f"{batch.items_created} items, "
                f"{batch.skipped_rows} rows skipped"
            )
        )
        self.stdout.write(
            f"{batch.sales_created} new sales, "
            f"{batch.skipped_duplicate} skipped as duplicate "
            f"(restaurant: {restaurant.name})"
        )
