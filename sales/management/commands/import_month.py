"""Import a folder of daily reports, skipping the traps real folders contain."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from sales.importers.folder import select_daily_reports
from sales.services import run_import
from tenants.utils import resolve_restaurant


class Command(BaseCommand):
    help = (
        "Import every daily report in a folder. Aggregates (a month printed in "
        "the daily layout) are skipped, and when a date has several files the "
        "fullest one wins."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dir", required=True, help="Folder of .pdf reports")
        parser.add_argument("--restaurant", help="Restaurant slug")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be imported without touching the database.",
        )

    def handle(self, *args, **options):
        folder = Path(options["dir"])
        if not folder.is_dir():
            raise CommandError(f"Not a folder: {folder}")
        restaurant = resolve_restaurant(options.get("restaurant"))

        chosen, skipped = select_daily_reports(folder)
        if not chosen:
            raise CommandError(f"No daily reports found in {folder}")

        self.stdout.write(
            f"{len(chosen)} day(s) to import, {len(skipped)} file(s) skipped."
        )
        for name, why in skipped:
            self.stdout.write(self.style.WARNING(f"  skipped {name}: {why}"))
        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Dry run: nothing was imported."))
            return

        sales = items = duplicates = 0
        for day in sorted(chosen):
            pdf = chosen[day]
            batch = run_import(pdf, restaurant, filename=pdf.name, source="cli")
            sales += batch.sales_created
            items += batch.items_created
            duplicates += batch.skipped_duplicate
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(chosen)} day(s) into {restaurant.name}: "
                f"{sales} sales, {items} items, {duplicates} skipped as duplicate."
            )
        )
